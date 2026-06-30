"""
Unit tests for the V4 Job Costing math engine.
"""

from app.core.job_costing import compute_job_profitability

def test_compute_job_profitability_normal_case():
    """Test standard profitability calculations."""
    results = compute_job_profitability(
        revenue=10000.0,
        materials=3000.0,
        labor=2000.0,
        overhead_pct=0.25,
        commission_pct=0.10
    )
    
    assert results["direct_costs"] == 5000.0
    assert results["gross_profit"] == 5000.0
    assert results["gross_margin"] == 0.5000
    assert results["overhead_cost"] == 2500.0
    assert results["net_profit"] == 2500.0
    assert results["canvasser_commission"] == 1000.0

def test_compute_job_profitability_low_margin():
    """Test when gross margin drops below 35%."""
    results = compute_job_profitability(
        revenue=10000.0,
        materials=4500.0,
        labor=2500.0,
        overhead_pct=0.20,
        commission_pct=0.10
    )
    
    assert results["direct_costs"] == 7000.0
    assert results["gross_profit"] == 3000.0
    assert results["gross_margin"] == 0.3000
    assert results["overhead_cost"] == 2000.0
    assert results["net_profit"] == 1000.0
    assert results["canvasser_commission"] == 1000.0

def test_compute_job_profitability_zero_division_safeguard():
    """Test zero division safeguard when revenue is 0."""
    results = compute_job_profitability(
        revenue=0.0,
        materials=3000.0,
        labor=2000.0,
        overhead_pct=0.25,
        commission_pct=0.10
    )
    
    assert results["direct_costs"] == 5000.0
    assert results["gross_profit"] == -5000.0
    assert results["gross_margin"] == 0.0
    assert results["overhead_cost"] == 0.0
    assert results["net_profit"] == -5000.0
    assert results["canvasser_commission"] == 0.0
