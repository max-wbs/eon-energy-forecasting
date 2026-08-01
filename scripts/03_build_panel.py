"""Stage 3: interim/02_clean -> processed/model_table.parquet.

Assembles the cleaned tables into the panel, builds the features under the
leakage rule (shift by FORECAST_LAG days) and assigns the temporal train/test
split.

Usage:
    poetry run python scripts/03_build_panel.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from utils import (  # noqa: E402
    checks,
    config,
    feature_selection,
    features,
    io,
    merge,
    preselection,
    splits,
)
from utils.reporting import Reporter  # noqa: E402


def prove_leakage_free(rep: Reporter, panel: pd.DataFrame, weather_daily: pd.DataFrame) -> None:
    """Independent counter-checks that the shifts really take effect.

    The proofs reconstruct the expected value via a self-join of their own and
    compare it against the built column. They therefore test the feature logic
    against a second, independent derivation - and not the shifted column
    against itself.

    For the weather this is the *only* safeguard since the `_lag` suffix was
    dropped: the columns carry the name of their daily aggregate, so the shift
    is no longer readable from the name. It is therefore proven here for each
    weather column individually, and in both directions - agreement with
    d-FORECAST_LAG *and* disagreement with the target-day value. Without the
    second half, an accidental shift of 0 days would go undetected whenever the
    series is smooth enough.
    """
    rep.step("Leakage proofs")

    for lag in config.TARGET_LAGS:
        ok, detail = checks.lag_matches_shifted_target(
            panel, f"{features.TARGET_PREFIX}_lag{lag}", lag
        )
        rep.check(f"recv_lag{lag} carries the target value of d-{lag}", ok, detail)

    lag_cols = [f"{features.TARGET_PREFIX}_lag{lag}" for lag in config.TARGET_LAGS]
    ok, detail = checks.first_rows_have_na_lags(panel, lag_cols)
    rep.check("first row of every household without lag values (groupby takes effect)", ok, detail)

    _prove_weather_shift(rep, panel, weather_daily)
    rep.raise_on_failures()


def _prove_weather_shift(rep: Reporter, panel: pd.DataFrame, weather_daily: pd.DataFrame) -> None:
    """Check every weather column against the station series, in both directions."""
    columns = [c for c in merge.WEATHER_OBSERVED_COLUMNS if c in panel.columns]

    n_proven = 0
    for col in columns:
        base = weather_daily[["Weather_ID", "date", col]]

        shifted = base.copy()
        shifted["date"] = shifted["date"] + io.days(config.FORECAST_LAG)
        shifted = shifted.rename(columns={col: "_expected"})
        same_day = base.rename(columns={col: "_same_day"})

        present = panel[panel[col].notna()]
        sample = present.sample(min(2_000, len(present)), random_state=0)
        checked = (
            sample[["Weather_ID", "date", col]]
            .merge(shifted, on=["Weather_ID", "date"], how="left")
            .merge(same_day, on=["Weather_ID", "date"], how="left")
        )

        mismatch = int((checked[col] - checked["_expected"]).abs().gt(1e-9).sum())
        # Counter-check: how often does the column differ from the target-day
        # value? Must be > 0, otherwise the shift had no effect and the test
        # above would be vacuous.
        differs = int((checked[col] - checked["_same_day"]).abs().gt(1e-9).sum())

        rep.check(
            f"{col} carries the observation from d-{config.FORECAST_LAG}",
            mismatch == 0,
            f"{len(checked)} samples, {mismatch} deviations",
        )
        rep.check(
            f"{col} is not the target-day value",
            differs > 0,
            f"{differs} of {len(checked)} samples differ from the target-day value",
        )
        if mismatch == 0 and differs > 0:
            n_proven += 1

    rep.metric("Weather columns passing the shift proof", f"{n_proven} of {len(columns)}")
    rep.note(
        "The weather columns no longer carry a lag suffix but the name of the daily "
        f"aggregate. The shift by {config.FORECAST_LAG} day(s) is therefore evidenced "
        "exclusively here - per column against an independent self-join, with a "
        "counter-check against the target-day value. Whoever reads the names must mind "
        "forecast_lag_days in the schema: it is an observation, not a target-day value"
    )


def drop_gap_rows(rep: Reporter, panel: pd.DataFrame) -> pd.DataFrame:
    """Remove the calendar rows inserted in stage 2 - their job is done.

    The gap rows exist for exactly one reason: `shift(k)` and `rolling(w)` are
    only correct on a gapless daily grid (see docs/decisions.md D-07). That
    purpose ends the moment the features are built. From here on they are rows
    without a single measurement, and keeping them would only inflate the
    artefact and every row count computed from it.

    The removal must happen *after* `features.build`. Doing it earlier would
    reintroduce exactly the gaps the reindex was there to close, and the lags
    would silently reach across them.
    """
    rep.step("Remove the inserted calendar gap rows")

    gaps = panel["is_gap"]
    n_gaps = int(gaps.sum())

    # Proof before removal: a gap row must not carry a single measurement.
    # Anything else would mean the reindex overwrote observed data - then these
    # rows would not be removable and the failure has to be loud.
    meter_cols = [c for c in config.SMART_METER_VALUE_COLUMNS if c in panel.columns]
    populated = {
        c: int(panel.loc[gaps, c].notna().sum())
        for c in meter_cols
        if int(panel.loc[gaps, c].notna().sum())
    }
    rep.check(
        "gap rows carry no measurement at all",
        not populated,
        f"{len(meter_cols)} meter columns checked, all empty on the gap rows"
        if not populated
        else f"populated cells found: {populated}",
    )

    out = panel[~gaps].reset_index(drop=True)

    rep.metric("Rows before", len(panel))
    rep.metric("Gap rows removed", n_gaps)
    rep.metric("Rows after", len(out))
    rep.metric("Households affected", int(panel.loc[gaps, "Household_ID"].nunique()))
    rep.metric("Households before / after", f"{panel['Household_ID'].nunique()} / {out['Household_ID'].nunique()}")

    rep.check(
        "no row without a target value left over from the gaps",
        int(out["is_gap"].sum()) == 0,
        "",
    )
    rep.note(
        "The gap rows only ever served the correctness of shift and rolling on a gapless "
        "daily grid. Now that the features exist they carry no information: not one of the "
        f"{len(meter_cols)} measurement columns is populated on them, the target value included"
    )
    rep.note(
        "Consequence for downstream stages: the panel is deliberately NO LONGER gapless per "
        "household. Any further time series operation on the model table would have to "
        "reindex first - the features built here are unaffected, they were computed on the "
        "complete grid"
    )

    rep.raise_on_failures()
    return out


def report_usability(rep: Reporter, panel: pd.DataFrame, groups: dict[str, list[str]]) -> None:
    """Quantify how many rows are modelable after the edge handling."""
    rep.step("Usability of the panel")

    has_target = panel[config.TARGET_COL].notna()
    mandatory = [f"{features.TARGET_PREFIX}_lag{lag}" for lag in config.TARGET_LAGS]
    has_lags = panel[mandatory].notna().all(axis=1)
    weather_key = config.daily_name("Temperature_avg_hourly", "mean")
    has_weather = panel[weather_key].notna()

    # The target value is the only condition - see docs/decisions.md D-19.
    # Neither a missing lag nor missing weather disqualifies a row: both occur
    # in production (meter outage, station outage) on days for which a bid
    # still has to be placed. Excluding them would measure the model only on
    # the days when everything worked.
    usable = has_target

    rep.metric("Panel rows", len(panel))
    rep.metric("of which with a target value", int(has_target.sum()))
    rep.metric("Share of modelable rows", 100 * usable.sum() / len(panel), "%")

    # Feature availability inside the modelable set - reported, not enforced.
    # These are the rows a model has to cope with rather than be spared from.
    rep.metric(f"Modelable rows without {', '.join(mandatory)}", int((usable & ~has_lags).sum()))
    rep.metric("Modelable rows without weather (station outage)", int((usable & ~has_weather).sum()))
    rep.note(
        "Neither lags nor weather are a condition of is_modelable. A missing lag follows a "
        "meter outage, a missing weather value a station outage - both happen in production, "
        "and a fleet that has to bid every day cannot skip those days. The model has to "
        "handle the NaN (tree models do so natively) instead of having the rows removed from "
        "its evaluation"
    )
    rep.note(
        "Feature availability stays readable per row from the columns themselves "
        f"({', '.join(mandatory)}, {weather_key}). A modeling script that needs the strict "
        "subset can reproduce it in one line - the reverse, recovering rows a flag already "
        "discarded, is not possible"
    )

    per_hh = usable.groupby(panel["Household_ID"], observed=True).sum()
    rep.metric("Households without a single modelable row", int((per_hh == 0).sum()))
    rep.metric("Median modelable rows per household", int(per_hh.median()))
    empty = sorted(per_hh[per_hh == 0].index.tolist())
    if empty:
        rep.note(
            f"Households without a modelable row: {empty} - not a single target value in the "
            "panel window. They stay in the panel; the modeling stage decides about excluding them"
        )

    panel["is_modelable"] = usable.astype("bool")
    rep.note(
        "The column is_modelable marks rows with a target value - nothing else. That makes "
        "the evaluation set model-independent: models with different feature requirements are "
        "scored on the same rows and stay comparable"
    )


def write_outputs(
    rep: Reporter,
    panel: pd.DataFrame,
    groups: dict[str, list[str]],
    deselected: dict[str, list[str]],
    contract: dict,
) -> None:
    rep.step("Write the panel")

    io.write_parquet(panel, config.PROCESSED / config.MODEL_TABLE_PARQUET)
    rep.metric(
        config.MODEL_TABLE_PARQUET,
        f"{len(panel):,} rows x {panel.shape[1]} columns",
    )


def write_schema(
    rep: Reporter,
    panel: pd.DataFrame,
    groups: dict[str, list[str]],
    deselected: dict[str, list[str]],
    contract: dict,
) -> None:
    """Write the schema last: it has to describe the artefacts that now exist.

    Separate from `write_outputs` because the split frames are written in
    between and their row counts belong in the schema. A schema written before
    them would describe an intention rather than the files on disk.
    """
    rep.step("Write the schema")

    # The column roles are stored next to the panel so that the modeling stage
    # does not have to guess the feature selection again. `feature_groups` is
    # the contract: a modeling script takes exactly these columns. `deselected`
    # lists the computed reserve with reasons - the basis for ablation
    # experiments.
    n_active = sum(len(c) for c in groups.values())
    schema = {
        "target": contract["target"],
        "keys": contract["keys"],
        "split_column": splits.SPLIT_COLUMN,
        # Two views of the same set, proven equal in preselection._sync_groups:
        # `feature_groups` grouped by origin, `preselection.features` as the
        # flat ordered contract. A modeling script should read the latter.
        "preselection": contract,
        "feature_groups": groups,
        "n_features": n_active,
        "panel_slim": config.PANEL_SLIM,
        "panel_slim_note": (
            "The panel holds only the contract columns: keys, target, features, split and "
            "is_modelable. The reserve, the passthrough measurements and the remaining row "
            "flags were computed and checked but not written. Set config.PANEL_SLIM = False "
            "and rerun stage 3 (about two seconds) to get them back. The survey attributes "
            f"need no rerun at all - they are in {config.CLEAN.name}/{config.HOUSEHOLDS_PARQUET} "
            "with one row per household and join back over Household_ID."
        )
        if config.PANEL_SLIM
        else (
            "The panel holds every computed column. The contract in `preselection` is then a "
            "declaration only - a modeling script that reads panel.columns instead of "
            "preselection.features would see the forbidden columns."
        ),
        "deselected": {
            "note": (
                "Computed and checked, but NOT passed on as a feature - and with "
                "config.PANEL_SLIM on, NOT present in the written panel either. For a "
                "comparison model add them to the respective group and rerun stage 3."
                if config.PANEL_SLIM
                else (
                    "Present in the panel and checked, but NOT passed on as a feature. "
                    "For a comparison model simply add them to the respective group."
                )
            ),
            "present_in_panel": not config.PANEL_SLIM,
            "reasons": feature_selection.DESELECTED_REASONS,
            "columns": deselected,
        },
        "passthrough": [c for c in config.PASSTHROUGH_COLUMNS if c in panel.columns],
        "flags": [
            c
            for c in ("is_gap", "kWh_spike_flag", "returned_was_substituted", "is_modelable")
            if c in panel.columns
        ],
        "forecast_lag_days": config.FORECAST_LAG,
        "weather_shift_days": config.FORECAST_LAG,
        "weather_naming_note": (
            "Weather columns carry the name of their daily aggregate without a lag suffix, "
            f"but contain the observation from d-{config.FORECAST_LAG} - see weather_shift_days. "
            "They are observations, not forecasts."
        ),
        "hdd_base_c": config.HDD_BASE_C,
        "split_cutoff": config.SPLIT_CUTOFF,
        # The window the panel actually covers, read off the data rather than
        # off the config - with the trim switched off the two differ, and the
        # schema has to describe the artefact, not the intention.
        "panel_window": [
            str(panel["date"].min().date()),
            str(panel["date"].max().date()),
        ],
        "weather_window": [config.PANEL_DATE_MIN, config.PANEL_DATE_MAX],
        "trimmed_to_weather_window": config.TRIM_TO_WEATHER_WINDOW,
        "weather_window_note": (
            "Rows outside weather_window were removed: no weather was delivered for that "
            "period, which is a property of the dataset rather than of the operating "
            "situation. A missing weather value INSIDE the window is a station outage and "
            "is kept - is_modelable does not require weather."
        )
        if config.TRIM_TO_WEATHER_WINDOW
        else (
            "panel_window is the metered period, weather_window the part of it for which "
            "shifted weather exists. Rows outside weather_window are kept and carry NaN in "
            "every weather column."
        ),
        "is_modelable_definition": (
            "target value present - nothing else. Neither lags nor weather are required: a "
            "missing lag follows a meter outage, a missing weather value a station outage, "
            "and both occur in production on days for which a bid still has to be placed. "
            "Feature availability is readable per row from the columns themselves, so a "
            "stricter subset can be reproduced in the modeling stage at any time."
        ),
        "gap_rows_removed": True,
        "gap_rows_note": (
            "The calendar rows inserted in stage 2 (is_gap) were removed after the features "
            "were built. They carried no measurement. As a result the panel is NOT gapless "
            "per household - reindex before running further time series operations on it."
        ),
    }
    schema_path = config.PROCESSED / "model_table_schema.json"
    schema_path.write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
    rep.metric(
        "model_table_schema.json",
        f"{len(groups)} feature groups, {n_active} active features",
    )
    rep.note(
        "The modeling stage builds its feature list from preselection.features in the schema, "
        "never from panel.columns: kWh_received_HeatPump and kWh_received_Other sum to the "
        f"target exactly, so a naive 'everything except {contract['target']}' would be reading "
        "the answer"
    )
    rep.note(f"Output directory: {config.PROCESSED.relative_to(config.ROOT)}")


def run(rep: Reporter) -> None:
    rep.step("Read the results of stage 2")
    panel = io.read_parquet(config.CLEAN / config.SMART_METER_PARQUET)
    households = io.read_parquet(config.CLEAN / config.HOUSEHOLDS_PARQUET)
    weather_daily = io.read_parquet(config.CLEAN / config.WEATHER_DAILY_PARQUET)

    rep.metric("Smart meter rows", len(panel))
    rep.metric("Households", panel["Household_ID"].nunique())
    rep.metric("Weather daily rows", len(weather_daily))
    rep.note(f"Source: {config.CLEAN.relative_to(config.ROOT)} (stage-2 output only)")

    lagged_weather = merge.build_lagged_weather(rep, weather_daily)
    station_flags = merge.build_station_flags(weather_daily)
    panel = merge.merge_panel(rep, panel, households, lagged_weather, station_flags)
    panel = merge.trim_to_window(rep, panel)

    panel, groups, deselected = features.build(rep, panel)
    # The leakage proofs run on the complete grid - that is the state in which
    # the shifts were computed and therefore the state they have to be proven
    # against. Only afterwards do the now-superfluous gap rows go.
    prove_leakage_free(rep, panel, weather_daily)
    panel = drop_gap_rows(rep, panel)
    panel = splits.assign_split(rep, panel)
    report_usability(rep, panel, groups)
    # The pre-selection runs last for two reasons. It needs `split` to keep
    # every statistic on the training rows, and it needs `is_modelable` so it
    # does not measure coverage over rows no model will ever see. It is also
    # where the contract names are applied - after that point the panel no
    # longer speaks the raw vocabulary the checks above are written against.
    panel, groups, contract = preselection.apply(rep, panel, groups)
    panel = preselection.slim(rep, panel, deselected)
    write_outputs(rep, panel, groups, deselected, contract)
    # The split frames come last and are derived from the written panel, so
    # they cannot disagree with it.
    contract["split_frames"] = preselection.write_splits(rep, panel)
    write_schema(rep, panel, groups, deselected, contract)


def main() -> int:
    try:
        with Reporter(stage=3, title="Panel, Features & Split") as rep:
            run(rep)
    except Exception as exc:
        print(f"\nAborted: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
