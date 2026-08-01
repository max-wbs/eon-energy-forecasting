"""Cleaning of the smart meter daily data (stage 2).

The guiding rule is "flag, don't repair": apart from one clearly justifiable
substitution, no measurement is altered. What stands out is flagged and passed
on - the decision about it is made later in the modeling stage, where it can be
made on the training split.

The order of the steps is not arbitrary:

1. Outliers are determined **before** the reindex so that the inserted gap
   rows do not dilute the robust statistics (median, MAD).
2. The visit date is read from the observed rows **before** the reindex, the
   regime features are computed **afterwards** - that way gap rows also get a
   correct regime state.
"""

from __future__ import annotations

import pandas as pd

from utils import checks, config
from utils.reporting import Reporter

_OBSERVED_MARKER = "_observed"


# --------------------------------------------------------------------------
# Outliers
# --------------------------------------------------------------------------


def flag_spikes(rep: Reporter, df: pd.DataFrame) -> pd.DataFrame:
    """Robust outlier marker per household: median + k * MAD.

    Median and MAD are insensitive to exactly the extreme values we want to
    find here - unlike mean and standard deviation, which would be dragged
    along by a single spike.
    """
    rep.step("Flag outliers")

    target = df[config.TARGET_COL]
    grouped = df.groupby("Household_ID", observed=True)[config.TARGET_COL]
    median = grouped.transform("median")
    mad = grouped.transform(lambda s: (s - s.median()).abs().median())

    # MAD == 0 means the series is (almost) constant. Any deviation would then
    # count as an outlier - nothing is flagged in that case.
    threshold = median + config.SPIKE_MAD_K * mad
    df = df.copy()
    df["kWh_spike_flag"] = (mad > 0) & target.notna() & (target > threshold)

    n_flagged = int(df["kWh_spike_flag"].sum())
    rep.metric("Flagged as outliers", n_flagged)
    rep.metric("Households affected", int(df.loc[df["kWh_spike_flag"], "Household_ID"].nunique()))
    rep.metric("Share of observed rows", 100 * n_flagged / max(int(target.notna().sum()), 1), "%")
    rep.note(
        f"Threshold: median + {config.SPIKE_MAD_K:g} x MAD per household. "
        "The values stay unchanged, only the marker is passed on"
    )
    return df


# --------------------------------------------------------------------------
# Feed-in
# --------------------------------------------------------------------------


def substitute_returned(rep: Reporter, df: pd.DataFrame) -> pd.DataFrame:
    """Separate structural empty cells in `kWh_returned_Total` from real gaps.

    A household without any positive feed-in structurally does not feed in -
    its empty cells mean "no feed-in", not "measurement missing". For active
    feeders, by contrast, an empty cell is a genuine measurement gap and stays
    NaN. Without this distinction the two cases could not be told apart later.
    """
    rep.step("Feed-in: separate structural empty cells from measurement gaps")

    df = df.copy()
    positive = df["kWh_returned_Total"].fillna(0) > 0
    feeds_in = positive.groupby(df["Household_ID"], observed=True).transform("any")

    substitute = ~feeds_in & df["kWh_returned_Total"].isna()
    df["returned_was_substituted"] = substitute
    df.loc[substitute, "kWh_returned_Total"] = 0.0

    n_active = int(df.loc[feeds_in, "Household_ID"].nunique())
    rep.metric("Households with positive feed-in", n_active)
    rep.metric("Households without any feed-in", int(df["Household_ID"].nunique() - n_active))
    rep.metric("Substituted cells (set to 0.0)", int(substitute.sum()))
    rep.metric(
        "Remaining genuine measurement gaps", int(df["kWh_returned_Total"].isna().sum())
    )
    rep.note(
        "Active feeders keep their NaN - there an empty cell is a measurement gap, "
        "not a zero value"
    )
    return df


