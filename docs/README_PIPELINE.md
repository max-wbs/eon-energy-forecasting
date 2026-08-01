# Data Preparation Pipeline

_E.ON Day-Ahead Energy Forecasting — TUM SS26_

Builds a model-ready, leakage-safe household-day panel with a temporal
train/test split out of four raw sources. The business problem is described in
[README_EON_Case_Study.md](../README_EON_Case_Study.md), the design in
[Project_Plan.md](Project_Plan.md), and every assumption made — with its
reasoning — in [decisions.md](decisions.md).

---

## Quick start

Setup is described in the [main README](../README.md). All commands run from the
project root:

```powershell
.\.venv\Scripts\python.exe scripts\01_load.py           # raw          -> interim/01_ingested
.\.venv\Scripts\python.exe scripts\02_clean_validate.py # 01_ingested  -> interim/02_clean
.\.venv\Scripts\python.exe scripts\03_build_panel.py    # 02_clean     -> processed
```

The three scripts are idempotent and can be run individually; each one reads
exclusively the output of its predecessor. After a full run the combined report
is in [reports/data_prep_report.md](../reports/data_prep_report.md).

**Result:** `data/processed/model_table.parquet` — 82,051 rows × 26 columns,
153 households, **21 active features**, covering 2019-01-02 to 2024-03-01.
Next to it lie the two ready-to-use frames `panel_train.parquet` (65,502 × 24)
and `panel_test.parquet` (15,583 × 24), already filtered and without the two
control columns.

---

## The three stages

| Stage | Script | Kind of intervention | Output |
|---|---|---|---|
| 1 | `01_load.py` | read, type, remove households without a target value, merge master data | 3 parquet files in `interim/01_ingested/` |
| 2 | `02_clean_validate.py` | make the calendar gapless, flag anomalies, aggregate weather to daily level, validate | 4 parquet files in `interim/02_clean/` + `quality_report.json` |
| 3 | `03_build_panel.py` | joins, features under the leakage rule, temporal split, hand-over contract | `processed/model_table.parquet`, `panel_train.parquet`, `panel_test.parquet` + `model_table_schema.json` |

Each stage performs exactly one kind of intervention. Stage 1 does not touch
values in substance, stage 2 builds no features, stage 3 no longer corrects any
data.

### What happens in stage 1
Header and file-count gates (156 household files, 8 weather stations; any
deviation → hard abort). Typing via central dtype maps: IDs as strings,
measurements as `float64`, survey booleans three-valued. Projection of the
timestamp (`23:59:59+00:00`) onto the UTC calendar day. One single substantive
intervention: three households without a single target value are removed (153
remain, 85,464 rows).

### What happens in stage 2
Outliers are flagged robustly (median + 5·MAD per household) but **not
corrected**. Structural empty cells in `kWh_returned_Total` are separated from
genuine measurement gaps. Every household is reindexed onto its own daily span
(1,347 gap rows carrying `is_gap`, the target value stays NaN → 86,811 rows).
Regime features are derived from the visit state. Weather: clean hourly first
(forward fill ≤ 3 h, 447 values), then aggregate onto the UTC day (15,088
station days), then heating degree days.

### What happens in stage 3
Three m:1 joins with an assertion on an unchanged row count. Trim to the usable
time window, autoregressive features (5 lags, 4 rolling statistics — of which 2
lags and 2 rolling statistics are active), calendar features, feature
selection, 25 leakage proofs, removal of the gap rows, fleet-wide calendar
cutoff for the split, and finally the hand-over contract: rename, checks,
reduction of the panel to the contract columns.

---

## The two switches in `config.py`

Both are on. They are switches rather than hard-coded behaviour because turning
them off is a one-line change plus one run of about two seconds.

| Switch | On (current) | Off |
|---|---|---|
| `TRIM_TO_WEATHER_WINDOW` | panel cut to 2019-01-02 … 2024-03-01, **3,413 rows dropped** (all of them with a target value, 100 households affected, none loses its full history) | full metering period 2018-11-02 … 2024-03-20; the extra rows keep their target value and carry NaN in every weather column |
| `PANEL_SLIM` | only the contract is written: **26 instead of 70 columns**, 44 dropped | full panel with the 30 reserve columns, 9 passthrough measurements, 3 row flags and 2 leftovers |

The trim removes rows for which weather was simply **never delivered** — a
property of this dataset, not of the operating situation (D-18). That is
explicitly *not* the same as a missing weather value *inside* the window: 107
rows are a station outage, a situation that occurs in production, and they
stay. Switching the trim off is sensible for a purely autoregressive model,
which needs no weather at all.

