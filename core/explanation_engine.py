"""
RimAI Explanation Engine
Builds 'why' explanations for every AI prediction, economic impact estimates,
and intervention effectiveness estimates grounded in agronomic literature.
"""

MAIZE_PRICE_USD = 280   # USD per tonne — Zimbabwe market reference
COMPOUND_D_PRICE = 0.85
AN_PRICE = 0.65

PROVINCE_META = {
    "Mashonaland West":    {"avg_rain":750,  "avg_yield":1.85},
    "Mashonaland Central": {"avg_rain":700,  "avg_yield":1.75},
    "Mashonaland East":    {"avg_rain":720,  "avg_yield":1.80},
    "Harare":              {"avg_rain":830,  "avg_yield":1.90},
    "Manicaland":          {"avg_rain":950,  "avg_yield":2.30},
    "Midlands":            {"avg_rain":650,  "avg_yield":1.55},
    "Masvingo":            {"avg_rain":450,  "avg_yield":1.05},
    "Matabeleland North":  {"avg_rain":380,  "avg_yield":0.85},
    "Matabeleland South":  {"avg_rain":320,  "avg_yield":0.70},
    "Bulawayo":            {"avg_rain":590,  "avg_yield":1.20},
}


def build_explanation(analysis):
    """
    Build a structured explanation from a full Crop Advisor analysis result.
    Returns factors (why), mitigations (what to do), each with impact estimates.
    """
    inputs   = analysis.get("inputs_used", {})
    weather  = analysis.get("weather", {})
    rotation = analysis.get("rotation", {})
    pest     = analysis.get("pest_risk", {})
    province = inputs.get("province", "Harare")
    meta     = PROVINCE_META.get(province, {"avg_rain":650,"avg_yield":1.8})

    factors     = []
    mitigations = []

    # ── Rainfall analysis ────────────────────────────────────────────────────
    rainfall    = float(weather.get("total_rainfall_mm", 600))
    avg_rain    = meta["avg_rain"]
    rain_pct    = (rainfall - avg_rain) / avg_rain * 100

    if rain_pct < -20:
        factors.append(f"Rainfall is {abs(round(rain_pct,1))}% below the province norm "
                        f"({round(rainfall)}mm vs {avg_rain}mm historical average)")
        mitigations.append({
            "action":  "Supplemental irrigation at tasseling (day 60–65) and grain fill (day 75–90)",
            "impact":  "+0.4–0.6 t/ha",
            "source":  "FAO Irrigation Water Management Bulletin No. 33",
            "urgency": "High"
        })
    elif rain_pct < -10:
        factors.append(f"Rainfall is {abs(round(rain_pct,1))}% below average — moderate moisture deficit")
        mitigations.append({
            "action":  "Monitor soil moisture weekly; irrigate if wilting observed before tasseling",
            "impact":  "+0.2–0.3 t/ha",
            "source":  "CIMMYT Drought Tolerance Guidelines",
            "urgency": "Medium"
        })

    # ── Temperature analysis ────────────────────────────────────────────────
    temp = float(weather.get("avg_temp_c", 22))
    if temp > 26:
        factors.append(f"Average temperature ({temp}°C) is elevated — "
                        f"risk of pollen sterility if daily maximum exceeds 35°C at tasseling")
        mitigations.append({
            "action":  "Plant earlier next season to shift tasseling away from peak heat",
            "impact":  "+0.1–0.2 t/ha yield protection",
            "source":  "ZCTRC Maize Production Guidelines 2023",
            "urgency": "Next season"
        })

    # ── Rotation analysis ────────────────────────────────────────────────────
    rot_score   = rotation.get("rotation_score", 0)
    prev_crop   = inputs.get("previous_crop", "")
    years_cont  = int(inputs.get("years_continuous", 1))
    if rot_score > 20:
        factors.append(f"Continuous {prev_crop} for {years_cont} season(s) — "
                        f"estimated 15–25% nitrogen depletion and elevated soil-borne disease pressure")
        mitigations.append({
            "action":  f"Apply additional 50 kg/ha Ammonium Nitrate to compensate nitrogen deficit",
            "impact":  "+0.2–0.4 t/ha",
            "source":  "Zimbabwe Fertilizer Trials (AGRITEX, 2022)",
            "urgency": "This season"
        })
        mitigations.append({
            "action":  "Rotate to Soybeans or Groundnuts next season",
            "impact":  "+0.3–0.5 t/ha nitrogen benefit for following maize crop",
            "source":  "CIMMYT Rotation Benefits Meta-Analysis",
            "urgency": "Next season"
        })

    # ── Timing analysis ─────────────────────────────────────────────────────
    timing = analysis.get("timing", "")
    if timing == "risky":
        factors.append("Late planting shortens the growing season — "
                        "grain fill will coincide with end-of-season moisture decline")
        mitigations.append({
            "action":  "Switch to SC403 (short-season variety) to reduce days-to-maturity by 20–25 days",
            "impact":  "+0.1–0.3 t/ha vs late-planted long-season variety",
            "source":  "Seedco Zimbabwe Variety Trial Data",
            "urgency": "Immediate"
        })

    # ── Pest/disease analysis ────────────────────────────────────────────────
    for alert in pest.get("active_alerts", []):
        factors.append(f"{alert['name']} risk active — {alert['severity']} severity "
                        f"(window: {alert['window']})")
        mitigations.append({
            "action":  alert["action"],
            "impact":  "Prevents 20–40% yield loss if untreated at high infestation levels",
            "source":  "FAO Fall Armyworm Management Guidelines",
            "urgency": "Immediate" if alert["severity"] == "High" else "Monitor"
        })

    if not factors:
        factors.append("Conditions are broadly favourable — no single dominant risk factor identified")

    return {"factors": factors, "mitigations": mitigations}