def cross_check_pv_flag(rep: Reporter, df: pd.DataFrame, households: pd.DataFrame) -> pd.DataFrame:
    """Check the feed-in evidence against the PV flag in the master data.

    Both directions are interesting: a household with a PV flag but without
    feed-in (measurement gap, or system installed after the metering period)
    and a household without a PV flag that feeds in nonetheless (wrong flag).
    """
    rep.step("Check the PV flag against the feed-in evidence")

    evidence = (
        df.assign(pos=df["kWh_returned_Total"].fillna(0) > 0)
        .groupby("Household_ID", observed=True)["pos"]
        .agg(feeds_in="any", evidence_days="size")
    )
    merged = households.merge(evidence, left_on="Household_ID", right_index=True, how="left")
    merged["feeds_in"] = merged["feeds_in"].fillna(False)
    merged["evidence_days"] = merged["evidence_days"].fillna(0).astype("int64")

    flag = merged["Installation_HasPVSystem"]
    flagged_no_feed = merged[(flag == True) & ~merged["feeds_in"]]  # noqa: E712
    feed_no_flag = merged[(flag == False) & merged["feeds_in"]]  # noqa: E712
    unknown = merged[flag.isna()]

    rep.metric("PV flag True and feed-in evidenced", int(((flag == True) & merged["feeds_in"]).sum()))  # noqa: E712
    rep.metric("PV flag True, but no feed-in", len(flagged_no_feed))
    rep.metric("PV flag False, but feed-in evidenced", len(feed_no_flag))

    if len(flagged_no_feed):
        rep.note(
            "PV according to the master data, without feed-in in the data: "
            + ", ".join(flagged_no_feed["Household_ID"].tolist())
            + " - possibly a measurement gap or a system installed after the metering period"
        )
    rep.check(
        "no household feeds in without being listed as a PV owner",
        len(feed_no_flag) == 0,
        ", ".join(feed_no_flag["Household_ID"].tolist()) if len(feed_no_flag) else "",
        hard=False,
    )

    # The one unknown PV flag can be resolved via the feed-in: a household
    # that never feeds in almost certainly has no system. The resolution is
    # logged and marked as derived, not entered silently.
    resolved = merged.copy()
    resolved["pv_flag_imputed"] = False
    for _, row in unknown.iterrows():
        inferred = bool(row["feeds_in"])
        mask = resolved["Household_ID"] == row["Household_ID"]
        resolved.loc[mask, "Installation_HasPVSystem"] = inferred
        resolved.loc[mask, "pv_flag_imputed"] = True
        rep.note(
            f"PV status of household {row['Household_ID']} was unknown and is set to "
            f"{inferred} based on the feed-in evidence over {int(row['evidence_days'])} "
            "metered days (flag: pv_flag_imputed)"
        )

    return resolved.drop(columns=["feeds_in", "evidence_days"])


# --------------------------------------------------------------------------
# Calendar
# --------------------------------------------------------------------------


def reindex_calendar(rep: Reporter, df: pd.DataFrame) -> pd.DataFrame:
    """Reindex every household onto its own daily span.

    The reindex runs from `first_date` to `last_date` of the respective
    household, not onto a fleet-wide calendar - otherwise rows would appear
    for periods in which the meter demonstrably was not running.

    The inserted rows serve the correctness of `shift` and `rolling`, not
    filling: the target value stays NaN and the row carries `is_gap`.
    """
    rep.step("Make the calendar gapless per household")

    before_rows = len(df)
    work = df.copy()
    work[_OBSERVED_MARKER] = True

    frames = []
    for hid, group in work.groupby("Household_ID", observed=True, sort=True):
        group = group.sort_values("date").set_index("date")
        full_range = pd.date_range(group.index.min(), group.index.max(), freq="D", name="date")
        reindexed = group.reindex(full_range)
        reindexed["Household_ID"] = hid
        frames.append(reindexed.reset_index())

    out = pd.concat(frames, ignore_index=True)
    out["is_gap"] = out[_OBSERVED_MARKER].isna()
    out = out.drop(columns=[_OBSERVED_MARKER])

    # The reindex turns 'string' and 'boolean' into 'object' in places - the
    # dtypes are restored explicitly so that the parquet round-trip check does
    # not fire.
    out["Household_ID"] = out["Household_ID"].astype("string")
    for col in ("Group", "AffectsTimePoint"):
        out[col] = out[col].astype("string")
    # Flags on the inserted rows are False by definition. `where` instead of
    # `fillna`, because fillna silently downcasts object columns.
    for col in ("kWh_spike_flag", "returned_was_substituted"):
        if col in out:
            out[col] = out[col].where(out[col].notna(), False).astype("bool")

    n_gap = int(out["is_gap"].sum())
    rep.metric("Rows before", before_rows)
    rep.metric("Inserted gap rows", n_gap)
    rep.metric("Rows after", len(out))
    rep.metric("Households with gaps", int(out.loc[out["is_gap"], "Household_ID"].nunique()))

    gap_sizes = (
        out[out["is_gap"]].groupby("Household_ID", observed=True).size().sort_values(ascending=False)
    )
    if len(gap_sizes):
        rep.metric("Largest gap total per household", int(gap_sizes.iloc[0]), "days")
        rep.note(
            "Households with the most gap days: "
            + ", ".join(f"{hid} ({int(n)})" for hid, n in gap_sizes.head(5).items())
        )

    rep.check(
        "households with gaps as documented",
        int(out.loc[out["is_gap"], "Household_ID"].nunique()) == config.EXPECTED["households_with_gaps"],
        f"{int(out.loc[out['is_gap'], 'Household_ID'].nunique())} households "
        f"({config.EXPECTED['households_with_gaps_raw']} in the raw data, two of them removed)",
        hard=False,
    )
    rep.note("The target value in gap rows stays NaN - the rows establish the grid, they do not fill it")
    return out


