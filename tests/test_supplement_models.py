"""
Unit tests for the supplement Pydantic models.

Tests the computed fields, null handling, and data validation
for the InsurTech Supplement Engine's data contracts.
"""

import pytest
from app.core.supplement_models import (
    EagleViewData,
    LineItem,
    StatementOfLoss,
    Discrepancy,
    DiscrepancyReport,
)


class TestEagleViewData:
    """Tests for the EagleViewData model and its computed fields."""

    def test_normalized_squares_default_waste(self):
        """2500 SF at 15% waste should produce 28.75 SQ."""
        data = EagleViewData(
            total_area_sf=2500.0,
            rake_lf=50.0,
            valley_lf=30.0,
            ridge_lf=40.0,
            hip_lf=60.0,
            eaves_lf=100.0,
            drip_edge_lf=150.0,
            flashing_lf=5.0,
            step_flashing_lf=10.0,
            total_facets=8,
            predominant_pitch="6/12",
        )
        assert data.normalized_squares == 28.75

    def test_normalized_squares_custom_waste(self):
        """6788 SF at 15% waste should produce 78.06 SQ (matches real EagleView report)."""
        data = EagleViewData(
            total_area_sf=6788.0,
            rake_lf=114.0,
            valley_lf=288.0,
            ridge_lf=120.0,
            hip_lf=315.0,
            eaves_lf=276.0,
            drip_edge_lf=390.0,
            flashing_lf=3.0,
            step_flashing_lf=16.0,
            total_facets=26,
            predominant_pitch="10/12",
            waste_factor=0.15,
        )
        assert data.normalized_squares == 78.06

    def test_normalized_squares_zero_waste(self):
        """With 0% waste, squares should just be area / 100."""
        data = EagleViewData(
            total_area_sf=10000.0,
            rake_lf=0.0,
            valley_lf=0.0,
            ridge_lf=0.0,
            hip_lf=0.0,
            eaves_lf=0.0,
            drip_edge_lf=0.0,
            flashing_lf=0.0,
            step_flashing_lf=0.0,
            total_facets=1,
            predominant_pitch="4/12",
            waste_factor=0.0,
        )
        assert data.normalized_squares == 100.0

    def test_default_waste_factor_is_fifteen_percent(self):
        """Default waste factor should be 0.15 (15%)."""
        data = EagleViewData(
            total_area_sf=1000.0,
            rake_lf=0.0,
            valley_lf=0.0,
            ridge_lf=0.0,
            hip_lf=0.0,
            eaves_lf=0.0,
            drip_edge_lf=0.0,
            flashing_lf=0.0,
            step_flashing_lf=0.0,
            total_facets=1,
            predominant_pitch="4/12",
        )
        assert data.waste_factor == 0.15


class TestLineItem:
    """Tests for LineItem null handling."""

    def test_line_item_with_all_fields(self):
        item = LineItem(
            trade="RFG",
            code="RFG 300",
            description="Shingle roofing",
            quantity=25.0,
            unit_of_measure="SQ",
            unit_price=85.50,
        )
        assert item.quantity == 25.0

    def test_line_item_with_null_fields(self):
        """SoLs may omit quantity or price — model must accept None."""
        item = LineItem(
            trade="RFG",
            code="RFG 300",
            description="Shingle roofing",
            quantity=None,
            unit_of_measure=None,
            unit_price=None,
        )
        assert item.quantity is None
        assert item.unit_price is None


class TestStatementOfLoss:
    """Tests for StatementOfLoss model."""

    def test_empty_line_items_default(self):
        sol = StatementOfLoss()
        assert sol.line_items == []
        assert sol.carrier_name is None

    def test_with_line_items(self):
        sol = StatementOfLoss(
            carrier_name="State Farm",
            claim_number="CLM-12345",
            line_items=[
                LineItem(trade="RFG", code="RFG 300", description="Shingles", quantity=25.0),
            ],
            overhead_and_profit_included=True,
        )
        assert len(sol.line_items) == 1
        assert sol.overhead_and_profit_included is True


class TestDiscrepancyReport:
    """Tests for the DiscrepancyReport output model."""

    def test_clean_report(self):
        report = DiscrepancyReport(
            job_id="test_123",
            ev_normalized_squares=78.06,
            sol_total_rfg_squares=78.0,
            square_variance=0.06,
        )
        assert report.discrepancies == []
        assert report.square_variance == 0.06

    def test_report_with_discrepancies(self):
        report = DiscrepancyReport(
            job_id="test_456",
            ev_normalized_squares=78.06,
            sol_total_rfg_squares=65.0,
            square_variance=13.06,
            discrepancies=[
                Discrepancy(
                    category="Area Shortage",
                    description="SoL underestimates roof area by 13.06 SQ",
                    ev_value=78.06,
                    sol_value=65.0,
                    variance=13.06,
                ),
            ],
        )
        assert len(report.discrepancies) == 1
        assert report.discrepancies[0].category == "Area Shortage"
