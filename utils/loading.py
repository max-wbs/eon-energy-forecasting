"""Stage 1 of the pipeline: load, type, merge master data.

This stage does not touch the raw values in substance. It reads, types,
checks the schemas and makes exactly one substantive intervention: households
without a single target value are removed, because they cannot contribute
anything to a forecast of the target variable.

Everything else - calendar gaps, outliers, weather aggregation - belongs to
stage 2.
"""

from __future__ import annotations

from datetime import time

import pandas as pd

from utils import config, io
from utils.reporting import Reporter

DAY_END_UTC = time(23, 59, 59)


# --------------------------------------------------------------------------
# Smart meter
# --------------------------------------------------------------------------


def ingest_smart_meter(rep: Reporter) -> pd.DataFrame:
    rep.step("Read smart meter daily data")

    files = io.smart_meter_files()
    rep.check(
        "File-count gate",
        len(files) == config.EXPECTED["smart_meter_files"],
        f"{len(files)} files found, {config.EXPECTED['smart_meter_files']} expected",
    )

    # The header gate lives in io.load_smart_meter_file and raises on drift.
    df = io.load_smart_meter_all()
    rep.check("Header gate", True, f"all {len(files)} files with {len(config.SMART_METER_COLUMNS)} columns")

    rep.metric("Files", len(files))
    rep.metric("Rows", len(df))
    rep.metric("Households", df["Household_ID"].nunique())
    rep.metric("Period from", df["date"].min().date())
    rep.metric("Period to", df["date"].max().date())
    rep.check(
        "Row count as documented",
        len(df) == config.EXPECTED["smart_meter_rows_raw"],
        f"{len(df)} rows, {config.EXPECTED['smart_meter_rows_raw']} documented",
        hard=False,
    )

    rep.step("Check identity and timestamps")

    id_mismatch = df.loc[df["Household_ID"] != df["source_file"], "source_file"].unique()
    rep.check(
        "Household_ID matches the file name",
        len(id_mismatch) == 0,
        f"{len(id_mismatch)} files deviating: {list(id_mismatch)[:5]}" if len(id_mismatch) else "",
    )

    wrong_time = int((df["Timestamp"].dt.time != DAY_END_UTC).sum())
    rep.check(
        "all timestamps at 23:59:59 UTC",
        wrong_time == 0,
        f"{wrong_time} rows with a deviating time" if wrong_time else "end of day uniform",
    )

    dupes = int(df.duplicated(subset=["Household_ID", "date"]).sum())
    rep.check(
        "(Household_ID, date) unique",
        dupes == 0,
        f"{dupes} duplicates" if dupes else "",
    )

    groups = sorted(df["Group"].dropna().unique())
    rep.check(
        "Group only with known values",
        set(groups) <= {"treatment", "control"},
        f"values encountered: {groups}",
        hard=False,
    )

    _check_visit_states(rep, df)

    rep.raise_on_failures()
    return df.drop(columns=["source_file"])


def _check_visit_states(rep: Reporter, df: pd.DataFrame) -> None:
    """Check the states and the progression of AffectsTimePoint.

    The column has four states. "during visit" marks the visit day itself and
    occurs exactly once per household - it therefore belongs to neither regime
    and has to be handled separately in stage 2. The actual requirement is not
    "exactly two values" but that the progression per household is monotone:
    no household may fall back into the pre-visit state after the visit.
    """
    rep.step("Check the visit state (AffectsTimePoint)")

    counts = df["AffectsTimePoint"].value_counts(dropna=False)
    for value in config.AFFECTS_TIME_POINT_VALUES:
        rep.metric(f"Rows '{value}'", int(counts.get(value, 0)))

    values = set(df["AffectsTimePoint"].dropna().unique())
    unexpected = values - set(config.AFFECTS_TIME_POINT_VALUES)
    rep.check(
        "known states only",
        not unexpected,
        f"unexpected: {sorted(unexpected)}" if unexpected else f"{sorted(values)}",
    )

    missing = int(df["AffectsTimePoint"].isna().sum())
    rep.check("AffectsTimePoint without gaps", missing == 0, f"{missing} missing values" if missing else "")

    # The visit day is a single day - more than one row per household would
    # hint at multiple visits and would break the regime derivation.
    per_hh_during = (
        df[df["AffectsTimePoint"] == config.VISIT_DURING].groupby("Household_ID", observed=True).size()
    )
    rep.metric("Households with a visit day inside the data window", len(per_hh_during))
    rep.check(
        "'during visit' at most one day per household",
        per_hh_during.empty or int(per_hh_during.max()) == 1,
        f"at most {int(per_hh_during.max())} days" if len(per_hh_during) else "no visit day present",
    )

    ordered = df.sort_values(["Household_ID", "date"])
    patterns: dict[str, int] = {}
    non_monotone: list[str] = []
    for hid, group in ordered.groupby("Household_ID", observed=True):
        seq = group["AffectsTimePoint"].tolist()
        collapsed = [seq[0]]
        for value in seq[1:]:
            if value != collapsed[-1]:
                collapsed.append(value)
        patterns[" -> ".join(collapsed)] = patterns.get(" -> ".join(collapsed), 0) + 1

        ranks = [config.VISIT_ORDER[v] for v in seq if v in config.VISIT_ORDER]
        if ranks != sorted(ranks):
            non_monotone.append(hid)

    rep.check(
        "progression per household monotone (no relapse to before the visit)",
        not non_monotone,
        f"{len(non_monotone)} households violate the ordering: {non_monotone[:5]}"
        if non_monotone
        else "",
    )

    for pattern, n in sorted(patterns.items(), key=lambda kv: -kv[1]):
        rep.note(f"{n} households: {pattern}")
    rep.check(
        "progression patterns as documented",
        patterns == config.EXPECTED["visit_patterns"],
        f"{len(patterns)} distinct patterns",
        hard=False,
    )
    rep.note(
        "Consequence for stage 2: 'during visit' is a transition day and gets its own flag; "
        "households with 'after visit' only had their visit before recording started, "
        "so their visit date is unknown"
    )


