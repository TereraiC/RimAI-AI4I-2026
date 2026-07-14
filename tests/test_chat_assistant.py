"""
Tests for core.rimai_assistant_free — the rule-grounded Virtual
Agronomist chat assistant.

Covers four capability upgrades: multi-intent detection (a message can
ask about more than one topic and get both answered), broader phrasing
coverage, a fuzzy word-level fallback pass, and follow-up context
awareness (a short message like "how much?" continues the previous
topic instead of falling back to a generic menu).
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.rimai_assistant_free import get_chat_response, match_intents, is_followup


FARM_DATA = {
    "province": "Mashonaland West", "soil_type": "Clay-Loam", "previous_crop": "Maize",
    "farm_size": 2, "timing": "wait", "risk_label": "Moderate", "risk_confidence": 62,
    "extrapolated_season_total_mm": 400, "total_rainfall_mm": 400, "avg_temp_c": 24,
    "avg_humidity_pct": 55, "recommended_variety": "SC403", "compound_d_kg": 300,
    "an_kg": 500, "irrigation": "Irrigation recommended.", "rotation_verdict": "High rotation risk",
    "rotation_note": "Continuous maize for 3 seasons.", "yield_t_ha": 1.2,
    "pest_alerts": [{"name": "Fall Armyworm", "severity": "High", "action": "Scout weekly."}],
    "agro_zone": "II",
}


def test_multi_intent_answers_both_topics():
    result = get_chat_response("when should I plant and what fertilizer should I use?", FARM_DATA)
    assert "too early to plant" in result["reply"].lower()
    assert "compound d" in result["reply"].lower()


def test_broader_phrasing_matches_natural_question():
    intents = match_intents("is it a good time to start planting?")
    assert "plant_now" in intents


def test_fuzzy_word_fallback_catches_informal_phrasing():
    intents = match_intents("any bugs I should worry about?")
    assert intents == ["pest_disease"]


def test_no_match_returns_empty_not_general_directly():
    # match_intents itself should return [] for genuinely unmatched input;
    # falling back to "general" is get_chat_response's job, not match_intents'.
    intents = match_intents("xyzabc123 completely unrelated gibberish")
    assert intents == []


def test_followup_detection():
    assert is_followup("how much?")
    assert is_followup("why not")
    assert is_followup("what about pests")
    assert not is_followup("what fertilizer should I use for my two hectare farm")


def test_followup_continues_previous_topic():
    first = get_chat_response("what fertilizer should I use?", FARM_DATA)
    assert first["intent"] == "fertilizer"
    followup = get_chat_response("how much?", FARM_DATA, last_intent=first["intent"])
    assert "compound d" in followup["reply"].lower()


def test_followup_without_last_intent_falls_back_to_general():
    result = get_chat_response("how much?", FARM_DATA, last_intent=None)
    assert result["intent"] == "general"


def test_general_fallback_mentions_specific_farm_state_not_just_menu():
    result = get_chat_response("xyzabc123 completely unrelated gibberish", FARM_DATA)
    assert result["intent"] == "general"
    assert "too early to plant" in result["reply"].lower() or "fall armyworm" in result["reply"].lower()