The slim write makes the feature/non-feature boundary physical instead of
conventional (D-22): `df.drop(columns=["gross_load"])` used to yield 69 columns
including `kWh_received_HeatPump` and `kWh_received_Other`, which sum to the
target exactly. Now the same call yields 25 columns and the two dangerous ones
are no longer there. The reserve columns are still computed and checked either
way — only the writing is conditional.

---

## The leakage rule

The day-ahead bid for target day *d* is placed at the **end of day *d−1*** —
whoever buys electricity today for tomorrow knows today's meter readings. The
last fully observed day is therefore ***d−1***.

**No perfect-forecast assumption** is made: the weather too enters only as an
observation from *d−1*, not as a forecast for the target day.

| Column group | Shift | Reasoning |
|---|---|---|
| `recv_lag{1,7}`, `recv_roll7_{mean,std}` | ≥ 1 day | autoregressive; *d* itself is unknown |
| all 9 weather columns | 1 day | without a forecast proxy, observed values only |
| calendar (`dow`, `month`, `season`, `is_weekend`, `is_holiday`) | 0 | deterministically known for the target day |
| regime (`is_post_visit`) | 0 | known at bidding time |
| static attributes (`Installation_HasPVSystem`, `weather_id`) | 0 | time-invariant |
| `gross_load` (source: `kWh_received_Total`) | — | **target variable** |
| submetering, `kWh_returned_Total`, `kvarh_*` | — | passthrough, never a feature, not written |

`FORECAST_LAG` in `config.py` is the only place where the horizon is stated.
Lags, rolling windows and the re-dating of the weather all derive from it — a
comparison variant with lag 2 is a one-line change.

Rolling statistics follow the *shift-before-rolling* pattern: shift first, then
place the window. Edges (the first days of every series, the days after a gap)
stay **NaN** — no backfill (that would be leakage), no forward fill (that would
be invented). Filtering is left to the modeling stage.

### How the rule is verified
`prove_leakage_free` in `scripts/03_build_panel.py` reconstructs the expected
value via a **self-join of its own** and compares it against the built column —
so the check tests the feature logic against a second, independent derivation
rather than the shifted column against itself.

For the weather this is the only safeguard since the columns no longer carry a
`_lag` suffix (D-16). The proof therefore runs **per weather column** and in
both directions: agreement with *d−1* **and** disagreement with the target-day
value. Without the second half, an accidental shift of 0 days would go
undetected. All 11 weather columns pass both tests — the 9 active ones plus
`WindSpeed_hourly_max` and `Pressure_BarometricHeight_avg_hourly_mean`, which
are shifted and proven even though they stay in reserve.

In addition: the first row of every household must be empty in all lag columns
(proving that `groupby` takes effect and does not shift across household
boundaries). 25 proofs in total.

---

## `is_modelable` — target value, nothing else

A row counts as modelable if `gross_load` is present. Neither missing lags nor
missing weather disqualify it (D-19). That covers **81,085 of 82,051 rows
(98.8 %)**.

The reasoning is the difference between a missing *label* and a missing
*feature*. Without a label there is neither a gradient nor a metric. A missing
feature, by contrast, is a state that occurs in production: a missing lag
follows a meter outage (1,315 modelable rows), a missing weather value a
station outage (107 rows) — and a fleet that has to bid every day cannot skip
those days.

The methodological side effect matters: because `is_modelable` does not depend
on any particular model's feature requirements, a purely autoregressive and a
weather-based model are scored on the **same rows** and stay comparable.
Feature availability stays readable per row from the columns themselves, so the
strict subset can be reproduced in one line — the reverse is not possible.

---

## The active feature selection

The panel computes 50 candidates and selects 20; the final pre-selection adds
`weather_id` as the 21st. The separation is deliberate: a narrow baseline model
is interpretable and provides the yardstick against which every extension has
to prove its contribution.

| Group | Active | Columns |
|---|---|---|
| autoregressive | 4 | `recv_lag1`, `recv_lag7`, `recv_roll7_mean`, `recv_roll7_std` |
| weather | 9 | `Temperature_avg_hourly_{mean,min,max}`, `Humidity_avg_hourly_mean`, `WindSpeed_hourly_mean`, `DewPoint_hourly_mean`, `Precipitation_total_hourly_sum`, `Sunshine_duration_hourly_sum`, `hdd_15` |
| calendar | 5 | `dow`, `month`, `season`, `is_weekend`, `is_holiday` |
| regime | 1 | `is_post_visit` |
| static | 2 | `Installation_HasPVSystem`, `weather_id` |

The **30 reserve columns** are computed and checked but, with `PANEL_SLIM` on,
not written. They stay documented in the schema under `deselected` — with a
reason per group and `present_in_panel: false`. The reserve includes, among
others, all 12 survey attributes, `recv_lag{3,9,14}`, `recv_roll28_*`,
`doy_sin`/`doy_cos`, pressure, wind maximum and the rolling weather windows.

