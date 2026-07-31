import sys
import json
import math
import uuid
import sqlite3
import requests
import structlog
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add project root to sys.path to import app modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core.database import get_db_path

logger = structlog.get_logger("scripts.cron_storm_ingest")

def haversine(lat1, lon1, lat2, lon2):
    R = 3958.8  # Earth radius in miles
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def fetch_storm_data():
    logger.info("storm_ingest_started", mode="historical_iem")
    
    zip_path = Path(__file__).resolve().parent.parent / "data" / "zipcodes.json"
    if not zip_path.exists():
        logger.error("missing_zipcodes_file")
        return
        
    with open(zip_path, 'r', encoding='utf-8') as f:
        zipcodes = json.load(f)
        
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    try:
        # Get unique zipcodes from leads
        cursor = conn.execute("SELECT DISTINCT postal_code FROM jobs WHERE postal_code IS NOT NULL AND postal_code != ''")
        active_zips = [row["postal_code"] for row in cursor.fetchall()]
        if not active_zips:
            # If no active jobs, fallback to checking some zipcodes or just abort
            logger.info("no_active_jobs_for_storm_ingestion")
            return
    except Exception as e:
        logger.error("db_query_failed", error=str(e))
        conn.close()
        return

    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=365)
    
    sts = start_date.strftime("%Y-%m-%dT%H:%M:%SZ")
    ets = end_date.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # Georgia WFOs + bordering
    wfos = "FFC,JAX,TAE,CHS,JGX"
    url = f"https://mesonet.agron.iastate.edu/geojson/lsr.php?wfos={wfos}&sts={sts}&ets={ets}"
    
    logger.info("fetching_iem_data", url=url)
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error("iem_fetch_failed", error=str(e))
        conn.close()
        return
        
    features = data.get("features", [])
    storm_features = [f for f in features if f['properties']['typetext'] in ('HAIL', 'TSTM WND GST', 'TSTM WND DMG')]
    
    logger.info("iem_data_fetched", total=len(features), storm=len(storm_features))
    
    inserted = 0
    try:
        for f in storm_features:
            props = f['properties']
            event_type = props['typetext']
            mag = props.get('magnitude', 0.0)
            if mag is None:
                mag = 0.0
            
            try:
                mag = float(mag)
            except (ValueError, TypeError):
                mag = 0.0
                
            lat = f['geometry']['coordinates'][1]
            lon = f['geometry']['coordinates'][0]
            
            matched_zips = []
            for zc in active_zips:
                coords = zipcodes.get(zc)
                if coords and haversine(lat, lon, coords['lat'], coords['lon']) <= 15.0:
                    matched_zips.append(zc)
                    
            if not matched_zips:
                continue
                
            event_time = props['valid']
            
            for zc in matched_zips:
                source_id = f"IEM_LSR_{props['wfo']}_{event_time}_{zc}"
                
                cur = conn.execute("SELECT 1 FROM storm_events WHERE source = ?", (source_id,))
                if not cur.fetchone():
                    conn.execute('''
                        INSERT INTO storm_events (id, zipcode, event_type, event_date, hail_size_inches, wind_speed_mph, source)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        str(uuid.uuid4()), zc, event_type, event_time[:10],
                        mag if event_type == 'HAIL' else 0.0,
                        mag if 'WND' in event_type else 0.0,
                        source_id
                    ))
                    inserted += 1
        conn.commit()
    except Exception as e:
        logger.error("db_insert_failed", error=str(e))
        conn.rollback()
    finally:
        conn.close()
        
    logger.info("storm_ingest_completed", inserted=inserted)

if __name__ == "__main__":
    fetch_storm_data()
