# E.ON Day-Ahead Energy Forecasting

_TUM SS26 — Data Analytics in Applications_

Day-ahead forecast of household electricity demand from smart-meter, weather and
survey data. The repository contains the data-preparation pipeline that builds a
leakage-safe household-day panel, plus the notebooks for analysis and modelling.

## Setup

Requires **Python 3.13**.

The two requirements files pin the same versions; `requirements.txt` additionally
pins `pywinpty`, which is Windows-only and will fail to install on macOS/Linux.
Use the file that matches your OS.

**Windows**

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

**macOS/Linux**

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements_mac.txt
```

`ipykernel` is included in both files, so no separate kernel registration step is
needed. In VS Code, open the repository folder and, for every notebook, use the
kernel picker in the top right (or `Python: Select Interpreter`) to select the
`.venv` interpreter — `.venv/bin/python` on macOS/Linux, `.venv\Scripts\python.exe`
on Windows — before running any cells.

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
`panel_test.parquet` (15,583 × 24), plus `model_table_schema.json`, the contract
every downstream notebook reads its feature groups, target and split cutoff
from. Every run writes a combined report to [reports/](reports/).

This step has to complete before any modelling notebook is run — 07 and 08 both
fail their first cell (a "fail-loud" contract gate) if `panel_train.parquet`,
`panel_test.parquet` or `model_table_schema.json` are missing or malformed.

## Notebooks

- [notebooks/data_understanding/](notebooks/data_understanding/) — exploration of
  the raw sources and of the prepared panel
- [notebooks/modelling/](notebooks/modelling/) — forecasting models and evaluation

Notebooks import from `utils/` and visualise; the transformations themselves live
in the modules. All notebooks are meant to be run top to bottom (Run All) with a
freshly started kernel — none of them depend on cells being re-run out of order.

### Modelling notebooks (07, 08)

Both `07_level0_baseline.ipynb` and `08_level1b_pv_classification.ipynb` are
self-contained: they import only `numpy`, `pandas`, `matplotlib`, `seaborn`,
`scikit-learn` and `scipy` (all in both requirements files), never `utils/`, and
locate the repository root themselves by walking up from the notebook's working
directory until they find `data/processed`. That means they run correctly
regardless of whether VS Code's working directory is the repo root or the
notebook's own folder, as long as the notebook is opened somewhere inside the
repository.

**Run order:** 07 before 08.

- `07_level0_baseline.ipynb` builds the Level 0 ladder — three naive benchmarks,
  a per-household energy-signature regression, and the pooled Random Forest —
  and writes the fitted energy signatures and per-household diagnostics that
  Level 1 reuses as inputs.
- `08_level1b_pv_classification.ipynb` builds the PV-ownership classifier and
  the two PV/non-PV segmented Random Forests. It refits its own copy of the
  Level 0 pooled model internally (identical hyperparameter search), so it will
  run on its own even if 07 hasn't been executed in the same session — but its
  printed sanity check quotes the expected leaf size against
  `reports/level0_baseline_report.md`, and its narrative assumes that report
  already exists, so run 07 first.

**Runtime:** 07 trains a 300-tree Random Forest once, re-fits it across 8
rolling-origin folds, and computes per-household diagnostics — a few minutes on
a laptop CPU. 08 repeats the same leaf-size sweep three times (pooled, PV-only,
non-PV-only) on top of a 5-fold cross-validated PV classifier, so budget longer,
roughly 5–10 minutes. All forests fit with `n_jobs=-1`, so more CPU cores help.
07 has one optional slow cell ("STEP 6c", `RUN_MAE_CRITERION = False` by
default); leave it off unless you specifically want the extra loss-criterion
comparison, which adds a couple more minutes.

**Reproducibility:** every model is fit with `random_state=42`, so a full,
unmodified re-run reproduces the numbers already written to `reports/` exactly.

**Outputs**, all written on a successful full run:

| Notebook | File | Contains |
|---|---|---|
| 07 | `data/processed/level0_test_predictions.parquet` | per-row test predictions for every Level 0 model |
| 07 | `reports/level0_energy_signatures.csv` | fitted base load / heating response per household |
| 07 | `reports/level0_per_household_errors.csv` | per-household error and bias diagnostics |
| 07 | `reports/level0_baseline_report.md` | narrative report, regenerated on every run |
| 08 | `reports/level1b_pv_classifier_household_features.csv` | household-level features and CV predictions from the PV classifier |
| 08 | `reports/level1b_comparison_table.csv` | pooled vs. segmented comparison table |
| 08 | `data/processed/level1b_segment_test_predictions.parquet` | per-row test predictions, pooled vs. segmented |

If any of these are missing after a run, the notebook did not reach its final
cell — check the last executed cell for the failure before assuming the setup
is at fault.

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
[README.md](README.md).
