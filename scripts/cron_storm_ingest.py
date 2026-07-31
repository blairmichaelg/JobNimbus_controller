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
    
    # Static list of zip codes representing the Thomasville + ~2hr drive time service area
    SERVICE_AREA_ZIPS = ["31001", "31015", "31072", "31077", "31079", "31084", "31092", "31512", "31519", "31533", "31535", "31550", "31552", "31601", "31602", "31605", "31606", "31620", "31622", "31623", "31624", "31625", "31626", "31627", "31629", "31630", "31631", "31632", "31634", "31635", "31636", "31637", "31638", "31639", "31641", "31642", "31643", "31645", "31647", "31648", "31649", "31650", "31698", "31699", "31701", "31705", "31707", "31709", "31712", "31714", "31716", "31719", "31720", "31721", "31722", "31730", "31733", "31735", "31738", "31743", "31744", "31747", "31749", "31750", "31756", "31757", "31763", "31764", "31765", "31768", "31771", "31772", "31773", "31774", "31775", "31778", "31779", "31780", "31781", "31783", "31784", "31787", "31788", "31789", "31790", "31791", "31792", "31793", "31794", "31795", "31796", "31798", "31824", "31832", "39813", "39815", "39817", "39819", "39823", "39824", "39825", "39826", "39827", "39828", "39834", "39836", "39837", "39840", "39841", "39842", "39845", "39846", "39851", "39859", "39861", "39862", "39866", "39867", "39870", "39877", "39885", "39886", "39897"]
    active_zips = SERVICE_AREA_ZIPS

    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=365)
    
    sts = start_date.strftime("%Y-%m-%dT%H:%M:%SZ")
    ets = end_date.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # Georgia WFOs + bordering
    wfos = "TAE,JAX"
    # TAE (Tallahassee, FL) - Thomasville, Valdosta, Tifton, Albany, Moultrie, Cairo, Bainbridge
    # JAX (Jacksonville, FL) - Waycross, Douglas
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
