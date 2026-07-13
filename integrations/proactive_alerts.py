"""
RimAI Proactive Alerts
Watches every farmer's last Crop Advisor run in the background and re-checks
live conditions on an interval. When risk escalates, a new pest alert
appears, or the planting window opens, it:

  1. Drops a message straight into the farmer's Farm Assistant chat history,
     so they see it the moment they next open the app, and
  2. Pushes it out over WhatsApp / Email for anyone subscribed to that
     alert type.

This reads/writes the database directly (not the Flask session), so it
works even when nobody has the app open — that's what makes it "proactive"
rather than just "recomputed on page load".
"""
import json
import time
import sqlite3
import threading

from core.crop_advisor import get_full_farm_analysis
from integrations.whatsapp_service import send_whatsapp, log_message as log_whatsapp
from integrations.email_service import send_email, log_email

CHECK_INTERVAL_SECONDS = 120   # short for demo purposes; use hours in production
RISK_RANK = {"Low": 0, "Moderate": 1, "High": 2}


def _db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_tables(db_path):
    with _db(db_path) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                alert_type TEXT,
                message TEXT,
                seen INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS email_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                email TEXT NOT NULL,
                alert_risk INTEGER DEFAULT 1,
                alert_pest INTEGER DEFAULT 1,
                alert_weekly INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS email_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                msg_type TEXT,
                message TEXT,
                status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        db.commit()


def _latest_prediction(db_path, user_id):
    with _db(db_path) as db:
        row = db.execute(
            "SELECT inputs, result FROM predictions "
            "WHERE user_id=? AND prediction_type='crop_advisor' "
            "ORDER BY created_at DESC LIMIT 1", (user_id,)).fetchone()
    if not row:
        return None, None
    return json.loads(row["inputs"]), json.loads(row["result"])


def _farm_data_from_analysis(analysis):
    fd = {}
    fd.update(analysis.get("inputs_used", {}))
    fd.update(analysis.get("weather", {}))
    fd["timing"]          = analysis.get("timing", "unknown")
    fd["risk_label"]      = analysis.get("risk_label", "unknown")
    fd["risk_confidence"] = analysis.get("risk_confidence")
    fd["yield_t_ha"]      = analysis.get("yield_t_ha")
    fd["pest_alerts"]     = analysis.get("pest_risk", {}).get("active_alerts", [])
    return fd


def _store_alert(db_path, user_id, alert_type, message):
    with _db(db_path) as db:
        db.execute("INSERT INTO alerts (user_id, alert_type, message) VALUES (?,?,?)",
                   (user_id, alert_type, message))
        db.execute("INSERT INTO chat_history (user_id, role, content) VALUES (?,?,?)",
                   (user_id, "assistant", "\U0001F514 " + message))
        db.commit()


def check_farmer(db_path, user_id):
    """
    Re-run the crop advisor on a farmer's last known inputs and diff the
    fresh result against what they were last shown.
    Returns (new_alerts, fresh_analysis) or None if the farmer has never
    run the Crop Advisor.
    """
    inputs, old = _latest_prediction(db_path, user_id)
    if not inputs or not old:
        return None

    try:
        fresh = get_full_farm_analysis(inputs)
    except Exception as e:
        print(f"[proactive_alerts] could not refresh user {user_id}: {e}")
        return None

    new_alerts = []
    old_risk, new_risk = old.get("risk_label"), fresh.get("risk_label")
    if new_risk and old_risk and RISK_RANK.get(new_risk, 0) > RISK_RANK.get(old_risk, 0):
        new_alerts.append(("risk_escalation",
            f"Your season risk just moved from {old_risk} to {new_risk}. "
            f"Ask me 'how risky is this season' to see what changed."))

    old_pests = {a["name"] for a in old.get("pest_risk", {}).get("active_alerts", [])}
    new_pests = {a["name"] for a in fresh.get("pest_risk", {}).get("active_alerts", [])}
    for pest in new_pests - old_pests:
        new_alerts.append(("pest",
            f"New pest alert for your area: {pest}. Ask me about it for scouting advice."))

    if old.get("timing") != "plant_now" and fresh.get("timing") == "plant_now":
        new_alerts.append(("planting_window",
            "The planting window for your farm just opened — ask me 'should I plant now'."))

    for alert_type, message in new_alerts:
        _store_alert(db_path, user_id, alert_type, message)

    # Persist the fresh reading so the *next* check diffs against this one,
    # not against the same stale baseline forever.
    with _db(db_path) as db:
        db.execute("INSERT INTO predictions (user_id,prediction_type,inputs,result) VALUES (?,?,?,?)",
                   (user_id, "crop_advisor", json.dumps(inputs), json.dumps(fresh)))
        db.commit()

    return new_alerts, fresh


def _dispatch(db_path, user_id, alert_type, message, farm_data):
    with _db(db_path) as db:
        wa_sub = db.execute("SELECT * FROM whatsapp_subscriptions WHERE user_id=?", (user_id,)).fetchone()
        em_sub = db.execute("SELECT * FROM email_subscriptions WHERE user_id=?", (user_id,)).fetchone()

    wa_pref = {"pest": "alert_pest", "planting_window": "alert_planting",
               "risk_escalation": "alert_weather"}.get(alert_type)
    if wa_sub and (wa_pref is None or wa_sub[wa_pref]):
        result = send_whatsapp(wa_sub["phone"], "RimAI Alert: " + message)
        log_whatsapp(db_path, user_id, alert_type, message, result)

    em_pref = {"pest": "alert_pest", "risk_escalation": "alert_risk"}.get(alert_type)
    if em_sub and (em_pref is None or em_sub[em_pref]):
        result = send_email(em_sub["email"], "RimAI Farm Alert", message)
        log_email(db_path, user_id, alert_type, message, result)


def run_watcher_once(db_path):
    ensure_tables(db_path)
    with _db(db_path) as db:
        user_ids = [r["id"] for r in db.execute("SELECT id FROM users WHERE role='farmer'").fetchall()]
    for uid in user_ids:
        try:
            out = check_farmer(db_path, uid)
            if not out:
                continue
            new_alerts, fresh = out
            if not new_alerts:
                continue
            farm_data = _farm_data_from_analysis(fresh)
            for alert_type, message in new_alerts:
                _dispatch(db_path, uid, alert_type, message, farm_data)
        except Exception as e:
            print(f"[proactive_alerts] skipped user {uid}: {e}")


def start_background_watcher(db_path, interval=CHECK_INTERVAL_SECONDS):
    ensure_tables(db_path)

    def loop():
        while True:
            time.sleep(interval)
            run_watcher_once(db_path)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    print(f"  ✓ Proactive alert watcher started (checks every {interval}s)")
    return t
