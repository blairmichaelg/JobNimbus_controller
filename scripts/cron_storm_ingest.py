import sys
import os
import json
import uuid
import requests
import sqlite3
import datetime
import structlog
from pathlib import Path

# Add project root to sys.path to import app modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core.database import get_db_path

logger = structlog.get_logger("scripts.cron_storm_ingest")

def fetch_storm_data(zipcode: str, zip_map: dict):
    """
    Real integration for NOAA/NWS storm events.
    Queries National Weather Service API based on the zipcode's coordinates.
    """
    coords = zip_map.get(zipcode)
    if not coords:
        logger.warning("zipcode_coords_not_found", zipcode=zipcode)
        return []
        
    lat = coords["lat"]
    lon = coords["lon"]
    
    url = f"https://api.weather.gov/alerts/active?point={lat},{lon}"
    headers = {"User-Agent": "WickhamRoofing/1.0 (info@wickhamroofing.com)"}
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error("nws_api_fetch_failed", zipcode=zipcode, error=str(e))
        return []
        
    features = data.get("features", [])
    events = []
    
    for feature in features:
        props = feature.get("properties", {})
        event_name = props.get("event", "Unknown Event")
        parameters = props.get("parameters", {})
        
        # Extract hail and wind if available (stored as arrays in NWS API)
        hail_size = parameters.get("hailSize", [0.0])[0]
        wind_gust = parameters.get("windGust", [0.0])[0]
        
        # Convert string to float safely
        try:
            hail_size = float(hail_size) if hail_size else 0.0
        except ValueError:
            hail_size = 0.0
            
        try:
            # Wind gust might come as "60 mph" or just "60", safely extract numeric
            if isinstance(wind_gust, str):
                wind_gust = float(''.join(filter(lambda x: x.isdigit() or x == '.', wind_gust)))
            else:
                wind_gust = float(wind_gust) if wind_gust else 0.0
        except ValueError:
            wind_gust = 0.0
            
        event_date = props.get("sent", (datetime.datetime.utcnow()).isoformat() + "Z")
        
        # We only care if there's significant wind or hail
        if hail_size > 0 or wind_gust > 40:
            events.append({
                "event_type": event_name.upper(),
                "event_date": event_date,
                "hail_size_inches": hail_size,
                "wind_speed_mph": wind_gust,
                "source": "NWS_API"
            })
            
    return events

def main():
    db_path = get_db_path()
    logger.info("starting_storm_ingestion", db=db_path)
    
    zip_map_path = Path(__file__).resolve().parent.parent / "data" / "zipcodes.json"
    if not zip_map_path.exists():
        logger.error("zipcodes_mapping_not_found", path=str(zip_map_path))
        return
        
    with open(zip_map_path, "r", encoding="utf-8") as f:
        zip_map = json.load(f)
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    try:
        # Get unique zipcodes from leads
        cursor = conn.execute("SELECT DISTINCT postal_code FROM jobs WHERE postal_code IS NOT NULL AND postal_code != ''")
        zipcodes = [row["postal_code"] for row in cursor.fetchall()]
        
        events_inserted = 0
        for zc in zipcodes:
            events = fetch_storm_data(zc, zip_map)
            for ev in events:
                conn.execute('''
                    INSERT INTO storm_events (id, zipcode, event_type, event_date, hail_size_inches, wind_speed_mph, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    str(uuid.uuid4()), zc, ev["event_type"], ev["event_date"], 
                    ev["hail_size_inches"], ev["wind_speed_mph"], ev["source"]
                ))
                events_inserted += 1
                
        conn.commit()
        logger.info("storm_ingestion_complete", zipcodes_checked=len(zipcodes), events_inserted=events_inserted)
    except Exception as e:
        logger.error("storm_ingestion_failed", error=str(e))
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    main()
