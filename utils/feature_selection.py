"""Feature selection (stage 3) - what the model sees and what only comes along.

The panel *computes* more columns than the model *receives*. That separation
is deliberate:

* **active** - listed in the schema under `feature_groups`, the model sees them.
* **reserve** - present in the panel, fully computed and checked, but not
  passed on as a feature.

The reason for a reserve instead of deleting: a later extension then costs one
line in `ACTIVE`, not a new pipeline run. And the comparison "model with meta
data against model without" is possible without any rebuild, because the
columns are physically there.

The active selection is deliberately narrow: 20 features from five groups. It
follows the principle of starting with the smallest set that covers the physics
of the problem - autoregression for the level, temperature and heating degree
days for the demand, calendar for the weekly rhythm. Anything beyond that has
to prove its contribution against this baseline model instead of having it
assumed.

Every non-selection is listed below with a reason. The joint reason for the
meta data: the daily consumption of a heat pump is dominated by temperature
and history; building attributes are time-invariant and can at best shift a
level in the pooled model that `recv_lag1` and `recv_roll7_mean` already
carry. Whether they contribute anything beyond that is an empirical question -
and exactly the one the ablation experiment is meant to answer, not an
assumption made while building features.
"""

from __future__ import annotations

import pandas as pd

from utils import config, merge
from utils.reporting import Reporter

TARGET_PREFIX = "recv"


# --------------------------------------------------------------------------
# Active selection
# --------------------------------------------------------------------------


def _autoregressive() -> list[str]:
    """History of the target variable: lags d-1 and d-7, weekly window."""
    lags = [f"{TARGET_PREFIX}_lag{lag}" for lag in config.TARGET_LAGS]
    rolls = [
        f"{TARGET_PREFIX}_roll{window}_{stat}"
        for window in config.ROLLING_WINDOWS
        for stat in ("mean", "std")
    ]
    return lags + rolls


def _weather() -> list[str]:
    """Weather observation from d-FORECAST_LAG, without pressure and wind maximum."""
    return [
        config.daily_name("Temperature_avg_hourly", "mean"),
        config.daily_name("Temperature_avg_hourly", "min"),
        config.daily_name("Temperature_avg_hourly", "max"),
        config.daily_name("Humidity_avg_hourly", "mean"),
        config.daily_name("WindSpeed_hourly", "mean"),
        config.daily_name("DewPoint_hourly", "mean"),
        config.daily_name("Precipitation_total_hourly", "sum"),
        config.daily_name("Sunshine_duration_hourly", "sum"),
        config.HDD_COLUMN,
    ]


CALENDAR_ACTIVE = ["dow", "month", "season", "is_weekend", "is_holiday"]
REGIME_ACTIVE = ["is_post_visit"]
STATIC_ACTIVE = ["Installation_HasPVSystem"]


def active_features() -> dict[str, list[str]]:
    """The feature groups the model sees. The order is stable."""
    return {
        "autoregressive": _autoregressive(),
        "weather": _weather(),
        "calendar": list(CALENDAR_ACTIVE),
        "regime": list(REGIME_ACTIVE),
        "static": list(STATIC_ACTIVE),
    }


# --------------------------------------------------------------------------
# Reserve: computed, but not passed on
# --------------------------------------------------------------------------

# Per group: (columns, reason for the non-selection). The reason ends up in
# the schema and in the report - a non-selection without a reason is an
# omission, one with a reason is a decision.
DESELECTED_REASONS: dict[str, str] = {
    "autoregressive": (
        "Lags 1 and 7 cover the daily and weekly rhythm, roll7 the level. "
        "Lags 3, 9, 14 and roll28 are strongly correlated with them and cost "
        "additional edge rows: roll28 needs 14 populated days of lead-in."
    ),
    "weather": (
        "Pressure is structurally missing at 3 of 8 stations (37.5 percent) and is "
        "of secondary importance for heating demand. The wind maximum is highly "
        "correlated with the mean. The rolling weather windows represent building "
        "inertia - a hypothesis to be tested against the baseline, not to be assumed "
        "up front."
    ),
    "calendar": (
        "doy_sin and doy_cos encode the yearly seasonality, which is already in the "
        "set via month and season. They remain available as a smooth alternative for "
        "linear models."
    ),
    "regime": (
        "days_since_visit cannot be determined for 98 of 153 households (40 percent "
        "of the rows NaN). is_visit_day affects 56 rows in the whole panel - too few "
        "for a pooled model. The intervention state itself stays active."
    ),
    "static": (
        "Survey attributes and equipment flags are time-invariant and can only shift "
        "the level in the pooled model that recv_lag1 and recv_roll7_mean already "
        "carry. Four survey columns additionally have 44 to 95 percent non-responses. "
        "Their contribution is the question of the ablation experiment."
    ),
}