# --------------------------------------------------------------------------
# Regime features
# --------------------------------------------------------------------------


def derive_visit_features(rep: Reporter, df: pd.DataFrame) -> pd.DataFrame:
    """Derive the visit date and regime state from AffectsTimePoint.

    `during visit` marks the visit day itself and occurs exactly once per
    household. Only for those households is a visit date known; households
    with `after visit` only had their visit before recording started, and for
    those with `before visit` only it falls outside the data window.

    `days_since_visit` stays NaN without a known visit date - a zero would be
    an invention.
    """
    rep.step("Derive regime features from the visit state")

    df = df.sort_values(["Household_ID", "date"]).reset_index(drop=True)

    visit_dates = (
        df.loc[df["AffectsTimePoint"] == config.VISIT_DURING]
        .groupby("Household_ID", observed=True)["date"]
        .min()
    )
    df["visit_date"] = df["Household_ID"].map(visit_dates)
    df["is_visit_day"] = df["AffectsTimePoint"] == config.VISIT_DURING

    # Gap rows have no state of their own. Since the progression per household
    # is monotone (proven in stage 1), a forward fill carries the last known
    # state forward correctly. This is not the imputation of a measurement but
    # the continuation of an intervention status.
    state = df.groupby("Household_ID", observed=True)["AffectsTimePoint"].ffill()
    n_filled = int(df["AffectsTimePoint"].isna().sum() - state.isna().sum())

    df["is_post_visit"] = (
        state.map(
            {
                config.VISIT_BEFORE: False,
                config.VISIT_DURING: False,
                config.VISIT_AFTER: True,
                config.VISIT_UNKNOWN: pd.NA,
            }
        )
        .astype("boolean")
    )

    delta = (df["date"] - df["visit_date"]).dt.days
    df["days_since_visit"] = delta.astype("Float64")

    rep.metric("Households with a known visit date", int(visit_dates.size))
    rep.metric("Households without a known visit date", int(df["Household_ID"].nunique() - visit_dates.size))
    rep.metric("Rows in state 'after visit'", int((df["is_post_visit"] == True).sum()))  # noqa: E712
    rep.metric("Rows in state 'before visit'", int((df["is_post_visit"] == False).sum()))  # noqa: E712
    rep.metric("Rows with an unknown state", int(df["is_post_visit"].isna().sum()))
    rep.metric("Gap rows with a carried-forward state", n_filled)

    rep.check(
        "visit day at most once per household",
        bool(df.groupby("Household_ID", observed=True)["is_visit_day"].sum().le(1).all()),
        "",
    )
    rep.check(
        "households with a known visit date as documented",
        int(visit_dates.size) == config.EXPECTED["households_with_visit_date"],
        f"{int(visit_dates.size)} households "
        f"({config.EXPECTED['households_with_visit_date_raw']} in the raw data, one of them removed)",
        hard=False,
    )
    rep.check(
        "days_since_visit set only where the visit date is known",
        bool(df.loc[df["visit_date"].isna(), "days_since_visit"].isna().all()),
        "",
    )
    rep.note(
        "days_since_visit stays NaN where the visit date is unknown; "
        "is_post_visit is three-valued so that the state 'unknown' does not become 'before visit'"
    )

    return df.drop(columns=["AffectsTimePoint", "Group"])


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def validate(rep: Reporter, df: pd.DataFrame) -> None:
    rep.step("Validate the smart meter data")

    ok, detail = checks.unique_keys(df, ["Household_ID", "date"])
    rep.check("(Household_ID, date) unique", ok, detail)

    ok, detail = checks.daily_calendar_complete(df)
    rep.check("daily grid gapless (precondition for all shift features)", ok, detail)

    ok, detail = checks.non_negative(df, config.SMART_METER_VALUE_COLUMNS)
    rep.check("no negative measurements", ok, detail)

    ok, detail = checks.submeter_consistency(df)
    rep.check("total equals HeatPump + Other where submetering exists", ok, detail, hard=False)

    n_submeter = int(df.loc[df["kWh_received_HeatPump"].notna(), "Household_ID"].nunique())
    rep.metric("Households with heat-pump submetering", n_submeter)
    rep.check(
        "submetering coverage as documented",
        n_submeter == config.EXPECTED["households_with_submeter"],
        f"{n_submeter} households ({config.EXPECTED['households_with_submeter_raw']} in the raw data - "
        "the three removed households meter the heat pump only)",
        hard=False,
    )

    n_missing_target = int(df[config.TARGET_COL].isna().sum())
    rep.metric("Rows without a target value (incl. gaps)", n_missing_target)
    rep.metric(
        "Rows with a target value", int(df[config.TARGET_COL].notna().sum())
    )
    rep.raise_on_failures()


