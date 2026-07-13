"""
RimAI Model Validation — Stage 2: Walk-forward backtest
Trains the Random Forest yield model using only data available up to year N,
predicts year N+1, and repeats across all available years. This mimics how
the model would actually be used in production — never trained on the future.

Reports RMSE, MAE, R^2 across all walk-forward predictions, plus a
predicted-vs-actual chart data export for the dashboard's Model Insights page.
"""
import os
import json
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score

PROCESSED_DIR = "data/processed"
MIN_TRAIN_YEARS = 4  # need at least this many years before first walk-forward prediction


def prepare_features(df):
    """
    Build the feature matrix from the master dataset.
    Features: total_rainfall_mm, avg_temp_c, avg_humidity_pct, area_harvested_ha
    Target: yield_t_ha
    """
    df = df.dropna(subset=["total_rainfall_mm", "avg_temp_c", "yield_t_ha"]).copy()
    df = df.sort_values("Year").reset_index(drop=True)

    feature_cols = ["total_rainfall_mm", "avg_temp_c", "avg_humidity_pct", "area_harvested_ha"]
    # Fill any remaining gaps (e.g. missing humidity for one year) with column median
    for col in feature_cols:
        if col in df.columns:
            df[col] = df[col].fillna(df[col].median())

    return df, feature_cols


def walk_forward_backtest(df, feature_cols, min_train_years=MIN_TRAIN_YEARS):
    """
    For each year Y starting after min_train_years of history exists,
    train on all years strictly before Y, predict Y, record the result.
    """
    results = []

    if len(df) <= min_train_years:
        raise ValueError(
            f"Not enough data for walk-forward backtest: have {len(df)} years, "
            f"need more than {min_train_years}. Add more historical years."
        )

    for i in range(min_train_years, len(df)):
        train = df.iloc[:i]
        test = df.iloc[i:i + 1]

        X_train = train[feature_cols].values
        y_train = train["yield_t_ha"].values
        X_test = test[feature_cols].values
        y_test = test["yield_t_ha"].values[0]

        model = RandomForestRegressor(n_estimators=100, random_state=42)
        model.fit(X_train, y_train)
        y_pred = model.predict(X_test)[0]

        results.append({
            "year": int(test["Year"].values[0]),
            "actual_yield_t_ha": round(float(y_test), 3),
            "predicted_yield_t_ha": round(float(y_pred), 3),
            "error": round(float(y_pred - y_test), 3),
            "abs_pct_error": round(abs(y_pred - y_test) / y_test * 100, 1) if y_test != 0 else None,
            "train_years_used": i,
        })

    return pd.DataFrame(results)


def compute_metrics(backtest_df):
    """Compute RMSE, MAE, R^2 across all walk-forward predictions."""
    actual = backtest_df["actual_yield_t_ha"].values
    predicted = backtest_df["predicted_yield_t_ha"].values

    rmse = float(np.sqrt(mean_squared_error(actual, predicted)))
    mae = float(mean_absolute_error(actual, predicted))

    # R^2 is unstable/misleading with very few points (e.g. < 3) — flag this honestly
    if len(actual) >= 3:
        r2 = float(r2_score(actual, predicted))
        r2_reliable = len(actual) >= 5
    else:
        r2 = None
        r2_reliable = False

    mean_actual = float(np.mean(actual))
    rmse_pct_of_mean = round(rmse / mean_actual * 100, 1) if mean_actual != 0 else None

    return {
        "n_predictions": len(actual),
        "rmse_t_ha": round(rmse, 3),
        "mae_t_ha": round(mae, 3),
        "r2": round(r2, 3) if r2 is not None else None,
        "r2_reliable": r2_reliable,
        "rmse_as_pct_of_mean_yield": rmse_pct_of_mean,
        "mean_actual_yield_t_ha": round(mean_actual, 3),
        "warning": None if len(actual) >= 5 else (
            f"Only {len(actual)} walk-forward predictions available — metrics are indicative, "
            f"not statistically robust. More historical years needed for a reliable R^2."
        ),
    }


def run_backtest(master_csv_path=None):
    if master_csv_path is None:
        master_csv_path = os.path.join(PROCESSED_DIR, "master_dataset.csv")

    df = pd.read_csv(master_csv_path)
    df, feature_cols = prepare_features(df)

    print(f"Running walk-forward backtest on {len(df)} years of real data...")
    print(f"Features used: {feature_cols}")

    backtest_df = walk_forward_backtest(df, feature_cols)
    metrics = compute_metrics(backtest_df)

    print("\n--- Walk-Forward Predictions ---")
    print(backtest_df.to_string(index=False))

    print("\n--- Backtest Metrics ---")
    for k, v in metrics.items():
        print(f"  {k}: {v}")

    # Save for the dashboard / Model Insights page
    backtest_df.to_csv(os.path.join(PROCESSED_DIR, "backtest_results.csv"), index=False)
    with open(os.path.join(PROCESSED_DIR, "backtest_metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2)

    print(f"\nSaved backtest_results.csv and backtest_metrics.json to {PROCESSED_DIR}/")
    return backtest_df, metrics


if __name__ == "__main__":
    run_backtest()
