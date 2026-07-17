"""
Tests for the page_visits logging feature (app.log_page_visit before_request
hook) and dashboards.admin.recent_activity().
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dashboards.admin import recent_activity


def test_page_visits_are_logged(monkeypatch, tmp_path):
    fake_db = str(tmp_path / "visit_test.db")
    import app as app_module
    from integrations.proactive_alerts import ensure_tables
    monkeypatch.setattr(app_module, "DB", fake_db)
    app_module.init_db()
    ensure_tables(fake_db)

    client = app_module.app.test_client()
    client.get("/")
    client.get("/login")
    client.post("/login", data={"username": "demo", "password": "rimai2026"})
    client.get("/dashboard")

    activity = recent_activity(fake_db)
    assert activity["total_count"] >= 3
    paths = [v["path"] for v in activity["visits"]]
    assert "/dashboard" in paths


def test_logged_in_visits_record_username_and_role(monkeypatch, tmp_path):
    fake_db = str(tmp_path / "visit_role_test.db")
    import app as app_module
    monkeypatch.setattr(app_module, "DB", fake_db)
    app_module.init_db()

    client = app_module.app.test_client()
    client.post("/login", data={"username": "admin", "password": "admin2026"})
    client.get("/admin")

    activity = recent_activity(fake_db)
    admin_visits = [v for v in activity["visits"] if v["path"] == "/admin"]
    assert len(admin_visits) >= 1
    assert admin_visits[0]["username"] == "admin"
    assert admin_visits[0]["role"] == "admin"


def test_api_chat_is_not_double_logged(monkeypatch, tmp_path):
    """/api/chat is intentionally excluded from page_visits since chat
    turns are already recorded in chat_history — shouldn't show up twice."""
    fake_db = str(tmp_path / "visit_chat_test.db")
    import app as app_module
    monkeypatch.setattr(app_module, "DB", fake_db)
    app_module.init_db()

    client = app_module.app.test_client()
    client.post("/login", data={"username": "demo", "password": "rimai2026"})
    client.post("/api/chat", data={"message": "hello"})

    activity = recent_activity(fake_db)
    paths = [v["path"] for v in activity["visits"]]
    assert "/api/chat" not in paths


def test_recent_activity_counts_unique_sessions(monkeypatch, tmp_path):
    fake_db = str(tmp_path / "visit_unique_test.db")
    import app as app_module
    from integrations.proactive_alerts import ensure_tables
    monkeypatch.setattr(app_module, "DB", fake_db)
    app_module.init_db()
    ensure_tables(fake_db)  # /dashboard's context processor queries the alerts table

    client = app_module.app.test_client()
    client.post("/login", data={"username": "demo", "password": "rimai2026"})
    client.get("/dashboard")
    client.get("/dashboard")
    client.get("/dashboard")

    activity = recent_activity(fake_db)
    # The three /dashboard visits are all by the same logged-in user and must
    # coalesce to one session, regardless of how many other anonymous/pre-auth
    # visits (e.g. the /login POST itself, logged before session.username is
    # set) also happened today.
    dashboard_visits = [v for v in activity["visits"] if v["path"] == "/dashboard"]
    assert len(dashboard_visits) == 3
    assert len({v["username"] for v in dashboard_visits}) == 1
