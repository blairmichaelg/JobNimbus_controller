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

def fetch_storm_data(zipcode: str):
    """
    Mock integration for NOAA/NWS storm events.
    In production, this would query NOAA's Severe Weather Data Inventory (SWDI)
    or National Weather Service APIs based on the zipcode's coordinates.
    """
    # Simulate a hail event if zip starts with '3' (e.g. GA)
    if zipcode.startswith('3'):
        return [
            {
                "event_type": "HAIL",
                "event_date": (datetime.datetime.utcnow() - datetime.timedelta(days=2)).isoformat() + "Z",
                "hail_size_inches": 1.75,
                "wind_speed_mph": 45.0,
                "source": "NOAA_SWDI_MOCK"
            }
        ]
    return []

def main():
    db_path = get_db_path()
    logger.info("starting_storm_ingestion", db=db_path)
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    try:
        # Get unique zipcodes from leads
        cursor = conn.execute("SELECT DISTINCT postal_code FROM jobs WHERE postal_code IS NOT NULL AND postal_code != ''")
        zipcodes = [row["postal_code"] for row in cursor.fetchall()]
        
        events_inserted = 0
        for zc in zipcodes:
            events = fetch_storm_data(zc)
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
