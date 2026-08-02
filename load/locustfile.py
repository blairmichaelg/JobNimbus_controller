from locust import HttpUser, task, between

import os

class CRMUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        pin = os.environ.get("LOAD_TEST_ADMIN_PIN")
        if not pin:
            raise Exception(
                "LOAD_TEST_ADMIN_PIN environment variable is required. "
                "Set it to the real admin PIN for the target environment "
                "before running this load test."
            )
        response = self.client.post("/auth/login", data={"pin": pin, "redirect_url": "/"}, allow_redirects=False)
        self.auth_token = response.cookies.get("auth_token", "")

    @task(3)
    def health_check(self):
        """Baseline - should always be fast and cheap"""
        self.client.get("/health")

    @task(2)
    def view_admin_dashboard(self):
        """Simulates office dashboard load"""
        self.client.get("/admin")

    @task(1)
    def create_lead(self):
        """Simulates a canvasser creating a new lead"""
        payload = {
            "homeowner_name": "Test Homeowner",
            "address_line1": "123 Main St",
            "city": "Testville",
            "state": "TS",
            "postal_code": "12345",
            "phone": "555-555-5555"
        }
        self.client.post("/api/field/jobs", json=payload)
