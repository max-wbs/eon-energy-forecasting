"""Cleaning and daily aggregation of the weather data (stage 2).

The order is deliberate: **clean first, aggregate second.**

Short gaps can only be filled at the hourly level - after aggregation the
missing hour is no longer addressable. And the completeness of a day is by
definition only checkable hourly. Aggregating first smears missing hours
invisibly into the daily values: a daily mean temperature built from 18
instead of 24 hours looks like a valid value.

Filling happens exclusively via forward fill with a limit of 3 hours, i.e.
only with values *before* the gap. Interpolation would be more accurate for
temperature but would draw on values *after* the gap - dispensable, and doing
without it makes the causality of the pipeline indisputable.
"""

from __future__ import annotations

import pandas as pd

from utils import checks, config
from utils.reporting import Reporter

# Aggregation rule per raw quantity: which aggregate functions the channel
# gets. The target column is consistently named <raw column>_<function>,
# formed via config.daily_name - so the raw name stays visible in the daily
# value. Sums need special treatment - see _mask_incomplete_days.
DAILY_AGGREGATIONS: dict[str, list[str]] = {
    "Temperature_avg_hourly": ["mean", "min", "max"],
    "DewPoint_hourly": ["mean"],
    "Humidity_avg_hourly": ["mean"],
    "WindSpeed_hourly": ["mean", "max"],
    config.WEATHER_PRESSURE_KEEP: ["mean"],
    "Precipitation_total_hourly": ["sum"],
    "Sunshine_duration_hourly": ["sum"],
}

# Resolved to {raw quantity: [(target column, function), ...]}.
DAILY_SPEC: dict[str, list[tuple[str, str]]] = {
    source: [(config.daily_name(source, func), func) for func in funcs]
    for source, funcs in DAILY_AGGREGATIONS.items()
}

# The daily mean temperature is the reference quantity for heating degree days.
TEMP_MEAN = config.daily_name("Temperature_avg_hourly", "mean")


# --------------------------------------------------------------------------
# Hourly cleaning
# --------------------------------------------------------------------------


def clean_hourly(rep: Reporter, df: pd.DataFrame) -> pd.DataFrame:
    rep.step("Validate the weather data hourly")

    ok, detail = checks.unique_keys(df, ["Weather_ID", "Timestamp"])
    rep.check("(Weather_ID, Timestamp) unique", ok, detail)

    ok, detail = checks.hourly_grid_complete(df)
    rep.check("hourly grid gapless (precondition for the daily aggregation)", ok, detail)

    ok, detail = checks.within_bounds(df, config.WEATHER_BOUNDS)
    rep.check("weather values within plausible bounds", ok, detail)

    rep.raise_on_failures()

    rep.step("Remove redundant pressure channels")
    coverage = {
        col: int(df.groupby("Weather_ID", observed=True)[col].count().gt(0).sum())
        for col in [config.WEATHER_PRESSURE_KEEP] + config.WEATHER_PRESSURE_DROP
    }
    for col, n in coverage.items():
        rep.metric(f"Stations with values in {col}", n)
    df = df.drop(columns=[c for c in config.WEATHER_PRESSURE_DROP if c in df])
    rep.note(
        f"{config.WEATHER_PRESSURE_KEEP} is carried forward; the other channels are "
        "conversions of the same measurement and carry no additional information at "
        "equal or worse coverage"
    )

    rep.step("Forward-fill short hourly gaps")
    fill_cols = [c for c in config.WEATHER_FFILL_COLUMNS if c in df]
    df = df.sort_values(["Weather_ID", "Timestamp"]).reset_index(drop=True)

    before = {c: int(df[c].isna().sum()) for c in fill_cols}
    df[fill_cols] = df.groupby("Weather_ID", observed=True)[fill_cols].ffill(
        limit=config.WEATHER_FFILL_LIMIT_H
    )
    after = {c: int(df[c].isna().sum()) for c in fill_cols}

    total_filled = sum(before[c] - after[c] for c in fill_cols)
    rep.metric("Hourly values filled in total", total_filled)
    for col in fill_cols:
        filled = before[col] - after[col]
        if filled:
            rep.metric(f"  {col}", filled)

    # The remaining gaps have to be reported separately: a channel a station
    # does not measure at all is not a gap but a known property of the
    # station. Summing both into one number would fake a data problem where
    # there is none.
    structural, real = _split_missing(df, fill_cols)
    rep.metric("Structurally not measured (station does not carry the channel)", structural)
    rep.metric("Genuine remaining gaps (station measures, value missing)", real)

    rep.note(
        f"Forward fill with a limit of {config.WEATHER_FFILL_LIMIT_H} h, exclusively with values "
        "before the gap. Precipitation and sunshine are not filled - they are spiky, and "
        "carrying them forward would invent rain that never fell"
    )

    return df


