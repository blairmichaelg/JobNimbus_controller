"""
Unit tests for the deterministic reconciliation engine.
"""

from app.core.reconciliation import reconcile
from app.core.supplement_models import EagleViewData, StatementOfLoss, LineItem


def test_reconcile_square_variance():
    ev = EagleViewData(
        total_area_sf=6788.0, rake_lf=0, valley_lf=0, ridge_lf=0, hip_lf=0,
        eaves_lf=0, drip_edge_lf=0, flashing_lf=0, step_flashing_lf=0,
        total_facets=1, predominant_pitch="10/12"
    )
    # Complexity: facets(1 * 0.2) + pitch(3 * 0.5) = 1.7
    # Waste: 0.10 + 0.017 = 0.117 (rounded to 0.12)
    # Normalized SQ: (6788 / 100) * 1.12 = 76.03
    
    sol = StatementOfLoss(
        line_items=[
            LineItem(trade="Roof", code="1", description="Remove", quantity=23.0, unit_of_measure="SQ"),
            LineItem(trade="Roof", code="2", description="Replace", quantity=25.0, unit_of_measure="SQ"),
        ],
        overhead_and_profit_included=True
    )
    
    # sol_total_rfg_squares should be max(23.0, 25.0) = 25.0
    report = reconcile(ev, sol, "job_1")
    
    assert report.sol_total_rfg_squares == 25.0
    assert report.square_variance == 51.03
    assert report.ev_normalized_squares == 76.03
    
    area_disc = next((d for d in report.discrepancies if d.category == "Area Shortage"), None)
    assert area_disc is not None
    assert area_disc.variance == 51.03


def test_reconcile_missing_ice_and_water():
    ev = EagleViewData(
        total_area_sf=1000.0, rake_lf=0, valley_lf=50.0, ridge_lf=0, hip_lf=0,
        eaves_lf=0, drip_edge_lf=0, flashing_lf=0, step_flashing_lf=0,
        total_facets=1, predominant_pitch="10/12"
    )
    
    sol = StatementOfLoss(
        line_items=[
            LineItem(trade="Roof", code="1", description="Shingles", quantity=10.0, unit_of_measure="SQ"),
        ],
        overhead_and_profit_included=True
    )
    
    report = reconcile(ev, sol, "job_1")
    
    iw_disc = next((d for d in report.discrepancies if d.category == "Missing Ice & Water Shield"), None)
    assert iw_disc is not None
    assert iw_disc.ev_value == 50.0


def test_reconcile_found_ice_and_water():
    ev = EagleViewData(
        total_area_sf=1000.0, rake_lf=0, valley_lf=50.0, ridge_lf=0, hip_lf=0,
        eaves_lf=0, drip_edge_lf=0, flashing_lf=0, step_flashing_lf=0,
        total_facets=1, predominant_pitch="10/12"
    )
    
    sol = StatementOfLoss(
        line_items=[
            LineItem(trade="Roof", code="1", description="Ice and Water Barrier", quantity=200.0, unit_of_measure="SF"),
        ],
        overhead_and_profit_included=True
    )
    
    report = reconcile(ev, sol, "job_1")
    
    iw_disc = next((d for d in report.discrepancies if d.category == "Missing Ice & Water Shield"), None)
    assert iw_disc is None


def test_reconcile_ridge_hip_shortage():
    ev = EagleViewData(
        total_area_sf=1000.0, rake_lf=0, valley_lf=0, ridge_lf=50.0, hip_lf=50.0,
        eaves_lf=0, drip_edge_lf=0, flashing_lf=0, step_flashing_lf=0,
        total_facets=1, predominant_pitch="10/12"
    )
    # Total ridge/hip = 100.0
    
    sol = StatementOfLoss(
        line_items=[
            LineItem(trade="Roof", code="1", description="Ridge Cap", quantity=40.0, unit_of_measure="LF"),
        ],
        overhead_and_profit_included=True
    )
    
    report = reconcile(ev, sol, "job_1")
    
    ridge_disc = next((d for d in report.discrepancies if d.category == "Ridge/Hip Cap Shortage"), None)
    assert ridge_disc is not None
    assert ridge_disc.variance == 60.0


def test_reconcile_missing_op():
    ev = EagleViewData(
        total_area_sf=1000.0, rake_lf=0, valley_lf=0, ridge_lf=0, hip_lf=0,
        eaves_lf=0, drip_edge_lf=0, flashing_lf=0, step_flashing_lf=0,
        total_facets=1, predominant_pitch="10/12"
    )
    
    sol = StatementOfLoss(
        line_items=[],
        overhead_and_profit_included=False
    )
    
    report = reconcile(ev, sol, "job_1")
    
    op_disc = next((d for d in report.discrepancies if d.category == "Missing O&P"), None)
    assert op_disc is not None


def test_reconcile_bom_calculation():
    ev = EagleViewData(
        total_area_sf=6788.0, rake_lf=114.0, valley_lf=288.0, ridge_lf=120.0, hip_lf=315.0,
        eaves_lf=276.0, drip_edge_lf=390.0, flashing_lf=3.0, step_flashing_lf=16.0,
        total_facets=26, predominant_pitch="10/12"
    )
    sol = StatementOfLoss(line_items=[], overhead_and_profit_included=True)
    report = reconcile(ev, sol, "job_1")
    
    # 26 facets * 0.2 = 5.2
    # 10/12 pitch = 1.5
    # 288 valley / 50 = 5.76 * 0.5 = 2.88
    # Total score = 5.2 + 1.5 + 2.88 = 9.58
    # Waste = 0.10 + 0.0958 = 0.1958 -> clamp/round to 0.20
    # SQ = 67.88 * 1.20 = 81.46
    
    bom = report.material_bom
    assert bom.field_shingle_bundles == 245  # ceil(81.46 * 3)
    assert bom.starter_bundles == 4          # ceil((276 + 114) / 100) -> 390 / 100 = 3.9 -> 4
    assert bom.ridge_cap_bundles == 14       # ceil((120 + 315) / 33) -> 435 / 33 = 13.18 -> 14
    assert bom.ice_water_rolls == 5          # ceil((288 * 3) / 200) -> 864 / 200 = 4.32 -> 5
    assert bom.underlayment_rolls == 9       # ceil(81.46 / 10) -> 8.146 -> 9