def _survey_columns() -> list[str]:
    return [
        *config.SURVEY_CATEGORICAL_COLUMNS,
        *config.SURVEY_NUMERIC_COLUMNS,
        *config.SURVEY_BOOL_COLUMNS,
    ]


def deselected_features(panel: pd.DataFrame) -> dict[str, list[str]]:
    """Feature candidates that exist but are not passed on, per group."""
    active = {c for group in active_features().values() for c in group}

    candidates: dict[str, list[str]] = {
        "autoregressive": (
            [f"{TARGET_PREFIX}_lag{lag}" for lag in config.TARGET_LAGS_RESERVE]
            + [
                f"{TARGET_PREFIX}_roll{window}_{stat}"
                for window in config.ROLLING_WINDOWS_RESERVE
                for stat in ("mean", "std")
            ]
        ),
        "weather": merge.weather_panel_columns(),
        "calendar": ["doy_sin", "doy_cos"],
        "regime": ["is_visit_day", "days_since_visit"],
        "static": [
            "pv_flag_imputed",
            "has_meta_survey",
            "has_heatpump_submeter",
            "station_has_sunshine",
            "station_has_pressure",
            *_survey_columns(),
        ],
    }

    return {
        group: [c for c in cols if c in panel.columns and c not in active]
        for group, cols in candidates.items()
    }


# --------------------------------------------------------------------------
# Control
# --------------------------------------------------------------------------


def verify(rep: Reporter, panel: pd.DataFrame) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Check the selection against the panel and return both lists."""
    rep.step("Feature selection")

    groups = active_features()
    features = [c for group in groups.values() for c in group]

    missing = sorted(c for c in features if c not in panel.columns)
    rep.check("all active features exist in the panel", not missing, f"{missing}")

    duplicates = sorted({c for c in features if features.count(c) > 1})
    rep.check("no column twice in the selection", not duplicates, f"{duplicates}")

    forbidden = set(config.PASSTHROUGH_COLUMNS) | {config.TARGET_COL}
    overlap = sorted(set(features) & forbidden)
    rep.check(
        "no passthrough or target column in the selection",
        not overlap,
        f"not permitted: {overlap}" if overlap else f"{len(features)} features checked",
    )

    # Flags describe the data quality of the row, not the household. A spike
    # flag on the target day reveals that consumption was unusually high.
    row_flags = {"is_gap", "kWh_spike_flag", "returned_was_substituted", "is_modelable"}
    flag_overlap = sorted(set(features) & row_flags)
    rep.check("no row quality flag used as a feature", not flag_overlap, f"{flag_overlap}")

    deselected = deselected_features(panel)

    for name, cols in groups.items():
        n_reserve = len(deselected.get(name, []))
        rep.metric(f"Features {name}", f"{len(cols)} active, {n_reserve} in reserve")
    rep.metric("Active features in total", len(features))
    rep.metric(
        "Reserve columns in total", sum(len(c) for c in deselected.values())
    )

    for name, cols in deselected.items():
        if cols:
            rep.note(f"Reserve {name}: {', '.join(cols)} - {DESELECTED_REASONS[name]}")

    rep.note(
        "The reserve columns stay in the panel so that a comparison model using them is "
        "possible without a new pipeline run. They are listed in the schema under 'deselected', "
        "not under 'feature_groups' - a modeling script that follows the schema does not see them"
    )

    rep.raise_on_failures()
    return groups, deselected
