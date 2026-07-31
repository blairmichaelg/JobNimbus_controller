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
    SERVICE_AREA_ZIPS = ["30286", "30410", "30411", "30412", "30421", "30427", "30428", "30436", "30445", "30453", "30454", "30457", "30470", "30473", "30474", "30475", "31001", "31002", "31003", "31005", "31006", "31007", "31008", "31009", "31011", "31012", "31014", "31015", "31016", "31017", "31019", "31020", "31021", "31022", "31023", "31025", "31027", "31028", "31030", "31036", "31037", "31039", "31041", "31042", "31044", "31047", "31050", "31051", "31052", "31055", "31057", "31058", "31060", "31063", "31065", "31066", "31068", "31069", "31070", "31071", "31072", "31075", "31076", "31077", "31078", "31079", "31081", "31083", "31084", "31088", "31091", "31092", "31093", "31097", "31098", "31201", "31204", "31206", "31207", "31210", "31211", "31213", "31216", "31217", "31220", "31501", "31503", "31510", "31512", "31513", "31516", "31518", "31519", "31523", "31532", "31533", "31535", "31537", "31539", "31542", "31543", "31544", "31545", "31546", "31547", "31548", "31549", "31550", "31551", "31552", "31553", "31554", "31555", "31556", "31557", "31560", "31562", "31563", "31565", "31566", "31567", "31568", "31569", "31601", "31602", "31605", "31606", "31620", "31622", "31623", "31624", "31625", "31626", "31627", "31629", "31630", "31631", "31632", "31634", "31635", "31636", "31637", "31638", "31639", "31641", "31642", "31643", "31645", "31647", "31648", "31649", "31650", "31698", "31699", "31701", "31705", "31707", "31709", "31711", "31712", "31714", "31716", "31719", "31720", "31721", "31722", "31730", "31733", "31735", "31738", "31743", "31744", "31747", "31749", "31750", "31756", "31757", "31763", "31764", "31765", "31768", "31771", "31772", "31773", "31774", "31775", "31778", "31779", "31780", "31781", "31783", "31784", "31787", "31788", "31789", "31790", "31791", "31792", "31793", "31794", "31795", "31796", "31798", "31801", "31803", "31804", "31805", "31806", "31807", "31808", "31810", "31811", "31812", "31814", "31815", "31816", "31820", "31821", "31823", "31824", "31825", "31826", "31827", "31829", "31831", "31832", "31836", "31901", "31903", "31904", "31905", "31906", "31907", "31909", "32003", "32008", "32009", "32011", "32024", "32025", "32026", "32038", "32040", "32043", "32044", "32046", "32052", "32053", "32054", "32055", "32058", "32059", "32060", "32061", "32062", "32063", "32064", "32065", "32066", "32068", "32071", "32072", "32073", "32079", "32083", "32087", "32091", "32094", "32096", "32097", "32113", "32140", "32202", "32204", "32205", "32206", "32207", "32208", "32209", "32210", "32211", "32212", "32217", "32218", "32219", "32220", "32221", "32222", "32223", "32234", "32244", "32254", "32277", "32301", "32303", "32304", "32305", "32308", "32309", "32310", "32311", "32312", "32317", "32320", "32321", "32322", "32323", "32324", "32327", "32328", "32330", "32331", "32332", "32333", "32334", "32336", "32340", "32343", "32344", "32346", "32347", "32348", "32350", "32351", "32352", "32355", "32356", "32358", "32359", "32361", "32399", "32401", "32403", "32404", "32405", "32407", "32408", "32409", "32410", "32413", "32420", "32421", "32423", "32424", "32425", "32426", "32427", "32428", "32430", "32431", "32432", "32433", "32435", "32437", "32438", "32439", "32440", "32442", "32443", "32444", "32445", "32446", "32447", "32448", "32449", "32455", "32456", "32459", "32460", "32461", "32462", "32463", "32464", "32465", "32466", "32539", "32541", "32542", "32550", "32567", "32578", "32580", "32601", "32603", "32605", "32606", "32607", "32608", "32609", "32612", "32615", "32616", "32618", "32619", "32621", "32622", "32625", "32626", "32628", "32631", "32639", "32640", "32641", "32643", "32648", "32653", "32656", "32658", "32664", "32666", "32667", "32668", "32669", "32680", "32681", "32683", "32686", "32692", "32693", "32694", "32696", "32697", "34431", "34449", "34482", "34498", "36005", "36009", "36010", "36016", "36017", "36027", "36028", "36029", "36031", "36034", "36035", "36039", "36048", "36049", "36053", "36079", "36081", "36082", "36083", "36089", "36301", "36303", "36305", "36310", "36311", "36312", "36313", "36314", "36316", "36317", "36318", "36319", "36320", "36321", "36322", "36323", "36330", "36340", "36343", "36344", "36345", "36346", "36350", "36351", "36352", "36353", "36360", "36362", "36370", "36371", "36373", "36374", "36375", "36376", "36442", "36453", "36455", "36467", "36477", "36804", "36830", "36856", "36858", "36859", "36860", "36867", "36869", "36870", "36871", "36874", "36875", "36877", "39813", "39815", "39817", "39819", "39823", "39824", "39825", "39826", "39827", "39828", "39834", "39836", "39837", "39840", "39841", "39842", "39845", "39846", "39851", "39854", "39859", "39861", "39862", "39866", "39867", "39870", "39877", "39885", "39886", "39897"]
    active_zips = SERVICE_AREA_ZIPS

    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=365)
    
    sts = start_date.strftime("%Y-%m-%dT%H:%M:%SZ")
    ets = end_date.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # Georgia WFOs + bordering
    wfos = "TAE,JAX,FFC"
    # TAE (Tallahassee, FL) - Thomasville, Valdosta, Tifton, Albany, Moultrie, Cairo, Bainbridge, Dothan AL, Panama City FL
    # JAX (Jacksonville, FL) - Waycross, Douglas
    # FFC (Peachtree City, GA) - Columbus GA
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
