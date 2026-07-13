"""
RimAI AGRITEX — supporting logic for the Officer Dashboard
("AI Extension Command Centre"): ward/district risk rollup, farmer
priority queue, and a small aggregate-data Q&A assistant.
"""
import json
import sqlite3

RISK_ORDER = {"High": 0, "Moderate": 1, "Low": 2}


def _db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def latest_farmer_snapshots(db_path):
    """One row per farmer: their most recent crop_advisor analysis."""
    with _db(db_path) as db:
        rows = db.execute("""
            SELECT u.id as user_id, u.username, u.full_name, p.result, p.created_at
            FROM predictions p
            JOIN users u ON u.id = p.user_id
            WHERE p.prediction_type='crop_advisor'
              AND p.id IN (SELECT MAX(id) FROM predictions WHERE prediction_type='crop_advisor' GROUP BY user_id)
              AND u.role='farmer'
        """).fetchall()

    snapshots = []
    for r in rows:
        try:
            result = json.loads(r["result"])
        except (TypeError, ValueError):
            continue
        inputs = result.get("inputs_used", {})
        pest_alerts = result.get("pest_risk", {}).get("active_alerts", [])
        snapshots.append({
            "user_id": r["user_id"],
            "name": r["full_name"] or r["username"].capitalize(),
            "province": inputs.get("province", "Unknown"),
            "district": inputs.get("district", "Unknown") or "Unknown",
            "risk_label": result.get("risk_label", "Unknown"),
            "risk_confidence": result.get("risk_confidence"),
            "yield_t_ha": result.get("yield_t_ha"),
            "pest_alerts": pest_alerts,
            "rotation_verdict": result.get("rotation", {}).get("verdict", ""),
            "timing": result.get("timing"),
            "last_updated": r["created_at"],
        })
    return snapshots


def ward_risk_table(snapshots):
    """District-level rollup: farmer count and risk mix per district."""
    table = {}
    for s in snapshots:
        key = (s["province"], s["district"])
        row = table.setdefault(key, {"province": s["province"], "district": s["district"],
                                      "farmers": 0, "high": 0, "moderate": 0, "low": 0,
                                      "pest_alerts": 0})
        row["farmers"] += 1
        row["pest_alerts"] += len(s["pest_alerts"])
        if s["risk_label"] == "High":
            row["high"] += 1
        elif s["risk_label"] == "Moderate":
            row["moderate"] += 1
        elif s["risk_label"] == "Low":
            row["low"] += 1

    rows = list(table.values())
    for row in rows:
        row["dominant_risk"] = ("High" if row["high"] >= max(row["moderate"], row["low"])
                                 else "Moderate" if row["moderate"] >= row["low"] else "Low")
    rows.sort(key=lambda r: (RISK_ORDER.get(r["dominant_risk"], 3), -r["farmers"]))
    return rows


def priority_queue(snapshots):
    """Farmers sorted by urgency: risk level first, then pest alert count."""
    return sorted(snapshots, key=lambda s: (RISK_ORDER.get(s["risk_label"], 3), -len(s["pest_alerts"])))


def ask_the_data(question, snapshots):
    """
    Very small aggregate-data Q&A: matches a district name and/or a topic
    keyword in the officer's question and answers using real aggregated
    numbers from the farmer snapshots — no invented figures.
    """
    q = question.lower()
    districts = {s["district"] for s in snapshots}
    matched_district = next((d for d in districts if d.lower() in q), None)

    scope = [s for s in snapshots if not matched_district or s["district"] == matched_district]
    if not scope:
        return "No farmer data found for that district yet — farmers need to run the Crop Advisor first."

    scope_label = matched_district or "all monitored wards"
    high = [s for s in scope if s["risk_label"] == "High"]
    pest_counts = {}
    for s in scope:
        for a in s["pest_alerts"]:
            pest_counts[a["name"]] = pest_counts.get(a["name"], 0) + 1
    top_pest = max(pest_counts.items(), key=lambda kv: kv[1]) if pest_counts else None
    continuous = [s for s in scope if "High rotation risk" in s.get("rotation_verdict", "")]

    parts = [f"In {scope_label}, {len(high)} of {len(scope)} monitored farms are at High risk."]
    if top_pest:
        parts.append(f"The most common pressure is {top_pest[0]} ({top_pest[1]} farm(s)).")
    if continuous:
        parts.append(f"{len(continuous)} farm(s) are on continuous maize, which is compounding the risk.")
    if not high and not top_pest:
        parts.append("No elevated risk or pest pressure detected right now.")
    return " ".join(parts)
