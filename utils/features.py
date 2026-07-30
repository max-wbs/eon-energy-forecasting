"""Feature engineering (stage 3) - the place of the deliberate assumptions.

This is where the leakage firewall lives. The principle:

    A feature for target day d may only contain what is known at the moment
    the bid is placed - at the end of day d-1.

For every group of quantities that implies:

* **autoregressive** (history of the target variable): shift by at least
  FORECAST_LAG = 1 day. Day d-1 is fully metered when the bid is placed, the
  target day d of course is not.
* **weather**: likewise d-1, as an *observation*, not as a forecast. The shift
  already happens at the join (see `utils/merge.py`).
* **calendar**: unshifted. The weekday and holiday status of the target day
  are in the calendar, they do not have to be forecast.
* **static and regime**: unshifted. Building attributes and the intervention
  status are known at bidding time.

All rolling statistics follow the *shift-before-rolling* pattern: shift first,
then place the window. The reverse order would pull the target day into the
window.

Which of the columns built here the model actually sees is decided by
`utils/feature_selection.py` - this module builds, it does not select.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from utils import config, feature_selection
from utils.feature_selection import TARGET_PREFIX
from utils.reporting import Reporter

__all__ = ["TARGET_PREFIX", "add_autoregressive", "add_calendar", "build"]

# Meteorological seasons (month -> label).
_SEASON_BY_MONTH = {
    12: "winter", 1: "winter", 2: "winter",
    3: "spring", 4: "spring", 5: "spring",
    6: "summer", 7: "summer", 8: "summer",
    9: "autumn", 10: "autumn", 11: "autumn",
}


def add_autoregressive(rep: Reporter, panel: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Lags and rolling statistics of the target variable, per household.

    Active *and* reserve horizons are built. The selection happens later in
    `feature_selection` - here we only compute, so that changing the selection
    does not require a new pipeline run.
    """
    rep.step("Autoregressive features (leakage firewall)")

    panel = panel.sort_values(["Household_ID", "date"]).reset_index(drop=True)
    grouped = panel.groupby("Household_ID", observed=True)[config.TARGET_COL]

    all_lags = sorted(set(config.TARGET_LAGS) | set(config.TARGET_LAGS_RESERVE))
    all_windows = sorted(set(config.ROLLING_WINDOWS) | set(config.ROLLING_WINDOWS_RESERVE))

    created: list[str] = []
    for lag in all_lags:
        name = f"{TARGET_PREFIX}_lag{lag}"
        panel[name] = grouped.shift(lag)
        created.append(name)

    # shift-before-rolling: the window ends at d - FORECAST_LAG.
    shifted = grouped.shift(config.FORECAST_LAG)
    by_household = shifted.groupby(panel["Household_ID"], observed=True)
    for window in all_windows:
        min_periods = config.ROLLING_MIN_PERIODS[window]
        for stat in ("mean", "std"):
            name = f"{TARGET_PREFIX}_roll{window}_{stat}"
            panel[name] = by_household.transform(
                lambda s, w=window, mp=min_periods, st=stat: getattr(
                    s.rolling(w, min_periods=mp), st
                )()
            )
            created.append(name)

    rep.metric("Lag columns", len(all_lags))
    rep.metric("Rolling columns", len(created) - len(all_lags))
    rep.metric("Active lags", ", ".join(f"d-{lag}" for lag in config.TARGET_LAGS))
    rep.metric("Smallest lag used", min(config.TARGET_LAGS), "days")
    rep.metric("Shift before the rolling", config.FORECAST_LAG, "days")
    for window in config.ROLLING_WINDOWS:
        rep.metric(
            f"min_periods in the {window}-day window", config.ROLLING_MIN_PERIODS[window]
        )

    # How many rows are unusable because of the edges? The longest *active*
    # lag determines how many days stay empty at the start of each household
    # series.
    max_lag = max(config.TARGET_LAGS)
    n_no_full_lags = int(panel[f"{TARGET_PREFIX}_lag{max_lag}"].isna().sum())
    rep.metric(f"Rows without a lag-{max_lag} value (edges and gaps)", n_no_full_lags)
    rep.metric(
        f"Rows without a lag-{config.FORECAST_LAG} value",
        int(panel[f"{TARGET_PREFIX}_lag{config.FORECAST_LAG}"].isna().sum()),
    )
    rep.note(
        "Edges stay NaN: no backfill (would be leakage), no forward fill (would be "
        "invented). Filtering these rows is left to the modeling stage so that the panel "
        "keeps its complete calendar structure"
    )
    rep.note(
        "After a calendar gap the lags are NaN as well, because the target value is missing "
        "in the gap rows - exactly the desired behaviour"
    )
    return panel, created


def add_calendar(rep: Reporter, panel: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Calendar features of the target day - unshifted, because deterministically known."""
    rep.step("Calendar features")

    import holidays

    dates = panel["date"]
    panel["dow"] = dates.dt.dayofweek.astype("int8")
    panel["month"] = dates.dt.month.astype("int8")
    panel["season"] = dates.dt.month.map(_SEASON_BY_MONTH).astype("category")
    panel["is_weekend"] = (dates.dt.dayofweek >= 5).astype("bool")

    years = range(int(dates.dt.year.min()), int(dates.dt.year.max()) + 1)
    german_holidays = holidays.Germany(years=list(years))
    panel["is_holiday"] = dates.dt.date.map(lambda d: d in german_holidays).astype("bool")

    # Cyclic encoding of the day of year: New Year's Eve and New Year's Day
    # end up next to each other, whereas a raw day number would jump from 365
    # to 1 there.
    doy = dates.dt.dayofyear
    days_in_year = np.where(dates.dt.is_leap_year, 366.0, 365.0)
    panel["doy_sin"] = np.sin(2 * np.pi * doy / days_in_year)
    panel["doy_cos"] = np.cos(2 * np.pi * doy / days_in_year)

    created = ["dow", "month", "season", "is_weekend", "is_holiday", "doy_sin", "doy_cos"]

    rep.metric("Calendar columns", len(created))
    rep.metric("Holidays in the panel", int(panel["is_holiday"].sum()))
    rep.metric("Distinct holiday dates", int(dates[panel["is_holiday"]].dt.date.nunique()))
    rep.metric("Weekend rows", int(panel["is_weekend"].sum()))
    rep.note(
        "Holidays taken nationally (holidays.Germany without subdiv). The household "
        "locations are only known through anonymised weather stations, a federal state "
        "cannot be assigned - state-specific holidays would be guesswork"
    )
    rep.note(
        "Day length was deliberately left out: at a fixed latitude it is a deterministic "
        "function of the day of year and therefore already covered by doy_sin/doy_cos; "
        "computing it would require a latitude assumption the data does not support"
    )
    return panel, created


def build(
    rep: Reporter, panel: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, list[str]], dict[str, list[str]]]:
    """Build all feature columns and make the selection.

    Returns (panel, active groups, reserve groups).
    """
    panel, _ = add_autoregressive(rep, panel)
    panel, _ = add_calendar(rep, panel)
    groups, deselected = feature_selection.verify(rep, panel)
    return panel, groups, deselected
