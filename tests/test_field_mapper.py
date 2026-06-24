"""
Unit tests for the FieldMapper.
"""

import pytest
from app.core.field_mapper import FieldMapper


@pytest.fixture
def custom_mapping():
    return {
        "cf_string_1": "insurance_carrier",
        "cf_string_2": "date_of_loss",
    }


def test_to_human_translates_mapped_keys(custom_mapping):
    mapper = FieldMapper(mapping=custom_mapping)
    payload = {
        "cf_string_1": "State Farm",
        "cf_string_2": "2023-01-01",
        "status_name": "Approved",
        "id": "12345",
    }

    translated = mapper.to_human(payload)

    assert translated["insurance_carrier"] == "State Farm"
    assert translated["date_of_loss"] == "2023-01-01"
    assert "cf_string_1" not in translated
    assert "cf_string_2" not in translated


def test_to_human_leaves_unmapped_keys_alone(custom_mapping):
    mapper = FieldMapper(mapping=custom_mapping)
    payload = {
        "cf_string_1": "State Farm",
        "status_name": "Approved",
        "unknown_cf_field": "test",
    }

    translated = mapper.to_human(payload)

    assert translated["status_name"] == "Approved"
    assert translated["unknown_cf_field"] == "test"
    assert translated["insurance_carrier"] == "State Farm"


def test_to_api_translates_human_keys_back(custom_mapping):
    mapper = FieldMapper(mapping=custom_mapping)
    payload = {
        "insurance_carrier": "Allstate",
        "date_of_loss": "2022-12-15",
        "status_name": "Pending",
        "id": "67890",
    }

    translated = mapper.to_api(payload)

    assert translated["cf_string_1"] == "Allstate"
    assert translated["cf_string_2"] == "2022-12-15"
    assert "insurance_carrier" not in translated
    assert "date_of_loss" not in translated


def test_to_api_leaves_unmapped_keys_alone(custom_mapping):
    mapper = FieldMapper(mapping=custom_mapping)
    payload = {
        "insurance_carrier": "Allstate",
        "status_name": "Pending",
        "unknown_human_field": "test",
    }

    translated = mapper.to_api(payload)

    assert translated["cf_string_1"] == "Allstate"
    assert translated["status_name"] == "Pending"
    assert translated["unknown_human_field"] == "test"


def test_default_mapping_is_used_if_none_provided():
    mapper = FieldMapper()
    # Assuming DEFAULT_MAPPING has cf_string_1 -> insurance_carrier
    payload = {"cf_string_1": "Geico"}
    translated = mapper.to_human(payload)
    assert translated.get("insurance_carrier") == "Geico"
