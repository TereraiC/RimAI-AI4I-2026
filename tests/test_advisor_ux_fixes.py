"""
Tests for three fixes:
1. GPS location capture now auto-selects the nearest province (previously
   only wrote to hidden lat/lon fields with no visible effect).
2. The redundant /yield tool (manual rainfall entry, no live weather or
   advice) now redirects to Crop Advisor instead of duplicating it.
3. The officer's nav/page framing was relabeled to clarify these are
   live field-visit tools, not "my own farm" tools.
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def test_yield_route_redirects_to_advisor(monkeypatch, tmp_path):
    fake_db = str(tmp_path / "yield_redirect_test.db")
    import app as app_module
    monkeypatch.setattr(app_module, "DB", fake_db)
    app_module.init_db()

    client = app_module.app.test_client()
    client.post("/login", data={"username": "demo", "password": "rimai2026"})
    resp = client.get("/yield", follow_redirects=False)

    assert resp.status_code == 302
    assert "/advisor" in resp.headers["Location"]


def test_yield_redirect_follows_through_with_flash_message(monkeypatch, tmp_path):
    fake_db = str(tmp_path / "yield_flash_test.db")
    import app as app_module
    from integrations.proactive_alerts import ensure_tables
    monkeypatch.setattr(app_module, "DB", fake_db)
    app_module.init_db()
    ensure_tables(fake_db)

    client = app_module.app.test_client()
    client.post("/login", data={"username": "demo", "password": "rimai2026"})
    resp = client.get("/yield", follow_redirects=True)

    assert resp.status_code == 200
    assert b"folded into Crop Advisor" in resp.data


def test_officer_sees_relabeled_nav_not_farmer_labels(monkeypatch, tmp_path):
    fake_db = str(tmp_path / "officer_nav_test.db")
    import app as app_module
    from integrations.proactive_alerts import ensure_tables
    monkeypatch.setattr(app_module, "DB", fake_db)
    app_module.init_db()
    ensure_tables(fake_db)

    client = app_module.app.test_client()
    client.post("/login", data={"username": "officer", "password": "officer2026"})
    resp = client.get("/advisor")
    body = resp.get_data(as_text=True)

    assert "Field Assessment Mode" in body


def test_farmer_does_not_see_officer_specific_banner(monkeypatch, tmp_path):
    fake_db = str(tmp_path / "farmer_no_banner_test.db")
    import app as app_module
    from integrations.proactive_alerts import ensure_tables
    monkeypatch.setattr(app_module, "DB", fake_db)
    app_module.init_db()
    ensure_tables(fake_db)

    client = app_module.app.test_client()
    client.post("/login", data={"username": "demo", "password": "rimai2026"})
    resp = client.get("/advisor")
    body = resp.get_data(as_text=True)

    assert "Field Assessment Mode" not in body


def test_gps_province_centroids_present_for_all_ten_provinces():
    """Sanity check that the JS-embedded centroid table (checked via the
    rendered template) covers all 10 provinces — a missing one would mean
    GPS silently fails to match for farmers in that province."""
    template_path = os.path.join(
        os.path.dirname(__file__), "..", "templates", "advisor.html"
    )
    content = open(template_path).read()
    provinces = [
        "Mashonaland Central", "Matabeleland South", "Masvingo",
        "Matabeleland North", "Midlands", "Mashonaland West",
        "Bulawayo", "Manicaland", "Mashonaland East", "Harare",
    ]
    for p in provinces:
        assert p in content, f"{p} missing from GPS centroid table in advisor.html"
