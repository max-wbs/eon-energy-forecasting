"""Central configuration of the data-preparation pipeline.

All paths, schema expectations and domain constants live here so that the
pipeline modules stay free of literals and every assumption is traceable to
exactly one place.

See docs/Project_Plan.md for the reasoning behind the values.
"""

from __future__ import annotations

from pathlib import Path

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent

DATA = ROOT / "data"
RAW = DATA / "raw"
INTERIM = DATA / "interim"
PROCESSED = DATA / "processed"
REPORTS = ROOT / "reports"

RAW_SMART_METER_DIR = RAW / "smart_meter_daily"
RAW_WEATHER_DIR = RAW / "weather_data_hourly"
RAW_META_DIR = RAW / "smart_meter_meta_data"
RAW_HOUSEHOLDS_FILE = RAW_META_DIR / "households.csv"
RAW_META_FILE = RAW_META_DIR / "meta_data.csv"

# Each stage writes into its own directory and reads only the previous
# stage's output. That makes the scope firewall between stages mechanically
# verifiable instead of merely conventional.
INGESTED = INTERIM / "01_ingested"
CLEAN = INTERIM / "02_clean"

SMART_METER_PARQUET = "smart_meter_daily.parquet"
HOUSEHOLDS_PARQUET = "households.parquet"
WEATHER_HOURLY_PARQUET = "weather_hourly.parquet"
WEATHER_DAILY_PARQUET = "weather_daily.parquet"
MODEL_TABLE_PARQUET = "model_table.parquet"
# Ready-to-use split frames next to the panel: keys, target and features only.
# The split column is gone because the file name carries it, and
# `is_modelable` is gone because the filter has already been applied.
PANEL_TRAIN_PARQUET = "panel_train.parquet"
PANEL_TEST_PARQUET = "panel_test.parquet"

QUALITY_REPORT_JSON = INTERIM / "quality_report.json"
DATA_PREP_REPORT_MD = REPORTS / "data_prep_report.md"

CSV_SEP = ";"
CSV_ENCODING = "utf-8"

# --------------------------------------------------------------------------
# Schema expectations (header gates, stage 1)
# --------------------------------------------------------------------------

N_SMART_METER_FILES = 156
N_WEATHER_STATIONS = 8

SMART_METER_COLUMNS = [
    "Household_ID",
    "Group",
    "AffectsTimePoint",
    "Timestamp",
    "kWh_received_Total",
    "kWh_received_HeatPump",
    "kWh_received_Other",
    "kWh_returned_Total",
    "kvarh_received_capacitive_Total",
    "kvarh_received_capacitive_HeatPump",
    "kvarh_received_capacitive_Other",
    "kvarh_received_inductive_Total",
    "kvarh_received_inductive_HeatPump",
    "kvarh_received_inductive_Other",
]

WEATHER_COLUMNS = [
    "Weather_ID",
    "Timestamp",
    "Temperature_avg_hourly",
    "DewPoint_hourly",
    "Humidity_avg_hourly",
    "Precipitation_total_hourly",
    "Pressure_BarometricHeight_avg_hourly",
    "Pressure_SeaLevelStandardAtmosphere_avg_hourly",
    "Pressure_SeaLevel_avg_hourly",
    "Sunshine_duration_hourly",
    "WindSpeed_hourly",
]

HOUSEHOLDS_COLUMNS = [
    "Household_ID",
    "Group",
    "Weather_ID",
    "Installation_HasPVSystem",
    "Protocols_Available",
    "Protocols_HasMultipleVisits",
    "Protocols_ReportIDs",
    "MetaData_Available",
    "SmartMeterData_Available_15min",
    "SmartMeterData_Available_Daily",
    "SmartMeterData_Available_Monthly",
]