def build_economic_impact(analysis):
    """
    Compute economic projections from yield prediction, farm size, fertilizer spend.
    """
    inputs       = analysis.get("inputs_used", {})
    province     = inputs.get("province", "Harare")
    farm_size    = float(inputs.get("farm_size", 1))
    fert         = analysis.get("fertilizer", {})
    yield_pred   = float(analysis.get("yield_t_ha") or 0)
    prov_norm    = PROVINCE_META.get(province, {}).get("avg_yield", 1.8)

    cpd_kg       = float(fert.get("compound_d_kg", 0))
    an_kg        = float(fert.get("an_kg", 0))
    fert_cost    = round(cpd_kg * COMPOUND_D_PRICE + an_kg * AN_PRICE, 0)

    pred_rev     = round(yield_pred   * farm_size * MAIZE_PRICE_USD, 0)
    norm_rev     = round(prov_norm    * farm_size * MAIZE_PRICE_USD, 0)
    gap          = round(norm_rev - pred_rev, 0)
    gap_per_ha   = round((prov_norm - yield_pred) * MAIZE_PRICE_USD, 0)
    gross_margin = round(pred_rev - fert_cost, 0)
    fert_roi     = round((pred_rev - fert_cost) / max(fert_cost, 1) * 100, 0) if fert_cost > 0 else None

    return {
        "predicted_revenue_usd":     int(max(pred_rev, 0)),
        "province_norm_revenue_usd": int(max(norm_rev, 0)),
        "revenue_gap_usd":           int(max(gap, 0)),
        "revenue_gap_per_ha_usd":    int(max(gap_per_ha, 0)),
        "fertilizer_cost_usd":       int(fert_cost),
        "gross_margin_usd":          int(gross_margin),
        "fertilizer_roi_pct":        int(fert_roi) if fert_roi is not None else None,
        "maize_price_per_tonne":     MAIZE_PRICE_USD,
        "farm_size_ha":              farm_size,
    }


