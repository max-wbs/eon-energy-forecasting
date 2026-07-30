# E.ON Day-Ahead Energy Forecasting

_TUM SS26 — Data Analytics in Applications_

Day-ahead forecast of household electricity demand from smart-meter, weather and
survey data. The repository contains the data-preparation pipeline that builds a
leakage-safe household-day panel, plus the notebooks for analysis and modelling.

## Setup

Requires **Python 3.13**.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Linux/macOS: `python3.13 -m venv .venv` and `.venv/bin/python` accordingly.

## Data preparation

Run the three stages in order:

```powershell
.\.venv\Scripts\python.exe scripts\01_load.py            # raw         -> interim/01_ingested
.\.venv\Scripts\python.exe scripts\02_clean_validate.py  # 01_ingested -> interim/02_clean
.\.venv\Scripts\python.exe scripts\03_build_panel.py     # 02_clean    -> processed
```

Each script is idempotent and reads exclusively the output of its predecessor.

**Result:** `data/processed/model_table.parquet` — 82,051 rows × 26 columns,
153 households, 21 active features, covering 2019-01-02 to 2024-03-01. Next to
it lie the ready-to-use `panel_train.parquet` (65,502 × 24) and
`panel_test.parquet` (15,583 × 24). Every run writes a combined report to
[reports/](reports/).

## Notebooks

- [notebooks/data_understanding/](notebooks/data_understanding/) — exploration of
  the raw sources and of the prepared panel
- [notebooks/modelling/](notebooks/modelling/) — forecasting models and evaluation

Notebooks import from `utils/` and visualise; the transformations themselves live
in the modules.

## Repository

```
data/         raw -> interim -> processed
scripts/      the three pipeline stages
utils/        all transformation logic
notebooks/    data understanding, modelling
docs/         design and documentation
reports/      generated, updated per run
```

## Documentation

The pipeline in detail, the design and every assumption made — with its
reasoning — are documented in [docs/](docs/). The original case brief is
[README_EON_Case_Study.md](README_EON_Case_Study.md).
