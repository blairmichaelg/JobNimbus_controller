from pydantic import BaseModel, model_validator, Field
from typing import TypeVar, Generic, List, Optional
from decimal import Decimal, ROUND_HALF_UP

T = TypeVar('T')

class EvidenceRef(BaseModel):
    doc_id: str
    page: int
    bounding_box: Optional[str] = None
    raw_text: str
    extraction_method: str

class SourcedValue(BaseModel, Generic[T]):
    value: T
    evidence: List[EvidenceRef] = Field(default_factory=list)
    verified: bool = False

class ClaimLineItem(BaseModel):
    category_code: str
    activity_code: str
    description: str
    quantity: SourcedValue[Decimal]
    unit: SourcedValue[str]
    unit_price: SourcedValue[Decimal]
    tax: SourcedValue[Decimal]
    claimed_rcv: SourcedValue[Decimal]
    depreciation: SourcedValue[Decimal]
    acv: SourcedValue[Decimal]
    verified: bool = False

    @model_validator(mode='after')
    def validate_math(self) -> 'ClaimLineItem':
        # (quantity * unit_price) + tax == claimed_rcv (tolerance 0.02)
        q = self.quantity.value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        up = self.unit_price.value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        t = self.tax.value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        rcv = self.claimed_rcv.value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        
        calculated = (q * up) + t
        difference = abs(calculated - rcv)
        
        if difference <= Decimal("0.02"):
            self.verified = True
        else:
            self.verified = False
            
        return self

class RoofGeometry(BaseModel):
    pitch: SourcedValue[str]
    total_squares: SourcedValue[Decimal]
    eaves_lf: SourcedValue[Decimal]
    valleys_lf: SourcedValue[Decimal]
    rakes_lf: SourcedValue[Decimal]

class ClaimFinancials(BaseModel):
    gross_rcv: SourcedValue[Decimal]
    total_depreciation: SourcedValue[Decimal]
    deductible: SourcedValue[Decimal]
    net_claim: SourcedValue[Decimal]

class UniversalClaimAST(BaseModel):
    line_items: List[ClaimLineItem]
    roof_geometry: RoofGeometry
    financials: ClaimFinancials

    @model_validator(mode='after')
    def validate_total(self) -> 'UniversalClaimAST':
        total_rcv = sum((item.claimed_rcv.value for item in self.line_items), Decimal("0.00"))
        
        # Simple cross-check. If they mismatch significantly, we could flag it.
        # For now, we rely on the line-item level verification.
        if abs(total_rcv - self.financials.gross_rcv.value) <= Decimal("0.05"):
            self.financials.gross_rcv.verified = True
            
        return self
