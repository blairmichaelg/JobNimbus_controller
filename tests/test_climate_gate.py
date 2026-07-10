import pytest
from app.workers.supplement_processor import generate_and_gate_flags
from app.core.database import get_connection

@pytest.fixture
def setup_test_jobs():
    conn = get_connection()
    try:
        # Create a Georgia job (climate gate False)
        conn.execute('''
            INSERT INTO jobs (id, homeowner_name, address_line1, city, state, postal_code, phone)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', ("TEST-GA-JOB", "GA Homeowner", "123 GA St", "Atlanta", "GA", "30000", "555-5555"))
        
        # Create a Minnesota job (climate gate True)
        conn.execute('''
            INSERT INTO jobs (id, homeowner_name, address_line1, city, state, postal_code, phone)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', ("TEST-MN-JOB", "MN Homeowner", "456 MN St", "Minneapolis", "MN", "55000", "555-5555"))
        
        # Create a Virginia job (climate gate None)
        conn.execute('''
            INSERT INTO jobs (id, homeowner_name, address_line1, city, state, postal_code, phone)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', ("TEST-VA-JOB", "VA Homeowner", "789 VA St", "Richmond", "VA", "23218", "555-5555"))
        
        conn.commit()
    finally:
        conn.close()
        
    yield
    
    conn = get_connection()
    try:
        conn.execute("DELETE FROM supplement_flags WHERE job_id IN ('TEST-GA-JOB', 'TEST-MN-JOB', 'TEST-VA-JOB')")
        conn.execute("DELETE FROM jobs WHERE id IN ('TEST-GA-JOB', 'TEST-MN-JOB', 'TEST-VA-JOB')")
        conn.commit()
    finally:
        conn.close()

def test_climate_gate_blocks_iws_in_georgia(setup_test_jobs):
    """
    Asserts that supplement_flags contains zero rows for a climate-dependent rule (IWS)
    on a Georgia job where ice_barrier_required is False.
    """
    from app.core.supplement_models import EagleViewData
    ev_data = EagleViewData(
        total_area_sf=1000.0, rake_lf=0.0, valley_lf=20.0, ridge_lf=0.0,
        hip_lf=0.0, eaves_lf=50.0, drip_edge_lf=0.0, flashing_lf=0.0,
        step_flashing_lf=0.0, total_facets=2, predominant_pitch="6/12"
    )
    # Trigger flag generation (ice_barrier_required = False)
    generate_and_gate_flags("TEST-GA-JOB", ice_barrier_required=False, ev_data=ev_data)
    
    conn = get_connection()
    try:
        # Check IWS rule flags (climate_dependent = 1)
        cursor = conn.execute('''
            SELECT f.id FROM supplement_flags f
            JOIN supplement_rules r ON f.rule_id = r.id
            WHERE f.job_id = ? AND r.climate_dependent = 1
        ''', ("TEST-GA-JOB",))
        iws_flags = cursor.fetchall()
        assert len(iws_flags) == 0, "Georgia job incorrectly generated a climate-dependent flag (IWS)"
        
        # Ensure DRIP rule (climate_dependent = 0) STILL generated
        cursor = conn.execute('''
            SELECT f.id FROM supplement_flags f
            JOIN supplement_rules r ON f.rule_id = r.id
            WHERE f.job_id = ? AND r.climate_dependent = 0
        ''', ("TEST-GA-JOB",))
        drip_flags = cursor.fetchall()
        assert len(drip_flags) > 0, "Georgia job incorrectly blocked non-climate dependent rules (DRIP)"
    finally:
        conn.close()

def test_climate_gate_allows_iws_in_minnesota(setup_test_jobs):
    """
    Asserts that supplement_flags DOES contain a row for the climate-dependent rule (IWS)
    on a Minnesota job where ice_barrier_required is True.
    """
    from app.core.supplement_models import EagleViewData
    ev_data = EagleViewData(
        total_area_sf=1000.0, rake_lf=0.0, valley_lf=20.0, ridge_lf=0.0,
        hip_lf=0.0, eaves_lf=50.0, drip_edge_lf=0.0, flashing_lf=0.0,
        step_flashing_lf=0.0, total_facets=2, predominant_pitch="6/12"
    )
    # Trigger flag generation (ice_barrier_required = True)
    generate_and_gate_flags("TEST-MN-JOB", ice_barrier_required=True, ev_data=ev_data)
    
    conn = get_connection()
    try:
        # Check IWS rule flags (climate_dependent = 1)
        cursor = conn.execute('''
            SELECT f.id FROM supplement_flags f
            JOIN supplement_rules r ON f.rule_id = r.id
            WHERE f.job_id = ? AND r.climate_dependent = 1
        ''', ("TEST-MN-JOB",))
        iws_flags = cursor.fetchall()
        assert len(iws_flags) > 0, "Minnesota job incorrectly blocked a climate-dependent flag (IWS)"
    finally:
        conn.close()

def test_climate_gate_blocks_iws_when_ambiguous(setup_test_jobs):
    """
    Asserts that supplement_flags contains zero rows for a climate-dependent rule (IWS)
    on an ambiguous job (e.g. Virginia) where ice_barrier_required is None.
    """
    from app.core.supplement_models import EagleViewData
    ev_data = EagleViewData(
        total_area_sf=1000.0, rake_lf=0.0, valley_lf=20.0, ridge_lf=0.0,
        hip_lf=0.0, eaves_lf=50.0, drip_edge_lf=0.0, flashing_lf=0.0,
        step_flashing_lf=0.0, total_facets=2, predominant_pitch="6/12"
    )
    # Trigger flag generation (ice_barrier_required = None)
    generate_and_gate_flags("TEST-VA-JOB", ice_barrier_required=None, ev_data=ev_data)
    
    conn = get_connection()
    try:
        # Check IWS rule flags (climate_dependent = 1)
        cursor = conn.execute('''
            SELECT f.id FROM supplement_flags f
            JOIN supplement_rules r ON f.rule_id = r.id
            WHERE f.job_id = ? AND r.climate_dependent = 1
        ''', ("TEST-VA-JOB",))
        iws_flags = cursor.fetchall()
        assert len(iws_flags) == 0, "Ambiguous job (Virginia) incorrectly generated a climate-dependent flag (IWS)"
    finally:
        conn.close()
