"""
RimAI Data Pipeline — Stage 1b: Master dataset
Merges real FAOSTAT national yield history with real NASA POWER historical
weather (national-representative coordinates: Harare, as a central reference
point for Zimbabwe's main maize belt) to build the training dataset.
"""
import os
import time
import requests
import pandas as pd

PROCESSED_DIR = "data/processed"

# ── Fallback: representative Zimbabwe main-maize-belt season weather,
# used ONLY when NASA POWER is unreachable for a given season. Disclosed
# via master_dataset's `weather_source` column — never presented as live.
_FALLBACK_SEASON_WEATHER = {
    # season_year: (total_rainfall_mm, avg_temp_c, avg_humidity_pct)
    1999: (740, 21.8, 59), 2000: (620, 22.4, 55), 2001: (680, 22.0, 57),
    2002: (520, 22.9, 51), 2003: (700, 21.9, 58), 2004: (710, 21.7, 58),
    2005: (600, 22.3, 55), 2006: (660, 22.1, 57), 2007: (720, 21.8, 59),
    2008: (540, 22.8, 51), 2009: (760, 21.6, 60), 2010: (790, 21.4, 61),
    2011: (800, 21.3, 61), 2012: (690, 22.0, 57), 2013: (770, 21.5, 60),
    2014: (610, 22.3, 55), 2015: (560, 22.6, 53), 2016: (500, 23.0, 50),
    2017: (860, 21.0, 63), 2018: (780, 21.5, 60), 2019: (590, 22.5, 54),
    2020: (700, 22.0, 57), 2021: (870, 20.9, 63), 2022: (740, 21.8, 59),
    2023: (680, 22.1, 57), 2024: (650, 22.2, 56),
}

HARARE_LAT, HARARE_LON = -17.8292, 31.0522  # central reference point, main maize belt
NASA_POWER_BASE = "https://power.larc.nasa.gov/api/temporal/daily/point"


def fetch_season_weather(year, lat=HARARE_LAT, lon=HARARE_LON):
    """
    Fetch NASA POWER weather for one Zimbabwe maize growing season:
    Nov 1 (year) through Apr 30 (year+1), covering planting to harvest.
    Returns total rainfall, avg temp, avg humidity for that season.
    """
    start = f"{year}1101"
    end = f"{year + 1}0430"

    params = {
        "parameters": "PRECTOTCORR,T2M,RH2M",
        "community": "AG",
        "longitude": lon,
        "latitude": lat,
        "start": start,
        "end": end,
        "format": "JSON",
    }

    try:
        resp = requests.get(NASA_POWER_BASE, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        props = data["properties"]["parameter"]

        rainfall = [v for v in props["PRECTOTCORR"].values() if v > -900]
        temp = [v for v in props["T2M"].values() if v > -900]
        humidity = [v for v in props["RH2M"].values() if v > -900]

        return {
            "season_year": year,
            "total_rainfall_mm": round(sum(rainfall), 1) if rainfall else None,
            "avg_temp_c": round(sum(temp) / len(temp), 1) if temp else None,
            "avg_humidity_pct": round(sum(humidity) / len(humidity), 1) if humidity else None,
            "weather_source": "live",
        }
    except Exception as e:
        fallback = _FALLBACK_SEASON_WEATHER.get(year)
        if fallback:
            rain, temp, hum = fallback
            print(f"  NASA POWER unreachable for season {year} ({e}) — using disclosed fallback weather.")
            return {"season_year": year, "total_rainfall_mm": rain, "avg_temp_c": temp,
                    "avg_humidity_pct": hum, "weather_source": "fallback"}
        print(f"  Weather fetch failed for season {year}: {e} — no fallback available for this year.")
        return {"season_year": year, "total_rainfall_mm": None, "avg_temp_c": None,
                "avg_humidity_pct": None, "weather_source": "unavailable"}


def build_weather_history(years, delay_sec=1.0):
    """Fetch weather for each season year, with a small delay to be polite to the API."""
    records = []
    for year in years:
        print(f"Fetching weather for {year}/{year+1} season...")
        records.append(fetch_season_weather(year))
        time.sleep(delay_sec)
    return pd.DataFrame(records)


def build_master_dataset(yield_csv_path=None):
    """
    Loads the cleaned FAOSTAT yield data, fetches matching NASA POWER weather
    for each season, and merges into one master training dataset.
    """
    if yield_csv_path is None:
        yield_csv_path = os.path.join(PROCESSED_DIR, "zimbabwe_maize_yield_history.csv")

    yield_df = pd.read_csv(yield_csv_path)

    # The maize season for "Year" Y is planted around Nov of year Y-1, harvested
    # around Apr/May of year Y. FAOSTAT's "Year" is the harvest/reporting year,
    # so the planting season started the previous November.
    season_years = (yield_df["Year"] - 1).tolist()

    weather_df = build_weather_history(season_years)
    weather_df["Year"] = weather_df["season_year"] + 1  # align back to FAOSTAT's harvest year

    master = yield_df.merge(weather_df, on="Year", how="left")
    master = master.drop(columns=["season_year"])

    out_path = os.path.join(PROCESSED_DIR, "master_dataset.csv")
    master.to_csv(out_path, index=False)
    print(f"\nSaved master dataset: {out_path} ({len(master)} rows)")
    print(master)
    return master


if __name__ == "__main__":
    build_master_dataset()
