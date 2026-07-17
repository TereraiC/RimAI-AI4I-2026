"""
Regression test for a real bug found during pre-submission QA: several
routes read columns/tables that were never actually defined in init_db(),
so a completely fresh database crashed on /farm-manager (missing
users.full_name) and /agritex (missing field_visits and
input_allocations tables). This had been silently masked because the
long-running development database already had these added by hand.

This test creates a throwaway fresh database and confirms every table
and column the application actually queries exists after init_db() runs.
"""
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def test_fresh_database_has_all_required_tables_and_columns(monkeypatch, tmp_path):
    fake_db = str(tmp_path / "fresh_test.db")
    monkeypatch.setenv("RIMAI_DB_PATH", fake_db)

    # app.py reads DB as a module-level constant, so patch it directly
    # after import rather than relying on an env var it doesn't read yet.
    import app as app_module
    monkeypatch.setattr(app_module, "DB", fake_db)
    app_module.init_db()

    conn = sqlite3.connect(fake_db)
    conn.row_factory = sqlite3.Row

    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}

    required_tables = {
        "users", "predictions", "yield_history",
        "whatsapp_subscriptions", "whatsapp_log", "chat_history",
        "field_visits", "input_allocations", "page_visits",
    }
    missing = required_tables - tables
    assert not missing, f"Fresh database is missing tables: {missing}"

    user_cols = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    assert "full_name" in user_cols, "users table is missing the full_name column"

    conn.close()


def test_fresh_database_has_all_four_demo_accounts(monkeypatch, tmp_path):
    """Regression test for a real bug found live on the Render deployment:
    init_db() only ever seeded 'demo' and 'officer' accounts. 'ministry'
    and 'admin' had only ever been added by hand in an old development
    database, so every genuinely fresh install (including the first
    Render deploy) had no way to log in as Ministry or Admin at all."""
    fake_db = str(tmp_path / "fresh_accounts_test.db")

    import app as app_module
    monkeypatch.setattr(app_module, "DB", fake_db)
    app_module.init_db()

    conn = sqlite3.connect(fake_db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT username, role FROM users").fetchall()
    usernames = {r["username"] for r in rows}
    conn.close()

    required_accounts = {"demo", "officer", "ministry", "admin"}
    missing = required_accounts - usernames
    assert not missing, f"Fresh database is missing demo accounts: {missing}"
