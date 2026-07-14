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
    crop = inputs.get("crop", "Maize")
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
    try:
        pd_obj = datetime.datetime.strptime(planting_date_str, "%Y-%m-%d")
        month = pd_obj.month
    except Exception:
        month = datetime.date.today().month

    optimal_start = prov_data["season_start"]
    if month < optimal_start:
        timing = "wait"
        timing_msg = f"Too early. Optimal planting for {province} begins around month {optimal_start}. Wait for sustained rains."
    elif month <= optimal_start + 1:
        timing = "plant_now"
        timing_msg = "Good timing — within the optimal planting window for this area."
    else:
        timing = "risky"
        timing_msg = "Late planting. Consider a short-season variety to reduce moisture-stress risk at tasseling."

    # ── 3. Fertilizer ──
    soil_data = SOIL_FERTILIZER.get(soil, SOIL_FERTILIZER["Clay-Loam"])
    an_kg = round(soil_data["AN"] * farm_size)
    cpd_kg = round(soil_data["Compound_D"] * farm_size)

    # ── 4. Irrigation, based on live/fallback rainfall ──
    rainfall = weather.get("total_rainfall_mm", 600)
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
    elif risk <= 7: risk_label = "High"
    else: risk_label = "Very High"

    # ── 7. ML risk confidence from yield model ──
    risk_confidence = None
    yield_t_ha = None
    try:
        from core.harvest_model import predict_yield as _py
        _yresult = _py({
            "province": province,
            "rainfall_mm": weather.get("total_rainfall_mm", rainfall),
            "temperature_c": weather.get("avg_temp_c", 22),
            "planting_month": month,
            "farm_size_ha": farm_size,
        })
        risk_label      = _yresult.get("risk_label", risk_label)
        risk_confidence = _yresult.get("risk_confidence")
        yield_t_ha      = _yresult.get("yield_t_ha")
    except Exception:
        pass

    # ── 8. Pest & disease risk ──
    pest_risk = assess_pest_risk(crop, weather)

    recommended_variety = "SC513" if rainfall >= 700 else ("SC403" if rainfall >= 450 else "SC301")

    result = {
        "weather": weather,
        "timing": timing,
        "timing_msg": timing_msg,
        "fertilizer": {
            "compound_d_kg": cpd_kg,
            "an_kg": an_kg,
            "notes": soil_data["notes"],
        },
        "irrigation": irrigation,
        "risk_score": risk,
        "risk_confidence": risk_confidence,
        "yield_t_ha": yield_t_ha,
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
