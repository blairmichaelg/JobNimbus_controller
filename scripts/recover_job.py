import sys
import os

# Add root dir to sys.path to allow importing app modules natively
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.core.database import update_job_status, JobStatus

def recover_job(job_id: str, target_status: str):
    print(f"===========================================================")
    print(f"Emergency Database Mutator: {job_id}")
    print(f"===========================================================")
    
    try:
        # Validate status enum manually so we fail fast before mutating
        valid_status = JobStatus(target_status)
        update_job_status(job_id, valid_status, note="Emergency manual SRE recovery")
        print(f"\n[SUCCESS] Job {job_id} forced to status: {valid_status.value}")
    except ValueError as ve:
        print(f"\n[FAILED] {ve}")
        print("Valid statuses:")
        for s in JobStatus:
            print(f"  - {s.value}")
    except Exception as e:
        print(f"\n[FAILED] Database mutation failed: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python scripts/recover_job.py <job_id> <TARGET_STATUS>")
    else:
        recover_job(sys.argv[1], sys.argv[2])