def _split_missing(df: pd.DataFrame, columns: list[str]) -> tuple[int, int]:
    """Split missing values into structurally absent and genuine gaps."""
    structural = 0
    real = 0
    for col in columns:
        per_station = df.groupby("Weather_ID", observed=True)[col].count()
        dead_stations = per_station[per_station == 0].index
        structural += int(df.loc[df["Weather_ID"].isin(dead_stations), col].isna().sum())
        real += int(df.loc[~df["Weather_ID"].isin(dead_stations), col].isna().sum())
    return structural, real


# --------------------------------------------------------------------------
# Daily aggregation
# --------------------------------------------------------------------------


def _channel_availability(df: pd.DataFrame) -> dict[str, pd.Series]:
    """Per raw quantity: which stations carry the channel at all?

    This distinction has to be made at station level, not at day level. A day
    without a valid hour means a full-day outage at a station that carries the
    channel - and nothing at all at a station that does not. Deciding both on
    `valid == 0` would disguise genuine outages as a known station property.
    """
    grouped = df.groupby("Weather_ID", observed=True)
    return {source: grouped[source].count() > 0 for source in DAILY_SPEC}


def _station_availability(df: pd.DataFrame) -> pd.DataFrame:
    """Station-wide flags for the two incomplete channels."""
    grouped = df.groupby("Weather_ID", observed=True)
    return pd.DataFrame(
        {
            "station_has_sunshine": grouped["Sunshine_duration_hourly"].count() > 0,
            "station_has_pressure": grouped[config.WEATHER_PRESSURE_KEEP].count() > 0,
        }
    )


