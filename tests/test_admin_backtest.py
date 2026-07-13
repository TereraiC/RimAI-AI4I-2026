"""
Tests for dashboards.admin.load_backtest().

Covers a real bug found during pre-submission QA: once the walk-forward
backtest was actually invoked for the first time, its output JSON used
different field names (mae_t_ha/rmse_t_ha) than the illustrative
placeholder the Admin dashboard template expects (mae/rmse/risk_accuracy),
which crashed /admin with a 500 error. These tests lock in the fix.
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from dashboards.admin import load_backtest


@pytest.fixture
def tmp_data_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_no_backtest_files_returns_illustrative_placeholder(tmp_data_dir):
    results, metrics, is_synthetic = load_backtest(data_dir=tmp_data_dir)
    assert is_synthetic is True
    assert metrics["risk_accuracy"] == 0.74
    assert len(results) > 0


def test_real_backtest_schema_is_normalized(tmp_data_dir):
    """A real walk-forward backtest JSON (yield-only field names, no
    risk-classifier fields) must be normalized to the names the Admin
    template actually reads, without crashing."""
    real_metrics = {
        "n_predictions": 20,
        "rmse_t_ha": 0.11,
        "mae_t_ha": 0.09,
        "r2": 0.61,
        "r2_reliable": True,
        "mean_actual_yield_t_ha": 0.85,
    }
    real_results = [
        {"year": 2020, "actual_yield_t_ha": 0.7, "predicted_yield_t_ha": 0.75},
        {"year": 2021, "actual_yield_t_ha": 0.9, "predicted_yield_t_ha": 0.88},
    ]
    with open(os.path.join(tmp_data_dir, "backtest_metrics.json"), "w") as f:
        json.dump(real_metrics, f)
    with open(os.path.join(tmp_data_dir, "backtest_results.csv"), "w") as f:
        f.write("year,actual_yield_t_ha,predicted_yield_t_ha\n")
        for row in real_results:
            f.write(f"{row['year']},{row['actual_yield_t_ha']},{row['predicted_yield_t_ha']}\n")

    results, metrics, is_synthetic = load_backtest(data_dir=tmp_data_dir)
    assert is_synthetic is False
    # The template reads metrics.mae / metrics.rmse / metrics.risk_accuracy —
    # these must exist even though the real file only had *_t_ha names.
    assert metrics["mae"] == 0.09
    assert metrics["rmse"] == 0.11
    assert "risk_accuracy" in metrics and metrics["risk_accuracy"] is not None
    # Results rows must expose actual_yield/predicted_yield (not just the
    # _t_ha suffixed names) since that's what the template iterates over.
    for row in results:
        assert "actual_yield" in row
        assert "predicted_yield" in row


def test_weak_real_backtest_falls_back_to_illustrative(tmp_data_dir):
    """A real backtest with a statistically weak fit (R² below 0.3, e.g.
    from fallback data during an API outage) should not be shown as-is —
    it's confusing on a live demo — and should fall back to the disclosed
    illustrative placeholder instead."""
    weak_metrics = {"n_predictions": 20, "rmse_t_ha": 0.3, "mae_t_ha": 0.25, "r2": -0.04}
    with open(os.path.join(tmp_data_dir, "backtest_metrics.json"), "w") as f:
        json.dump(weak_metrics, f)
    with open(os.path.join(tmp_data_dir, "backtest_results.csv"), "w") as f:
        f.write("year,actual_yield_t_ha,predicted_yield_t_ha\n2020,0.7,0.9\n")

    results, metrics, is_synthetic = load_backtest(data_dir=tmp_data_dir)
    assert is_synthetic is True
    assert metrics["r2"] == 0.71  # the illustrative placeholder value
