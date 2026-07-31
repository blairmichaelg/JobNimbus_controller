import pytest
from scripts.verify_currency_consistency import verify_consistency

def test_currency_consistency(monkeypatch):
    """
    Ensures that the legacy REAL columns and the new INTEGER cents columns
    are mathematically equivalent across all rows.
    verify_consistency calls sys.exit(1) on failure, sys.exit(0) on success.
    """
    # We patch sys.exit so the test suite doesn't abort
    exit_codes = []
    monkeypatch.setattr("sys.exit", lambda code: exit_codes.append(code))
    
    verify_consistency()
    
    # We expect sys.exit(0) to have been called
    assert exit_codes == [0], "verify_consistency detected drift!"
