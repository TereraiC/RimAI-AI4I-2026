"""
RimAI Synthetic Data Registry
Central, transparent record of every dataset the platform uses: where it
came from, whether it is real / synthetic / hybrid, why, and how
confident we are in it. This module never fabricates data itself — it
classifies and reports on datasets produced elsewhere in the pipeline
(fetch_faostat.py, build_master_dataset.py, weather_service.py,
harvest_model.py, the demo seeder in Cell 9).

Registry entries are stored in data/processed/synthetic_registry.json so
admins can enable/disable a dataset for testing without touching code.
"""
import os
import json
import datetime

REGISTRY_PATH = "data/processed/synthetic_registry.json"

# ── Static registry definition ──────────────────────────────────────────
# source: "real" | "synthetic" | "hybrid"
# Each entry documents provenance per the AI4I Development Track disclosure
# requirement: source, generation methodology, why synthetic was needed,
# and confidence/validation notes.
_DEFAULT_REGISTRY = [
    {
        "id": "faostat_yield_history",
        "name": "Zimbabwe National Maize Yield History",
        "category": "Crop Production",
        "source": "real",
        "provider": "FAOSTAT",
        "reason": "N/A — real national data available 2000-2024.",
        "methodology": "Direct download via FAOSTAT bulk API (fetch_faostat.py).",
        "confidence": "High — official UN/FAO statistics.",
        "date_generated": None,
        "license": "FAOSTAT terms of use (open data, attribution required)",
        "enabled": True,
    },
    {
        "id": "nasa_power_weather",
        "name": "Rainfall, Temperature, Humidity (live + historical)",
        "category": "Weather",
        "source": "real",
        "provider": "NASA POWER",
        "reason": "N/A — real satellite/reanalysis data, fetched live per farm.",
        "methodology": "NASA POWER daily point API, per-province or per-GPS coordinates "
                        "(weather_service.py). Falls back to historical provincial "
                        "averages only if the live API is unreachable.",
        "confidence": "High — satellite + reanalysis product, validated against ground stations by NASA.",
        "date_generated": None,
        "license": "NASA POWER open data",
        "enabled": True,
    },
    {
        "id": "enso_index",
        "name": "ENSO (El Ni\u00f1o/La Ni\u00f1a) Index by Year",
        "category": "Climate",
        "source": "real",
        "provider": "NOAA (hand-classified into model lookup table)",
        "reason": "N/A — real historical NOAA ENSO classifications.",
        "methodology": "Static lookup table (harvest_model.py: ENSO_BY_YEAR) built from published NOAA ONI classifications.",
        "confidence": "High for years covered (2000-2024).",
        "date_generated": None,
        "license": "NOAA public domain",
        "enabled": True,
    },
    {
        "id": "yield_feature_augmentation",
        "name": "Soil Moisture, NDVI proxy, Fertilizer Rate, Planting Date, Previous Yield",
        "category": "Crop Production",
        "source": "synthetic",
        "provider": "RimAI agronomic simulation (harvest_model.py: _generate_augmented_dataset)",
        "reason": "No farm-level historical records exist yet for soil moisture, NDVI, "
                  "fertilizer application, or planting dates at the granularity ML "
                  "training requires. FAOSTAT only reports national yield totals.",
        "methodology": "Agronomically-calibrated distributions derived from province "
                        "rainfall/zone norms (e.g. soil_moisture \u2248 rainfall/1200, NDVI "
                        "proxy \u2248 0.3 + rainfall/2000), perturbed with bounded Gaussian "
                        "noise, seeded (np.random.seed(42)) for reproducibility.",
        "confidence": "Moderate \u2014 directionally realistic, not measured. Cross-validated "
                       "model R\u00b2=0.824 reflects performance on this augmented data, not "
                       "on held-out real farm observations.",
        "date_generated": None,
        "license": "N/A (generated)",
        "enabled": True,
    },
    {
        "id": "demo_farmer_accounts",
        "name": "Demo Farmer Profiles (~20 accounts across 10 provinces)",
        "category": "Farmers",
        "source": "synthetic",
        "provider": "RimAI demo seeder (Cell 9)",
        "reason": "RimAI has no real onboarded farmer base yet (pre-launch prototype). "
                  "AGRITEX and Ministry dashboards need realistic spread of farms across "
                  "provinces/districts to demonstrate aggregation, mapping, and outbreak "
                  "detection features end to end.",
        "methodology": "Procedurally generated demographics, farm sizes, crops, and risk "
                        "profiles distributed across all 10 provinces / 20 districts, "
                        "deliberately varied so dashboards show a realistic risk spread "
                        "rather than uniform green.",
        "confidence": "N/A \u2014 illustrative only, clearly not real farmers.",
        "date_generated": None,
        "license": "N/A (generated)",
        "enabled": True,
    },
    {
        "id": "backtest_results",
        "name": "Model Backtest Table (predicted vs actual yield)",
        "category": "Model Evaluation",
        "source": "hybrid",
        "provider": "admin.py: load_backtest()",
        "reason": "Real backtest artifacts (data/processed/backtest_results.csv + "
                  "backtest_metrics.json) are used when present. Until a full holdout "
                  "backtest run has been executed and saved, the Admin dashboard shows "
                  "clearly-labelled illustrative placeholder figures so the page is never blank.",
        "methodology": "See admin.py \u2014 checks for real CSV/JSON artifacts first; falls "
                        "back to fixed illustrative numbers only if absent.",
        "confidence": "Depends on whether real artifacts exist \u2014 flagged live via is_synthetic.",
        "date_generated": None,
        "license": "N/A",
        "enabled": True,
    },
    {
        "id": "district_fertilizer_allocation",
        "name": "District Fertilizer Allocation Figures",
        "category": "Government",
        "source": "synthetic",
        "provider": "RimAI demo seeder (Cell 9)",
        "reason": "Real AGRITEX/Ministry input-allocation records are not yet integrated "
                  "via API or data-sharing agreement.",
        "methodology": "Illustrative per-district figures generated for the Intervention "
                        "Tracking panel; proportional to demo farmer counts per district.",
        "confidence": "N/A \u2014 illustrative only.",
        "date_generated": None,
        "license": "N/A (generated)",
        "enabled": True,
    },
]

