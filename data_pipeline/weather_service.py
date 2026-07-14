"""
RimAI Weather Service
Fetches live rainfall, temperature, and solar data from NASA POWER API
based on farm GPS coordinates. No API key required.
"""
import requests
import datetime

NASA_POWER_BASE = "https://power.larc.nasa.gov/api/temporal/daily/point"


def get_season_window():
    """
    Zimbabwe's maize growing season runs 1 Oct - 31 Mar. A fixed
    'N days back from today' window breaks for 6 months of the year: from
    April to September (the dry season), rainfall is naturally near zero
    everywhere regardless of province or actual drought conditions, so
    comparing that trailing window against a full wet-season norm would
    always show a severe false 'deficit'.

    Returns (start_date, end_date, prorate_fraction, season_label):
    - During the dry season (Apr-Sep): use the most recently COMPLETED
      season's full Oct-Mar total, prorate_fraction=1.0 (compare like-for-like
      against the full-season norm).
    - During an active growing season (Oct-Mar): use Oct 1 through today,
      with prorate_fraction = how much of the season has elapsed, so the
      comparison norm can be scaled down to a fair 'on track for this
      point in the season' comparison instead of the full-season total.
    """
    today = datetime.date.today()
    if 4 <= today.month <= 9:
        season_start = datetime.date(today.year - 1, 10, 1)
        season_end = datetime.date(today.year, 3, 31)
        label = f"{season_start.year}/{season_end.year} season (completed)"
        return season_start, season_end, 1.0, label

    season_start = datetime.date(today.year, 10, 1) if today.month >= 10 \
        else datetime.date(today.year - 1, 10, 1)
    season_end = today
    full_season_days = (datetime.date(season_start.year + 1, 3, 31) - season_start).days
    elapsed_days = max(1, (today - season_start).days)
    prorate_fraction = min(1.0, elapsed_days / full_season_days) if full_season_days else 1.0
    label = f"{season_start.year}/{season_start.year+1} season to date"
    return season_start, season_end, prorate_fraction, label

PROVINCE_COORDS = {
    "Harare":              (-17.8292, 31.0522),
    "Mashonaland West":    (-17.6833, 29.8167),
    "Mashonaland Central": (-17.0667, 31.3667),
    "Mashonaland East":    (-18.1833, 32.0500),
    "Manicaland":          (-18.9667, 32.6500),
    "Midlands":            (-19.1167, 29.8167),
    "Masvingo":            (-20.0667, 30.8333),
    "Matabeleland North":  (-18.5000, 27.5000),
    "Matabeleland South":  (-21.0500, 29.0000),
    "Bulawayo":            (-20.1500, 28.5833),
}


def get_coords_for_province(province):
    """Fallback: get representative coordinates for a province if no GPS given."""
    return PROVINCE_COORDS.get(province, PROVINCE_COORDS["Harare"])


