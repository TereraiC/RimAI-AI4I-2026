"""
RimAI Crop Advisor — Module 1
Now pulls live weather automatically and factors in rotation + pest risk.
Farmer only provides: location, soil type, previous crop, farm size.
"""
import datetime
from core.explanation_engine import build_explanation, build_economic_impact
from data_pipeline.weather_service import get_weather_for_farm
from core.agronomy_engine import analyze_rotation, assess_pest_risk

PROVINCE_AGRO = {
    "Mashonaland West":    {"season_start": 11, "zone": "II"},
    "Mashonaland Central": {"season_start": 11, "zone": "II"},
    "Mashonaland East":    {"season_start": 11, "zone": "II"},
    "Harare":              {"season_start": 11, "zone": "II"},
    "Manicaland":          {"season_start": 10, "zone": "I"},
    "Midlands":            {"season_start": 11, "zone": "IIa"},
    "Masvingo":            {"season_start": 11, "zone": "III"},
    "Matabeleland North":  {"season_start": 12, "zone": "IV"},
    "Matabeleland South":  {"season_start": 12, "zone": "V"},
    "Bulawayo":            {"season_start": 12, "zone": "III"},
}

SOIL_FERTILIZER = {
    "Sandy":        {"AN": 350, "Compound_D": 200, "notes": "Sandy soils — apply Compound D in splits to reduce leaching."},
    "Sandy-Loam":   {"AN": 300, "Compound_D": 200, "notes": "Good drainage. Consider basal application of Compound D before planting."},
    "Clay-Loam":    {"AN": 250, "Compound_D": 150, "notes": "Excellent moisture retention. Standard recommendation."},
    "Clay":         {"AN": 250, "Compound_D": 150, "notes": "Heavy soil — ensure drainage channels to prevent waterlogging."},
    "Loam":         {"AN": 250, "Compound_D": 150, "notes": "Ideal texture. Standard rates apply."},
    "Red Clay":     {"AN": 300, "Compound_D": 175, "notes": "High iron content. Slightly increased phosphate recommended."},
    "Black Cotton": {"AN": 200, "Compound_D": 125, "notes": "High shrink/swell risk. Avoid heavy machinery. Excellent fertility."},
}


