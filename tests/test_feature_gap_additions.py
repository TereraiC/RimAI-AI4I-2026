"""
Tests for three features added in response to a feature-gap audit against
a full agronomy-assistant feature list:

1. Potential Yield — real historical max yield per province, surfaced
   next to the prediction, closing the "potential yield estimate" gap.
2. What-If Simulator planting delay — the exact example from the
   original request ("what happens if I delay planting by 10 days?")
   wasn't previously supported at all (planting_month was hardcoded).
3. Quantified $ stakes on the yield gap, closing part of the
   Explainable AI "estimated loss if recommendations are ignored" gap.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.crop_advisor import get_full_farm_analysis
from core.farm_manager import run_scenario


def _base_analysis(province="Mashonaland West", planting_date="2026-11-05"):
    return get_full_farm_analysis({
        "province": province, "district": "Chinhoyi", "soil_type": "Clay-Loam",
        "previous_crop": "Maize", "years_continuous": 2,
        "planting_date": planting_date, "farm_size": 2,
    })


def test_potential_yield_is_computed_from_real_history(monkeypatch, tmp_path):
    fake_db = str(tmp_path / "potential_yield_test.db")
    import app as app_module
    monkeypatch.setattr(app_module, "DB", fake_db)
    app_module.init_db()

    potential = app_module.get_potential_yield("Manicaland")
    assert potential is not None
    assert potential["potential_yield_t_ha"] > 0
    assert "\u2013" in potential["years_range"]  # e.g. "2020\u20132023"


def test_potential_yield_covers_all_ten_provinces(monkeypatch, tmp_path):
    """Regression test: originally only 5 of 10 provinces had historical
    yield data seeded, so this silently failed for half the country."""
    fake_db = str(tmp_path / "potential_yield_all_test.db")
    import app as app_module
    monkeypatch.setattr(app_module, "DB", fake_db)
    app_module.init_db()

    provinces = ["Mashonaland West", "Mashonaland Central", "Mashonaland East",
                 "Harare", "Manicaland", "Midlands", "Masvingo",
                 "Matabeleland North", "Matabeleland South", "Bulawayo"]
    for prov in provinces:
        potential = app_module.get_potential_yield(prov)
        assert potential is not None, f"{prov} has no historical yield data"


def test_planting_delay_within_window_has_no_penalty():
    base = _base_analysis()
    result = run_scenario(base, planting_delay_days=10)
    assert result["delay_penalty_applied"] is False
    assert result["yield_delta"] == 0.0


def test_planting_delay_past_window_reduces_yield():
    """The exact scenario from the original request: 'what happens if I
    delay planting by 10 days' should work, and a genuinely late delay
    should show a real, negative yield impact — not stay flat and not
    (as a real bug found during testing) show yield INCREASING for a
    worse delay."""
    base = _base_analysis()
    result_60 = run_scenario(base, planting_delay_days=60)
    result_90 = run_scenario(base, planting_delay_days=90)
    assert result_60["delay_penalty_applied"] is True
    assert result_60["yield_delta"] < 0
    # A longer delay should be worse than a shorter one, not better —
    # this is the exact directional bug found and fixed.
    assert result_90["yield_t_ha"] <= result_60["yield_t_ha"]


def test_yield_gap_dollar_value_present_when_below_potential():
    base = _base_analysis(province="Matabeleland South")
    gap_usd = base["economic"]["revenue_gap_per_ha_usd"]
    assert gap_usd is not None