def drop_households_without_target(rep: Reporter, df: pd.DataFrame) -> pd.DataFrame:
    """Remove households without a single target value.

    The only substantive intervention of this stage. A household whose target
    column is empty throughout can neither be trained on nor evaluated - it
    would only carry rows with a NaN target through the pipeline.
    """
    rep.step("Remove households without a target value")

    target_counts = df.groupby("Household_ID", observed=True)[config.TARGET_COL].count()
    empty = sorted(target_counts[target_counts == 0].index.tolist())

    rep.metric("Missing target values in total", int(df[config.TARGET_COL].isna().sum()))
    rep.metric("Households without any target value", len(empty))
    for hid in empty:
        n_rows = int((df["Household_ID"] == hid).sum())
        rep.note(f"Household {hid} removed: {n_rows} rows, not a single target value")

    rep.check(
        "removed households as documented",
        empty == sorted(config.EXPECTED["households_no_target"]),
        f"removed: {empty}",
        hard=False,
    )

    out = df[~df["Household_ID"].isin(empty)].reset_index(drop=True)
    rep.metric("Rows after the drop", len(out))
    rep.metric("Households after the drop", out["Household_ID"].nunique())
    rep.check(
        "household count after the drop as documented",
        out["Household_ID"].nunique() == config.EXPECTED["households_after_drop"],
        f"{out['Household_ID'].nunique()} households",
        hard=False,
    )

    # Households with a very short history are kept but reported - whether
    # they are modelable is a decision for the modeling stage.
    short = target_counts[(target_counts > 0) & (target_counts < 30)]
    if len(short):
        rep.note(
            "kept, but with a very short history (< 30 target values): "
            + ", ".join(f"{hid} ({int(n)})" for hid, n in short.items())
        )

    return out


# --------------------------------------------------------------------------
# Master data
# --------------------------------------------------------------------------


def ingest_households(rep: Reporter, keep_ids: set[str]) -> pd.DataFrame:
    """Combine households.csv and meta_data.csv into one master table."""
    rep.step("Read and merge master data")

    households = io.load_households()
    meta = io.load_meta()

    rep.metric("households.csv rows", len(households))
    rep.metric("meta_data.csv rows", len(meta))

    rep.check(
        "households.csv row count as documented",
        len(households) == config.EXPECTED["households_rows"],
        f"{len(households)} rows",
        hard=False,
    )
    rep.check(
        "meta_data.csv covers only part of the households",
        len(meta) == config.EXPECTED["meta_rows"],
        f"{len(meta)} of {len(households)} households with survey data",
        hard=False,
    )
    rep.check(
        "Household_ID unique in households.csv",
        households["Household_ID"].is_unique,
        "",
    )
    rep.check(
        "Household_ID unique in meta_data.csv",
        meta["Household_ID"].is_unique,
        "",
    )
    rep.check(
        "every meta ID exists in households.csv",
        set(meta["Household_ID"]) <= set(households["Household_ID"]),
        "",
    )

    pv_true = int((households["Installation_HasPVSystem"] == True).sum())  # noqa: E712
    pv_missing = int(households["Installation_HasPVSystem"].isna().sum())
    rep.metric("PV flag True", pv_true)
    rep.metric("PV flag unknown", pv_missing)
    rep.check(
        "PV flags as documented",
        pv_true == config.EXPECTED["pv_flag_true"] and pv_missing == config.EXPECTED["pv_flag_missing"],
        f"{pv_true} True, {pv_missing} unknown",
        hard=False,
    )
    if pv_missing:
        unknown = households.loc[households["Installation_HasPVSystem"].isna(), "Household_ID"].tolist()
        rep.note(
            f"PV status unknown for {unknown} - stays <NA>; resolution via feed-in "
            "evidence happens in stage 2"
        )

    merged = households.merge(meta, on="Household_ID", how="left", validate="one_to_one")
    rep.check(
        "left join households x meta multiplies no rows",
        len(merged) == len(households),
        f"{len(households)} -> {len(merged)}",
    )

    merged["has_meta_survey"] = merged["Household_ID"].isin(set(meta["Household_ID"]))

    before = len(merged)
    survey_before = int(merged["has_meta_survey"].sum())
    merged = merged[merged["Household_ID"].isin(keep_ids)].reset_index(drop=True)

    # The metrics are collected AFTER the drop so that they describe the table
    # that is actually written. Numbers reported before the drop would not
    # match the artefact.
    rep.metric("Master data rows after the drop", len(merged))
    rep.metric("Households with survey data", int(merged["has_meta_survey"].sum()))
    rep.metric("Households without survey data", int((~merged["has_meta_survey"]).sum()))
    rep.note(
        f"{survey_before - int(merged['has_meta_survey'].sum())} of the removed households had "
        f"survey data; of the {len(merged)} remaining ones, "
        f"{int(merged['has_meta_survey'].sum())} have a survey record"
    )
    rep.note(
        "Empty survey booleans stay <NA> (unknown), they do not become False - "
        "an unanswered question is not a denial"
    )

    rep.check(
        "master table covers exactly the remaining households",
        set(merged["Household_ID"]) == keep_ids,
        f"{before} -> {len(merged)} rows, {len(keep_ids)} households in the meter frame",
    )

    rep.raise_on_failures()
    return merged


