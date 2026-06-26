"""
Unit tests for the Smart Code Router (Zero-Cost RAG).
"""

import pytest
import os
from unittest.mock import patch, MagicMock
from app.core.code_router import parse_code_files, get_relevant_codes
from app.core.supplement_models import DiscrepancyReport, Discrepancy, MaterialBOM

class TestCodeRouter:
    @patch("app.core.code_router.Path")
    def test_parse_code_files(self, mock_path_class):
        mock_path_instance = MagicMock()
        mock_path_instance.exists.return_value = True
        
        mock_file_1 = MagicMock()
        mock_file_1.name = "test1.txt"
        mock_file_1.read_text.return_value = "<TAG_1>Content for tag 1.</TAG_1>\n<TAG_2>\nMultiline\nContent\n</TAG_2>"
        
        mock_file_2 = MagicMock()
        mock_file_2.name = "test2.txt"
        mock_file_2.read_text.return_value = "<TAG_3>Content for tag 3.</TAG_3>"
        
        mock_path_instance.glob.return_value = [mock_file_1, mock_file_2]
        mock_path_class.return_value = mock_path_instance

        code_index = parse_code_files("fake_dir")
        
        assert "TAG_1" in code_index
        assert code_index["TAG_1"] == "Content for tag 1."
        assert "TAG_2" in code_index
        assert "Multiline\nContent" in code_index["TAG_2"]
        assert "TAG_3" in code_index
        assert code_index["TAG_3"] == "Content for tag 3."

    def test_get_relevant_codes(self):
        report = DiscrepancyReport(
            job_id="TEST-1",
            ev_normalized_squares=10.0,
            sol_total_rfg_squares=5.0,
            square_variance=5.0,
            waste_explanation="Test",
            material_bom=MaterialBOM(field_shingle_bundles=30, starter_bundles=1, ridge_cap_bundles=1, ice_water_rolls=1, underlayment_rolls=1),
            discrepancies=[
                Discrepancy(category="Missing Drip Edge", description="Test", ev_value=1.0, sol_value=0.0, variance=1.0),
                Discrepancy(category="Missing Ice & Water Shield", description="Test", ev_value=1.0, sol_value=0.0, variance=1.0),
                Discrepancy(category="Unknown Category", description="Test", ev_value=1.0, sol_value=0.0, variance=1.0)
            ]
        )
        
        code_index = {
            "SECTION_R905_2_8_5": "Drip edge is required.",
            "GA_R905_2_8_5": "Georgia amendments for drip edge.",
            "SECTION_R905_2_8_2": "Ice barrier required.",
            "SOME_OTHER_TAG": "Not relevant."
        }
        
        result = get_relevant_codes(report, code_index)
        
        assert "<SECTION_R905_2_8_5>" in result
        assert "Drip edge is required." in result
        assert "<GA_R905_2_8_5>" in result
        assert "Georgia amendments for drip edge." in result
        assert "<SECTION_R905_2_8_2>" in result
        assert "Ice barrier required." in result
        assert "SOME_OTHER_TAG" not in result