META_COLUMNS = [
    "Household_ID",
    "Survey_Building_Type",
    "Survey_Building_LivingArea",
    "Survey_Building_Residents",
    "Survey_HeatPump_Installation_Type",
    "Survey_HeatDistribution_System_FloorHeating",
    "Survey_HeatDistribution_System_Radiator",
    "Survey_DHW_Production_ByHeatPump",
    "Survey_DHW_Production_ByElectricWaterHeater",
    "Survey_DHW_Production_BySolar",
    "Survey_Installation_HasDryer",
    "Survey_Installation_HasFreezer",
    "Survey_Installation_HasElectricVehicle",
]

# --------------------------------------------------------------------------
# Column groups
# --------------------------------------------------------------------------

KEY_COLUMNS = ["Household_ID", "date"]
TARGET_COL = "kWh_received_Total"

# AffectsTimePoint has four states, not two. "during visit" occurs exactly
# once per household - that is the visit day itself and therefore a
# transition day belonging to neither regime. "unknown" occurs for a single
# household only.
VISIT_BEFORE = "before visit"
VISIT_DURING = "during visit"
VISIT_AFTER = "after visit"
VISIT_UNKNOWN = "unknown"

AFFECTS_TIME_POINT_VALUES = [VISIT_BEFORE, VISIT_DURING, VISIT_AFTER, VISIT_UNKNOWN]

# Ordering for the monotonicity check; "unknown" cannot be placed in the
# sequence and is excluded from that check.
VISIT_ORDER = {VISIT_BEFORE: 0, VISIT_DURING: 1, VISIT_AFTER: 2}

# IDs stay strings throughout: they are identifiers, not numbers, and must
# never end up in arithmetic operations or int64 comparisons.
ID_COLUMNS = ["Household_ID", "Weather_ID"]

SMART_METER_VALUE_COLUMNS = [c for c in SMART_METER_COLUMNS if c.startswith(("kWh_", "kvarh_"))]

WEATHER_VALUE_COLUMNS = [c for c in WEATHER_COLUMNS if c not in ("Weather_ID", "Timestamp")]

# Weather quantities that behave continuously and may therefore be carried
# forward across short gaps. Precipitation and sunshine are deliberately
# absent: they are spiky, and a forward fill would invent rainfall.
WEATHER_FFILL_COLUMNS = [
    "Temperature_avg_hourly",
    "DewPoint_hourly",
    "Humidity_avg_hourly",
    "Pressure_BarometricHeight_avg_hourly",
    "Pressure_SeaLevelStandardAtmosphere_avg_hourly",
    "Pressure_SeaLevel_avg_hourly",
    "WindSpeed_hourly",
]

# Only one of the three pressure channels is carried forward. Barometric
# height and SeaLevelStandardAtmosphere both cover 5 of 8 stations, SeaLevel
# only 4 - the first channel wins at equal coverage.
WEATHER_PRESSURE_KEEP = "Pressure_BarometricHeight_avg_hourly"
WEATHER_PRESSURE_DROP = [
    "Pressure_SeaLevelStandardAtmosphere_avg_hourly",
    "Pressure_SeaLevel_avg_hourly",
]


def daily_name(source: str, func: str) -> str:
    """Naming convention for daily weather aggregates: <raw column>_<aggregate>.

    The raw name stays visible in the daily value and the aggregate function
    can be read off the column name - `Temperature_avg_hourly_min` is legible
    as the daily minimum of the hourly means without consulting the docs.
    """
    return f"{source}_{func}"

SURVEY_BOOL_COLUMNS = [
    "Survey_HeatDistribution_System_FloorHeating",
    "Survey_HeatDistribution_System_Radiator",
    "Survey_DHW_Production_ByHeatPump",
    "Survey_DHW_Production_ByElectricWaterHeater",
    "Survey_DHW_Production_BySolar",
    "Survey_Installation_HasDryer",
    "Survey_Installation_HasFreezer",
    "Survey_Installation_HasElectricVehicle",
]

SURVEY_CATEGORICAL_COLUMNS = [
    "Survey_Building_Type",
    "Survey_HeatPump_Installation_Type",
]

SURVEY_NUMERIC_COLUMNS = [
    "Survey_Building_LivingArea",
    "Survey_Building_Residents",
]

