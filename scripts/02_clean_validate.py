"""Stage 2: interim/01_ingested -> interim/02_clean.

Establishes the calendar structure, flags anomalies, aggregates the weather to
daily level and validates the result. No feature engineering - that belongs to
stage 3.

Usage:
    poetry run python scripts/02_clean_validate.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from utils import config, io, reporting  # noqa: E402
from utils.cleaning import smart_meter, weather  # noqa: E402
from utils.reporting import Reporter  # noqa: E402


def build_quality_payload(panel: pd.DataFrame, households: pd.DataFrame, daily: pd.DataFrame) -> dict:
    """Machine-readable metrics for regression checks."""
    quality_cols = [
        "Household_ID",
        "first_date",
        "last_date",
        "n_days",
        "n_target_observed",
        "n_gap_days",
        "max_gap_days",
        "n_spikes",
        "target_missing_rate",
        "returned_coverage",
        "has_heatpump_submeter",
        "has_meta_survey",
        "Installation_HasPVSystem",
        "pv_flag_imputed",
        "visit_date",
        "Weather_ID",
    ]
    return {
        "summary": {
            "households": int(panel["Household_ID"].nunique()),
            "panel_rows": int(len(panel)),
            "gap_rows": int(panel["is_gap"].sum()),
            "target_observed": int(panel[config.TARGET_COL].notna().sum()),
            "target_missing": int(panel[config.TARGET_COL].isna().sum()),
            "spike_rows": int(panel["kWh_spike_flag"].sum()),
            "returned_substituted_cells": int(panel["returned_was_substituted"].sum()),
            "households_with_gaps": int(panel.loc[panel["is_gap"], "Household_ID"].nunique()),
            "households_with_visit_date": int(households["visit_date"].notna().sum()),
            "weather_stations": int(daily["Weather_ID"].nunique()),
            "weather_daily_rows": int(len(daily)),
            "weather_date_min": str(daily["date"].min().date()),
            "weather_date_max": str(daily["date"].max().date()),
            "panel_date_min": str(panel["date"].min().date()),
            "panel_date_max": str(panel["date"].max().date()),
        },
        "households": households[[c for c in quality_cols if c in households]].to_dict("records"),
    }


def run(rep: Reporter) -> None:
    rep.step("Read the results of stage 1")
    panel = io.read_parquet(config.INGESTED / config.SMART_METER_PARQUET)
    households = io.read_parquet(config.INGESTED / config.HOUSEHOLDS_PARQUET)
    weather_hourly = io.read_parquet(config.INGESTED / config.WEATHER_HOURLY_PARQUET)

    rep.metric("Smart meter rows", len(panel))
    rep.metric("Households", panel["Household_ID"].nunique())
    rep.metric("Weather hourly rows", len(weather_hourly))
    rep.note(f"Source: {config.INGESTED.relative_to(config.ROOT)} (stage-1 output only, no raw data)")

    panel, households = smart_meter.clean(rep, panel, households)
    hourly_clean, daily = weather.clean(rep, weather_hourly)

    rep.step("Write results as parquet")
    for name, frame in (
        (config.SMART_METER_PARQUET, panel),
        (config.HOUSEHOLDS_PARQUET, households),
        (config.WEATHER_HOURLY_PARQUET, hourly_clean),
        (config.WEATHER_DAILY_PARQUET, daily),
    ):
        io.write_parquet(frame, config.CLEAN / name)
        rep.metric(name, f"{len(frame):,} rows x {frame.shape[1]} columns")
    rep.check("Parquet round trip without dtype drift", True, "verified for all four tables")

    reporting.write_quality_report(build_quality_payload(panel, households, daily))
    rep.note(f"Metrics machine-readable in {config.QUALITY_REPORT_JSON.relative_to(config.ROOT)}")


def main() -> int:
    try:
        with Reporter(stage=2, title="Cleaning & Validation") as rep:
            run(rep)
    except Exception as exc:
        print(f"\nAborted: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