def get_full_farm_analysis(inputs):
    """
    Main entry point. Takes minimal farmer input and returns a complete
    analysis: timing, fertilizer, irrigation, rotation risk, pest risk,
    using live weather data fetched automatically.

    Required inputs: province, soil_type, previous_crop, farm_size
    Optional inputs: district, lat, lon, planting_date, years_continuous, crop (defaults to Maize)
    """
    province = inputs.get("province", "Harare")
    soil = inputs.get("soil_type", "Clay-Loam")
    # RimAI's current MVP scope is maize only — the yield/risk models,
    # fertilizer rates, and pest thresholds are all calibrated and
    # validated against maize specifically. The form has no crop selector
    # (so a normal user can never choose anything else), but this also
    # enforces it server-side against any direct API call, so the result
    # can never silently claim validated advice for an unvalidated crop.
    crop = "Maize"
    previous_crop = inputs.get("previous_crop", "Fallow/None")
    farm_size = float(inputs.get("farm_size", 1))
    years_continuous = int(inputs.get("years_continuous", 1))
    lat = inputs.get("lat")
    lon = inputs.get("lon")
    planting_date_str = inputs.get("planting_date", "")

    # ── 1. Fetch live weather automatically ──
    weather = get_weather_for_farm(province, lat, lon)

    # ── 2. Timing analysis ──
    prov_data = PROVINCE_AGRO.get(province, PROVINCE_AGRO["Harare"])
    today = datetime.date.today()
    try:
        pd_obj = datetime.datetime.strptime(planting_date_str, "%Y-%m-%d")
        month = pd_obj.month
        chosen_date = pd_obj.date()
    except Exception:
        month = today.month
        chosen_date = None

    optimal_start = prov_data["season_start"]
    # The suggested date is the 1st of the season-start month, in whichever
    # year makes it the next upcoming occurrence (this year if that month
    # hasn't passed yet, otherwise next year) — a specific, actionable date
    # rather than just validating whatever the farmer typed.
    suggested_year = today.year if today.month <= optimal_start else today.year + 1
    suggested_date = datetime.date(suggested_year, optimal_start, 1)
    suggested_date_str = suggested_date.strftime("%d %B %Y")

    # Months elapsed since the window opened, wraparound-safe (0-11). A raw
    # "month < optimal_start" comparison breaks across a year boundary —
    # e.g. February (month=2) is numerically less than November (11) even
    # though it's chronologically well past a Nov-Dec planting window, not
    # before it.
    months_since_start = (month - optimal_start) % 12

    if months_since_start == 0 or months_since_start == 1:
        timing = "plant_now"
        if chosen_date and chosen_date != suggested_date:
            timing_msg = (f"Your chosen date is within the optimal window for {province}. "
                           f"For the strongest start, the suggested optimal date this season is {suggested_date_str}.")
        else:
            timing_msg = f"Good timing — {suggested_date_str} is the suggested optimal planting date for {province} this season."
    elif months_since_start <= 4:
        timing = "risky"
        timing_msg = (f"Late planting for this season. Consider a short-season variety to reduce "
                       f"moisture-stress risk at tasseling. Suggested planting date for next season: "
                       f"{suggested_date_str}.")
    else:
        timing = "wait"
        timing_msg = (f"Too early to plant. Suggested planting date for {province}: "
                       f"{suggested_date_str} (start of the optimal window) — wait for sustained rains before then.")

    # ── 3. Fertilizer ──
    soil_data = SOIL_FERTILIZER.get(soil, SOIL_FERTILIZER["Clay-Loam"])
    an_kg = round(soil_data["AN"] * farm_size)
    cpd_kg = round(soil_data["Compound_D"] * farm_size)

    # ── 4. Irrigation, based on live/fallback rainfall ──
    rainfall = weather.get("extrapolated_season_total_mm", weather.get("total_rainfall_mm", 600))
    if rainfall >= 700:
        irrigation = "Rainfed conditions look sufficient. Supplemental irrigation optional during dry spells."
    elif rainfall >= 450:
        irrigation = "Supplemental irrigation recommended, especially at tasseling and grain fill."
    else:
        irrigation = "Irrigation likely essential for a viable yield this season."

    # ── 5. Risk score (timing + zone + weather) ──
    risk = 0
    if timing == "risky": risk += 4
    elif timing == "wait": risk += 2
    if prov_data["zone"] in ["IV", "V"]: risk += 3
    elif prov_data["zone"] == "III": risk += 2
    if rainfall < 400: risk += 3

    # ── 6. Rotation analysis ──
    rotation = analyze_rotation(crop, previous_crop, years_continuous)
    if rotation["rotation_score"] > 20:
        risk += 2

    risk = min(risk, 10)
    if risk <= 2: risk_label = "Low"
    elif risk <= 5: risk_label = "Moderate"
    else: risk_label = "High"

    # ── 7. ML risk confidence from yield model ──
    risk_confidence = None
    yield_t_ha = None
    vs_province_norm = None
    try:
        from core.harvest_model import predict_yield as _py
        _yresult = _py({
            "province": province,
            "rainfall_mm": weather.get("extrapolated_season_total_mm", rainfall),
            "temperature_c": weather.get("avg_temp_c", 22),
            "planting_month": month,
            "farm_size_ha": farm_size,
        })
        risk_confidence = _yresult.get("risk_confidence")
        yield_t_ha      = _yresult.get("yield_t_ha")
        vs_province_norm = _yresult.get("vs_province_norm")
        # Deliberately NOT overwriting risk_label here: the score above
        # already accounts for planting timing, agro-ecological zone,
        # rainfall, AND rotation/pest pressure (rotation_score bonus).
        # The yield model's risk_label is a simpler yield-ratio-only
        # classification, correct for the national map view but too
        # coarse for farm-level advice — it would silently discard real
        # rotation/pest risk that this richer score already captures.
    except Exception:
        pass

    # ── 8. Pest & disease risk ──
    pest_risk = assess_pest_risk(crop, weather)

    recommended_variety = "SC513" if rainfall >= 700 else ("SC403" if rainfall >= 450 else "SC301")

    result = {
        "weather": weather,
        "timing": timing,
        "timing_msg": timing_msg,
        "suggested_planting_date": suggested_date_str,
        "suggested_planting_date_iso": suggested_date.strftime("%Y-%m-%d"),
        # Whether the crop is actually likely to be growing right now.
        # 'timing' (wait/risky/plant_now) only says whether the chosen
        # date falls in a good window — it says nothing about whether that
        # date is in the past or future, or whether a crop planted long
        # enough ago has already been harvested. A farmer who enters a
        # planting date next week correctly gets timing="plant_now" (good
        # time to plant), but nothing is growing yet; a farmer whose
        # chosen date was 8 months ago has almost certainly already
        # harvested (standard cycle is ~135 days) — neither should show
        # active pest/scouting language for a field that's empty either
        # way. Buffer beyond 135 days accounts for late harvest/drying time.
        "has_planted": bool(chosen_date and chosen_date <= today
                             and (today - chosen_date).days <= 150),
        "fertilizer": {
            "compound_d_kg": cpd_kg,
            "an_kg": an_kg,
            "notes": soil_data["notes"],
        },
        "irrigation": irrigation,
        "risk_score": risk,
        "risk_confidence": risk_confidence,
        "yield_t_ha": yield_t_ha,
        "vs_province_norm": vs_province_norm,
        "risk_label": risk_label,
        "agro_zone": prov_data["zone"],
        "recommended_variety": recommended_variety,
        "rotation": rotation,
        "pest_risk": pest_risk,
        "inputs_used": {
            "province": province, "district": inputs.get("district", ""), "soil_type": soil, "crop": crop,
            "previous_crop": previous_crop, "farm_size": farm_size,
            "planting_date": planting_date_str, "years_continuous": years_continuous,
        },
    }
    result["explanation"] = build_explanation(result)
    result["economic"]    = build_economic_impact(result)
    return result
