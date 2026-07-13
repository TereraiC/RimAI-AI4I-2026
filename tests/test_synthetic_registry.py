"""
Tests for data_pipeline.synthetic_registry — the dataset registry backing
the Admin "Data Provenance & Transparency" page.
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

import data_pipeline.synthetic_registry as registry_module


@pytest.fixture
def isolated_registry(monkeypatch, tmp_path):
    """Point the registry at a throwaway file so tests never touch the real one."""
    fake_path = tmp_path / "synthetic_registry.json"
    monkeypatch.setattr(registry_module, "REGISTRY_PATH", str(fake_path))
    yield fake_path


def test_load_registry_seeds_on_first_call(isolated_registry):
    registry = registry_module.load_registry()
    assert isinstance(registry, list)
    assert len(registry) > 0
    for entry in registry:
        assert entry["source"] in ("real", "synthetic", "hybrid")


def test_every_entry_has_required_provenance_fields(isolated_registry):
    registry = registry_module.load_registry()
    required = {"id", "name", "source", "reason", "methodology"}
    for entry in registry:
        assert required.issubset(entry.keys()), f"{entry.get('id')} missing fields"


def test_detect_gaps_flags_known_missing_data(isolated_registry):
    gaps = registry_module.detect_gaps()
    gap_text = " ".join(g.get("feature", "") + " " + g.get("status", "") for g in gaps).lower()
    # These are real gaps disclosed in the proposal — livestock records and
    # market price history have no live source yet.
    assert "livestock" in gap_text or "market" in gap_text


def test_completeness_score_is_between_0_and_100(isolated_registry):
    score = registry_module.completeness_score()
    assert 0 <= score <= 100


def test_set_dataset_enabled_persists(isolated_registry):
    registry = registry_module.load_registry()
    dataset_id = registry[0]["id"]
    registry_module.set_dataset_enabled(dataset_id, False)
    updated = registry_module.load_registry()
    entry = next(e for e in updated if e["id"] == dataset_id)
    assert entry["enabled"] is False
