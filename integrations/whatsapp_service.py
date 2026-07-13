"""
RimAI WhatsApp Notification Service
Sends real WhatsApp messages via Twilio sandbox (free tier).
Gracefully disabled when credentials are not configured — app works fine without it.

Message types:
  - planting_alert    : planting window opened / closing
  - pest_warning      : active pest/disease outbreak detected
  - weather_alert     : rainfall or temperature threshold crossed
  - fertilizer_reminder: top-dressing timing based on planting date
  - harvest_reminder  : estimated harvest window approaching
  - weekly_digest     : weekly farm status summary
"""
import os
import json
import datetime
import sqlite3

TWILIO_SID   = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM  = "whatsapp:+14155238886"   # Twilio sandbox number (universal)

def _is_configured():
    return bool(TWILIO_SID and TWILIO_TOKEN and
                TWILIO_SID != "PASTE_YOUR_TWILIO_SID" and
                TWILIO_TOKEN != "PASTE_YOUR_TWILIO_TOKEN")

def send_whatsapp(to_number, message):
    """
    Send a WhatsApp message via Twilio sandbox.
    to_number: farmer's phone number in E.164 format, e.g. +263771234567
    Returns: {"success": True, "sid": "..."} or {"success": False, "error": "..."}
    """
    if not _is_configured():
        return {"success": False, "error": "Twilio not configured — message logged only",
                "simulated": True, "message": message}
    try:
        from twilio.rest import Client
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        msg = client.messages.create(
            from_=TWILIO_FROM,
            to=f"whatsapp:{to_number}",
            body=message
        )
        return {"success": True, "sid": msg.sid}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Message builders ─────────────────────────────────────────────────────────

def build_planting_alert(farm_data):
    province  = farm_data.get("province", "your area")
    timing    = farm_data.get("timing", "unknown")
    variety   = farm_data.get("recommended_variety", "SC513")
    rainfall  = farm_data.get("total_rainfall_mm", 0)
    risk      = farm_data.get("risk_label", "unknown")

    if timing == "plant_now":
        return (f"🌾 *RimAI Planting Alert*\n\n"
                f"✅ The planting window is NOW OPEN for {province}.\n\n"
                f"📊 Current conditions:\n"
                f"• Seasonal rainfall: {rainfall}mm\n"
                f"• Risk level: {risk}\n"
                f"• Recommended variety: {variety}\n\n"
                f"⏰ Plant as soon as possible to maximise your growing season.\n\n"
                f"_Reply STOP to unsubscribe · RimAI.zw_")
    elif timing == "wait":
        return (f"🌾 *RimAI Planting Update*\n\n"
                f"⏳ Not yet time to plant in {province}.\n\n"
                f"Current rainfall ({rainfall}mm) is below the planting threshold. "
                f"Watch for 25mm+ of sustained rain before planting.\n\n"
                f"We will alert you when the window opens. 📱\n\n"
                f"_RimAI.zw_")
    else:
        return (f"⚠️ *RimAI Late Planting Warning*\n\n"
                f"You are in the late planting window for {province}.\n\n"
                f"Risk: *{risk}*. Consider a short-season variety (SC403) "
                f"to reduce moisture stress at tasseling.\n\n"
                f"Act now — delays reduce yield further.\n\n"
                f"_RimAI.zw_")


def build_pest_warning(farm_data):
    province    = farm_data.get("province", "your area")
    pest_alerts = farm_data.get("pest_alerts", [])

    if not pest_alerts:
        return None

    lines = [f"🐛 *RimAI Pest Alert — {province}*\n"]
    for alert in pest_alerts:
        sev_icon = "🔴" if alert["severity"] == "High" else "🟡"
        lines.append(f"{sev_icon} *{alert['name']}* ({alert['severity']} risk)")
        lines.append(f"   Window: {alert['window']}")
        lines.append(f"   Action: {alert['action']}\n")

    lines.append("🔍 Scout your crop immediately. Early detection saves significant cost.")
    lines.append("\n_RimAI.zw · Reply STOP to unsubscribe_")
    return "\n".join(lines)


def build_weather_alert(farm_data):
    province = farm_data.get("province", "your area")
    rainfall = float(farm_data.get("total_rainfall_mm", 600))
    temp     = float(farm_data.get("avg_temp_c", 22))
    humidity = float(farm_data.get("avg_humidity_pct", 55))

    alerts = []
    if rainfall < 350:
        alerts.append(f"⚠️ *Critical low rainfall* — {rainfall}mm this season. "
                      f"Irrigation now essential for viable yield.")
    elif rainfall < 500:
        alerts.append(f"🌦️ *Below-average rainfall* — {rainfall}mm. "
                      f"Supplemental irrigation strongly recommended at tasseling.")
    if temp > 28:
        alerts.append(f"🌡️ *Heat stress risk* — average {temp}°C. "
                      f"Monitor crop at tasseling for pollen viability issues.")
    if humidity > 75:
        alerts.append(f"💧 *High humidity* — {humidity}%. "
                      f"Elevated fungal disease risk. Scout for grey leaf spot.")

    if not alerts:
        return None

    msg = f"🌤️ *RimAI Weather Alert — {province}*\n\n"
    msg += "\n\n".join(alerts)
    msg += f"\n\n_RimAI.zw · {datetime.date.today().strftime('%d %b %Y')}_"
    return msg


