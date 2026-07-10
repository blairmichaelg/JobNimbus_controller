import base64
import httpx
from datetime import datetime, timedelta
import structlog
import urllib.parse
import uuid

from app.core.database import get_connection, get_financials
from app.config import get_settings

logger = structlog.get_logger("app.core.qbo_client")

class QBOClient:
    def __init__(self):
        settings = get_settings()
        self.client_id = settings.qbo_client_id
        self.client_secret = settings.qbo_client_secret
        self.environment = settings.qbo_environment
        
        self.auth_url = "https://appcenter.intuit.com/connect/oauth2"
        self.token_url = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
        
        if self.environment == "production":
            self.api_base = "https://quickbooks.api.intuit.com"
        else:
            self.api_base = "https://sandbox-quickbooks.api.intuit.com"

    def get_authorization_url(self, redirect_uri: str) -> str:
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "scope": "com.intuit.quickbooks.accounting",
            "redirect_uri": redirect_uri,
            "state": "qbo_state"
        }
        return f"{self.auth_url}?{urllib.parse.urlencode(params)}"

    async def exchange_code(self, code: str, realm_id: str, redirect_uri: str) -> None:
        auth_header = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.token_url,
                headers={
                    "Authorization": f"Basic {auth_header}",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json"
                },
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri
                }
            )
            response.raise_for_status()
            data = response.json()
            self._save_tokens(realm_id, data)

    def _save_tokens(self, realm_id: str, data: dict) -> None:
        access_token = data["access_token"]
        refresh_token = data["refresh_token"]
        expires_in = data["expires_in"]
        x_refresh_token_expires_in = data["x_refresh_token_expires_in"]
        
        now = datetime.utcnow()
        token_expires_at = (now + timedelta(seconds=expires_in)).isoformat()
        refresh_expires_at = (now + timedelta(seconds=x_refresh_token_expires_in)).isoformat()
        
        conn = get_connection()
        try:
            conn.execute('''
                INSERT OR REPLACE INTO qbo_credentials 
                (realm_id, access_token, refresh_token, token_expires_at, refresh_expires_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (realm_id, access_token, refresh_token, token_expires_at, refresh_expires_at))
            conn.commit()
        finally:
            conn.close()

    async def _get_valid_token(self, realm_id: str) -> str:
        conn = get_connection()
        try:
            cursor = conn.execute("SELECT * FROM qbo_credentials WHERE realm_id = ?", (realm_id,))
            row = cursor.fetchone()
            if not row:
                raise Exception("No QBO credentials found")
            cred = dict(row)
        finally:
            conn.close()
            
        expires_at = datetime.fromisoformat(cred["token_expires_at"])
        if expires_at <= datetime.utcnow() + timedelta(minutes=5):
            logger.info("qbo_token_refresh_triggered", realm_id=realm_id)
            auth_header = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.token_url,
                    headers={
                        "Authorization": f"Basic {auth_header}",
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Accept": "application/json"
                    },
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": cred["refresh_token"]
                    }
                )
                response.raise_for_status()
                data = response.json()
                self._save_tokens(realm_id, data)
                return data["access_token"]
        return cred["access_token"]

    async def get_status(self) -> dict:
        conn = get_connection()
        try:
            cursor = conn.execute("SELECT * FROM qbo_credentials LIMIT 1")
            row = cursor.fetchone()
            if not row:
                return {"connected": False}
            cred = dict(row)
            expires_at = datetime.fromisoformat(cred["token_expires_at"])
            return {
                "connected": True,
                "realm_id": cred["realm_id"],
                "expires_at": cred["token_expires_at"],
                "needs_refresh": expires_at <= datetime.utcnow() + timedelta(minutes=5)
            }
        finally:
            conn.close()

    async def disconnect(self) -> None:
        conn = get_connection()
        try:
            conn.execute("DELETE FROM qbo_credentials")
            conn.commit()
        finally:
            conn.close()

    async def push_job_to_qbo(self, job_id: str) -> None:
        conn = get_connection()
        try:
            cursor = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            job_row = cursor.fetchone()
            if not job_row:
                raise Exception("Job not found")
            job = dict(job_row)
            
            cursor = conn.execute("SELECT * FROM qbo_credentials LIMIT 1")
            cred_row = cursor.fetchone()
            if not cred_row:
                raise Exception("QBO not connected")
            realm_id = cred_row["realm_id"]
            
            fin = get_financials(job_id)
            if not fin:
                raise Exception("Financials not found")
                
            cursor = conn.execute("SELECT * FROM qbo_mappings WHERE job_id = ?", (job_id,))
            map_row = cursor.fetchone()
            qbo_mapping = dict(map_row) if map_row else None
        finally:
            conn.close()

        access_token = await self._get_valid_token(realm_id)
        
        async with httpx.AsyncClient() as client:
            client.headers.update({
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
                "Content-Type": "application/json"
            })
            
            customer_id = None
            if qbo_mapping and qbo_mapping.get("qbo_customer_id"):
                customer_id = qbo_mapping["qbo_customer_id"]
            else:
                names = job["homeowner_name"].split(" ", 1)
                first_name = names[0]
                last_name = names[1] if len(names) > 1 else ""
                
                customer_payload = {
                    "DisplayName": f'{job["homeowner_name"]} - {job_id[:4]}',
                    "GivenName": first_name,
                    "FamilyName": last_name,
                    "PrimaryPhone": {"FreeFormNumber": job["phone"]},
                    "BillAddr": {
                        "Line1": job["address_line1"],
                        "City": job["city"],
                        "CountrySubDivisionCode": job["state"],
                        "PostalCode": job["postal_code"]
                    }
                }
                
                res = await client.post(
                    f"{self.api_base}/v3/company/{realm_id}/customer",
                    json=customer_payload
                )
                res.raise_for_status()
                customer_id = res.json()["Customer"]["Id"]
                
                conn = get_connection()
                try:
                    mapping_id = qbo_mapping["id"] if qbo_mapping else str(uuid.uuid4())
                    if qbo_mapping:
                        conn.execute("UPDATE qbo_mappings SET qbo_customer_id = ? WHERE id = ?", (customer_id, mapping_id))
                    else:
                        conn.execute("INSERT INTO qbo_mappings (id, job_id, qbo_customer_id) VALUES (?, ?, ?)", (mapping_id, job_id, customer_id))
                    conn.commit()
                finally:
                    conn.close()
                    
                # Re-fetch mapping after insert
                conn = get_connection()
                try:
                    cursor = conn.execute("SELECT * FROM qbo_mappings WHERE job_id = ?", (job_id,))
                    qbo_mapping = dict(cursor.fetchone())
                finally:
                    conn.close()
                    
            revenue = fin.get("revenue", 0.0)
            deductible = fin.get("deductible", 0.0)
            
            from typing import Dict, Any
            invoice_payload: Dict[str, Any] = {
                "CustomerRef": {"value": customer_id},
                "PrivateNote": f"Job ID: {job_id}\\nClaim: {job.get('claim_number', 'N/A')}",
                "Line": []
            }
            
            if revenue > 0:
                invoice_payload["Line"].append({
                    "DetailType": "SalesItemLineDetail",
                    "Amount": revenue,
                    "SalesItemLineDetail": {
                        "ItemRef": {"value": "1"} 
                    },
                    "Description": "Roofing Scope of Work"
                })
            
            if deductible > 0:
                invoice_payload["Line"].append({
                    "DetailType": "SalesItemLineDetail",
                    "Amount": -deductible,
                    "SalesItemLineDetail": {
                        "ItemRef": {"value": "1"}
                    },
                    "Description": "Homeowner Deductible (Credit)"
                })
                
            res = await client.post(
                f"{self.api_base}/v3/company/{realm_id}/invoice",
                json=invoice_payload
            )
            res.raise_for_status()
            invoice_id = res.json()["Invoice"]["Id"]
            
            conn = get_connection()
            try:
                conn.execute("UPDATE qbo_mappings SET qbo_invoice_id = ? WHERE job_id = ?", (invoice_id, job_id))
                conn.commit()
            finally:
                conn.close()
                
            logger.info("job_pushed_to_qbo", job_id=job_id, customer_id=customer_id, invoice_id=invoice_id)
