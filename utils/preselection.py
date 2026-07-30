"""Final feature pre-selection (stage 3, step 10.5) - the handoff contract.

Stage 3 speaks two vocabularies and this module is the boundary between them.

*Upstream* every column carries its source name: the target is
`kWh_received_Total`, the station is `Weather_ID`. That naming is what keeps
the pipeline auditable - the leakage proofs, the checks and every entry in
docs/decisions.md refer to it, and any column can be traced back to the
delivered CSV without a lookup table.

*Downstream* the model receives the vocabulary of the modeling stage: the
target is `gross_load`, the station is `weather_id`. `gross_load` states what
the quantity *is* - gross draw from the grid, before any netting against PV
self-consumption - instead of how it happened to be metered.

The rename therefore happens here and nowhere earlier: after the leakage
proofs (step 7), after the split (step 9) and after `is_modelable` (step 10),
as the last transformation before the panel is written. Everything upstream
keeps its source names and stays comparable to the report; the mapping is
recorded in the schema under `preselection.renamed`.

The selection itself is a **declaration**, not a search. `FEATURES` below is
what the modeling stage gets, and this module does not shorten it. What it
does is prove the list is sound - every column present, none of them a
passthrough or the target in disguise, none constant - and report the
properties a reader would otherwise have to rediscover: functional
dependencies between features, strongly correlated pairs, coverage.

That split is deliberate. Dropping a feature because of a statistic computed
against the *target* would move model fitting into the data preparation, where
no cross-validation can see it - the selection error would then appear in no
metric at all. Everything checked here is target-independent, and every
row-based statistic is computed on `train` only: the test window must not
influence the model specification, not even through a coverage figure.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from utils import config, io, splits
from utils.reporting import Reporter

# --------------------------------------------------------------------------
# The contract
# --------------------------------------------------------------------------

TARGET = "gross_load"
KEYS = list(config.KEY_COLUMNS)

# The columns the modeling stage receives, in this order. Grouped by origin
# for readability only - the groups carry no meaning downstream.
FEATURES = [
    # Calendar - the target day's own calendar, deliberately unshifted
    "dow",
    "month",
    "season",
    "is_weekend",
    "is_holiday",
    # Weather - daily aggregate of the observation from d-FORECAST_LAG,
    # never a forecast (see docs/decisions.md D-05, D-16)
    "Temperature_avg_hourly_mean",
    "Temperature_avg_hourly_min",
    "Temperature_avg_hourly_max",
    "Humidity_avg_hourly_mean",
    "WindSpeed_hourly_mean",
    "DewPoint_hourly_mean",
    "Precipitation_total_hourly_sum",
    "Sunshine_duration_hourly_sum",
    # Weather-derived
    "hdd_15",
    # Autoregressive - history of the target, shifted by FORECAST_LAG
    "recv_lag1",
    "recv_lag7",
    "recv_roll7_mean",
    "recv_roll7_std",
    # Structure / meta / marker
    "is_post_visit",
    "Installation_HasPVSystem",
    "weather_id",
]

# source name -> contract name. Applied to the panel in this step.
RENAME = {
    config.TARGET_COL: TARGET,
    "Weather_ID": "weather_id",
}

# The station identifier becomes a feature, so it needs a dtype a tree model
# can consume as a category rather than as an accidental ordinal.
CATEGORICAL = ["weather_id", "season"]

# Row-level quality markers. They describe the data situation of a row, not
# the household - a spike flag on the target day would reveal that consumption
# was unusually high.
ROW_FLAGS = ["is_gap", "kWh_spike_flag", "returned_was_substituted", "is_modelable"]


def forbidden_columns() -> set[str]:
    """Columns that must never appear among the features.

    The target under either name, every same-day measurement and the row
    quality markers. `kWh_received_HeatPump` and `kWh_received_Other` are the
    sharpest case: they sum to the target exactly, so a model that sees them
    would be reading the answer.
    """
    return {
        *config.PASSTHROUGH_COLUMNS,
        config.TARGET_COL,
        TARGET,
        *ROW_FLAGS,
        splits.SPLIT_COLUMN,
    }


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def apply(
    rep: Reporter, panel: pd.DataFrame, groups: dict[str, list[str]]
) -> tuple[pd.DataFrame, dict[str, list[str]], dict]:
    """Rename to the contract names, verify the selection, report its structure.

    Returns (panel, synced feature groups, contract dict for the schema).
    """
    rep.step("Final feature pre-selection")

    panel = _rename(rep, panel)
    groups = _sync_groups(rep, groups)
    _verify(rep, panel, groups)
    contract = _report_structure(rep, panel)

    rep.raise_on_failures()
    return panel, groups, contract


# --------------------------------------------------------------------------
# Rename
# --------------------------------------------------------------------------


def _rename(rep: Reporter, panel: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(c for c in RENAME if c not in panel.columns)
    rep.check(
        "all columns to be renamed exist in the panel",
        not missing,
        f"missing: {missing}" if missing else ", ".join(f"{a} -> {b}" for a, b in RENAME.items()),
    )
    # A target name that is already taken would silently collide and one of
    # the two columns would win - the failure has to be loud.
    collisions = sorted(v for v in RENAME.values() if v in panel.columns)
    rep.check(
        "no contract name is already occupied",
        not collisions,
        f"already present: {collisions}" if collisions else "",
    )
    rep.raise_on_failures()

    panel = panel.rename(columns=RENAME)

    for col in CATEGORICAL:
        if col in panel.columns and panel[col].dtype.name != "category":
            panel[col] = panel[col].astype("category")

    rep.metric("Renamed columns", len(RENAME))
    rep.metric("Target", TARGET)
    rep.metric("Keys", ", ".join(KEYS))
    rep.metric(
        "Categorical dtype",
        ", ".join(f"{c} ({panel[c].cat.categories.size} levels)" for c in CATEGORICAL if c in panel),
    )
    rep.note(
        "The rename happens at the very end of stage 3, after the leakage proofs and the "
        "split. Everything upstream keeps the source names, so the report and "
        "docs/decisions.md stay readable against the raw data; the mapping is recorded in "
        "the schema under preselection.renamed"
    )
    rep.note(
        f"{config.TARGET_COL} becomes {TARGET}: the quantity is the gross draw from the grid, "
        "before any netting against PV self-consumption. The name states what it is rather "
        "than how it was metered"
    )
    rep.note(
        "weather_id enters as a feature and is cast to category. With 8 levels it carries the "
        "regional offset the weather columns do not capture - but it is invariant per "
        "household, so it also encodes fleet structure. See docs/decisions.md D-21"
    )
    return panel


def _sync_groups(rep: Reporter, groups: dict[str, list[str]]) -> dict[str, list[str]]:
    """Bring the grouped declaration in line with FEATURES, then prove they match.

    Two representations of the same set survive into the schema: `feature_groups`
    grouped by origin and `preselection.features` as a flat ordered list. They
    must not drift apart, so the equality is checked rather than assumed.
    """
    synced = {name: list(cols) for name, cols in groups.items()}
    for col in FEATURES:
        if col in {c for cols in synced.values() for c in cols}:
            continue
        synced.setdefault("static", []).append(col)

    flat = {c for cols in synced.values() for c in cols}
    only_groups = sorted(flat - set(FEATURES))
    only_features = sorted(set(FEATURES) - flat)
    rep.check(
        "feature_groups and preselection.features describe the same set",
        not only_groups and not only_features,
        f"only in groups: {only_groups}, only in FEATURES: {only_features}"
        if (only_groups or only_features)
        else f"{len(flat)} columns in both",
    )
    return synced


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------


def _verify(rep: Reporter, panel: pd.DataFrame, groups: dict[str, list[str]]) -> None:
    # The heating degree day column derives its name from HDD_BASE_C (D-10).
    # Flipping the base to 18 would produce hdd_18 and silently drop the
    # feature from the contract - this makes that fail loudly instead.
    rep.check(
        f"the configured HDD column ({config.HDD_COLUMN}) is part of the contract",
        config.HDD_COLUMN in FEATURES,
        f"HDD_BASE_C={config.HDD_BASE_C:g} produces {config.HDD_COLUMN}",
    )

    missing = sorted(c for c in FEATURES if c not in panel.columns)
    rep.check("all contract features exist in the panel", not missing, f"missing: {missing}")

    duplicates = sorted({c for c in FEATURES if FEATURES.count(c) > 1})
    rep.check("no feature listed twice", not duplicates, f"{duplicates}")

    absent_keys = sorted(c for c in [*KEYS, TARGET] if c not in panel.columns)
    rep.check("target and keys exist", not absent_keys, f"missing: {absent_keys}")

    overlap = sorted(set(FEATURES) & forbidden_columns())
    rep.check(
        "no target, passthrough or row flag among the features",
        not overlap,
        f"not permitted: {overlap}"
        if overlap
        else f"{len(forbidden_columns())} forbidden columns checked",
    )

    rep.raise_on_failures()

    # Constancy is judged on train only: a feature that never varies there
    # cannot be learned from, whatever it does in the test window.
    train = _train_rows(panel)
    constant = sorted(c for c in FEATURES if train[c].nunique(dropna=True) <= 1)
    rep.check(
        "no feature constant on train",
        not constant,
        f"constant: {constant}" if constant else f"{len(FEATURES)} features checked",
    )

    rep.metric("Contract features", len(FEATURES))
    rep.metric("Rows train (modelable)", len(train))
    rep.note(
        "The pre-selection is a declaration, not a search: it does not shorten the list. It "
        "proves the list is sound and reports what a reader would otherwise have to "
        "rediscover. Anything computed against the target belongs in the modeling stage, "
        "inside the cross-validation - otherwise the selection error appears in no metric"
    )


def _train_rows(panel: pd.DataFrame) -> pd.DataFrame:
    """The rows every statistic in this step is computed on."""
    mask = panel[splits.SPLIT_COLUMN] == splits.TRAIN
    if "is_modelable" in panel.columns:
        mask &= panel["is_modelable"].astype("boolean").fillna(False)
    return panel.loc[mask]


# --------------------------------------------------------------------------
# Structural report
# --------------------------------------------------------------------------


def _report_structure(rep: Reporter, panel: pd.DataFrame) -> dict:
    train = _train_rows(panel)

    coverage = {c: float(train[c].notna().mean()) for c in FEATURES}
    thin = {c: r for c, r in coverage.items() if r < config.PRESELECT_COVERAGE_WARN}
    rep.check(
        f"every feature at least {config.PRESELECT_COVERAGE_WARN:.0%} populated on train",
        not thin,
        ", ".join(f"{c} {r:.1%}" for c, r in sorted(thin.items(), key=lambda x: x[1]))
        if thin
        else f"lowest: {min(coverage, key=coverage.get)} {min(coverage.values()):.1%}",
        hard=False,
    )
    incomplete = {c: r for c, r in coverage.items() if r < 1.0}
    if incomplete:
        rep.note(
            "Not fully populated on train (kept deliberately - a missing value is a meter or "
            "station outage, a state the model has to handle rather than be spared from, "
            "see D-19): "
            + ", ".join(f"{c} {r:.2%}" for c, r in sorted(incomplete.items(), key=lambda x: x[1]))
        )

    dependencies = _functional_dependencies(train)
    if dependencies:
        rep.note(
            "Exact functional dependencies among the features: "
            + "; ".join(f"{dep} = f({det})" for det, dep in dependencies)
            + ". Tree models are invariant to a monotone transform of a single feature, so "
            "these carry no additional information for RF or LightGBM - they do for a linear "
            "model, where the kink is real. Reported, not removed: the choice belongs to the "
            "model, not to the panel"
        )
    rep.metric("Exact functional dependencies", len(dependencies))

    pairs = _correlated_pairs(train)
    if pairs:
        rep.note(
            f"Feature pairs with |r| >= {config.PRESELECT_CORR_REPORT}: "
            + "; ".join(f"{a}/{b} {r:.3f}" for a, b, r in pairs)
            + ". Deliberately not filtered: multicollinearity costs tree models "
            "interpretability of the importances, not accuracy. Dropping the temperature "
            "extremes would cost exactly the cold days that matter most for procurement"
        )
    rep.metric(f"Correlated pairs (|r| >= {config.PRESELECT_CORR_REPORT})", len(pairs))

    return {
        "target": TARGET,
        "keys": KEYS,
        "features": list(FEATURES),
        "n_features": len(FEATURES),
        "renamed": dict(RENAME),
        "categorical": [c for c in CATEGORICAL if c in panel.columns],
        "excluded": sorted(forbidden_columns()),
        "statistics_computed_on": (
            f"{splits.TRAIN} and is_modelable ({len(train):,} rows) - the test window must not "
            "influence the model specification"
        ),
        "coverage_train": {c: round(r, 6) for c, r in coverage.items()},
        "functional_dependencies": [
            {"determinant": det, "dependent": dep} for det, dep in dependencies
        ],
        "correlated_pairs": [{"a": a, "b": b, "abs_r": round(r, 4)} for a, b, r in pairs],
        "note": (
            "features is the contract: the modeling stage takes exactly these columns under "
            "exactly these names. The list is a declaration - nothing here was selected by a "
            "statistic against the target. Functional dependencies and correlated pairs are "
            "reported so the modeling stage can act on them; the panel does not."
        ),
    }


def contract_columns() -> list[str]:
    """Everything the written panel keeps when `config.PANEL_SLIM` is on.

    The features alone would not be usable: without the keys a row cannot be
    identified, without the target nothing can be trained, and without `split`
    and `is_modelable` the two mandatory filters cannot be applied. These four
    are therefore part of the contract, not an exception to it.
    """
    return [*KEYS, TARGET, *FEATURES, splits.SPLIT_COLUMN, "is_modelable"]


def slim(rep: Reporter, panel: pd.DataFrame, deselected: dict[str, list[str]]) -> pd.DataFrame:
    """Reduce the panel to the contract columns, and say what that costs.

    The dropped columns were all computed and checked - the run is identical
    up to this point. Only the writing is conditional, which is why the switch
    is reversible: `config.PANEL_SLIM = False` plus one run of about two
    seconds brings them back.
    """
    rep.step("Reduce the panel to the contract columns")

    if not config.PANEL_SLIM:
        rep.metric("Slim panel", False)
        rep.metric("Columns kept", panel.shape[1])
        rep.note(
            "config.PANEL_SLIM is off: the panel keeps the reserve, the passthrough "
            "measurements and all row flags. The contract is then a declaration in the schema "
            "only, so a modeling script that reads panel.columns instead of "
            "preselection.features would see the forbidden columns"
        )
        return panel

    keep = [c for c in contract_columns() if c in panel.columns]
    missing = sorted(c for c in contract_columns() if c not in panel.columns)
    rep.check("every contract column exists before the reduction", not missing, f"missing: {missing}")
    rep.raise_on_failures()

    dropped = [c for c in panel.columns if c not in keep]
    reserve = {c for cols in deselected.values() for c in cols}

    # Grouped by why the column existed, so the report states what was given
    # up rather than only how much.
    by_role = {
        "reserve (D-17)": sorted(c for c in dropped if c in reserve),
        "passthrough": sorted(c for c in dropped if c in config.PASSTHROUGH_COLUMNS),
        "row flags": sorted(c for c in dropped if c in ROW_FLAGS),
        "other": sorted(
            c
            for c in dropped
            if c not in reserve
            and c not in config.PASSTHROUGH_COLUMNS
            and c not in ROW_FLAGS
        ),
    }

    out = panel[keep].copy()

    rep.metric("Slim panel", True)
    rep.metric("Columns before", panel.shape[1])
    rep.metric("Columns dropped", len(dropped))
    rep.metric("Columns kept", out.shape[1])
    rep.metric(
        "Kept",
        f"{len(KEYS)} keys, 1 target, {len(FEATURES)} features, "
        f"{splits.SPLIT_COLUMN} and is_modelable",
    )
    for role, cols in by_role.items():
        if cols:
            rep.metric(f"dropped - {role}", len(cols))
    rep.check(
        "no forbidden column left in the panel",
        not (set(out.columns) & (forbidden_columns() - {TARGET, "is_modelable", splits.SPLIT_COLUMN})),
        "the measurement columns that sum to the target are gone",
    )
    rep.check(
        "row count unchanged by the reduction",
        len(out) == len(panel),
        f"{len(panel):,} rows",
    )

    for role, cols in by_role.items():
        if cols:
            rep.note(f"Dropped, {role}: {', '.join(cols)}")

    rep.note(
        "The dropped columns were computed and checked as before - the run is identical up to "
        "this point, only the writing is conditional. config.PANEL_SLIM = False plus one run "
        "(about two seconds) restores them, which is what makes the ablation experiment from "
        "D-17 affordable despite the reduction"
    )
    rep.note(
        "The survey attributes remain available without any rerun: they live in "
        f"{config.CLEAN.name}/{config.HOUSEHOLDS_PARQUET} with one row per household (153 x 39) "
        "and join back over Household_ID. That is also the better source for segmentation, "
        "because it weights every household once instead of once per day - see D-20"
    )
    rep.note(
        "Not recoverable by a join, only by a rerun: the computed reserve features "
        "(recv_lag3/9/14, recv_roll28_*, doy_sin/cos, the rolling weather windows, pressure, "
        "WindSpeed_hourly_max, days_since_visit, is_visit_day) and the passthrough "
        "measurements used for the PV cross-check in D-20"
    )

    rep.raise_on_failures()
    return out


def split_columns() -> list[str]:
    """Column layout of the two split frames: keys, target, features.

    Neither `split` nor `is_modelable` appears. The split is in the file name,
    and the modelable filter has already been applied - a column stating that
    every row satisfies it would carry no information.
    """
    return [*KEYS, TARGET, *FEATURES]


def write_splits(rep: Reporter, panel: pd.DataFrame) -> dict:
    """Write panel_train.parquet and panel_test.parquet next to the panel.

    These are the frames a modeling script can read without knowing anything
    about the pipeline: no filtering left to do, no forbidden column to avoid.
    The panel stays the source of truth - it keeps `split` and `is_modelable`,
    so the two frames are derivable from it and nothing is stored twice for a
    different reason.

    Rows are restricted to `is_modelable`, which here means: the target value
    is present (D-19). Rows without a label can be neither trained nor scored,
    and since the flag is not carried along, leaving them in would hand the
    modeling stage a `y` with holes and no way left to spot them.
    """
    rep.step("Write the split frames")

    columns = [c for c in split_columns() if c in panel.columns]
    missing = sorted(c for c in split_columns() if c not in panel.columns)
    rep.check("every contract column exists for the split frames", not missing, f"missing: {missing}")
    rep.raise_on_failures()

    modelable = panel["is_modelable"].astype("boolean").fillna(False)
    targets = {
        splits.TRAIN: config.PANEL_TRAIN_PARQUET,
        splits.TEST: config.PANEL_TEST_PARQUET,
    }

    written: dict[str, dict] = {}
    for split_name, filename in targets.items():
        mask = (panel[splits.SPLIT_COLUMN] == split_name) & modelable
        frame = panel.loc[mask, columns].reset_index(drop=True)

        io.write_parquet(frame, config.PROCESSED / filename)

        rep.metric(
            filename,
            f"{len(frame):,} rows x {frame.shape[1]} columns",
        )
        rep.check(
            f"{filename} without a gap in {TARGET}",
            int(frame[TARGET].isna().sum()) == 0,
            f"{len(frame):,} rows, all labelled",
        )
        written[split_name] = {
            "file": filename,
            "rows": int(len(frame)),
            "columns": int(frame.shape[1]),
            "households": int(frame["Household_ID"].nunique()),
            "date_min": str(frame["date"].min().date()),
            "date_max": str(frame["date"].max().date()),
        }

    train_max = written[splits.TRAIN]["date_max"]
    test_min = written[splits.TEST]["date_min"]
    rep.check(
        "the test frame starts strictly after the training frame",
        train_max < test_min,
        f"{train_max} < {test_min}",
    )

    # Categorical levels have to be identical across both files. Were they
    # derived per frame, a station absent from one split would shift the codes
    # and train and test would silently disagree on what a code means.
    for col in CATEGORICAL:
        if col not in columns:
            continue
        levels = {
            name: list(
                pd.read_parquet(config.PROCESSED / info["file"], columns=[col])[col]
                .cat.categories.astype(str)
            )
            for name, info in written.items()
        }
        identical = len(set(map(tuple, levels.values()))) == 1
        rep.check(
            f"{col} carries the same categories in both files",
            identical,
            f"{len(next(iter(levels.values())))} levels"
            if identical
            else f"train: {levels[splits.TRAIN]}, test: {levels[splits.TEST]}",
        )

    rep.metric("Rows dropped as unlabelled", int((~modelable).sum()))
    rep.note(
        f"Rows are restricted to is_modelable - the target value is present (D-19). The flag "
        f"itself is not carried along, so the filter has to be applied here: a y with holes and "
        f"no column left to detect them would be worse than the {int((~modelable).sum())} "
        "missing rows"
    )
    rep.note(
        f"{splits.SPLIT_COLUMN} is not a column of these files - it is the file name. The panel "
        "keeps both it and is_modelable, so the two frames stay derivable from it and nothing is "
        "stored twice for a different purpose"
    )
    rep.note(
        "Categorical levels were checked for equality across the two files. Derived per frame "
        "they could diverge, and a code would then mean a different station in train than in "
        "test - a failure that shows up as a slightly worse metric, never as an error"
    )

    rep.raise_on_failures()
    return {
        "columns": columns,
        "n_columns": len(columns),
        "filter": "is_modelable (target value present, see D-19)",
        "splits": written,
        "note": (
            "Ready-to-use frames: keys, target and features, rows already filtered. No split "
            "column (it is the file name) and no is_modelable (the filter has been applied). "
            "The panel remains the source of truth and keeps both."
        ),
    }


def _functional_dependencies(train: pd.DataFrame) -> list[tuple[str, str]]:
    """Feature pairs where one is an exact function of the other.

    Only low-cardinality determinants are tested - the check is a groupby per
    pair, and a continuous determinant would trivially "determine" everything
    without that meaning anything. The one continuous case in the contract is
    known by construction (`hdd_15` from the daily mean temperature) and is
    checked explicitly.
    """
    found: list[tuple[str, str]] = []

    candidates = [
        c
        for c in FEATURES
        if c in train.columns and train[c].nunique(dropna=True) <= config.PRESELECT_FUNC_DEP_MAX_LEVELS
    ]
    for determinant in candidates:
        base = train[determinant]
        for dependent in candidates:
            if dependent == determinant:
                continue
            if base.nunique(dropna=True) < train[dependent].nunique(dropna=True):
                continue
            counts = train.groupby(determinant, observed=True)[dependent].nunique(dropna=True)
            if len(counts) and int(counts.max()) <= 1:
                found.append((determinant, dependent))

    # Known construction: hdd_15 = max(0, HDD_BASE_C - daily mean temperature).
    # A monotone (clipped) transform of a single column, so for a tree it adds
    # nothing the temperature does not already offer.
    temp = config.daily_name("Temperature_avg_hourly", "mean")
    if config.HDD_COLUMN in train.columns and temp in train.columns:
        both = train[[config.HDD_COLUMN, temp]].dropna()
        if len(both) and np.allclose(
            both[config.HDD_COLUMN], np.maximum(0.0, config.HDD_BASE_C - both[temp])
        ):
            found.append((temp, config.HDD_COLUMN))

    return found


def _correlated_pairs(train: pd.DataFrame) -> list[tuple[str, str, float]]:
    """Strongly correlated feature pairs, for the report only.

    Categoricals are factorised so the pair appears at all; the coefficient is
    then not a meaningful effect size, which is another reason this is reported
    rather than acted upon.
    """
    numeric = pd.DataFrame(index=train.index)
    for col in FEATURES:
        series = train[col]
        if series.dtype.name in ("category", "string", "object"):
            codes = pd.factorize(series)[0].astype("float64")
            numeric[col] = np.where(codes < 0, np.nan, codes)
        else:
            numeric[col] = series.astype("float64")

    corr = numeric.corr().abs()
    threshold = config.PRESELECT_CORR_REPORT
    pairs = [
        (corr.index[i], corr.columns[j], float(corr.iat[i, j]))
        for i in range(len(corr))
        for j in range(i + 1, len(corr))
        if pd.notna(corr.iat[i, j]) and corr.iat[i, j] >= threshold
    ]
    return sorted(pairs, key=lambda x: -x[2])
