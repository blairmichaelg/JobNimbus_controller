"""
Pydantic V2 models for the InsurTech Supplement Engine.

These models enforce strict data contracts between the extraction,
reconciliation, and generation layers. The LLM never touches these
models for math — only for extraction and narrative.

Key design decisions:
- EagleViewData uses @computed_field for automatic waste normalization
- LineItem allows None for missing quantities (SoLs are inconsistent)
- DiscrepancyReport is the pure-Python math engine's output contract
"""

from pydantic import BaseModel, computed_field


class EagleViewData(BaseModel):
    """
    Normalized EagleView measurement data extracted via pdfplumber.

    The @computed_field automatically converts raw SF to roofing Squares
    with the configured waste factor applied, so downstream consumers
    never need to do this math themselves.
    """

    total_area_sf: float
    rake_lf: float
    valley_lf: float
    ridge_lf: float
    hip_lf: float
    eaves_lf: float
    drip_edge_lf: float
    flashing_lf: float
    step_flashing_lf: float
    total_facets: int
    predominant_pitch: str
    waste_factor: float = 0.15

    @computed_field
    @property
    def normalized_squares(self) -> float:
        """Total area in Squares (SQ) with waste factor applied."""
        return round((self.total_area_sf / 100) * (1 + self.waste_factor), 2)


class LineItem(BaseModel):
    """
    A single line item from a Carrier Statement of Loss / Xactimate estimate.

    Fields may be None when the carrier omits data or the value
    could not be confidently extracted. The LLM is instructed to
    return null rather than guess.
    """

    trade: str
    code: str
    description: str
    quantity: float | None = None
    unit_of_measure: str | None = None
    unit_price: float | None = None


class StatementOfLoss(BaseModel):
    """
    Structured representation of a Carrier Statement of Loss PDF,
    extracted via Gemini Multimodal File API.
    """

    carrier_name: str | None = None
    claim_number: str | None = None
    line_items: list[LineItem] = []
    overhead_and_profit_included: bool | None = None


class Discrepancy(BaseModel):
    """A single variance identified between EagleView and SoL data."""

    category: str
    description: str
    ev_value: float | None = None
    sol_value: float | None = None
    variance: float | None = None
    code_citation: str | None = None


class DiscrepancyReport(BaseModel):
    """
    Output of the deterministic Python reconciliation engine.

    This is the bridge between the math layer and the AI narrative layer.
    The AI uses this report to write the supplement letter, but
    NEVER recalculates any of the numbers.
    """

    job_id: str
    ev_normalized_squares: float
    sol_total_rfg_squares: float
    square_variance: float
    discrepancies: list[Discrepancy] = []
