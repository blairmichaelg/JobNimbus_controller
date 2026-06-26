"""
Complexity engine to dynamically calculate roofing waste factors.

Replaces the static 15% assumption with a deterministic algorithm based
on EagleView measurements (facets, pitch, and valleys).
"""

import math
from app.core.supplement_models import EagleViewData


def _parse_pitch(pitch_str: str) -> float:
    """Safely parse a pitch string (e.g. '10/12') to a float (e.g. 10.0)."""
    if not pitch_str:
        return 0.0
    try:
        # Get the numerator
        parts = pitch_str.split("/")
        return float(parts[0])
    except (ValueError, IndexError):
        return 0.0


def compute_complexity_score(ev_data: EagleViewData) -> float:
    """
    Calculate a complexity score based on roof geometry.
    - Each facet adds 0.2 points.
    - Pitch > 7/12 adds 0.5 points per degree over 7.
    - Every 50 LF of valley adds 0.5 points.
    """
    score = 0.0
    
    # 1. Facets
    score += ev_data.total_facets * 0.2
    
    # 2. Pitch
    pitch_val = _parse_pitch(ev_data.predominant_pitch)
    if pitch_val > 7.0:
        score += (pitch_val - 7.0) * 0.5
        
    # 3. Valleys
    score += (ev_data.valley_lf / 50.0) * 0.5
    
    return round(score, 2)


def calculate_dynamic_waste(score: float) -> float:
    """
    Map the complexity score to a dynamic waste percentage.
    Minimum 10% (0.10), Maximum 22% (0.22).
    Base waste is 10%, each score point adds 1% (0.01).
    """
    base_waste = 0.10
    dynamic_waste = base_waste + (score * 0.01)
    
    # Clamp between 10% and 22%
    clamped_waste = max(0.10, min(dynamic_waste, 0.22))
    return round(clamped_waste, 2)


def build_waste_explanation(ev_data: EagleViewData, waste_pct: float) -> str:
    """Generate a human-readable justification for the calculated waste percentage."""
    waste_int = int(waste_pct * 100)
    return (
        f"A {waste_int}% waste factor is required due to "
        f"{ev_data.total_facets} intersecting facets, "
        f"{ev_data.valley_lf} LF of valleys, and a "
        f"{ev_data.predominant_pitch} pitch."
    )
