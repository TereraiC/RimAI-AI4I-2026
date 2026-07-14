"""
Tests for core.farm_manager.daily_brief() and health_score().

Regression test for a real bug: daily_brief() checked pest alerts before
timing status, so a farmer told "too early to plant" (e.g. planting date
entered as July for a November-season province) would still see
"Priority today: scout for X" as their headline message — instructing
them to scout a crop that isn't in the ground. Similarly, health_score()
penalized the Pest Risk component from weather-only pest triggers
regardless of whether anything was actually planted.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.farm_manager import daily_brief, health_score


def _analysis(timing, risk_label="Moderate", alerts=None, yield_t_ha=1.5):
    return {
        "timing": timing,
        "risk_label": risk_label,
        "yield_t_ha": yield_t_ha,
        "inputs_used": {"province": "Mashonaland West"},
        "pest_risk": {"active_alerts": alerts or []},
        "economic": {"fertilizer_roi_pct": 40},
    }


PEST_ALERT = {"name": "Fall Armyworm", "severity": "High", "action": "Scout weekly. Apply insecticide if needed."}


def test_daily_brief_prioritizes_timing_over_pest_when_too_early():
    analysis = _analysis("wait", alerts=[PEST_ALERT])
    brief = daily_brief(analysis)
    assert "Too early to plant" in brief
    assert "Priority today: scout" not in brief


def test_daily_brief_still_mentions_pest_as_forward_looking_when_too_early():
    analysis = _analysis("wait", alerts=[PEST_ALERT])
    brief = daily_brief(analysis)
    assert "Fall Armyworm" in brief
    assert "once you do plant" in brief


def test_daily_brief_prioritizes_pest_scouting_when_actually_planted():
    analysis = _analysis("plant_now", alerts=[PEST_ALERT])
    brief = daily_brief(analysis)
    assert "Priority today: scout for Fall Armyworm" in brief


def test_daily_brief_risky_timing_does_not_get_overridden_by_pest():
    analysis = _analysis("risky", alerts=[PEST_ALERT])
    brief = daily_brief(analysis)
    assert "Late planting window" in brief


def test_health_score_neutralizes_pest_penalty_when_not_planted():
    analysis = _analysis("wait", alerts=[PEST_ALERT])
    score = health_score(analysis)
    assert score["pest"] == 100


def test_health_score_applies_pest_penalty_when_actually_planted():
    analysis = _analysis("plant_now", alerts=[PEST_ALERT])
    score = health_score(analysis)
    assert score["pest"] < 100