def build_fertilizer_reminder(farm_data):
    province     = farm_data.get("province", "your area")
    planting_date= farm_data.get("planting_date", "")
    an_kg        = farm_data.get("an_kg", 0)
    size         = farm_data.get("farm_size", 1)

    try:
        pd_obj = datetime.datetime.strptime(planting_date, "%Y-%m-%d").date()
        days_since = (datetime.date.today() - pd_obj).days
        top_dress_day = 35  # 4-6 leaf stage, typically 35-42 days after planting
        days_to_td = top_dress_day - days_since

        if 0 <= days_to_td <= 7:
            urgency = "NOW" if days_to_td <= 3 else f"in {days_to_td} days"
            return (f"🌱 *RimAI Fertilizer Reminder — {province}*\n\n"
                    f"⏰ Top-dressing is due *{urgency}*!\n\n"
                    f"📋 Your recommendation:\n"
                    f"• Ammonium Nitrate: *{an_kg}kg* for your {size}ha\n"
                    f"• Apply when soil is moist after rain\n"
                    f"• Do NOT apply during drought — burns the crop\n\n"
                    f"Timing top-dressing correctly adds up to 0.4 t/ha to your yield. 💪\n\n"
                    f"_RimAI.zw_")
    except Exception:
        pass
    return None


def build_harvest_reminder(farm_data):
    province     = farm_data.get("province", "your area")
    planting_date= farm_data.get("planting_date", "")
    yield_pred   = farm_data.get("yield_t_ha", 0)
    size         = farm_data.get("farm_size", 1)
    variety      = farm_data.get("recommended_variety", "SC513")

    # Days to maturity by variety
    maturity_days = {"SC513": 140, "SC403": 120, "SC301": 100}.get(variety, 130)

    try:
        pd_obj = datetime.datetime.strptime(planting_date, "%Y-%m-%d").date()
        harvest_date = pd_obj + datetime.timedelta(days=maturity_days)
        days_to_harvest = (harvest_date - datetime.date.today()).days

        if 0 <= days_to_harvest <= 14:
            total = round(float(yield_pred) * float(size), 1) if yield_pred else "—"
            return (f"🌽 *RimAI Harvest Alert — {province}*\n\n"
                    f"Your maize is approaching maturity! "
                    f"Expected harvest: *{harvest_date.strftime('%d %b %Y')}*\n\n"
                    f"📊 Your forecast:\n"
                    f"• Predicted yield: {yield_pred} t/ha\n"
                    f"• Estimated total: {total} tonnes\n\n"
                    f"✅ Pre-harvest checklist:\n"
                    f"• Arrange storage or market before cutting\n"
                    f"• Check grain moisture before bagging (14% or below)\n"
                    f"• Record your actual yield in RimAI to improve future predictions\n\n"
                    f"_RimAI.zw_")
    except Exception:
        pass
    return None


def build_weekly_digest(farm_data):
    province  = farm_data.get("province", "your area")
    risk      = farm_data.get("risk_label", "unknown")
    rainfall  = farm_data.get("total_rainfall_mm", 0)
    temp      = farm_data.get("avg_temp_c", 0)
    yield_pred= farm_data.get("yield_t_ha", 0)
    pest_alerts = farm_data.get("pest_alerts", [])
    timing    = farm_data.get("timing", "unknown")

    today = datetime.date.today().strftime("%d %b %Y")
    risk_icon = {"Low":"✅","Moderate":"⚠️","High":"🔴"}.get(risk, "ℹ️")

    pest_line = (f"🐛 Active alerts: {', '.join(a['name'] for a in pest_alerts)}"
                 if pest_alerts else "🐛 No active pest alerts")

    timing_line = {"plant_now":"🌱 Planting window: OPEN — plant now",
                   "wait":"⏳ Planting window: Not yet open",
                   "risky":"⚠️ Late planting — act urgently"}.get(timing, "")

    return (f"🌾 *RimAI Weekly Digest — {today}*\n"
            f"📍 {province}\n\n"
            f"{risk_icon} Season risk: *{risk}*\n"
            f"🌧️ Rainfall: {rainfall}mm\n"
            f"🌡️ Avg temp: {temp}°C\n"
            f"📊 Predicted yield: {yield_pred} t/ha\n"
            f"{pest_line}\n"
            f"{timing_line}\n\n"
            f"Open RimAI for full recommendations. 📱\n"
            f"_RimAI.zw · Reply STOP to unsubscribe_")


def send_all_relevant(to_number, farm_data):
    """
    Check all message types and send whichever are triggered by current conditions.
    Returns list of results.
    """
    results = []
    builders = [
        ("planting_alert",     build_planting_alert),
        ("pest_warning",       build_pest_warning),
        ("weather_alert",      build_weather_alert),
        ("fertilizer_reminder",build_fertilizer_reminder),
        ("harvest_reminder",   build_harvest_reminder),
    ]
    for msg_type, builder in builders:
        try:
            msg = builder(farm_data)
            if msg:
                result = send_whatsapp(to_number, msg)
                result["type"] = msg_type
                result["preview"] = msg[:80] + "..."
                results.append(result)
        except Exception as e:
            results.append({"type": msg_type, "success": False, "error": str(e)})
    return results


def log_message(db_path, user_id, msg_type, message, result):
    """Log every outbound message to the database."""
    try:
        conn = sqlite3.connect(db_path)
        status = "simulated" if result.get("simulated") else ("sent" if result.get("success") else "failed")
        conn.execute(
            "INSERT INTO whatsapp_log (user_id, msg_type, message, status, created_at) "
            "VALUES (?,?,?,?,?)",
            (user_id, msg_type, message, status,
             datetime.datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
    except Exception:
        pass
