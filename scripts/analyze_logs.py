import json
from datetime import datetime, timedelta
from pathlib import Path

def analyze_logs(log_file="data/logs/truck_server.log", hours=1):
    log_path = Path(log_file)
    if not log_path.exists():
        print(f"Log file not found at {log_path}. Ensure structlog is piping to this file.")
        return

    cutoff = datetime.utcnow() - timedelta(hours=hours)
    
    print("===========================================================")
    print(f"Dry Run Diagnostics: Scanning for ERROR/CRITICAL (Last {hours}h)")
    print("===========================================================\n")
    
    count = 0
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            try:
                entry = json.loads(line)
                level = entry.get("level", "").upper()
                
                if level in ("ERROR", "CRITICAL"):
                    timestamp_str = entry.get("timestamp", "")
                    if timestamp_str:
                        # Clean Z suffix for isoformat parsing if present
                        clean_ts = timestamp_str.replace("Z", "+00:00")
                        log_time = datetime.fromisoformat(clean_ts).replace(tzinfo=None)
                        if log_time < cutoff:
                            continue
                            
                    job_id = entry.get("job_id", "UNKNOWN_JOB")
                    event = entry.get("event", "UNKNOWN_EVENT")
                    logger_name = entry.get("logger", "UNKNOWN_STAGE")
                    
                    print(f"[{level}] {timestamp_str}")
                    print(f"  Stage   : {logger_name}")
                    print(f"  Job ID  : {job_id}")
                    print(f"  Event   : {event}")
                    if "error" in entry:
                        print(f"  Trace   : {entry['error']}")
                    print("-" * 60)
                    count += 1
            except Exception:
                # Silently skip lines that aren't valid JSON
                pass

    if count == 0:
        print("All green. No errors found in the specified timeframe.")
    else:
        print(f"\nFound {count} critical issue(s). Use scripts/recover_job.py if pipeline is stuck.")

if __name__ == "__main__":
    analyze_logs()
