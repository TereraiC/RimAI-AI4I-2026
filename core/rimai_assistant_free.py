
INTENTS = [
    ("plant_now",    ["should i plant","plant now","time to plant","when to plant","right time","plant maize"]),
    ("fertilizer",   ["fertilizer","fertiliser","compound d","ammonium","npk","basal","top dress","topdress"]),
    ("yield",        ["yield","harvest","how much maize","expect to harvest","tonnes","how much will"]),
    ("low_yield",    ["why is my yield low","low yield","poor yield","yield down","bad harvest"]),
    ("irrigation",   ["irrigat","when to water","dry spell","moisture","water stress"]),
    ("weather",      ["weather","rainfall","rain","temperature","forecast","humidity"]),
    ("pest_disease", ["pest","disease","armyworm","leaf spot","streak","insect","bug","yellow leaf","holes in","white powder"]),
    ("rotation",     ["rotation","previous crop","last season","same crop","what to plant next","groundnut","soybean"]),
    ("risk",         ["risk","danger","warning","alert","safe to plant","worried","how risky"]),
    ("variety",      ["variety","seed","sc403","sc513","sc301","which seed","best seed","hybrid"]),
]

def match_intent(message):
    msg = message.lower()
    for intent, keywords in INTENTS:
        if any(k in msg for k in keywords):
            return intent
    return "general"

def build_greeting(username, farm_data, chat_history_count):
    province    = farm_data.get("province", "")
    soil        = farm_data.get("soil_type", "")
    prev_crop   = farm_data.get("previous_crop", "")
    size        = farm_data.get("farm_size", "")
    risk        = farm_data.get("risk_label", "")
    risk_conf   = farm_data.get("risk_confidence", "")
    rainfall    = farm_data.get("extrapolated_season_total_mm") or farm_data.get("total_rainfall_mm", "")
    timing      = farm_data.get("timing", "")
    yield_pred  = farm_data.get("yield_t_ha", "")
    pest_alerts = farm_data.get("pest_alerts", [])
    variety     = farm_data.get("recommended_variety", "")
    name        = username.capitalize() if username else "there"

    if not province:
        return (f"Welcome back, {name}. I am your RimAI Agronomist. "
                f"Run the Crop Advisor first and I will give you a full "
                f"briefing on your farm — no generic answers.")

    parts = []
    parts.append(f"Welcome back, {name}." if chat_history_count > 0
                 else f"Good to meet you, {name}.")

    farm_line = f"Your {size}ha {soil} farm in {province}"
    if prev_crop:
        farm_line += f", previously planted with {prev_crop}"
    parts.append(farm_line + ".")

    if risk and risk_conf:
        icon = {"Low": "✅", "Moderate": "⚠️", "High": "🔴"}.get(risk, "ℹ️")
        parts.append(f"{icon} This season is rated {risk} risk ({risk_conf}% confidence).")

    if rainfall:
        parts.append(f"Seasonal rainfall: {rainfall}mm.")

    if pest_alerts:
        names = ", ".join(a["name"] for a in pest_alerts[:2])
        parts.append(f"⚠️ Active alert: {names} — ask me about this.")
    elif timing == "plant_now":
        parts.append(f"The planting window is open — {variety} recommended.")
    elif timing == "risky":
        parts.append(f"You are in a late planting window — ask me what to do.")

    if yield_pred:
        parts.append(f"Predicted yield: {yield_pred} t/ha.")

    parts.append("What would you like to know?")
    return " ".join(parts)

