"""Assembly of the household-day panel (stage 3).

The guiding rule here is "integrate, don't decide": things get joined and
trimmed, but no domain assumption is made. The single exception is the time
offset of the weather - it belongs to the join, because it expresses itself
more cleanly as a date shift than as a column operation.

Every join is m:1 and must not change the row count. That is asserted after
each step, not hoped for: an unnoticed row multiplication is one of the most
expensive errors in a panel pipeline, because it disguises itself as "more
data".
"""

from __future__ import annotations

import pandas as pd

from utils import checks, config, io
from utils.reporting import Reporter

# Columns of the daily aggregate that enter the panel as a shifted observation.
WEATHER_OBSERVED_COLUMNS = [
    config.daily_name("Temperature_avg_hourly", "mean"),
    config.daily_name("Temperature_avg_hourly", "min"),
    config.daily_name("Temperature_avg_hourly", "max"),
    config.daily_name("DewPoint_hourly", "mean"),
    config.daily_name("Humidity_avg_hourly", "mean"),
    config.daily_name("WindSpeed_hourly", "mean"),
    config.daily_name("WindSpeed_hourly", "max"),
    config.daily_name(config.WEATHER_PRESSURE_KEEP, "mean"),
    config.daily_name("Precipitation_total_hourly", "sum"),
    config.daily_name("Sunshine_duration_hourly", "sum"),
    config.HDD_COLUMN,
]

# Station properties are time-invariant. They are joined on Weather_ID, not on
# (Weather_ID, date): a date-dependent join would leave NaN wherever no
# shifted weather row exists and would turn a clear bool into a three-valued
# field.
WEATHER_STATIC_COLUMNS = ["station_has_sunshine", "station_has_pressure"]

WEATHER_ROLLING_WINDOWS = [7]
WEATHER_ROLLING_COLUMNS = [
    config.HDD_COLUMN,
    config.daily_name("Temperature_avg_hourly", "mean"),
]


def weather_panel_columns() -> list[str]:
    """All weather columns the panel carries as an observation from d-FORECAST_LAG.

    This list is the registry for the leakage proof. It replaces the naming
    convention used before (suffix `_lag2`): the columns now carry the name of
    the daily aggregate, because it describes the measured quantity more
    precisely. That means the shift can no longer be read off the name -
    instead it is proven in `prove_leakage_free` for *every* column of this
    list against an independent self-join, with a counter-check against the
    target-day value. That is the stronger test: a wrong shift is caught, a
    wrong name at most is.
    """
    rolling = [
        f"{col}_roll{window}_mean"
        for col in WEATHER_ROLLING_COLUMNS
        for window in WEATHER_ROLLING_WINDOWS
    ]
    return WEATHER_OBSERVED_COLUMNS + rolling