# ── Features that need data but have no source registered at all yet ───
# (used by gap detection to warn *before* a feature silently breaks)
_KNOWN_FEATURE_REQUIREMENTS = {
    "Livestock production/health records": "livestock_records",
    "Historical market/commodity prices": "market_prices",
    "Extension officer visit/inspection reports": "extension_reports",
    "Disease/pest observation logs (farmer-submitted)": "disease_observations",
    "Provincial/district food security indicators": "food_security_indicators",
}


def _ensure_dir():
    os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)


def load_registry():
    """Load the registry from disk, seeding it with defaults on first run.
    Never overwrites an existing registry file (preserves any manual
    enable/disable toggles an admin has made)."""
    _ensure_dir()
    if not os.path.exists(REGISTRY_PATH):
        seeded = []
        for entry in _DEFAULT_REGISTRY:
            e = dict(entry)
            e["date_generated"] = datetime.date.today().isoformat()
            seeded.append(e)
        save_registry(seeded)
        return seeded
    with open(REGISTRY_PATH) as f:
        return json.load(f)


def save_registry(entries):
    _ensure_dir()
    with open(REGISTRY_PATH, "w") as f:
        json.dump(entries, f, indent=2)


def set_dataset_enabled(dataset_id, enabled):
    entries = load_registry()
    found = False
    for e in entries:
        if e["id"] == dataset_id:
            e["enabled"] = bool(enabled)
            found = True
    if found:
        save_registry(entries)
    return found


def detect_gaps(registry=None):
    """Compare known feature data-requirements against what's registered.
    Returns a list of gaps: real data that does not exist for a feature
    RimAI claims to support, i.e. anything not marked 'real' or 'hybrid'."""
    registry = registry or load_registry()
    registered_ids = {e["id"] for e in registry}
    gaps = []
    for feature_name, needed_id in _KNOWN_FEATURE_REQUIREMENTS.items():
        if needed_id not in registered_ids:
            gaps.append({
                "feature": feature_name,
                "status": "No dataset registered \u2014 feature not yet implemented or fully synthetic/unsourced.",
            })
    # Also flag any registered dataset that is synthetic/hybrid, as a
    # transparency reminder (not a "problem", just visibility).
    for e in registry:
        if e["source"] in ("synthetic", "hybrid"):
            gaps.append({
                "feature": e["name"],
                "status": f"Uses {e['source']} data \u2014 {e['reason']}",
            })
    return gaps


def completeness_score(registry=None):
    """Simple transparency metric: % of registered datasets that are
    real or hybrid (i.e. grounded in at least some real data)."""
    registry = registry or load_registry()
    if not registry:
        return 0.0
    grounded = sum(1 for e in registry if e["source"] in ("real", "hybrid"))
    return round(100 * grounded / len(registry), 1)


def data_quality_summary(registry=None):
    registry = registry or load_registry()
    total = len(registry)
    by_source = {"real": 0, "synthetic": 0, "hybrid": 0}
    for e in registry:
        by_source[e["source"]] = by_source.get(e["source"], 0) + 1
    return {
        "total_datasets": total,
        "real": by_source.get("real", 0),
        "synthetic": by_source.get("synthetic", 0),
        "hybrid": by_source.get("hybrid", 0),
        "pct_real": round(100 * by_source.get("real", 0) / total, 1) if total else 0,
        "pct_synthetic": round(100 * by_source.get("synthetic", 0) / total, 1) if total else 0,
        "pct_hybrid": round(100 * by_source.get("hybrid", 0) / total, 1) if total else 0,
        "completeness_score": completeness_score(registry),
    }
