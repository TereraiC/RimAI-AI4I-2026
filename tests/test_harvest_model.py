"""
Tests for core.harvest_model.

Covers the yield/risk consistency guard added after a real bug was found
during pre-submission QA: the yield regressor and risk classifier are
separately-trained models that could disagree (e.g. a very low predicted
yield shown next to a "Low" risk badge). These tests make sure that bug
can't silently come back.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from core.harvest_model import PROVINCE_META, predict_yield, train_yield_model


@pytest.fixture(scope="module", autouse=True)
def ensure_models_trained():
    """Train models once for this test session if they aren't already present."""
    if not os.path.exists("models/yield_model_xgb.pkl"):
        train_yield_model()


def _risk_from_ratio(yield_t_ha, province_norm):
    ratio = yield_t_ha / province_norm if province_norm else 1.0
    if ratio < 0.75:
        return "High"
    if ratio < 1.0:
        return "Moderate"
    return "Low"


@pytest.mark.parametrize("province", list(PROVINCE_META.keys()))
def test_risk_label_never_contradicts_yield(province):
    """For every province, across a spread of rainfall inputs, the displayed
    risk label must always match the label implied by the predicted yield
    vs. that province's norm. This is the exact bug found in Matabeleland
    South during QA (a low yield shown next to a 'Low' risk badge)."""
    meta = PROVINCE_META[province]
    for rainfall in range(150, 950, 50):
        result = predict_yield(
            {
                "province": province,
                "rainfall_mm": rainfall,
                "temperature_c": 22,
                "planting_month": 11,
                "farm_size_ha": 1,
            }
        )
        expected = _risk_from_ratio(result["yield_t_ha"], meta["avg_yield"])
        assert result["risk_label"] == expected, (
            f"{province} at rainfall={rainfall}: yield={result['yield_t_ha']} "
            f"(norm={meta['avg_yield']}) shows risk={result['risk_label']} "
            f"but should be {expected}"
        )


def test_predict_yield_returns_expected_keys():
    result = predict_yield({"province": "Harare", "rainfall_mm": 800})
    for key in ("yield_t_ha", "risk_label", "risk_confidence", "vs_province_norm", "province_norm"):
        assert key in result


def test_predict_yield_unknown_province_falls_back_to_harare():
    """An unrecognised province name should not crash prediction."""
    result = predict_yield({"province": "Not A Real Province", "rainfall_mm": 700})
    assert result["province_norm"] == PROVINCE_META["Harare"]["avg_yield"]


def test_province_meta_has_all_ten_provinces():
    assert len(PROVINCE_META) == 10
    for meta in PROVINCE_META.values():
        assert "avg_yield" in meta and meta["avg_yield"] > 0
        assert "avg_rain" in meta and meta["avg_rain"] > 0