Three ways back, of differing cost:

| What | How | Cost |
|---|---|---|
| survey attributes | join `02_clean/households.parquet` (153 × 39) over `Household_ID` | no run |
| computed reserve | `PANEL_SLIM = False` | one run, ~2 s |
| passthrough measurements | `PANEL_SLIM = False` | one run, ~2 s |

The first way was the better one even before the slim write: for segmentation
`households.parquet` is the right source anyway, because there every household
counts once instead of once per day (D-20).

The planned comparison: **model with meta data against model without.** The
expectation is that time-invariant building attributes contribute little in the
pooled model, because `recv_lag1` and `recv_roll7_mean` already carry the
household level — that is a hypothesis for the experiment to test, not a
finding.

---

## The hand-over contract

Stage 3 ends with a declaration, not a search: **21 features, `gross_load` as
the target, `Household_ID` and `date` as keys** — in `utils/preselection.py`
and in the schema under `preselection`. Anything computed against the target
belongs in the modeling stage, inside the cross-validation.

Upstream every column keeps its source name; that is what makes the leakage
proofs and every entry in `docs/decisions.md` traceable back to the delivered
CSV. Only at the very end, after the proofs and the split, does the modeling
vocabulary take over (D-21):

| Source name | Contract name |
|---|---|
| `kWh_received_Total` | `gross_load` |
| `Weather_ID` | `weather_id` |

`gross_load` states *what* the quantity is — gross draw from the grid, before
any netting against PV self-consumption — instead of how it was metered. With
39 PV households that is not cosmetic. `weather_id` enters as a `category` with
8 levels: it carries the regional offset the weather columns do not capture,
and with 8 levels across 153 households it cannot memorise household identity.

The contract is checked, not trusted: every feature exists, none is listed
twice, none is a target, passthrough or row flag, none is constant on train,
and every one is at least 80 % populated on train (lowest:
`Sunshine_duration_hourly_sum` at 90.8 %). All statistics run on **train and
`is_modelable` only** (65,502 rows) — the test window must not influence the
model specification.

Reported but deliberately **not** acted upon: 3 exact functional dependencies
(`is_weekend = f(dow)`, `season = f(month)`, `hdd_15 = f(Temperature_avg_hourly_mean)`)
and 10 feature pairs with |r| ≥ 0.9. Multicollinearity costs tree models
interpretability of the importances, not accuracy, and dropping the temperature
extremes would cost exactly the cold days that matter most for procurement.
The choice belongs to the model, not to the panel.

---

## Directories

```
data/raw/                     untouched, read-only
data/interim/01_ingested/     stage-1 output
data/interim/02_clean/        stage-2 output
data/interim/quality_report.json
data/processed/               model_table.parquet, panel_train.parquet,
                              panel_test.parquet, model_table_schema.json
reports/data_prep_report.md   combined report across all stages
utils/                        all transformations as functions
scripts/                      the three executable stages
notebooks/                    data understanding and EDA
docs/                         plan and assumption log
```

Guiding principle: **notebooks narrate, modules compute.** Every transformation
is a function in `utils/`; notebooks only import and visualise. That way the
pipeline runs reproducibly without executing a single notebook.

### Modules

| Module | Purpose |
|---|---|
| `utils/config.py` | paths, schema expectations, `FORECAST_LAG`, `SPLIT_CUTOFF`, the two switches, column lists, regression expectations |
| `utils/io.py` | exactly one loader per raw source, header gate, dtype maps, parquet with round-trip check |
| `utils/reporting.py` | structured console logging and markdown report |
| `utils/checks.py` | reusable sanity-check predicates, returning `(ok, detail)` |
| `utils/loading.py` | stage 1 |
| `utils/cleaning/smart_meter.py` | reindex, regime features, feed-in substitution, outlier flag |
| `utils/cleaning/weather.py` | hourly cleaning, daily aggregation, heating degree days |
| `utils/merge.py` | joins with m:1 assertions, re-dating of the weather, time window |
| `utils/features.py` | lags, rolling statistics, calendar — builds, does not select |
| `utils/feature_selection.py` | active selection, reserve, reasons, leakage control of the lists |
| `utils/splits.py` | fleet-wide temporal cutoff |
| `utils/preselection.py` | hand-over contract: rename, checks, diagnostics, slim write, schema |

---

## The split

A **fleet-wide calendar cutoff** at 2023-06-30; the boundary day belongs to
`train`, the test set is strictly the future. Result: 65,502 labelled training
rows (2019-01-02 … 2023-06-30) and 15,583 labelled test rows
(2023-07-01 … 2024-03-01), a test share of 19.2 %.

