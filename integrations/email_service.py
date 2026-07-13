"""
RimAI Email Reports & Alerts
Sends farm alerts and weekly reports by email over plain SMTP — works with
ANY provider (Gmail, Brevo, SendGrid, Zoho, etc). Gracefully falls back to a
"simulated" demo mode when no credentials are configured, so the app never
breaks a demo.

Recommended provider for this project: Brevo (https://www.brevo.com) — free
forever plan, 300 emails/day, no credit card, and its SMTP relay is built
for exactly this kind of transactional/alert sending (unlike Gmail, which
increasingly throttles or blocks unattended script logins even with an app
password). Point EMAIL_SMTP_HOST at smtp-relay.brevo.com if you go that
route; Gmail's smtp.gmail.com works too for the demo.
"""
import os
import smtplib
import ssl
import datetime
import sqlite3
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

SMTP_HOST     = os.environ.get("EMAIL_SMTP_HOST", "")
SMTP_PORT     = int(os.environ.get("EMAIL_SMTP_PORT", "587"))
SMTP_USER     = os.environ.get("EMAIL_SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("EMAIL_SMTP_PASSWORD", "")
EMAIL_FROM    = os.environ.get("EMAIL_FROM", SMTP_USER)


def _is_configured():
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD and
                SMTP_PASSWORD != "PASTE_YOUR_EMAIL_APP_PASSWORD")


def send_email(to_addr, subject, body_text):
    """
    Send a plain-text email.
    Returns {"success": True} or {"success": False, "simulated": True, ...}
    in demo mode, or {"success": False, "error": ...} on a real failure.
    """
    if not _is_configured():
        return {"success": False, "simulated": True,
                "error": "Email not configured — message logged only",
                "message": body_text}
    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_FROM
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg.attach(MIMEText(body_text, "plain"))
        context = ssl.create_default_context()
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.starttls(context=context)
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(EMAIL_FROM, to_addr, msg.as_string())
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Report builders (email-friendly siblings of whatsapp_service builders) ──

def build_risk_alert_email(farm_data):
    province = farm_data.get("province", "your farm")
    risk     = farm_data.get("risk_label", "unknown")
    conf     = farm_data.get("risk_confidence", "")
    rainfall = farm_data.get("total_rainfall_mm", 0)
    conf_str = f" ({conf}% confidence)" if conf else ""
    subject = f"RimAI Alert: {risk} risk season for {province}"
    body = (f"RimAI Season Risk Update — {province}\n\n"
            f"Risk level: {risk}{conf_str}\n"
            f"Seasonal rainfall so far: {rainfall}mm\n\n"
            f"Log in to RimAI for the full breakdown and recommended actions.\n\n"
            f"— RimAI, Zimbabwe Agricultural Intelligence Platform")
    return subject, body


def build_pest_alert_email(farm_data):
    pest_alerts = farm_data.get("pest_alerts", [])
    if not pest_alerts:
        return None
    province = farm_data.get("province", "your farm")
    subject = f"RimAI Pest Alert: {len(pest_alerts)} active alert(s) for {province}"
    lines = [f"RimAI Pest & Disease Alert — {province}", ""]
    for a in pest_alerts:
        lines.append(f"- {a['name']} ({a['severity']} risk)")
        lines.append(f"  Window: {a['window']}")
        lines.append(f"  Action: {a['action']}")
        lines.append("")
    lines.append("Scout your field as soon as possible.")
    lines.append("")
    lines.append("— RimAI")
    return subject, "\n".join(lines)


def build_weekly_report_email(farm_data):
    province    = farm_data.get("province", "your farm")
    risk        = farm_data.get("risk_label", "unknown")
    rainfall    = farm_data.get("total_rainfall_mm", 0)
    temp        = farm_data.get("avg_temp_c", 0)
    yield_pred  = farm_data.get("yield_t_ha", 0)
    size        = farm_data.get("farm_size", 1)
    pest_alerts = farm_data.get("pest_alerts", [])
    timing      = farm_data.get("timing", "unknown")
    today       = datetime.date.today().strftime("%d %b %Y")

    timing_line = {"plant_now": "Planting window: OPEN — plant now",
                   "wait":      "Planting window: not yet open",
                   "risky":     "Late planting window — act urgently"}.get(timing, "")
    pest_line = (f"Active pest alerts: {', '.join(a['name'] for a in pest_alerts)}"
                 if pest_alerts else "No active pest alerts")
    total = round(float(yield_pred) * float(size), 1) if yield_pred else "-"

    subject = f"RimAI Weekly Farm Report — {province} — {today}"
    body = (
        f"RimAI Weekly Farm Report\n"
        f"{province} — {today}\n"
        f"{'=' * 40}\n\n"
        f"Season risk: {risk}\n"
        f"Rainfall: {rainfall}mm | Avg temp: {temp}C\n"
        f"Predicted yield: {yield_pred} t/ha ({total} t total on {size}ha)\n"
        f"{pest_line}\n"
        f"{timing_line}\n\n"
        f"Log in to RimAI for the full recommendation and to chat with your "
        f"Farm Assistant.\n\n"
        f"— RimAI, Zimbabwe Agricultural Intelligence Platform"
    )
    return subject, body


def log_email(db_path, user_id, msg_type, message, result):
    """Log every outbound email to the database (mirrors whatsapp_service.log_message,
    fixing the same status bug: demo/simulated sends must not show up as 'failed')."""
    try:
        conn = sqlite3.connect(db_path)
        status = "simulated" if result.get("simulated") else ("sent" if result.get("success") else "failed")
        conn.execute(
            "INSERT INTO email_log (user_id, msg_type, message, status, created_at) "
            "VALUES (?,?,?,?,?)",
            (user_id, msg_type, message, status, datetime.datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
    except Exception:
        pass
