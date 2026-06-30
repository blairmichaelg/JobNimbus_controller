"""
Unit tests for the SQLite-backed V3 PhotoAnalysis cache layer.
"""

import sqlite3
import pytest
from pathlib import Path

from app.core.cache import (
    init_db,
    get_cached_analysis,
    set_cached_analysis,
    get_cached_analyses_for_job,
    _get_connection,
    DB_PATH
)
from app.core.inspection_models import PhotoAnalysis, DamageType, Severity

@pytest.fixture(autouse=True)
def clean_db():
    """Ensure a clean database for each test."""
    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()
    yield
    if DB_PATH.exists():
        try:
            DB_PATH.unlink()
        except PermissionError:
            pass


def _make_sample_analysis(filename: str = "test.jpg") -> PhotoAnalysis:
    return PhotoAnalysis(
        filename=filename,
        damage_detected=True,
        damage_type=DamageType.HAIL,
        severity=Severity.MODERATE,
        confidence=0.85,
        hail_hits_visible=True,
        crease_marks=False,
        granule_loss=True,
        exposed_fiberglass=False,
        forensic_narrative="Hail impacts visible."
    )


class TestCacheLayer:
    def test_cache_miss_returns_none(self):
        """get_cached_analysis should return None if the key doesn't exist."""
        result = get_cached_analysis("JOB-123", "nonexistent_hash")
        assert result is None

    def test_cache_hit_returns_model(self):
        """get_cached_analysis should return a valid PhotoAnalysis."""
        analysis = _make_sample_analysis()
        
        set_cached_analysis("JOB-123", "hash_abc", analysis)
        
        result = get_cached_analysis("JOB-123", "hash_abc")
        
        assert result is not None
        assert isinstance(result, PhotoAnalysis)
        assert result.filename == "test.jpg"
        assert result.damage_type == DamageType.HAIL

    def test_cache_overwrites_on_conflict(self):
        """set_cached_analysis should update an existing entry."""
        analysis1 = _make_sample_analysis("first.jpg")
        set_cached_analysis("JOB-123", "hash_abc", analysis1)
        
        analysis2 = _make_sample_analysis("second.jpg")
        analysis2.severity = Severity.SEVERE
        set_cached_analysis("JOB-123", "hash_abc", analysis2)
        
        result = get_cached_analysis("JOB-123", "hash_abc")
        assert result.filename == "second.jpg"
        assert result.severity == Severity.SEVERE

    def test_get_cached_analyses_for_job(self):
        """Should return all analyses for a specific job."""
        set_cached_analysis("JOB-001", "hash_1", _make_sample_analysis("a.jpg"))
        set_cached_analysis("JOB-001", "hash_2", _make_sample_analysis("b.jpg"))
        set_cached_analysis("JOB-002", "hash_3", _make_sample_analysis("c.jpg"))
        
        results = get_cached_analyses_for_job("JOB-001")
        assert len(results) == 2
        
        filenames = {r.filename for r in results}
        assert filenames == {"a.jpg", "b.jpg"}

    def test_corrupt_json_handled_safely(self):
        """Malformed JSON in the DB should be caught and return None."""
        analysis = _make_sample_analysis()
        set_cached_analysis("JOB-BAD", "hash_x", analysis)
        
        # Manually corrupt the JSON
        with _get_connection() as conn:
            conn.execute("UPDATE analysis_cache SET analysis_json = 'bad_json' WHERE job_id = 'JOB-BAD'")
            conn.commit()
            
        result = get_cached_analysis("JOB-BAD", "hash_x")
        assert result is None
