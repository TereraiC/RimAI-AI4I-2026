"""
Regression test for a real gap found when the user pushed back on
whether yield prediction — the platform's core value proposition —
was being surfaced prominently enough. Checked the actual template and
found result.yield_t_ha was computed by every Crop Advisor analysis but
never displayed anywhere on the results page at all.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.crop_advisor import get_full_farm_analysis


def test_yield_t_ha_is_computed_and_present():
    result = get_full_farm_analysis({
        "province": "Mashonaland West", "district": "Chinhoyi", "soil_type": "Clay-Loam",
        "previous_crop": "Maize", "years_continuous": "2", "farm_size": 2,
    })
    assert result["yield_t_ha"] is not None
    assert result["yield_t_ha"] > 0


def test_vs_province_norm_is_threaded_through():
    """This field existed in the yield model's own output for a long time,
    but crop_advisor.py never pulled it into its own result dict — so it
    was always None on the farmer-facing side even though the underlying
    number was already being computed."""
    result = get_full_farm_analysis({
        "province": "Mashonaland West", "district": "Chinhoyi", "soil_type": "Clay-Loam",
        "previous_crop": "Maize", "years_continuous": "2", "farm_size": 2,
    })
    assert "vs_province_norm" in result
    assert result["vs_province_norm"] is not None


def test_predicted_yield_actually_renders_on_advisor_page(monkeypatch, tmp_path):
    fake_db = str(tmp_path / "yield_display_test.db")
    import app as app_module
    from integrations.proactive_alerts import ensure_tables
    monkeypatch.setattr(app_module, "DB", fake_db)
    app_module.init_db()
    ensure_tables(fake_db)

    client = app_module.app.test_client()
    client.post("/login", data={"username": "demo", "password": "rimai2026"})
    resp = client.post("/advisor", data={
        "province": "Mashonaland West", "district": "Chinhoyi", "soil_type": "Clay-Loam",
        "crop": "Maize", "previous_crop": "Maize", "years_continuous": "2",
        "planting_date": "2026-11-05", "farm_size": "2",
    })
    body = resp.get_data(as_text=True)
    assert "Predicted Yield" in body
    assert "t/ha" in body