The alternative "the last X percent per household" would mean that training
rows of one household lie calendrically *after* test rows of another — the
model would then have access to information about the period it is supposed to
predict, for instance a cold snap that produces training data in one household
and test data in another.

**Note:** the cutoff implies that only 71 of the 153 households have test rows
(70 of them with a label, so `panel_test.parquet` covers 70) — for 82
households the recording ends before the cutoff, and 7 appear only in the test
set without any training history. For a pooled fleet model this is the
realistic case (households whose meters no longer report are not part of the
future). For per-household models it is a limitation that has to be taken into
account in the modeling stage.

`panel_train.parquet` and `panel_test.parquet` hold keys, target and the 21
features, restricted to `is_modelable` — 966 unlabelled rows drop out. They
carry neither `split` (that is the file name) nor `is_modelable` (the filter
has been applied); the panel keeps both, so the frames stay derivable from it.
The categorical levels of `weather_id` and `season` were checked for equality
across the two files: derived per frame they could diverge, and a code would
then mean a different station in train than in test — a failure that shows up
as a slightly worse metric, never as an error.

---

## Report and failure behaviour

Every pipeline action logs in a structured way to the console and to
`reports/data_prep_report.md`. Two principles:

- **report-then-raise** — the report is always written *before* a hard abort
  propagates upwards. Even a failed run leaves a complete protocol behind.
- **compute, don't transcribe** — every number in the report is produced at
  runtime from the current DataFrame. The values in `config.EXPECTED` are
  regression expectations only and are never copied into the report.

Hard violations (header drift, duplicates, calendar gaps after the reindex, row
multiplication in a join, dtype drift in the parquet round trip) abort the run.
Soft findings (outliers, missingness, deviations from the regression
expectations) are logged.

Within a stage, several failed checks are collected and only raised at the next
gate — so a run shows all violations, not just the first one.

---

## Handling of missing values

The principle is **flag rather than repair**. Imputation happens in exactly one
place: short hourly weather gaps via forward fill with a limit of 3 h, i.e.
exclusively with values from *before* the gap (447 values). Everything else
stays NaN and carries a flag.

| Flag | Meaning | Where it lives |
|---|---|---|
| `is_modelable` | target value present | panel |
| `is_gap` | inserted calendar row, no measurement available | `02_clean` — the rows themselves are removed from the panel after the features are built |
| `kWh_spike_flag` | robust outlier marker (median + 5·MAD per household) | `02_clean/smart_meter_daily.parquet` |
| `returned_was_substituted` | empty cell in `kWh_returned_Total` was set to 0.0 (household structurally does not feed in) | `02_clean/smart_meter_daily.parquet` |
| `weather_day_incomplete` | daily value built from too few valid hours | `02_clean/weather_daily.parquet` |
| `station_has_sunshine`, `station_has_pressure` | whether the station carries the channel at all | `02_clean` + reserve |
| `has_meta_survey` | survey data available for this household (139 of 153; 142 of 156 in the raw data, three of the removed households had a survey record) | `02_clean/households.parquet` + reserve |
| `pv_flag_imputed` | PV status was unknown and was derived from the feed-in evidence | `02_clean/households.parquet` + reserve |

With `PANEL_SLIM` on, only `is_modelable` remains in the panel; the others stay
available in the stage-2 output or come back with `PANEL_SLIM = False`. The
exception is `weather_day_incomplete`: the weather join carries only the daily
measurement aggregates, so this flag never enters the panel regardless of the
switch — recover it from `02_clean/weather_daily.parquet` via (`Weather_ID`,
`date`).

The gap rows are removed only *after* the features have been built — they
existed to make shift and rolling correct on a gapless daily grid, and not one
of the 10 measurement columns is populated on them. Consequence for downstream
stages: the panel is deliberately **no longer gapless** per household. Any
further time series operation on the model table has to reindex first.

Categorical gaps are not imputed but carried as `<NA>`. Empty survey booleans
mean *unknown*, explicitly not *False*. Global statistics (mean, median over
the whole dataset) do not occur in the data preparation — should the model need
imputation, the imputer is fitted exclusively on `train`.

---

## Next steps

1. `notebooks/data_understanding/01_delivered_data.ipynb` and
   `02_data_quality.ipynb` — data understanding on the delivered files:
   coverage, gaps and quality on `data/raw/` (zone split per D-23)
2. `notebooks/data_understanding/03_eda.ipynb` — seasonality,
   temperature-load curve, visit effect, PV signatures, heterogeneity
   across households, on the processed panel
3. Modeling on `panel_train.parquet` / `panel_test.parquet`, or on
   `model_table.parquet` via the `split` column; build the feature list from
   `preselection.features` in the schema, never from `panel.columns`; fit
   encoders, scalers and imputers exclusively on `train`