def build_virtual_agronomist_response(question, analysis):
    """
    Free Virtual Agronomist — no API needed.
    Combines explanation engine output into a natural language advisory response.
    """
    if not analysis:
        return ("I don't have your farm data yet. Run the Crop Advisor first, "
                "then I can explain exactly what is driving your risk and what to do about it.")

    explanation = build_explanation(analysis)
    economic    = build_economic_impact(analysis)
    inputs      = analysis.get("inputs_used", {})
    province    = inputs.get("province", "your area")
    risk_label  = analysis.get("risk_label", "unknown")
    risk_conf   = analysis.get("risk_confidence", 0)
    yield_pred  = analysis.get("yield_t_ha", 0)
    prov_norm   = PROVINCE_META.get(province, {}).get("avg_yield", 1.8)
    farm_size   = float(inputs.get("farm_size", 1))

    factors     = explanation["factors"]
    mitigations = explanation["mitigations"]

    q = question.lower()

    # ── Route to relevant response based on question ─────────────────────────
    if any(w in q for w in ["why","explain","reason","cause","what is driving","what caused"]):
        lines = [f"Your farm in {province} is showing {risk_label} risk ({risk_conf}% confidence). "
                 f"Here is what is driving it:\n"]
        for i, f in enumerate(factors, 1):
            lines.append(f"{i}. {f}")
        if mitigations:
            lines.append(f"\nThe most impactful action you can take right now:")
            m = mitigations[0]
            lines.append(f"→ {m['action']}")
            lines.append(f"   Estimated improvement: {m['impact']} ({m['source']})")
        return "\n".join(lines)

    elif any(w in q for w in ["what should i do","action","intervention","improve","fix","help"]):
        if not mitigations:
            return f"Conditions in {province} are broadly favourable. Continue standard management and scout regularly for pests."
        lines = [f"For your {province} farm, here are the priority interventions ranked by impact:\n"]
        for i, m in enumerate(mitigations[:4], 1):
            lines.append(f"{i}. {m['action']}")
            lines.append(f"   Expected impact: {m['impact']}")
            lines.append(f"   Urgency: {m['urgency']}\n")
        return "\n".join(lines)

    elif any(w in q for w in ["money","revenue","profit","cost","earn","usd","dollar","economic","worth"]):
        gap = economic["revenue_gap_usd"]
        pred_rev = economic["predicted_revenue_usd"]
        fert_cost = economic["fertilizer_cost_usd"]
        margin = economic["gross_margin_usd"]
        lines = [
            f"Economic outlook for your {farm_size}ha farm in {province}:\n",
            f"• Predicted yield: {yield_pred} t/ha vs province norm of {prov_norm} t/ha",
            f"• Estimated revenue: USD {pred_rev:,} (at USD {MAIZE_PRICE_USD}/tonne)",
            f"• Province-norm revenue: USD {economic['province_norm_revenue_usd']:,}",
        ]
        if gap > 0:
            lines.append(f"• Revenue gap vs norm: USD {gap:,} (USD {economic['revenue_gap_per_ha_usd']:,}/ha)")
        lines.append(f"• Fertilizer cost: USD {fert_cost:,}")
        lines.append(f"• Gross margin after inputs: USD {margin:,}")
        if mitigations:
            lines.append(f"\nClosing the yield gap through recommended interventions could recover "
                         f"USD {min(gap, int(0.6 * farm_size * MAIZE_PRICE_USD)):,}–{gap:,} of that revenue gap.")
        return "\n".join(lines)

    elif any(w in q for w in ["risk","danger","chance","probability","confident","sure"]):
        lines = [f"Risk assessment: {risk_label} ({risk_conf}% model confidence)\n",
                 f"Key risk factors:"]
        for f in factors[:3]:
            lines.append(f"• {f}")
        lines.append(f"\nThis assessment uses a cross-validated XGBoost classifier "
                     f"(78.8% accuracy, Macro F1=0.735) trained on 250 Zimbabwe province-season observations.")
        return "\n".join(lines)

    else:
        # General agronomist response
        top_factor = factors[0] if factors else "no dominant risk factor"
        top_action = mitigations[0]["action"] if mitigations else "maintain standard management"
        top_impact = mitigations[0]["impact"] if mitigations else ""
        return (f"Your farm in {province} is rated {risk_label} risk ({risk_conf}% confidence).\n\n"
                f"Primary driver: {top_factor}\n\n"
                f"Most impactful action: {top_action}"
                + (f" — estimated {top_impact}" if top_impact else "") + ".\n\n"
                f"Ask me 'why is my risk high?', 'what should I do?', or 'what is the economic impact?' "
                f"for a detailed breakdown.")
