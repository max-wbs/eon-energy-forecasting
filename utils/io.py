"""Input and output: exactly one loader per raw source, plus parquet helpers.

The loaders are the only place in the project that reads raw files. They
enforce the header gate and return typed DataFrames - so there is no second,
diverging parse logic in notebooks or scripts.

Typing principles:

* IDs are strings, never integers. They are identifiers, not numbers.
* Measurements are `float64`. Empty fields become NaN and stay NaN - nothing
  is imputed here.
* Boolean survey fields are three-valued (`boolean`): empty means *unknown*,
  explicitly not *False*.
* Timestamps are parsed tz-aware in UTC right away.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from utils import config


class SchemaError(ValueError):
    """The header of a raw file does not match the expectation."""


# --------------------------------------------------------------------------
# Header gate
# --------------------------------------------------------------------------


def read_header(path: Path) -> list[str]:
    with path.open("r", encoding=config.CSV_ENCODING) as fh:
        first_line = fh.readline()
    return [c.strip() for c in first_line.strip().split(config.CSV_SEP)]

def assert_header(path: Path, expected: list[str]) -> None:
    """Fails loudly if column names or their order deviate."""
    found = read_header(path)
    if found != expected:
        missing = [c for c in expected if c not in found]
        extra = [c for c in found if c not in expected]
        raise SchemaError(
            f"Header drift in {path.name}: {len(found)} columns instead of {len(expected)}. "
            f"Missing: {missing or '-'} | Unexpected: {extra or '-'}"
        )


# --------------------------------------------------------------------------
# Typing helpers
# --------------------------------------------------------------------------


def to_nullable_bool(series: pd.Series) -> pd.Series:
    """Convert a text column with True/False/empty into three-valued `boolean`.

    Empty cells become `pd.NA` - unknown, not False. That distinction matters
    in substance: an empty "Survey_Installation_HasElectricVehicle" field
    means the household did not answer the question, not that it owns no
    electric vehicle.
    """
    mapped = series.astype("string").str.strip().str.lower().map({"true": True, "false": False})
    return mapped.astype("boolean")


def days(n: int) -> pd.Timedelta:
    """Day-valued time span, without the deprecated bare-integer conversion.

    `pd.Timedelta(days=n)` raises a DeprecationWarning about the generic
    NumPy timedelta unit under pandas 2.3 and numpy 2.5. The explicit unit
    avoids that and states the intent more clearly anyway.
    """
    return pd.to_timedelta(n, unit="D")


def _parse_utc(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, format="ISO8601")


def _to_utc_date(timestamps: pd.Series) -> pd.Series:
    """Project UTC timestamps onto the corresponding UTC calendar day.

    The result is tz-naive (`datetime64[ns]`, midnight) so that the meter and
    weather sides share the same join-key dtype and parquet round trips
    produce no timezone surprises.
    """
    return timestamps.dt.normalize().dt.tz_localize(None)


# --------------------------------------------------------------------------
# Loader: smart meter
# --------------------------------------------------------------------------

_SMART_METER_DTYPES = {
    "Household_ID": "string",
    "Group": "string",
    "AffectsTimePoint": "string",
    "Timestamp": "string",
    **{c: "float64" for c in config.SMART_METER_VALUE_COLUMNS},
}


def smart_meter_files() -> list[Path]:
    return sorted(config.RAW_SMART_METER_DIR.glob("*.csv"))


def load_smart_meter_file(path: Path) -> pd.DataFrame:
    """Load one household file, type it and project it onto the UTC day."""
    assert_header(path, config.SMART_METER_COLUMNS)
    df = pd.read_csv(path, sep=config.CSV_SEP, dtype=_SMART_METER_DTYPES)

    df["Timestamp"] = _parse_utc(df["Timestamp"])
    df["date"] = _to_utc_date(df["Timestamp"])
    df["source_file"] = path.stem
    return df


def load_smart_meter_all() -> pd.DataFrame:
    """Combine all household files into a single long table."""
    files = smart_meter_files()
    if not files:
        raise FileNotFoundError(f"No CSVs in {config.RAW_SMART_METER_DIR}")
    frames = [load_smart_meter_file(p) for p in files]
    return pd.concat(frames, ignore_index=True)


# --------------------------------------------------------------------------
# Loader: weather
# --------------------------------------------------------------------------

_WEATHER_DTYPES = {
    "Weather_ID": "string",
    "Timestamp": "string",
    **{c: "float64" for c in config.WEATHER_VALUE_COLUMNS},
}


def weather_files() -> list[Path]:
    return sorted(config.RAW_WEATHER_DIR.glob("*.csv"))


def load_weather_file(path: Path) -> pd.DataFrame:
    """Load one weather station hourly. No aggregation - that happens in stage 2."""
    assert_header(path, config.WEATHER_COLUMNS)
    df = pd.read_csv(path, sep=config.CSV_SEP, dtype=_WEATHER_DTYPES)
    df["Timestamp"] = _parse_utc(df["Timestamp"])
    df["date"] = _to_utc_date(df["Timestamp"])
    return df


def load_weather_all() -> pd.DataFrame:
    files = weather_files()
    if not files:
        raise FileNotFoundError(f"No CSVs in {config.RAW_WEATHER_DIR}")
    frames = [load_weather_file(p) for p in files]
    return pd.concat(frames, ignore_index=True)


# --------------------------------------------------------------------------
# Loader: master data
# --------------------------------------------------------------------------


def load_households() -> pd.DataFrame:
    """Load households.csv; boolean flags three-valued, IDs as strings."""
    path = config.RAW_HOUSEHOLDS_FILE
    assert_header(path, config.HOUSEHOLDS_COLUMNS)
    df = pd.read_csv(path, sep=config.CSV_SEP, dtype="string")
    for col in config.HOUSEHOLDS_BOOL_COLUMNS:
        df[col] = to_nullable_bool(df[col])
    return df


def load_meta() -> pd.DataFrame:
    """Load meta_data.csv (survey attributes, does not cover all households)."""
    path = config.RAW_META_FILE
    assert_header(path, config.META_COLUMNS)
    df = pd.read_csv(path, sep=config.CSV_SEP, dtype="string")
    for col in config.SURVEY_BOOL_COLUMNS:
        df[col] = to_nullable_bool(df[col])
    for col in config.SURVEY_NUMERIC_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


# --------------------------------------------------------------------------
# Parquet
# --------------------------------------------------------------------------


def write_parquet(df: pd.DataFrame, path: Path) -> dict[str, str]:
    """Write in sorted order and prove the dtypes survive the round trip.

    The round-trip check catches silent type changes (such as `boolean` to
    `object`) that would later cause hard-to-locate errors in stage 2 or 3.
    Returns the dtypes that actually ended up in the file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    df = df.reset_index(drop=True)
    df.to_parquet(path, engine="pyarrow", index=False)

    written = pd.read_parquet(path, engine="pyarrow")
    before = {c: str(t) for c, t in df.dtypes.items()}
    after = {c: str(t) for c, t in written.dtypes.items()}
    drift = {c: (before[c], after[c]) for c in before if before[c] != after.get(c)}
    if drift:
        details = ", ".join(f"{c}: {a} -> {b}" for c, (a, b) in drift.items())
        raise SchemaError(f"Dtype drift in the parquet round trip of {path.name}: {details}")
    if len(written) != len(df):
        raise SchemaError(f"Row loss while writing {path.name}: {len(df)} -> {len(written)}")
    return after


def read_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing. Has the previous pipeline stage been run?"
        )
    return pd.read_parquet(path, engine="pyarrow")
