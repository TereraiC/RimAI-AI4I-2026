"""
RimAI Ministry — supporting logic for the "National Food Intelligence
Platform": a single Food Security Index, national production vs demand,
an auto-generated Early Warning feed, a rainfall/temperature Policy
Simulator, and Input Allocation Intelligence (which provinces have the
most recoverable yield potential per hectare).

Zimbabwe's national maize requirement (~1.8 million tonnes for human
consumption) is a public estimate reported in government crop & livestock
assessments and FAO/USDA briefings — used here as a fixed reference point,
not something the model predicts.
"""
NATIONAL_MAIZE_DEMAND_TONNES = 1_800_000
RISK_PENALTY = {"Low": 0, "Moderate": 15, "High": 35}


def food_security_index(province_data):
    """
    0-100 composite: average yield-vs-benchmark performance across
    provinces, penalised by how many provinces are at elevated risk.
    """
    if not province_data:
        return {"score": 0, "at_risk_provinces": 0}
    vs_norm_avg = sum(p["vs_norm"] for p in province_data.values()) / len(province_data)
    risk_penalty_avg = sum(RISK_PENALTY.get(p["risk"], 15) for p in province_data.values()) / len(province_data)
    score = 70 + vs_norm_avg / 2 - risk_penalty_avg / 2
    at_risk = sum(1 for p in province_data.values() if p["risk"] in ("Moderate", "High"))
    return {"score": max(0, min(100, round(score))), "at_risk_provinces": at_risk}


def national_production(province_data):
    total_tonnes = sum(p["yield"] * p["area_ha"] for p in province_data.values())
    gap = total_tonnes - NATIONAL_MAIZE_DEMAND_TONNES
    return {
        "total_tonnes": round(total_tonnes),
        "demand_tonnes": NATIONAL_MAIZE_DEMAND_TONNES,
        "gap_tonnes": round(gap),
        "status": "Surplus" if gap >= 0 else "Deficit",
    }


def early_warning_feed(province_data):
    """Auto-generated warnings for provinces at elevated risk or with a
    meaningful rainfall shortfall versus their own province average."""
    warnings = []
    for prov, p in province_data.items():
        if p["risk"] == "High":
            warnings.append(f"🔴 {prov}: High crop failure risk — {p['recommendation']}")
        elif p["risk"] == "Moderate" and p["vs_norm"] < -10:
            warnings.append(f"🟠 {prov}: Yield tracking {abs(p['vs_norm'])}% below provincial norm.")
    warnings.sort()
    if not warnings:
        warnings = ["✅ No provinces currently show elevated risk."]
    return warnings


def policy_simulation(rainfall_pct_change, temp_delta_c, area_ha_map, province_meta):
    """Re-run the national yield model with adjusted rainfall/temperature
    across every province and compare total production to baseline."""
    from core.harvest_model import predict_yield
    from data_pipeline.weather_service import get_weather_for_farm

    baseline_total, scenario_total = 0, 0
    provinces_hit = []
    for prov, meta in province_meta.items():
        weather = get_weather_for_farm(prov)
        base_rain = weather.get("extrapolated_season_total_mm", weather.get("total_rainfall_mm", meta["avg_rain"]))
        base_temp = weather.get("avg_temp_c", 22)
        area = area_ha_map.get(prov, 50000)

        base_result = predict_yield({"province": prov, "rainfall_mm": base_rain,
                                      "temperature_c": base_temp, "planting_month": 11, "farm_size_ha": 1})
        scenario_result = predict_yield({
            "province": prov,
            "rainfall_mm": round(base_rain * (1 + rainfall_pct_change / 100), 1),
            "temperature_c": round(base_temp + temp_delta_c, 1),
            "planting_month": 11, "farm_size_ha": 1,
        })
        baseline_total += base_result["yield_t_ha"] * area
        scenario_total += scenario_result["yield_t_ha"] * area
        if scenario_result["yield_t_ha"] < base_result["yield_t_ha"] * 0.85:
            provinces_hit.append(prov)

    production_delta_pct = round(((scenario_total - baseline_total) / baseline_total) * 100, 1) if baseline_total else 0
    new_gap = scenario_total - NATIONAL_MAIZE_DEMAND_TONNES
    return {
        "baseline_tonnes": round(baseline_total),
        "scenario_tonnes": round(scenario_total),
        "production_delta_pct": production_delta_pct,
        "new_status": "Surplus" if new_gap >= 0 else "Deficit",
        "new_gap_tonnes": round(new_gap),
        "provinces_hardest_hit": provinces_hit,
    }


def input_allocation_intelligence(province_data):
    """Rank provinces by recoverable yield potential per hectare — where a
    bag of fertilizer is likely to have the biggest marginal impact."""
    ranked = sorted(
        province_data.items(),
        key=lambda kv: (kv[1]["norm"] - kv[1]["yield"]) if kv[1]["vs_norm"] < 0 else -1,
        reverse=True,
    )
    out = []
    for prov, p in ranked[:5]:
        if p["vs_norm"] >= 0:
            continue
        recoverable_t_ha = round(p["norm"] - p["yield"], 2)
        out.append({
            "province": prov, "recoverable_t_ha": recoverable_t_ha,
            "recoverable_tonnes": round(recoverable_t_ha * p["area_ha"]),
            "risk": p["risk"],
        })
    return out