def fetch_nasa_power_data(lat, lon, days_back=None):
    """
    Fetch rainfall and temperature data from NASA POWER for a given
    lat/lon, over Zimbabwe's current or most recently completed growing
    season (see get_season_window) rather than a fixed trailing window.
    Returns averaged season-relevant stats, or None on failure.
    """
    start, end, prorate_fraction, season_label = get_season_window()

    params = {
        "parameters": "PRECTOTCORR,T2M,T2M_MAX,T2M_MIN,RH2M",
        "community": "AG",
        "longitude": lon,
        "latitude": lat,
        "start": start.strftime("%Y%m%d"),
        "end": end.strftime("%Y%m%d"),
        "format": "JSON",
    }

    try:
        resp = requests.get(NASA_POWER_BASE, params=params, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        props = data["properties"]["parameter"]

        rainfall_daily = list(props["PRECTOTCORR"].values())
        temp_daily = list(props["T2M"].values())
        temp_max_daily = list(props["T2M_MAX"].values())
        humidity_daily = list(props["RH2M"].values())

        # Filter out NASA's fill value for missing data (-999)
        rainfall_daily = [v for v in rainfall_daily if v > -900]
        temp_daily = [v for v in temp_daily if v > -900]
        temp_max_daily = [v for v in temp_max_daily if v > -900]
        humidity_daily = [v for v in humidity_daily if v > -900]

        total_rainfall = sum(rainfall_daily) if rainfall_daily else 0
        avg_temp = sum(temp_daily) / len(temp_daily) if temp_daily else 22
        avg_temp_max = sum(temp_max_daily) / len(temp_max_daily) if temp_max_daily else 28
        avg_humidity = sum(humidity_daily) / len(humidity_daily) if humidity_daily else 55

        # Last 7 days for "current conditions" feel
        recent_rain = sum(rainfall_daily[-7:]) if len(rainfall_daily) >= 7 else total_rainfall
        recent_temp = sum(temp_daily[-7:]) / len(temp_daily[-7:]) if len(temp_daily) >= 7 else avg_temp

        # Full-season-equivalent rainfall: mid-season, total_rainfall_mm is
        # only a partial-season-to-date figure, which would look like a
        # false 'deficit' against a full-season province norm even in a
        # perfectly normal season. Extrapolate to what the season would
        # total at the current pace, for fair comparison purposes — the
        # raw to-date figure is still returned separately for anyone who
        # wants the actual measurement rather than the comparison-adjusted one.
        extrapolated_total = round(total_rainfall / prorate_fraction, 1) if prorate_fraction > 0 else total_rainfall

        return {
            "success": True,
            "total_rainfall_mm": round(total_rainfall, 1),
            "extrapolated_season_total_mm": extrapolated_total,
            "avg_temp_c": round(avg_temp, 1),
            "avg_temp_max_c": round(avg_temp_max, 1),
            "avg_humidity_pct": round(avg_humidity, 1),
            "recent_7day_rainfall_mm": round(recent_rain, 1),
            "recent_7day_avg_temp_c": round(recent_temp, 1),
            "period_days": (end - start).days,
            "prorate_fraction": prorate_fraction,
            "season_label": season_label,
            "source": "NASA POWER (satellite + reanalysis)",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


PROVINCE_FALLBACK_AVERAGES = {
    # Used only if NASA POWER is unreachable. Based on long-term Zim averages.
    "Harare":              {"rainfall": 830, "temp": 22.0, "temp_max": 27.0, "humidity": 60},
    "Mashonaland West":    {"rainfall": 750, "temp": 22.5, "temp_max": 28.0, "humidity": 58},
    "Mashonaland Central": {"rainfall": 700, "temp": 22.0, "temp_max": 28.0, "humidity": 57},
    "Mashonaland East":    {"rainfall": 720, "temp": 21.5, "temp_max": 27.5, "humidity": 58},
    "Manicaland":          {"rainfall": 950, "temp": 20.5, "temp_max": 26.0, "humidity": 65},
    "Midlands":            {"rainfall": 650, "temp": 21.0, "temp_max": 27.0, "humidity": 55},
    "Masvingo":            {"rainfall": 450, "temp": 23.5, "temp_max": 30.0, "humidity": 48},
    "Matabeleland North":  {"rainfall": 380, "temp": 24.0, "temp_max": 31.0, "humidity": 42},
    "Matabeleland South":  {"rainfall": 320, "temp": 24.5, "temp_max": 31.5, "humidity": 40},
    "Bulawayo":            {"rainfall": 590, "temp": 19.5, "temp_max": 25.5, "humidity": 50},
}


def get_weather_for_farm(province, lat=None, lon=None):
    """
    Main entry point: get weather data for a farm. Uses GPS if provided,
    otherwise falls back to province-level representative coordinates.
    Falls back to historical averages if NASA POWER is unreachable.
    """
    if lat is None or lon is None:
        lat, lon = get_coords_for_province(province)
        location_precision = "province-level estimate"
    else:
        location_precision = "exact GPS"

    result = fetch_nasa_power_data(lat, lon)
    result["location_precision"] = location_precision
    result["lat"] = lat
    result["lon"] = lon

    if not result.get("success"):
        # Graceful fallback so the farmer never sees a broken page
        fallback = PROVINCE_FALLBACK_AVERAGES.get(province, PROVINCE_FALLBACK_AVERAGES["Harare"])
        result.update({
            "total_rainfall_mm": fallback["rainfall"],
            "extrapolated_season_total_mm": fallback["rainfall"],
            "avg_temp_c": fallback["temp"],
            "avg_temp_max_c": fallback["temp_max"],
            "avg_humidity_pct": fallback["humidity"],
            "recent_7day_rainfall_mm": round(fallback["rainfall"] / 17, 1),
            "recent_7day_avg_temp_c": fallback["temp"],
            "period_days": "historical average",
            "prorate_fraction": 1.0,
            "season_label": "long-term historical average",
            "source": "Historical provincial average (live data unavailable)",
        })
    return result