HOUSEHOLDS_BOOL_COLUMNS = [
    "Installation_HasPVSystem",
    "Protocols_Available",
    "Protocols_HasMultipleVisits",
    "MetaData_Available",
    "SmartMeterData_Available_15min",
    "SmartMeterData_Available_Daily",
    "SmartMeterData_Available_Monthly",
]

# Columns the panel carries along but never exposes as a predictor. The
# target itself and all same-day measurements belong here: they are not
# known at bidding time.
PASSTHROUGH_COLUMNS = [
    "kWh_received_HeatPump",
    "kWh_received_Other",
    "kWh_returned_Total",
    "kvarh_received_capacitive_Total",
    "kvarh_received_capacitive_HeatPump",
    "kvarh_received_capacitive_Other",
    "kvarh_received_inductive_Total",
    "kvarh_received_inductive_HeatPump",
    "kvarh_received_inductive_Other",
]

# --------------------------------------------------------------------------
# Domain constants
# --------------------------------------------------------------------------

# The bid for target day d is placed at the end of day d-1; day d-1 is fully
# metered by then. Last fully observed day: d-1. This holds without a
# forecast proxy for meter readings AND weather - only observed values enter,
# just up to d-1 instead of d-2.
#
# This constant is the single place where the horizon is set: lags, rolling
# windows and the re-dating of the weather all derive from it.
FORECAST_LAG = 1

# Actively built autoregressive horizons. The reserve is computed as well but
# not passed on as a feature - see utils/feature_selection.py.
TARGET_LAGS = [1, 7]
TARGET_LAGS_RESERVE = [3, 9, 14]

ROLLING_WINDOWS = [7]
ROLLING_WINDOWS_RESERVE = [28]
ROLLING_MIN_PERIODS = {7: 4, 28: 14}

# Base temperature for heating degree days. 15 degrees C is the German
# convention (G15): below a daily mean of 15 degrees, heating is on. The
# value is part of the column name so the assumption does not go invisible.
HDD_BASE_C = 15.0
HDD_COLUMN = f"hdd_{HDD_BASE_C:g}"

WEATHER_FFILL_LIMIT_H = 3
MIN_VALID_HOURS_PER_DAY = 20
HOURS_PER_DAY = 24

# Robust outlier marker: median + k * MAD per household. Flagged only, the
# value itself is left untouched.
SPIKE_MAD_K = 5.0

# Plausibility bounds for the weather validation.
WEATHER_BOUNDS = {
    "Temperature_avg_hourly": (-30.0, 45.0),
    "DewPoint_hourly": (-40.0, 35.0),
    "Humidity_avg_hourly": (0.0, 100.0),
    "Precipitation_total_hourly": (0.0, 100.0),
    "Pressure_BarometricHeight_avg_hourly": (800.0, 1100.0),
    "Pressure_SeaLevelStandardAtmosphere_avg_hourly": (900.0, 1100.0),
    "Pressure_SeaLevel_avg_hourly": (900.0, 1100.0),
    "Sunshine_duration_hourly": (0.0, 60.0),
    "WindSpeed_hourly": (0.0, 60.0),
}

# Smart meter data spans 2018-11-02 to 2024-03-20, weather only 2019-01-01 to
# 2024-02-29. The panel is trimmed to the period for which the *shifted*
# weather exists: every target day d needs the observation from d-1, so the
# usable window moves back by FORECAST_LAG.
WEATHER_DATE_MIN = "2019-01-01"
WEATHER_DATE_MAX = "2024-02-29"


def _shift_date(date_str: str, days: int) -> str:
    import pandas as pd  # local, so config stays importable without pandas

    return str((pd.Timestamp(date_str) + pd.Timedelta(days=days)).date())


PANEL_DATE_MIN = _shift_date(WEATHER_DATE_MIN, FORECAST_LAG)  # 2019-01-02
PANEL_DATE_MAX = _shift_date(WEATHER_DATE_MAX, FORECAST_LAG)  # 2024-03-01

