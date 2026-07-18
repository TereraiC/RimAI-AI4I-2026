"""
Tests for maize-only scope enforcement, prompted by a direct question:
"how do we ensure it's only maize that judges use here."

Checked the actual UI first: there was no crop selector in the Crop
Advisor form at all (only previous_crop, which is legitimately about
rotation history, not what's being analyzed now), so a normal user could
never select anything other than maize through the browser. But the
pest engine has dormant Tobacco and Cotton profiles, reachable via a
direct API call bypassing the form. These tests confirm the server-side
enforcement closes that gap and the scope is stated explicitly, not just
implicitly true by omission.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.crop_advisor import get_full_farm_analysis


def test_crop_is_always_maize_even_if_overridden():
    """Direct attempt to force a non-maize crop, bypassing the form
    entirely (which has no crop field to begin with)."""
    result = get_full_farm_analysis({
        "province": "Mashonaland West", "district": "Chinhoyi", "soil_type": "Clay-Loam",
        "crop": "Tobacco", "previous_crop": "Maize", "farm_size": 2,
    })
    assert result["inputs_used"]["crop"] == "Maize"


def test_pest_alerts_are_always_maize_pests_not_other_crops():
    result = get_full_farm_analysis({
        "province": "Mashonaland West", "district": "Chinhoyi", "soil_type": "Clay-Loam",
        "crop": "Cotton", "previous_crop": "Maize", "years_continuous": 3, "farm_size": 2,
    })
    from core.agronomy_engine import PEST_RISK_PROFILES
    maize_pest_names = {p["name"] for p in PEST_RISK_PROFILES["Maize"]}
    cotton_pest_names = {p["name"] for p in PEST_RISK_PROFILES.get("Cotton", [])}
    returned_names = {a["name"] for a in result["pest_risk"]["active_alerts"]}
    assert returned_names.issubset(maize_pest_names)
    assert not returned_names.intersection(cotton_pest_names - maize_pest_names)


def test_advisor_page_shows_explicit_maize_scope_badge(monkeypatch, tmp_path):
    fake_db = str(tmp_path / "maize_scope_test.db")
    import app as app_module
    from integrations.proactive_alerts import ensure_tables
    monkeypatch.setattr(app_module, "DB", fake_db)
    app_module.init_db()
    ensure_tables(fake_db)

    client = app_module.app.test_client()
    client.post("/login", data={"username": "demo", "password": "rimai2026"})
    resp = client.get("/advisor")
    body = resp.get_data(as_text=True)
    assert "MVP scope" in body


def test_about_page_states_maize_only_scope_explicitly(monkeypatch, tmp_path):
    fake_db = str(tmp_path / "about_scope_test.db")
    import app as app_module
    from integrations.proactive_alerts import ensure_tables
    monkeypatch.setattr(app_module, "DB", fake_db)
    app_module.init_db()
    ensure_tables(fake_db)

    client = app_module.app.test_client()
    client.post("/login", data={"username": "demo", "password": "rimai2026"})
    resp = client.get("/about")
    body = resp.get_data(as_text=True)
    assert "maize only" in body.lower()
