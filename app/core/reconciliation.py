"""
Pure Python reconciliation engine.

Deterministically compares normalized EagleView measurement data
against extracted Carrier Statement of Loss line items to generate
a DiscrepancyReport. This isolates all math from the LLM.
"""

import math

from app.core.supplement_models import (
    EagleViewData,
    StatementOfLoss,
    Discrepancy,
    DiscrepancyReport,
    MaterialBOM
)
from app.core.complexity import (
    compute_complexity_score,
    calculate_dynamic_waste,
    build_waste_explanation
)
import app.core.coverage_constants as constants


def reconcile(ev: EagleViewData, sol: StatementOfLoss, job_id: str) -> DiscrepancyReport:
    """
    Deterministically reconcile EV measurements against SoL items.
    """
    discrepancies = []

    # 1. Dynamic Waste & Area Computation
    score = compute_complexity_score(ev)
    waste_pct = calculate_dynamic_waste(score)
    waste_explanation = build_waste_explanation(ev, waste_pct)
    
    ev_normalized_squares = round((ev.total_area_sf / 100.0) * (1.0 + waste_pct), 2)
    
    sol_total_rfg_squares = 0.0
    sq_items = [
        item.quantity for item in sol.line_items 
        if item.quantity is not None 
        and item.unit_of_measure 
        and item.unit_of_measure.upper().strip() in ("SQ", "SQ.")
    ]
    if sq_items:
        sol_total_rfg_squares = max(sq_items)

    square_variance = round(ev_normalized_squares - sol_total_rfg_squares, 2)

    if square_variance > 0.01:
        discrepancies.append(
            Discrepancy(
                category="Area Shortage",
                description=f"Carrier allowed {sol_total_rfg_squares} SQ. EagleView normalized is {ev_normalized_squares} SQ.",
                ev_value=ev_normalized_squares,
                sol_value=sol_total_rfg_squares,
                variance=square_variance,
            )
        )

    # 2. Ice & Water Shield (Valleys)
    if ev.valley_lf > 0:
        found_ice_water = any(
            "ice" in item.description.lower() or 
            "water" in item.description.lower() or 
            "barrier" in item.description.lower()
            for item in sol.line_items if item.description
        )
        if not found_ice_water:
            discrepancies.append(
                Discrepancy(
                    category="Missing Ice & Water Shield",
                    description=f"EagleView shows {ev.valley_lf} LF of valleys, but no Ice & Water Shield is included in the SoL.",
                    ev_value=ev.valley_lf,
                    sol_value=0.0,
                    variance=ev.valley_lf,
                )
            )

    # 3. Ridge / Hip Cap
    total_ridge_hip_lf = ev.ridge_lf + ev.hip_lf
    if total_ridge_hip_lf > 0:
        ridge_items = [
            item.quantity for item in sol.line_items
            if item.quantity is not None 
            and item.description 
            and ("ridge" in item.description.lower() or "hip" in item.description.lower())
            and item.unit_of_measure
            and item.unit_of_measure.upper() in ("LF", "LF.")
        ]
        
        # Max of the ridge items to avoid double-counting remove/replace
        sol_ridge_hip_lf = max(ridge_items) if ridge_items else 0.0
        
        ridge_variance = round(total_ridge_hip_lf - sol_ridge_hip_lf, 2)
        if ridge_variance > 0.01:
            discrepancies.append(
                Discrepancy(
                    category="Ridge/Hip Cap Shortage",
                    description=f"EagleView shows {total_ridge_hip_lf} LF of Ridges & Hips. Carrier allowed {sol_ridge_hip_lf} LF.",
                    ev_value=total_ridge_hip_lf,
                    sol_value=sol_ridge_hip_lf,
                    variance=ridge_variance,
                )
            )

    # 4. Overhead & Profit Check
    if sol.overhead_and_profit_included is False:
        discrepancies.append(
            Discrepancy(
                category="Missing O&P",
                description="Overhead and Profit (O&P) is missing from the Carrier Statement of Loss.",
                ev_value=None,
                sol_value=None,
                variance=None,
            )
        )

    # 5. Deterministic Material BOM
    bom = MaterialBOM(
        field_shingle_bundles=math.ceil(ev_normalized_squares * constants.SHINGLE_BUNDLES_PER_SQUARE),
        starter_bundles=math.ceil((ev.eaves_lf + ev.rake_lf) / constants.STARTER_LF_PER_BUNDLE),
        ridge_cap_bundles=math.ceil(total_ridge_hip_lf / constants.HIP_RIDGE_LF_PER_BUNDLE),
        ice_water_rolls=math.ceil((ev.valley_lf * 3.0) / constants.ICE_WATER_SF_PER_ROLL),
        underlayment_rolls=math.ceil(ev_normalized_squares / constants.UNDERLAYMENT_SQUARES_PER_ROLL),
    )

    return DiscrepancyReport(
        job_id=job_id,
        ev_normalized_squares=ev_normalized_squares,
        sol_total_rfg_squares=sol_total_rfg_squares,
        square_variance=square_variance,
        waste_explanation=waste_explanation,
        material_bom=bom,
        discrepancies=discrepancies,
    )
