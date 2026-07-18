"""
Tests for a real data-minimization gap found during a privacy review:
the proposal's own text states "AGRITEX and Ministry users viewing only
aggregated district or provincial intelligence unless explicitly
authorized" (Section 4), but the actual code showed individual farmer
names to every logged-in role with no restriction at all, and the field
visit query wasn't even scoped by province for the officer role itself.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _login(client, username, password):
    return client.post("/login", data={"username": username, "password": password})


def test_ministry_does_not_see_individual_farmer_names(monkeypatch, tmp_path):
    fake_db = str(tmp_path / "privacy_ministry_test.db")
    import app as app_module
    from integrations.proactive_alerts import ensure_tables
    monkeypatch.setattr(app_module, "DB", fake_db)
    app_module.init_db()
    ensure_tables(fake_db)
    app_module.seed_demo_farmer_data()

    client = app_module.app.test_client()
    _login(client, "ministry", "ministry2026")
    resp = client.get("/agritex")
    body = resp.get_data(as_text=True)

    assert "Tendai Moyo" not in body  # a real seeded farmer name
    assert "Farmer #" in body  # anonymized placeholder present instead


def test_officer_still_sees_real_farmer_names(monkeypatch, tmp_path):
    fake_db = str(tmp_path / "privacy_officer_test.db")
    import app as app_module
    from integrations.proactive_alerts import ensure_tables
    monkeypatch.setattr(app_module, "DB", fake_db)
    app_module.init_db()
    ensure_tables(fake_db)
    app_module.seed_demo_farmer_data()

    client = app_module.app.test_client()
    _login(client, "officer", "officer2026")
    resp = client.get("/agritex")
    body = resp.get_data(as_text=True)

    assert "Tendai Moyo" in body  # officer needs real names for fieldwork


def test_ministry_cannot_see_log_a_field_visit_form(monkeypatch, tmp_path):
    fake_db = str(tmp_path / "privacy_form_test.db")
    import app as app_module
    from integrations.proactive_alerts import ensure_tables
    monkeypatch.setattr(app_module, "DB", fake_db)
    app_module.init_db()
    ensure_tables(fake_db)

    client = app_module.app.test_client()
    _login(client, "ministry", "ministry2026")
    resp = client.get("/agritex")
    body = resp.get_data(as_text=True)

    assert "Log a Field Visit" not in body


def test_officer_field_visits_are_scoped_to_own_province(monkeypatch, tmp_path):
    """Regression test: field visit reports weren't scoped by province at
    all before this fix — any officer could see visit reports written by
    officers in every other province."""
    fake_db = str(tmp_path / "privacy_scope_test.db")
    import app as app_module
    from integrations.proactive_alerts import ensure_tables
    monkeypatch.setattr(app_module, "DB", fake_db)
    app_module.init_db()
    ensure_tables(fake_db)
    app_module.seed_demo_farmer_data()

    with app_module.get_db() as db:
        db.execute(
            "INSERT INTO field_visits (officer_id, farmer_id, observation, recommendation, follow_up_date) "
            "SELECT (SELECT id FROM users WHERE username='officer'), id, 'Test observation', "
            "'Test recommendation', '2026-12-01' FROM users WHERE username='farmer_gwanda'"
        )
        db.commit()

    client = app_module.app.test_client()
    _login(client, "officer", "officer2026")  # scoped to Mashonaland West
    resp = client.get("/agritex")
    body = resp.get_data(as_text=True)

    # farmer_gwanda is in Matabeleland South, not the officer's Mashonaland
    # West — this visit report should not appear.
    assert "Test observation" not in body
