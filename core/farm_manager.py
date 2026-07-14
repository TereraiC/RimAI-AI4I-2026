"""
RimAI Farm Manager — supporting logic for the Farmer Dashboard
("My AI Farm Manager"): Farm Health Score, AI Daily Brief, Farm Memory,
Action Calendar, and the What-If Scenario Simulator.

Everything here is derived from real analysis output already produced by
crop_advisor.get_full_farm_analysis() and harvest_model.predict_yield() —
no numbers are invented that aren't traceable back to those.
"""
import datetime
from core.harvest_model import PROVINCE_META, predict_yield


def health_score(analysis):
    """
    Composite 0-100 Farm Health Score from four real signals:
    season risk, pest pressure, yield vs provincial benchmark, and
    fertilizer ROI (financial health proxy).
    """
    risk_label = analysis.get("risk_label", "Moderate")
    risk_score = {"Low": 92, "Moderate": 62, "High": 32}.get(risk_label, 55)

    alerts = analysis.get("pest_risk", {}).get("active_alerts", [])
    penalty = sum(25 if a.get("severity") == "High" else 15 if a.get("severity") == "Moderate" else 8
                  for a in alerts)
    pest_score = max(0, 100 - penalty)

    province = analysis.get("inputs_used", {}).get("province", "Harare")
    benchmark = PROVINCE_META.get(province, {}).get("avg_yield", 1.8)
    yield_pred = float(analysis.get("yield_t_ha") or 0)
    ratio = (yield_pred / benchmark) if benchmark else 1
    yield_score = max(0, min(100, round(50 + (ratio - 1) * 100)))

    roi = analysis.get("economic", {}).get("fertilizer_roi_pct")
    if roi is not None:
        financial_score = max(0, min(100, round(50 + roi / 2)))
    else:
        financial_score = 60

    overall = round(0.30 * risk_score + 0.20 * pest_score + 0.30 * yield_score + 0.20 * financial_score)
    return {
        "overall": max(0, min(100, overall)),
        "risk": risk_score,
        "pest": pest_score,
        "yield": yield_score,
        "financial": financial_score,
    }


def daily_brief(analysis, latest_alert_message=None):
    """
    A short, dynamic "what matters today" sentence built from real signals:
    the most recent proactive alert (if any), otherwise the current risk,
    pest, and timing status.
    """
    if latest_alert_message:
        return latest_alert_message

    timing = analysis.get("timing", "unknown")
    risk_label = analysis.get("risk_label", "unknown")
    alerts = analysis.get("pest_risk", {}).get("active_alerts", [])

    if alerts:
        top = alerts[0]
        return (f"Priority today: scout for {top['name']} ({top['severity']} risk) — "
                f"{top['action'].split('.')[0]}.")
    if timing == "plant_now":
        return f"The planting window is open and season risk is {risk_label}. Good day to plant or continue planting."
    if timing == "wait":
        return "Too early to plant — hold off until sustained rain arrives. No action needed today."
    if timing == "risky":
        return f"Late planting window — {risk_label} risk. Consider a short-season variety to reduce exposure."
    return f"Current season risk: {risk_label}. No urgent actions flagged today."


def farm_memory(current, previous):
    """
    Compares this run's analysis to the farmer's last recorded season and
    returns a one-line "the AI remembers" note, or None if there isn't a
    prior season to compare against.
    """
    if not previous:
        return None
    cur_yield = current.get("yield_t_ha")
    prev_yield = previous.get("yield_t_ha")
    cur_rain = current.get("weather", {}).get("extrapolated_season_total_mm") or current.get("weather", {}).get("total_rainfall_mm")
    prev_rain = previous.get("weather", {}).get("extrapolated_season_total_mm") or previous.get("weather", {}).get("total_rainfall_mm")
    prev_inputs = previous.get("inputs_used", {})
    planting_date = prev_inputs.get("planting_date", "last season")
    crop = prev_inputs.get("crop", "maize")

    if cur_yield is None or prev_yield is None:
        return None

    diff_pct = round(((cur_yield - prev_yield) / prev_yield) * 100, 1) if prev_yield else 0
    direction = "up" if diff_pct >= 0 else "down"
    rain_note = ""
    if cur_rain and prev_rain:
        rain_diff_pct = round(((cur_rain - prev_rain) / prev_rain) * 100, 1)
        if abs(rain_diff_pct) >= 5:
            rain_note = f" Rainfall is {'up' if rain_diff_pct >= 0 else 'down'} {abs(rain_diff_pct)}% versus that season."

    month_label = planting_date[:7] if isinstance(planting_date, str) else "last season"
    return (f"Last season you planted {crop.lower()} around {month_label} and harvested "
            f"{prev_yield} t/ha. This season's forecast is {cur_yield} t/ha — "
            f"{direction} {abs(diff_pct)}%.{rain_note}")


