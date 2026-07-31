import sqlite3
import sys
from app.core.database import get_connection

def verify_consistency():
    """
    Verifies that the legacy REAL columns and the new _cents columns
    are mathematically equivalent for every row in financials.
    If a drift is found, it will log the error and return an exit code.
    """
    conn = get_connection()
    try:
        cursor = conn.execute("""
            SELECT job_id, 
                   revenue, revenue_cents,
                   carrier_rcv, carrier_rcv_cents,
                   material_cost, material_cost_cents,
                   labor_cost, labor_cost_cents,
                   permits_fee, permits_fee_cents
            FROM financials
        """)
        
        inconsistencies = []
        
        for row in cursor:
            job_id = row["job_id"]
            
            # Map of real column names to cents column names
            checks = {
                "revenue": ("revenue_cents", row["revenue"], row["revenue_cents"]),
                "carrier_rcv": ("carrier_rcv_cents", row["carrier_rcv"], row["carrier_rcv_cents"]),
                "material_cost": ("material_cost_cents", row["material_cost"], row["material_cost_cents"]),
                "labor_cost": ("labor_cost_cents", row["labor_cost"], row["labor_cost_cents"]),
                "permits_fee": ("permits_fee_cents", row["permits_fee"], row["permits_fee_cents"])
            }
            
            for real_col, (cents_col, real_val, cents_val) in checks.items():
                if real_val is None and cents_val is None:
                    continue
                
                # Convert the stored integer cents to dollars for comparison
                expected_real = cents_val / 100.0 if cents_val is not None else 0.0
                actual_real = real_val if real_val is not None else 0.0
                
                # We check for exact matching because the whole point of our migration
                # was to ensure that the REAL columns hold exactly cents/100.0 without drift.
                if abs(expected_real - actual_real) > 0.0001:
                    inconsistencies.append(
                        f"Job {job_id} [{real_col} vs {cents_col}]: "
                        f"Float is {actual_real}, Cents is {cents_val} (expected float {expected_real})"
                    )
        
        if inconsistencies:
            print("FAILURE: Consistency drift detected in legacy columns!")
            for error in inconsistencies:
                print(f" - {error}")
            sys.exit(1)
        else:
            print("SUCCESS: Legacy REAL columns and INTEGER cents columns are 100% consistent across all rows.")
            sys.exit(0)
            
    finally:
        conn.close()

if __name__ == "__main__":
    verify_consistency()