def aggregate_daily(rep: Reporter, df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate hourly values onto the UTC calendar day."""
    rep.step("Aggregate the weather to daily level")

    agg_spec: dict[str, tuple[str, str]] = {}
    for source, targets in DAILY_SPEC.items():
        for name, func in targets:
            agg_spec[name] = (source, func)
        # Number of valid hours per source quantity - the basis for masking
        # incomplete days.
        agg_spec[f"_valid_{source}"] = (source, "count")
    agg_spec["_n_hours"] = ("Timestamp", "size")

    daily = df.groupby(["Weather_ID", "date"], observed=True).agg(**agg_spec).reset_index()

    rep.metric("Hourly rows in", len(df))
    rep.metric("Daily rows out", len(daily))
    rep.metric("Stations", daily["Weather_ID"].nunique())

    full_days = int((daily["_n_hours"] == config.HOURS_PER_DAY).sum())
    rep.metric("Days with a full 24 hourly rows", full_days)
    rep.check(
        "every day has 24 hourly rows",
        full_days == len(daily),
        f"{len(daily) - full_days} days with a deviating hour count",
    )

    daily = _mask_incomplete_days(rep, daily, _channel_availability(df))

    daily[config.HDD_COLUMN] = (config.HDD_BASE_C - daily[TEMP_MEAN]).clip(lower=0)
    rep.metric("Heating degree days mean", float(daily[config.HDD_COLUMN].mean()))
    rep.metric("Days with HDD equal to 0", int((daily[config.HDD_COLUMN] == 0).sum()))
    rep.note(
        f"{config.HDD_COLUMN} = max(0, {config.HDD_BASE_C:g} - daily mean temperature); "
        "NaN parity with the temperature, no filling. The base temperature is part of the "
        "column name and changeable in config.py in one place - the name follows along"
    )

    availability = _station_availability(df)
    daily = daily.merge(availability, left_on="Weather_ID", right_index=True, how="left")
    for col in ("station_has_sunshine", "station_has_pressure"):
        n_without = int(daily.loc[~daily[col], "Weather_ID"].nunique())
        rep.metric(f"Stations without {col.replace('station_has_', '')}", n_without)
        daily[col] = daily[col].astype("bool")

    daily = daily.drop(columns=[c for c in daily.columns if c.startswith("_")])

    ok, detail = checks.unique_keys(daily, ["Weather_ID", "date"])
    rep.check("(Weather_ID, date) unique in the daily aggregate", ok, detail)
    rep.raise_on_failures()

    return daily


def _mask_incomplete_days(
    rep: Reporter, daily: pd.DataFrame, channel_available: dict[str, pd.Series]
) -> pd.DataFrame:
    """Discard daily values that rest on too few valid hours.

    For sums this matters twice over: `sum` over a group of all-NaN returns
    0.0, not NaN. Without this mask the three stations without sunshine
    measurement would show a sunshine duration of exactly zero minutes every
    day - an invented measurement that looks like a valid observation.
    """
    incomplete_any = pd.Series(False, index=daily.index)
    n_structural = 0
    n_outage = 0
    n_partial = 0

    for source, targets in DAILY_SPEC.items():
        valid = daily[f"_valid_{source}"]
        station_has = daily["Weather_ID"].map(channel_available[source]).fillna(False)

        # Three distinct circumstances that all lead to a NaN daily value but
        # have to be judged differently:
        structural = ~station_has  # station does not carry the channel at all
        outage = station_has & (valid == 0)  # station measures, whole day missing
        partial = station_has & (valid > 0) & (valid < config.MIN_VALID_HOURS_PER_DAY)

        # Only outage and partial outage are data quality problems of the day -
        # a missing channel is a known station property.
        incomplete_any |= outage | partial

        drop = structural | outage | partial
        if drop.any():
            for name, _ in targets:
                daily.loc[drop, name] = pd.NA

        n_structural += int(structural.sum())
        n_outage += int(outage.sum())
        n_partial += int(partial.sum())

        if outage.any() or partial.any():
            rep.metric(
                f"{source}: full-day outages / partial outages",
                f"{int(outage.sum())} / {int(partial.sum())}",
            )
        if structural.any():
            rep.metric(f"{source}: channel not carried at the station", int(structural.sum()), "station days")

    daily["weather_day_incomplete"] = incomplete_any.astype("bool")
    rep.metric("Daily rows with an incomplete data basis", int(incomplete_any.sum()))
    rep.note(
        f"A daily value is only formed from at least {config.MIN_VALID_HOURS_PER_DAY} valid "
        "hours, otherwise NaN. This also catches a trap of sum aggregation: `sum` over "
        "all-missing hours returns 0.0, not NaN - without the mask the three stations without "
        "sunshine measurement would show exactly zero minutes of sun every day, an invented "
        "measurement"
    )
    rep.note(
        f"{n_structural} station days concern channels the respective station does not carry at all "
        f"(sunshine and pressure at three stations) - a known property, marked via station_has_*. "
        f"To be distinguished from those are {n_outage} genuine full-day outages and {n_partial} "
        "partial outages at stations that do carry the channel; only these set weather_day_incomplete"
    )

    # After setting pd.NA the float columns have to be float64 again so that
    # the parquet round-trip check does not fire on 'object'.
    for targets in DAILY_SPEC.values():
        for name, _ in targets:
            daily[name] = pd.to_numeric(daily[name], errors="coerce").astype("float64")

    return daily


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def clean(rep: Reporter, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (hourly cleaned, daily aggregate)."""
    hourly = clean_hourly(rep, df)
    daily = aggregate_daily(rep, hourly)
    return hourly, daily