def action_calendar(analysis):
    """
    A forward-looking calendar: fertilizer top-dress, key pest scouting
    windows, tasseling/grain fill irrigation windows, and an estimated
    harvest date.

    Anchored on the farmer's own planting date ONLY if that date actually
    falls within the recommended planting window (timing == 'plant_now').
    If the farmer's date was too early or too late, building a calendar
    from a date the system has already flagged as wrong would produce a
    nonsensical schedule (e.g. a 'Tasseling' window in the middle of the
    dry season) — so the calendar instead anchors on the suggested
    recommended date, clearly labelled as such.
    """
    inputs = analysis.get("inputs_used", {})
    timing = analysis.get("timing")
    chosen_date_str = inputs.get("planting_date")
    suggested_date_str = analysis.get("suggested_planting_date_iso")

    using_suggested = False
    anchor_str = chosen_date_str
    if timing != "plant_now" and suggested_date_str:
        anchor_str = suggested_date_str
        using_suggested = True

    events = []
    if not anchor_str:
        return {"events": events, "using_suggested_date": False, "chosen_date_was_rejected": False}
    try:
        planting_date = datetime.datetime.strptime(anchor_str[:10], "%Y-%m-%d").date()
    except ValueError:
        return {"events": events, "using_suggested_date": False, "chosen_date_was_rejected": False}

    events.append({"date": planting_date, "label": "Planting",
                    "note": "Plant seed at recommended spacing."})
    events.append({"date": planting_date + datetime.timedelta(days=21),
                    "label": "Scout for Fall Armyworm", "note": "Check whorls for window-pane damage weekly from here."})
    events.append({"date": planting_date + datetime.timedelta(days=30),
                    "label": "Top-dress fertilizer", "note": "Apply Ammonium Nitrate at 4-6 leaf stage."})
    events.append({"date": planting_date + datetime.timedelta(days=62),
                    "label": "Tasseling — critical irrigation window", "note": "Prioritise water here if supply is limited."})
    events.append({"date": planting_date + datetime.timedelta(days=85),
                    "label": "Grain fill — irrigation window", "note": "Second most critical water stage."})
    events.append({"date": planting_date + datetime.timedelta(days=135),
                    "label": "Estimated harvest", "note": "Based on a standard ~135-day medium-season variety."})

    today = datetime.date.today()
    for e in events:
        e["date_str"] = e["date"].strftime("%d %b %Y")
        e["is_past"] = e["date"] < today
        e["days_away"] = (e["date"] - today).days

    return {
        "events": events,
        "using_suggested_date": using_suggested,
        "chosen_date_was_rejected": using_suggested and bool(chosen_date_str),
    }


def run_scenario(base_analysis, rainfall_pct_change=0, temp_delta_c=0, fertilizer_on=True):
    """
    Re-run the yield model with adjusted rainfall/temperature/fertilizer
    assumptions and compare against the farmer's current baseline —
    the What-If Scenario Simulator.
    """
    inputs = base_analysis.get("inputs_used", {})
    weather = base_analysis.get("weather", {})
    province = inputs.get("province", "Harare")
    farm_size = float(inputs.get("farm_size", 1))

    base_rainfall = float(weather.get("extrapolated_season_total_mm") or weather.get("total_rainfall_mm") or PROVINCE_META.get(province, {}).get("avg_rain", 700))
    base_temp = float(weather.get("avg_temp_c", 22))
    base_fert_rate = 180 if fertilizer_on else 0

    scenario_inputs = {
        "province": province,
        "rainfall_mm": round(base_rainfall * (1 + rainfall_pct_change / 100), 1),
        "temperature_c": round(base_temp + temp_delta_c, 1),
        "planting_month": 11,
        "farm_size_ha": farm_size,
        "fertilizer_rate": base_fert_rate,
    }
    result = predict_yield(scenario_inputs)

    base_yield = float(base_analysis.get("yield_t_ha") or 0)
    new_yield = result["yield_t_ha"]
    yield_delta = round(new_yield - base_yield, 2)

    price = base_analysis.get("economic", {}).get("maize_price_per_tonne", 280)
    revenue_delta = round(yield_delta * farm_size * price, 0)

    return {
        "scenario_inputs": scenario_inputs,
        "yield_t_ha": new_yield,
        "risk_label": result["risk_label"],
        "yield_delta": yield_delta,
        "revenue_delta_usd": int(revenue_delta),
    }
