"""
V4 Job Costing Engine.
Pure Python domain logic for calculating job profitability and margins.
"""

def compute_job_profitability(revenue: float, materials: float, labor: float, overhead_pct: float, commission_pct: float) -> dict:
    """
    Computes precise industry financial metrics before a build begins.
    
    Returns a dictionary of:
    - direct_costs
    - gross_profit
    - gross_margin
    - overhead_cost
    - net_profit
    - canvasser_commission
    """
    direct_costs = materials + labor
    gross_profit = revenue - direct_costs
    
    # Handle zero division safety
    if revenue > 0.0:
        gross_margin = gross_profit / revenue
    else:
        gross_margin = 0.0
        
    overhead_cost = revenue * overhead_pct
    net_profit = gross_profit - overhead_cost
    canvasser_commission = revenue * commission_pct
    
    return {
        "direct_costs": round(direct_costs, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_margin": round(gross_margin, 4),
        "overhead_cost": round(overhead_cost, 2),
        "net_profit": round(net_profit, 2),
        "canvasser_commission": round(canvasser_commission, 2)
    }