# Whether the panel is actually cut down to that window. See docs/decisions.md
# D-18: outside the window no weather was *delivered*, which is a property of
# this dataset and not of the operating situation - in production the d-1
# observation is available. Rows outside the window are therefore removed
# rather than carried along as a permanent NaN block.
#
# This is explicitly NOT the same as a missing weather value *inside* the
# window: that is a station outage, a situation the model has to cope with in
# production, so those rows stay.
TRIM_TO_WEATHER_WINDOW = True

# A fleet-wide calendar cutoff, not a per-household split: day-ahead
# procurement buys for the entire fleet over a fixed future window.
# The boundary day belongs to train, the test set is strictly the future.
SPLIT_CUTOFF = "2023-06-30"

# --------------------------------------------------------------------------
# Final pre-selection (stage 3, step 10.5)
# --------------------------------------------------------------------------
# The contract itself - which columns the model receives under which names -
# lives in utils/preselection.py. Only the thresholds of its diagnostics are
# configuration.
#
# All three are *reporting* thresholds, not filters. Nothing is removed from
# the contract because of them: a correlation filter would cost tree models
# the temperature extremes that matter most for procurement, and a
# near-zero-variance rule would kill is_holiday, whose 2.5 percent of rows
# are precisely the days when the load profile shifts.

# Coverage on train below which a feature is flagged as thin (soft check).
PRESELECT_COVERAGE_WARN = 0.80

# From this absolute correlation on, a feature pair is listed in the report.
PRESELECT_CORR_REPORT = 0.90

# Maximum number of distinct values for a column to be tested as the
# determinant of a functional dependency. A continuous determinant would
# trivially "determine" every other column without that meaning anything.
PRESELECT_FUNC_DEP_MAX_LEVELS = 32

# Whether the written panel is reduced to the contract columns: keys, target,
# the features and the two columns needed to *use* the table (split,
# is_modelable). Everything else - the reserve from D-17, the passthrough
# measurements, the remaining row flags - is dropped.
#
# Switching this off restores the full panel, and that is the whole reason it
# is a switch rather than a deletion: stage 3 runs in about two seconds, so
# the reserve is one flag flip plus one run away. The reserve columns are
# computed and checked either way; only the writing is conditional.
PANEL_SLIM = True

# --------------------------------------------------------------------------
# Regression expectations
# --------------------------------------------------------------------------
# These numbers were verified against the delivered raw data. If a run
# deviates, the raw data has changed - then update the number here rather
# than removing the check.

EXPECTED = {
    "smart_meter_files": 156,
    "smart_meter_rows_raw": 88_791,
    "weather_stations": 8,
    "weather_rows_per_station": 45_264,
    "households_rows": 156,
    "meta_rows": 142,
    "households_after_drop": 153,
    "pv_flag_true": 39,
    "pv_flag_missing": 1,
    "target_missing_raw": 4_293,
    "households_no_target": ["747511", "768498", "996610"],
    # These three households have continuous heat-pump submetering but not a
    # single total-meter value - they only measure the heat pump. Their
    # removal explains the difference between the figures before and after
    # the drop. The checks run after the drop, so both states are recorded.
    "households_with_gaps_raw": 41,
    "households_with_gaps": 39,
    "households_with_submeter_raw": 10,
    "households_with_submeter": 7,
    "households_with_visit_date_raw": 56,
    "households_with_visit_date": 55,
    # Progression patterns of AffectsTimePoint, counted on the raw data:
    # 78 households with "before visit" only (visit outside the data window),
    # 56 with a clean transition before -> during -> after,
    # 21 with "after visit" only (visit predates the start of recording),
    # 1 with "before visit -> unknown".
    "visit_patterns": {
        "before visit": 78,
        "before visit -> during visit -> after visit": 56,
        "after visit": 21,
        "before visit -> unknown": 1,
    },
    "visit_day_rows": 56,
    "visit_unknown_rows": 16,
}