# --------------------------------------------------------------------------
# Household quality statistics
# --------------------------------------------------------------------------


def household_quality_stats(df: pd.DataFrame) -> pd.DataFrame:
    """One row per household with coverage and quality metrics.

    This table is appended to the master data and doubles as the data
    inventory for the report.
    """
    grouped = df.groupby("Household_ID", observed=True)

    stats = pd.DataFrame(
        {
            "first_date": grouped["date"].min(),
            "last_date": grouped["date"].max(),
            "n_days": grouped.size(),
            "n_target_observed": grouped[config.TARGET_COL].count(),
            "n_gap_days": grouped["is_gap"].sum(),
            "n_spikes": grouped["kWh_spike_flag"].sum(),
            "target_mean": grouped[config.TARGET_COL].mean(),
            "target_max": grouped[config.TARGET_COL].max(),
            "n_returned_observed": grouped["kWh_returned_Total"].count(),
            "has_heatpump_submeter": grouped["kWh_received_HeatPump"].count() > 0,
            "visit_date": grouped["visit_date"].first(),
        }
    )

    stats["target_missing_rate"] = 1 - stats["n_target_observed"] / stats["n_days"]
    stats["returned_coverage"] = stats["n_returned_observed"] / stats["n_days"]

    # Longest contiguous gap per household - more informative than the sum of
    # gap days, because it shows whether lag features can connect at all.
    longest_gap = {}
    for hid, group in df.sort_values("date").groupby("Household_ID", observed=True):
        runs = (group["is_gap"] != group["is_gap"].shift()).cumsum()
        gap_runs = group[group["is_gap"]].groupby(runs).size()
        longest_gap[hid] = int(gap_runs.max()) if len(gap_runs) else 0
    stats["max_gap_days"] = pd.Series(longest_gap)

    return stats.reset_index()


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def clean(rep: Reporter, df: pd.DataFrame, households: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Complete smart meter cleaning. Returns (panel, master data)."""
    df = flag_spikes(rep, df)
    df = substitute_returned(rep, df)
    households = cross_check_pv_flag(rep, df, households)
    df = reindex_calendar(rep, df)
    df = derive_visit_features(rep, df)
    validate(rep, df)

    rep.step("Extend the master data with quality metrics")
    stats = household_quality_stats(df)
    before = len(households)
    households = households.merge(stats, on="Household_ID", how="left", validate="one_to_one")
    ok, detail = checks.no_row_multiplication(before, len(households), "master data x quality statistics")
    rep.check("enrichment multiplies no rows", ok, detail)

    rep.metric("Median days per household", int(households["n_days"].median()))
    rep.metric("Households with fewer than 365 days", int((households["n_days"] < 365).sum()))
    rep.metric("Longest single gap across all households", int(households["max_gap_days"].max()), "days")
    rep.metric(
        "Mean missing rate of the target value",
        float(100 * households["target_missing_rate"].mean()),
        "%",
    )

    # numpy bools from the aggregations would land as object in the parquet
    # round trip - convert them to pandas dtypes explicitly here.
    households["has_heatpump_submeter"] = households["has_heatpump_submeter"].astype("bool")
    for col in ("n_days", "n_target_observed", "n_gap_days", "n_spikes", "n_returned_observed", "max_gap_days"):
        households[col] = households[col].astype("int64")

    rep.raise_on_failures()
    return df, households