def build_response(intent, farm_data, username=""):
    province    = farm_data.get("province", "your province")
    soil        = farm_data.get("soil_type", "your soil")
    prev_crop   = farm_data.get("previous_crop", "unknown")
    size        = farm_data.get("farm_size", 1)
    timing      = farm_data.get("timing", "unknown")
    risk_label  = farm_data.get("risk_label", "unknown")
    risk_score  = farm_data.get("risk_score", 0)
    risk_conf   = farm_data.get("risk_confidence", "")
    rainfall    = farm_data.get("extrapolated_season_total_mm") or farm_data.get("total_rainfall_mm", 600)
    temp        = farm_data.get("avg_temp_c", 22)
    humidity    = farm_data.get("avg_humidity_pct", 55)
    variety     = farm_data.get("recommended_variety", "SC513")
    cpd_kg      = farm_data.get("compound_d_kg", round(150 * float(size)))
    an_kg       = farm_data.get("an_kg", round(250 * float(size)))
    irrigation  = farm_data.get("irrigation", "Supplemental irrigation recommended.")
    rot_note    = farm_data.get("rotation_note", "")
    rot_verdict = farm_data.get("rotation_verdict", "Neutral")
    yield_pred  = farm_data.get("yield_t_ha")
    pest_alerts = farm_data.get("pest_alerts", [])
    agro_zone   = farm_data.get("agro_zone", "II")
    name        = username.capitalize() if username else ""
    p           = f"{name}, " if name else ""

    if intent == "plant_now":
        if timing == "plant_now":
            return (f"{p}conditions in {province} are within the optimal planting window. "
                    f"Rainfall: {rainfall}mm, temperature: {temp}°C — plant now. "
                    f"Recommended variety: {variety}.")
        elif timing == "wait":
            return (f"{p}too early to plant in {province}. Wait for 25mm+ of sustained rain. "
                    f"Current rainfall: {rainfall}mm. Planting dry wastes seed.")
        else:
            conf = f" ({risk_conf}% confidence)" if risk_conf else ""
            return (f"{p}late planting window in {province} — {risk_label} risk{conf}. "
                    f"Use SC403 short-season variety to reduce growing period.")

    elif intent == "fertilizer":
        return (f"For your {size}ha {soil} farm in {province}: "
                f"Compound D (basal): {cpd_kg}kg at planting. "
                f"Ammonium Nitrate (top dress): {an_kg}kg at 4-6 leaf stage. "
                f"Apply Compound D in the furrow for maximum root contact.")

    elif intent == "yield":
        if yield_pred:
            nat_avg   = 1.8
            diff      = round(((float(yield_pred) - nat_avg) / nat_avg) * 100, 1)
            total     = round(float(yield_pred) * float(size), 1)
            direction = "above" if diff >= 0 else "below"
            return (f"{p}predicted yield: {yield_pred} t/ha — {abs(diff)}% {direction} "
                    f"the national average. For your {size}ha: {total} tonnes total.")
        return f"Run the Yield Prediction module first for a specific forecast."

    elif intent == "low_yield":
        reasons = []
        if float(rainfall) < 500:
            reasons.append(f"low rainfall ({rainfall}mm)")
        if rot_verdict in ["High rotation risk","Caution advised"] or prev_crop == "Maize":
            reasons.append(f"continuous {prev_crop} depleting soil nitrogen")
        if timing == "risky":
            reasons.append("late planting stressing crop at grain fill")
        if not reasons:
            reasons = ["check soil pH — acid soils lock phosphorus",
                       "check plant population — overcrowding reduces yield"]
        return (f"{p}most likely causes: " + "; ".join(reasons) +
                ". Fix rotation first, then adjust fertilizer.")

    elif intent == "irrigation":
        return (f"{irrigation} Critical windows: tasseling (day 60-65) and "
                f"grain fill (day 75-90). Missing tasseling irrigation costs up to "
                f"50% yield loss. Prioritise tasseling if water is limited.")

    elif intent == "weather":
        msg = "Below average — moisture stress risk elevated." if float(rainfall)<500 else "Within acceptable range."
        return (f"NASA POWER data for {province}: rainfall {rainfall}mm. {msg} "
                f"Temperature: {temp}°C. Humidity: {humidity}%.")

    elif intent == "pest_disease":
        if pest_alerts:
            alerts = " | ".join(f"{a['name']} ({a['severity']}): {a['action']}"
                                for a in pest_alerts)
            return f"{p}active alerts: {alerts} Scout twice per week."
        return (f"No elevated alerts for {province} currently. Scout for "
                f"Fall Armyworm frass from 2 weeks after emergence.")

    elif intent == "rotation":
        rec = ("Rotate to Soybeans or Groundnuts next season — legumes fix nitrogen "
               "and will improve your next maize crop significantly."
               if prev_crop == "Maize" else "Your rotation is agronomically sound.")
        return f"Previous crop: {prev_crop}. Verdict: {rot_verdict}. {rot_note} {rec}"

    elif intent == "risk":
        factors = []
        if float(rainfall) < 450: factors.append(f"low rainfall ({rainfall}mm)")
        if timing == "risky": factors.append("late planting")
        if rot_verdict == "High rotation risk": factors.append("continuous cropping")
        if agro_zone in ["IV","V"]: factors.append(f"low-rainfall zone ({agro_zone})")
        if pest_alerts: factors.append(f"{len(pest_alerts)} pest alert(s)")
        conf = f" ({risk_conf}% confidence)" if risk_conf else ""
        f_str = "; ".join(factors) + "." if factors else "No major risk factors elevated."
        return f"{p}risk: {risk_label}{conf}. {f_str}"

    elif intent == "variety":
        desc = {
            "SC513": "Long-season high-yield hybrid for Zone I/II, 650mm+ rainfall.",
            "SC403": "Medium-season drought-tolerant for 450-700mm zones.",
            "SC301": "Short-season for low-rainfall zones below 450mm.",
        }.get(variety, "Ask your local Seedco agrodealer.")
        return (f"Recommended for {province} Zone {agro_zone} ({rainfall}mm): "
                f"{variety}. {desc} Always buy certified seed.")

    else:
        conf = f" ({risk_conf}% confidence)" if risk_conf else ""
        return (f"I am your RimAI Agronomist{', ' + name if name else ''}. "
                f"I know your {size}ha farm in {province} — "
                f"current season: {risk_label} risk{conf}. "
                f"Ask me about planting, fertilizer, yield, pests, "
                f"irrigation, weather, rotation, risk, or varieties.")


def get_chat_response(message, farm_data, username=""):
    intent = match_intent(message)
    return {"success": True, "reply": build_response(intent, farm_data, username), "intent": intent}