# --------------------------------------------------------------------------
# Weather
# --------------------------------------------------------------------------


def ingest_weather(rep: Reporter, households: pd.DataFrame) -> pd.DataFrame:
    rep.step("Read hourly weather data")

    files = io.weather_files()
    rep.check(
        "Station-count gate",
        len(files) == config.EXPECTED["weather_stations"],
        f"{len(files)} stations found",
    )

    df = io.load_weather_all()
    rep.check("Header gate", True, f"all {len(files)} files with {len(config.WEATHER_COLUMNS)} columns")

    rep.metric("Stations", df["Weather_ID"].nunique())
    rep.metric("Rows", len(df))
    rep.metric("Period from", df["Timestamp"].min())
    rep.metric("Period to", df["Timestamp"].max())

    per_station = df.groupby("Weather_ID", observed=True).size()
    rep.check(
        "all stations with an identical row count",
        per_station.nunique() == 1,
        f"{per_station.min()} to {per_station.max()} rows",
    )

    dupes = int(df.duplicated(subset=["Weather_ID", "Timestamp"]).sum())
    rep.check("(Weather_ID, Timestamp) unique", dupes == 0, f"{dupes} duplicates" if dupes else "")

    rep.step("Referential integrity household to weather station")

    needed = set(households["Weather_ID"].dropna())
    available = set(df["Weather_ID"].unique())
    missing_stations = needed - available
    rep.check(
        "every Weather_ID of the households has a weather file",
        not missing_stations,
        f"missing stations: {sorted(missing_stations)}" if missing_stations else "",
    )
    rep.check(
        "Weather_ID in the master table without gaps",
        int(households["Weather_ID"].isna().sum()) == 0,
        "",
    )
    unused = available - needed
    if unused:
        rep.note(f"Stations without an assigned household: {sorted(unused)}")

    # The three stations without sunshine and pressure values are documented;
    # here we only record which ones they actually are.
    all_nan = {
        col: sorted(
            df.groupby("Weather_ID", observed=True)[col]
            .apply(lambda s: s.isna().all())
            .pipe(lambda s: s[s].index.tolist())
        )
        for col in ("Sunshine_duration_hourly", config.WEATHER_PRESSURE_KEEP)
    }
    for col, stations in all_nan.items():
        rep.note(f"{col}: empty throughout at {stations or 'no station'}")

    rep.raise_on_failures()
    return df


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def run(rep: Reporter) -> None:
    smart_meter = ingest_smart_meter(rep)
    smart_meter = drop_households_without_target(rep, smart_meter)

    keep_ids = set(smart_meter["Household_ID"].unique())
    households = ingest_households(rep, keep_ids)
    weather = ingest_weather(rep, households)

    rep.step("Write results as parquet")
    for name, frame in (
        (config.SMART_METER_PARQUET, smart_meter),
        (config.HOUSEHOLDS_PARQUET, households),
        (config.WEATHER_HOURLY_PARQUET, weather),
    ):
        path = config.INGESTED / name
        io.write_parquet(frame, path)
        rep.metric(name, f"{len(frame):,} rows x {frame.shape[1]} columns")
    rep.check("Parquet round trip without dtype drift", True, "verified for all three tables")
    rep.note(f"Output directory: {config.INGESTED.relative_to(config.ROOT)}")
