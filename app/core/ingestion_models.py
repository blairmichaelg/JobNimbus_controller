from pydantic import BaseModel, model_validator

class LineItem(BaseModel):
    category_code: str
    activity_code: str
    description: str
    quantity: float
    unit_price: float
    rcv: float
    depreciation: float
    acv: float

class RoofGeometry(BaseModel):
    pitch: str
    total_squares: float
    eaves_lf: float
    valleys_lf: float
    rakes_lf: float

class ClaimFinancials(BaseModel):
    gross_rcv: float
    total_depreciation: float
    deductible: float
    net_claim: float

class UniversalClaimAST(BaseModel):
    line_items: list[LineItem]
    roof_geometry: RoofGeometry
    financials: ClaimFinancials

    @model_validator(mode='after')
    def validate_math(self) -> 'UniversalClaimAST':
        total_rcv = 0.0
        for item in self.line_items:
            expected_rcv = item.quantity * item.unit_price
            if abs(expected_rcv - item.rcv) > 0.05:
                raise ValueError(f"Line item math mismatch: {expected_rcv} != {item.rcv}")
            total_rcv += item.rcv
        
        if abs(total_rcv - self.financials.gross_rcv) > 0.05:
            raise ValueError(f"Total RCV mismatch: {total_rcv} != {self.financials.gross_rcv}")
        return self
