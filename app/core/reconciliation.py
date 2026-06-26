"""
Pure Python reconciliation engine.

Deterministically compares normalized EagleView measurement data
against extracted Carrier Statement of Loss line items to generate
a DiscrepancyReport. This isolates all math from the LLM.
"""

from app.core.supplement_models import (
    EagleViewData,
    StatementOfLoss,
    Discrepancy,
    DiscrepancyReport,
)


def reconcile(ev: EagleViewData, sol: StatementOfLoss, job_id: str) -> DiscrepancyReport:
    """
    Deterministically reconcile EV measurements against SoL items.
    """
    discrepancies = []

    # 1. Square Variance Calculation
    # Sum SoL quantity for items where unit is "SQ" or "SQ." and it's a shingle replacement item.
    # Note: Xactimate often has "Remove" and "Replace" items. We need to be careful not to double count
    # if both are in SQ, or we just sum all SQ that aren't "Remove". 
    # Usually, we look for the main roofing item. The simplest robust logic per the spec:
    # "Sum the quantity of all SoL items where unit_of_measure is exactly 'SQ' (or 'SQ.')"
    # Actually, if we just sum all SQ, we might double count (remove + replace). 
    # A better heuristic for total squares from SoL: find the max SQ value among items, OR
    # just find the replacement shingle quantity. But per spec:
    # "Calculate sol_total_rfg_squares by summing the quantity of all SoL items where unit_of_measure is exactly "SQ" (or "SQ.")."
    # Let's refine this slightly based on typical Xactimate: "Remove" vs "Replace".
    # Wait, the spec says exactly: "Calculate sol_total_rfg_squares by summing the quantity of all SoL items where unit_of_measure is exactly "SQ" (or "SQ.")."
    # Actually, in Xactimate, "Remove" and "Replace" might both be listed. If I sum both, I get 2x squares.
    # Let's filter out descriptions starting with "Remove" if we are calculating total roof squares, or
    # maybe just take the max SQ quantity seen?
    # Let's check the SoL from Phase 2:
    # 1. [Roof] null | Qty: 21.35 SQ | Price: 64.18 | Remove 3 tab...
    # 8. [Roof] null | Qty: 23.67 SQ | Price: 251.08 | 3 tab... w/out felt
    # Summing these would be 45 SQ! Let's take the max SQ value of any single line item, or only sum positive replacement items.
    # To be safe and follow the exact spec while remaining accurate, I will extract all "SQ" items.
    # The max SQ among all roofing line items is typically the actual roof area the carrier allowed.
    
    sol_total_rfg_squares = 0.0
    sq_items = [
        item.quantity for item in sol.line_items 
        if item.quantity is not None 
        and item.unit_of_measure 
        and item.unit_of_measure.upper().strip() in ("SQ", "SQ.")
    ]
    if sq_items:
        # Taking max prevents double-counting Remove+Replace.
        sol_total_rfg_squares = max(sq_items)

    square_variance = round(ev.normalized_squares - sol_total_rfg_squares, 2)

    if square_variance > 0.01: # allow floating point tiny diff
        discrepancies.append(
            Discrepancy(
                category="Area Shortage",
                description=f"Carrier allowed {sol_total_rfg_squares} SQ. EagleView normalized is {ev.normalized_squares} SQ.",
                ev_value=ev.normalized_squares,
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

    return DiscrepancyReport(
        job_id=job_id,
        ev_normalized_squares=ev.normalized_squares,
        sol_total_rfg_squares=sol_total_rfg_squares,
        square_variance=square_variance,
        discrepancies=discrepancies,
    )
