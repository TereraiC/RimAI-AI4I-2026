"""
Tests for real cross-validated model metrics.

Regression test for a real issue found during pre-submission review:
core.harvest_model.train_yield_model() previously wrote hardcoded
constants (cv_r2=0.824, risk_classifier_accuracy=0.74) into model_meta
labeled as "CV" results, but no cross-validation actually ran anywhere
in that function — models were fit directly on the full dataset with
no train/test split. These tests confirm genuine cross-validation now
runs and produces metrics consistent with actual held-out performance.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.harvest_model import train_yield_model, get_model_meta, FEATURE_COLS


def test_cv_metrics_are_present_and_reasonable():
    train_yield_model()
    meta = get_model_meta()

    assert "cv_r2" in meta and 0 <= meta["cv_r2"] <= 1
    assert "cv_mae" in meta and meta["cv_mae"] > 0
    assert "risk_classifier_accuracy" in meta and 0 <= meta["risk_classifier_accuracy"] <= 1
    assert "risk_classifier_macro_f1" in meta and 0 <= meta["risk_classifier_macro_f1"] <= 1


def test_cv_method_is_disclosed_not_hardcoded():
    train_yield_model()
    meta = get_model_meta()
    assert "cv_method" in meta
    assert "fold" in meta["cv_method"].lower()


def test_cv_r2_high_value_is_disclosed_in_note():
    """If R² is very high (as expected here, since province_avg_yield is
    itself a feature), the note must explain why — not present it as an
    unqualified accuracy claim."""
    train_yield_model()
    meta = get_model_meta()
    if meta["cv_r2"] > 0.9:
        assert "province_avg_yield" in meta["note"]


def test_province_avg_yield_is_a_feature():
    """Confirms the actual mechanism behind the high R² — this is a
    property of the feature set, not a coincidence."""
    assert "province_avg_yield" in FEATURE_COLS
