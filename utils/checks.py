"""Reusable sanity-check predicates.

Every function returns `(ok, detail)` and changes nothing in the data. The
severity - hard or soft - is decided by the caller, because the same check
carries different weight depending on context: a calendar gap is an
observation in the raw data and an error after the reindex.
"""

from __future__ import annotations

import pandas as pd

from utils import config


def unique_keys(df: pd.DataFrame, keys: list[str]) -> tuple[bool, str]:
    n_dupes = int(df.duplicated(subset=keys).sum())
    if n_dupes == 0:
        return True, ""
    sample = df[df.duplicated(subset=keys, keep=False)][keys].head(3).to_dict("records")
    return False, f"{n_dupes} duplicates, e.g. {sample}"


def daily_calendar_complete(df: pd.DataFrame, group_col: str = "Household_ID") -> tuple[bool, str]:
    """Checks per group that consecutive days are exactly one day apart.

    This is the precondition for every `shift(k)`: only on a gapless daily
    grid does the row k positions back correspond to day d-k.
    """
    offenders: list[str] = []
    for key, group in df.sort_values([group_col, "date"]).groupby(group_col, observed=True):
        diffs = group["date"].diff().dropna().dt.days
        if len(diffs) and not (diffs == 1).all():
            worst = int(diffs.max())
            offenders.append(f"{key} (max {worst} days)")
    if not offenders:
        return True, f"{df[group_col].nunique()} groups gapless"
    return False, f"{len(offenders)} groups with gaps: {offenders[:5]}"


def hourly_grid_complete(df: pd.DataFrame, group_col: str = "Weather_ID") -> tuple[bool, str]:
    offenders: list[str] = []
    for key, group in df.sort_values([group_col, "Timestamp"]).groupby(group_col, observed=True):
        diffs = group["Timestamp"].diff().dropna()
        if len(diffs) and not (diffs == pd.Timedelta(hours=1)).all():
            offenders.append(str(key))
    if not offenders:
        return True, f"{df[group_col].nunique()} stations gapless hourly"
    return False, f"gaps at: {offenders}"


def non_negative(df: pd.DataFrame, columns: list[str]) -> tuple[bool, str]:
    """Measurements must not be negative - an upper bound is deliberately not checked."""
    offenders = {c: int((df[c] < 0).sum()) for c in columns if c in df and (df[c] < 0).any()}
    if not offenders:
        return True, f"{len(columns)} columns checked"
    return False, f"negative values: {offenders}"


def within_bounds(df: pd.DataFrame, bounds: dict[str, tuple[float, float]]) -> tuple[bool, str]:
    offenders = {}
    for col, (low, high) in bounds.items():
        if col not in df:
            continue
        bad = int(((df[col] < low) | (df[col] > high)).sum())
        if bad:
            offenders[col] = f"{bad} values outside [{low}, {high}]"
    if not offenders:
        return True, f"{len(bounds)} value ranges checked"
    return False, "; ".join(f"{c}: {d}" for c, d in offenders.items())


def submeter_consistency(df: pd.DataFrame, tolerance: float = 0.5) -> tuple[bool, str]:
    """Where submetering exists: total should equal HeatPump + Other.

    A soft hint only - deviations may come from rounding or from loads that
    no submeter captures.
    """
    mask = df["kWh_received_HeatPump"].notna() & df["kWh_received_Other"].notna()
    if not mask.any():
        return True, "no submetering present"
    subset = df[mask]
    residual = (
        subset["kWh_received_Total"] - subset["kWh_received_HeatPump"] - subset["kWh_received_Other"]
    ).abs()
    n_bad = int((residual > tolerance).sum())
    detail = (
        f"{int(mask.sum())} rows with submetering, "
        f"maximum deviation {residual.max():.2f} kWh, "
        f"{n_bad} rows above the tolerance of {tolerance} kWh"
    )
    return n_bad == 0, detail


def referential_integrity(
    child: pd.Series, parent: pd.Series, child_name: str, parent_name: str
) -> tuple[bool, str]:
    missing = set(child.dropna().unique()) - set(parent.dropna().unique())
    if not missing:
        return True, f"all values from {child_name} present in {parent_name}"
    return False, f"{len(missing)} values from {child_name} missing in {parent_name}: {sorted(missing)[:5]}"


def no_row_multiplication(before: int, after: int, label: str) -> tuple[bool, str]:
    """An m:1 join must not change the row count."""
    return before == after, f"{label}: {before} -> {after} rows"


def lag_matches_shifted_target(
    df: pd.DataFrame, lag_col: str, lag_days: int, n_samples: int = 200, seed: int = 0
) -> tuple[bool, str]:
    """Sample-based proof that a lag column really carries the value of d-k.

    Builds the comparison value independently of the feature logic via a
    self-join on (Household_ID, date - k days). The check is therefore not the
    shifted column talking to itself but a genuine counter-derivation.
    """
    lookup = df[["Household_ID", "date", config.TARGET_COL]].copy()
    lookup["date"] = lookup["date"] + pd.Timedelta(days=lag_days)
    lookup = lookup.rename(columns={config.TARGET_COL: "_expected"})

    candidates = df[df[lag_col].notna()]
    if candidates.empty:
        return False, f"{lag_col} contains not a single value"

    sample = candidates.sample(min(n_samples, len(candidates)), random_state=seed)
    merged = sample.merge(lookup, on=["Household_ID", "date"], how="left")

    mismatch = int((merged[lag_col] - merged["_expected"]).abs().gt(1e-9).sum())
    unmatched = int(merged["_expected"].isna().sum())
    detail = f"{len(merged)} samples, {mismatch} deviations, {unmatched} without a counterpart"
    return mismatch == 0 and unmatched == 0, detail


def first_rows_have_na_lags(df: pd.DataFrame, lag_cols: list[str]) -> tuple[bool, str]:
    """The first row of every household must not carry a lag value.

    Proves that the shift operations run grouped per household and do not
    shift across household boundaries.
    """
    first = df.sort_values(["Household_ID", "date"]).groupby("Household_ID", observed=True).head(1)
    leaked = {c: int(first[c].notna().sum()) for c in lag_cols if c in first and first[c].notna().any()}
    if not leaked:
        return True, f"{len(first)} households, all lag columns empty at the start of the series"
    return False, f"values present at the start of the series: {leaked}"
