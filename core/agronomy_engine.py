"""
RimAI Agronomy Engine
Crop rotation analysis + pest/disease risk scoring
"""

# Nitrogen-fixing legumes that improve soil after planting
LEGUMES = {"Groundnuts", "Soybeans", "Velvet Beans", "Cowpeas"}

# Crops that build up shared pest/disease pressure if repeated
HEAVY_FEEDERS = {"Maize", "Tobacco", "Cotton"}

ROTATION_RULES = {
    ("Maize", "Maize"):       {"penalty": 25, "note": "Maize after maize depletes nitrogen and builds up stalk borer and grey leaf spot pressure."},
    ("Tobacco", "Tobacco"):   {"penalty": 30, "note": "Continuous tobacco sharply increases nematode and bacterial wilt risk."},
    ("Cotton", "Cotton"):     {"penalty": 20, "note": "Continuous cotton increases bollworm carryover in soil and residue."},
    ("Maize", "Groundnuts"):  {"penalty": -15, "note": "Excellent rotation — groundnuts fix nitrogen that benefits the next maize crop."},
    ("Maize", "Soybeans"):    {"penalty": -15, "note": "Strong rotation choice — soybeans replenish soil nitrogen."},
    ("Maize", "Cotton"):      {"penalty": 5, "note": "Acceptable rotation, modest pest-cycle break."},
    ("Maize", "Fallow/None"): {"penalty": -10, "note": "Resting the land allows partial nutrient and moisture recovery."},
}

# Known Zimbabwe pest/disease pressure by crop, season conditions
PEST_RISK_PROFILES = {
    "Maize": [
        {
            "name": "Fall Armyworm",
            "trigger": lambda w: w["avg_temp_c"] >= 22 and w["recent_7day_rainfall_mm"] > 15,
            "severity": "High",
            "window": "2-6 weeks after emergence",
            "action": "Scout whorls weekly for window-pane leaf damage and frass. Consider early-stage biopesticide (Bt-based) or approved synthetic if economic threshold (>20% plants infested) is reached.",
        },
        {
            "name": "Grey Leaf Spot",
            "trigger": lambda w: w["avg_humidity_pct"] > 55 and w["avg_temp_c"] >= 20,
            "severity": "Moderate",
            "window": "Tasseling to grain fill",
            "action": "Higher risk on continuous maize fields. Ensure adequate plant spacing for airflow; resistant varieties (e.g. ZAP series) reduce severity.",
        },
        {
            "name": "Maize Streak Virus",
            "trigger": lambda w: w["avg_temp_c"] >= 24,
            "severity": "Moderate",
            "window": "Early vegetative stage",
            "action": "Transmitted by leafhoppers thriving in warm conditions. Plant early in the recommended window to avoid peak vector activity; use tolerant varieties where available.",
        },
    ],
    "Tobacco": [
        {
            "name": "Bacterial Wilt",
            "trigger": lambda w: w["avg_humidity_pct"] > 50,
            "severity": "High",
            "window": "Any growth stage, worse in continuous tobacco fields",
            "action": "Practice strict rotation (minimum 3 seasons out of tobacco). Avoid working in wet fields to limit spread.",
        },
    ],
    "Cotton": [
        {
            "name": "Bollworm (African and Pink)",
            "trigger": lambda w: w["avg_temp_c"] >= 23,
            "severity": "High",
            "window": "Squaring to boll formation",
            "action": "Scout for shot-holes in squares and bolls. Pheromone traps help with early detection.",
        },
    ],
}


def analyze_rotation(current_crop, previous_crop, years_continuous=1):
    """
    Returns a rotation risk assessment comparing current vs previous crop.
    """
    key = (current_crop, previous_crop)
    rule = ROTATION_RULES.get(key)

    if rule is None:
        if previous_crop in LEGUMES:
            rule = {"penalty": -10, "note": f"{previous_crop} as a legume likely improved soil nitrogen for this season."}
        elif previous_crop == current_crop and current_crop in HEAVY_FEEDERS:
            rule = {"penalty": 20, "note": f"Continuous {current_crop} cultivation increases pest carryover and nutrient depletion risk."}
        else:
            rule = {"penalty": 0, "note": "Neutral rotation — no strong agronomic benefit or penalty detected."}

    # Compound penalty for multiple continuous years of same crop
    continuous_penalty = 0
    if previous_crop == current_crop and years_continuous >= 2:
        continuous_penalty = min((years_continuous - 1) * 8, 24)

    total_penalty = rule["penalty"] + continuous_penalty

    if total_penalty <= -10:
        verdict = "Beneficial rotation"
    elif total_penalty <= 5:
        verdict = "Neutral"
    elif total_penalty <= 20:
        verdict = "Caution advised"
    else:
        verdict = "High rotation risk"

    return {
        "verdict": verdict,
        "rotation_score": total_penalty,
        "note": rule["note"],
        "years_continuous": years_continuous,
        "continuous_warning": f"This field has grown {current_crop} for {years_continuous} consecutive seasons — consider breaking the cycle." if years_continuous >= 3 else None,
    }


def assess_pest_risk(crop, weather_data):
    """
    Cross-references current weather conditions against known pest/disease
    triggers for the given crop. Returns a list of active risk alerts.
    """
    profiles = PEST_RISK_PROFILES.get(crop, [])
    active_risks = []

    for p in profiles:
        try:
            if p["trigger"](weather_data):
                active_risks.append({
                    "name": p["name"],
                    "severity": p["severity"],
                    "window": p["window"],
                    "action": p["action"],
                })
        except Exception:
            continue

    if not active_risks:
        overall = "Low"
    elif any(r["severity"] == "High" for r in active_risks):
        overall = "High"
    elif any(r["severity"] == "Moderate" for r in active_risks):
        overall = "Moderate"
    else:
        overall = "Low"

    return {
        "overall_risk": overall,
        "active_alerts": active_risks,
        "crop": crop,
    }