def build_lagged_weather(rep: Reporter, daily: pd.DataFrame) -> pd.DataFrame:
    """Re-date the daily aggregate forward by FORECAST_LAG days.

    Instead of shifting the weather columns per household after the join, the
    weather itself is re-dated: the observation from day D receives the label
    D + FORECAST_LAG. A join on `date` then yields exactly the observation from
    d - FORECAST_LAG for every target day.

    This is not only more elegant, it also loses less data: a household whose
    series starts in the middle of the weather period gets real weather values
    for its first days too - a `groupby(...).shift(2)` on the panel would
    produce NaN there even though the measurement exists.
    """
    rep.step("Date the weather to the forecasting point in time")

    work = daily.sort_values(["Weather_ID", "date"]).copy()

    # Rolling weather statistics are computed on the unshifted station series
    # and shifted along afterwards. That way the window also ends at
    # d - FORECAST_LAG and contains no information from after that.
    rolling_cols: list[str] = []
    grouped = work.groupby("Weather_ID", observed=True)
    for col in WEATHER_ROLLING_COLUMNS:
        for window in WEATHER_ROLLING_WINDOWS:
            name = f"{col}_roll{window}_mean"
            work[name] = grouped[col].transform(
                lambda s, w=window: s.rolling(w, min_periods=max(w // 2, 1)).mean()
            )
            rolling_cols.append(name)

    value_cols = WEATHER_OBSERVED_COLUMNS + rolling_cols
    lagged = work[["Weather_ID", "date"] + value_cols].copy()
    lagged["date"] = lagged["date"] + io.days(config.FORECAST_LAG)

    rep.metric("Weather daily rows", len(lagged))
    rep.metric("Shifted weather columns", len(value_cols))
    rep.metric("of which rolling statistics", len(rolling_cols))
    rep.metric("Shift", config.FORECAST_LAG, "days")
    rep.metric("Valid for target days from", str(lagged["date"].min().date()))
    rep.metric("Valid for target days to", str(lagged["date"].max().date()))
    rep.note(
        f"The weather columns keep the name of their daily aggregate and contain the "
        f"observation from d-{config.FORECAST_LAG}. The shift is therefore no longer readable "
        "from the name - it is proven in prove_leakage_free for each column individually "
        "against an independent self-join, including a counter-check against the target-day value"
    )
    rep.note(
        "No target-day weather is carried along: only observed values enter, no forecast. "
        "A perfect-forecast assumption is not made"
    )
    return lagged


def build_station_flags(daily: pd.DataFrame) -> pd.DataFrame:
    """Time-invariant station properties, one row per station."""
    return (
        daily.groupby("Weather_ID", observed=True)[WEATHER_STATIC_COLUMNS].first().reset_index()
    )


def merge_panel(
    rep: Reporter, panel: pd.DataFrame, households: pd.DataFrame, lagged_weather: pd.DataFrame,
    station_flags: pd.DataFrame,
) -> pd.DataFrame:
    rep.step("Assemble the panel")

    n_before = len(panel)

    # Master data. The quality and reporting columns stay out: they describe
    # the household as a whole and would, as a row feature, leak information
    # about the entire period, including the test window.
    static_cols = [c for c in households.columns if c not in _HOUSEHOLD_SUMMARY_COLUMNS]
    panel = panel.merge(households[static_cols], on="Household_ID", how="left", validate="many_to_one")
    ok, detail = checks.no_row_multiplication(n_before, len(panel), "panel x master data")
    rep.check("join with the master data multiplies no rows", ok, detail)
    rep.note(
        "Household-wide metrics (n_days, target_missing_rate, ...) are deliberately NOT "
        "joined into the panel - they are computed over the entire period and would carry "
        "information from the test window into the training rows"
    )

    n_before = len(panel)
    panel = panel.merge(lagged_weather, on=["Weather_ID", "date"], how="left", validate="many_to_one")
    ok, detail = checks.no_row_multiplication(n_before, len(panel), "panel x shifted weather")
    rep.check("join with the weather multiplies no rows", ok, detail)

    n_before = len(panel)
    panel = panel.merge(station_flags, on="Weather_ID", how="left", validate="many_to_one")
    ok, detail = checks.no_row_multiplication(n_before, len(panel), "panel x station properties")
    rep.check("join with the station properties multiplies no rows", ok, detail)
    for col in WEATHER_STATIC_COLUMNS:
        rep.check(
            f"{col} populated on all rows",
            int(panel[col].isna().sum()) == 0,
            f"{int(panel[col].isna().sum())} rows without a value",
        )
        panel[col] = panel[col].astype("bool")

    ok, detail = checks.unique_keys(panel, ["Household_ID", "date"])
    rep.check("(Household_ID, date) unique after the joins", ok, detail)

    rep.metric("Panel rows", len(panel))
    rep.metric("Panel columns", panel.shape[1])
    rep.raise_on_failures()
    return panel


def trim_to_window(rep: Reporter, panel: pd.DataFrame) -> pd.DataFrame:
    """Trim the panel to the period with available shifted weather.

    Can be switched off via `config.TRIM_TO_WEATHER_WINDOW`. With the switch
    off the full metering period is kept: the rows outside the weather window
    keep their target value and carry NaN in every weather column. They
    therefore drop out of any weather-based model through `is_modelable` while
    staying available to a purely autoregressive one. What changes is not the
    data situation but where the decision is made - in modeling instead of here.
    """
    rep.step("Trim the panel to the usable time window")

    lo = pd.Timestamp(config.PANEL_DATE_MIN)
    hi = pd.Timestamp(config.PANEL_DATE_MAX)

    n_before = len(panel)
    hh_before = panel["Household_ID"].nunique()
    target_before = int(panel[config.TARGET_COL].notna().sum())
    outside = (panel["date"] < lo) | (panel["date"] > hi)

    rep.metric("Trim active", "yes" if config.TRIM_TO_WEATHER_WINDOW else "no")

    if not config.TRIM_TO_WEATHER_WINDOW:
        return _keep_full_period(rep, panel, lo, hi, outside)

    out = panel[~outside].reset_index(drop=True)

    rep.metric("Window from", str(lo.date()))
    rep.metric("Window to", str(hi.date()))
    rep.metric("Rows before", n_before)
    rep.metric("Rows after", len(out))
    rep.metric("Discarded rows", n_before - len(out))
    rep.metric("of which with a target value", target_before - int(out[config.TARGET_COL].notna().sum()))
    rep.metric("Households before", hh_before)
    rep.metric("Households after", out["Household_ID"].nunique())
    rep.metric("Households affected", int(panel.loc[outside, "Household_ID"].nunique()))

    lost = set(panel["Household_ID"]) - set(out["Household_ID"])
    if lost:
        rep.note(f"Households without rows inside the window: {sorted(lost)}")

    rep.note(
        f"The window is the weather window ({config.WEATHER_DATE_MIN} to "
        f"{config.WEATHER_DATE_MAX}) moved back by {config.FORECAST_LAG} day(s), because "
        f"every target day needs the observation from d-{config.FORECAST_LAG}"
    )

    rep.check(
        "no date outside the window",
        bool(out["date"].between(lo, hi).all()),
        "",
    )
    # After the trim the daily grid per household must still be gapless -
    # otherwise the lag features would later reach into the wrong row.
    ok, detail = checks.daily_calendar_complete(out)
    rep.check("daily grid still gapless after the trim", ok, detail)

    rep.raise_on_failures()
    return out


def _keep_full_period(
    rep: Reporter, panel: pd.DataFrame, lo: pd.Timestamp, hi: pd.Timestamp, outside: pd.Series
) -> pd.DataFrame:
    """Report the weather window without cutting anything away.

    The rows outside the window are not a defect - they are metered days for
    which no weather exists. Reporting them here keeps the cost of the switch
    visible instead of letting it disappear into an unexplained NaN block
    further downstream.
    """
    n_outside = int(outside.sum())
    weather_key = config.daily_name("Temperature_avg_hourly", "mean")

    rep.metric("Weather window from", str(lo.date()))
    rep.metric("Weather window to", str(hi.date()))
    rep.metric("Panel from", str(panel["date"].min().date()))
    rep.metric("Panel to", str(panel["date"].max().date()))
    rep.metric("Rows (unchanged)", len(panel))
    rep.metric("Rows outside the weather window", n_outside)
    rep.metric(
        "of which with a target value",
        int((outside & panel[config.TARGET_COL].notna()).sum()),
    )
    rep.metric("Households affected", int(panel.loc[outside, "Household_ID"].nunique()))
    rep.metric("Rows without weather", int(panel[weather_key].isna().sum()))

    rep.note(
        f"The trim is switched off via config.TRIM_TO_WEATHER_WINDOW: the panel keeps the "
        f"full metering period. The {n_outside} rows outside the weather window "
        f"({config.WEATHER_DATE_MIN} to {config.WEATHER_DATE_MAX}, moved back by "
        f"{config.FORECAST_LAG} day(s)) keep their target value but carry NaN in every "
        "weather column"
    )
    rep.note(
        "Consequence: those rows are unusable for weather-based models and are excluded "
        "through is_modelable. A purely autoregressive model can still use them - that is "
        "the point of the switch"
    )

    # Every row outside the window must be free of weather, every row inside
    # must have it wherever the station measured. The first half is the one
    # that matters here: it proves no weather value leaked past the window.
    leaked = int(panel.loc[outside, weather_key].notna().sum())
    rep.check(
        "no weather value outside the weather window",
        leaked == 0,
        f"{leaked} rows outside the window carry a temperature value",
    )
    ok, detail = checks.daily_calendar_complete(panel)
    rep.check("daily grid gapless", ok, detail)

    rep.raise_on_failures()
    return panel.reset_index(drop=True)


# Household-wide metrics: useful for the report and for grouping, but not a
# row feature (they are aggregated over the entire period).
_HOUSEHOLD_SUMMARY_COLUMNS = {
    "first_date",
    "last_date",
    "n_days",
    "n_target_observed",
    "n_gap_days",
    "max_gap_days",
    "n_spikes",
    "n_returned_observed",
    "target_mean",
    "target_max",
    "target_missing_rate",
    "returned_coverage",
    "visit_date",
    "Protocols_Available",
    "Protocols_HasMultipleVisits",
    "Protocols_ReportIDs",
    "MetaData_Available",
    "SmartMeterData_Available_15min",
    "SmartMeterData_Available_Daily",
    "SmartMeterData_Available_Monthly",
    "Group",
}
