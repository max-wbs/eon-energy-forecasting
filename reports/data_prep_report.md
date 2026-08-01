# Data Preparation Report

_Generated automatically. Every number comes from the respective run, not from the plan._
_Produced by `utils/reporting.py`; configuration in `utils/config.py`, reasoning in `docs/Project_Plan.md`._

| Stage | Title | Status | Run (UTC) |
|---|---|---|---|
| 1 | Load & Type | ok | 2026-07-30T11:50:24+00:00 |
| 2 | Cleaning & Validation | ok | 2026-07-30T11:50:30+00:00 |
| 3 | Panel, Features & Split | ok | 2026-08-01T07:18:24+00:00 |

---

## Stage 1 - Load & Type

_Run: 2026-07-30T11:50:24+00:00 UTC - status: successful_

### Read smart meter daily data

| Metric | Value |
|---|---|
| Files | 156 |
| Rows | 88,791 |
| Households | 156 |
| Period from | 2018-11-02 |
| Period to | 2024-03-20 |

- [ok] File-count gate - 156 files found, 156 expected
- [ok] Header gate - all 156 files with 14 columns
- [ok] Row count as documented - 88791 rows, 88791 documented

### Check identity and timestamps

- [ok] Household_ID matches the file name
- [ok] all timestamps at 23:59:59 UTC - end of day uniform
- [ok] (Household_ID, date) unique
- [ok] Group only with known values - values encountered: ['treatment']

### Check the visit state (AffectsTimePoint)

| Metric | Value |
|---|---|
| Rows 'before visit' | 65,364 |
| Rows 'during visit' | 56 |
| Rows 'after visit' | 23,355 |
| Rows 'unknown' | 16 |
| Households with a visit day inside the data window | 56 |

- 78 households: before visit
- 56 households: before visit -> during visit -> after visit
- 21 households: after visit
- 1 households: before visit -> unknown
- Consequence for stage 2: 'during visit' is a transition day and gets its own flag; households with 'after visit' only had their visit before recording started, so their visit date is unknown

- [ok] known states only - ['after visit', 'before visit', 'during visit', 'unknown']
- [ok] AffectsTimePoint without gaps
- [ok] 'during visit' at most one day per household - at most 1 days
- [ok] progression per household monotone (no relapse to before the visit)
- [ok] progression patterns as documented - 4 distinct patterns

### Remove households without a target value

| Metric | Value |
|---|---|
| Missing target values in total | 4,293 |
| Households without any target value | 3 |
| Rows after the drop | 85,464 |
| Households after the drop | 153 |

- Household 747511 removed: 770 rows, not a single target value
- Household 768498 removed: 734 rows, not a single target value
- Household 996610 removed: 1823 rows, not a single target value
- kept, but with a very short history (< 30 target values): 109104 (22), 461104 (21), 7086681 (5)

- [ok] removed households as documented - removed: ['747511', '768498', '996610']
- [ok] household count after the drop as documented - 153 households

### Read and merge master data

| Metric | Value |
|---|---|
| households.csv rows | 156 |
| meta_data.csv rows | 142 |
| PV flag True | 39 |
| PV flag unknown | 1 |
| Master data rows after the drop | 153 |
| Households with survey data | 139 |
| Households without survey data | 14 |

- PV status unknown for ['877881'] - stays <NA>; resolution via feed-in evidence happens in stage 2
- 3 of the removed households had survey data; of the 153 remaining ones, 139 have a survey record
- Empty survey booleans stay <NA> (unknown), they do not become False - an unanswered question is not a denial

- [ok] households.csv row count as documented - 156 rows
- [ok] meta_data.csv covers only part of the households - 142 of 156 households with survey data
- [ok] Household_ID unique in households.csv
- [ok] Household_ID unique in meta_data.csv
- [ok] every meta ID exists in households.csv
- [ok] PV flags as documented - 39 True, 1 unknown
- [ok] left join households x meta multiplies no rows - 156 -> 156
- [ok] master table covers exactly the remaining households - 156 -> 153 rows, 153 households in the meter frame

### Read hourly weather data

| Metric | Value |
|---|---|
| Stations | 8 |
| Rows | 362,112 |
| Period from | 2019-01-01 00:00:00+00:00 |
| Period to | 2024-02-29 23:00:00+00:00 |

- [ok] Station-count gate - 8 stations found
- [ok] Header gate - all 8 files with 11 columns
- [ok] all stations with an identical row count - 45264 to 45264 rows
- [ok] (Weather_ID, Timestamp) unique

### Referential integrity household to weather station

- Sunshine_duration_hourly: empty throughout at ['HbsbG', 'ceOxS', 'sV3mR']
- Pressure_BarometricHeight_avg_hourly: empty throughout at ['HbsbG', 'ceOxS', 'sV3mR']

- [ok] every Weather_ID of the households has a weather file
- [ok] Weather_ID in the master table without gaps

### Write results as parquet

| Metric | Value |
|---|---|
| smart_meter_daily.parquet | 85,464 rows x 15 columns |
| households.parquet | 153 rows x 24 columns |
| weather_hourly.parquet | 362,112 rows x 12 columns |

- Output directory: data\interim\01_ingested

- [ok] Parquet round trip without dtype drift - verified for all three tables

---

## Stage 2 - Cleaning & Validation

_Run: 2026-07-30T11:50:30+00:00 UTC - status: successful_

### Read the results of stage 1

| Metric | Value |
|---|---|
| Smart meter rows | 85,464 |
| Households | 153 |
| Weather hourly rows | 362,112 |

- Source: data\interim\01_ingested (stage-1 output only, no raw data)

### Flag outliers

| Metric | Value |
|---|---|
| Flagged as outliers | 564 |
| Households affected | 61 |
| Share of observed rows | 0.67 % |

- Threshold: median + 5 x MAD per household. The values stay unchanged, only the marker is passed on

### Feed-in: separate structural empty cells from measurement gaps

| Metric | Value |
|---|---|
| Households with positive feed-in | 37 |
| Households without any feed-in | 116 |
| Substituted cells (set to 0.0) | 57,460 |
| Remaining genuine measurement gaps | 13,816 |

- Active feeders keep their NaN - there an empty cell is a measurement gap, not a zero value

### Check the PV flag against the feed-in evidence

| Metric | Value |
|---|---|
| PV flag True and feed-in evidenced | 37 |
| PV flag True, but no feed-in | 2 |
| PV flag False, but feed-in evidenced | 0 |

- PV according to the master data, without feed-in in the data: 7374981, 1211151 - possibly a measurement gap or a system installed after the metering period
- PV status of household 877881 was unknown and is set to False based on the feed-in evidence (flag: pv_flag_imputed)

- [ok] no household feeds in without being listed as a PV owner

### Make the calendar gapless per household

| Metric | Value |
|---|---|
| Rows before | 85,464 |
| Inserted gap rows | 1,347 |
| Rows after | 86,811 |
| Households with gaps | 39 |
| Largest gap total per household | 333 days |

- Households with the most gap days: 861116 (333), 611629 (246), 699801 (185), 881223 (136), 712718 (87)
- The target value in gap rows stays NaN - the rows establish the grid, they do not fill it

- [ok] households with gaps as documented - 39 households (41 in the raw data, two of them removed)

### Derive regime features from the visit state

| Metric | Value |
|---|---|
| Households with a known visit date | 55 |
| Households without a known visit date | 98 |
| Rows in state 'after visit' | 22,667 |
| Rows in state 'before visit' | 64,128 |
| Rows with an unknown state | 16 |
| Gap rows with a carried-forward state | 1,347 |

- days_since_visit stays NaN where the visit date is unknown; is_post_visit is three-valued so that the state 'unknown' does not become 'before visit'

- [ok] visit day at most once per household
- [ok] households with a known visit date as documented - 55 households (56 in the raw data, one of them removed)
- [ok] days_since_visit set only where the visit date is known

### Validate the smart meter data

| Metric | Value |
|---|---|
| Households with heat-pump submetering | 7 |
| Rows without a target value (incl. gaps) | 2,313 |
| Rows with a target value | 84,498 |

- [ok] (Household_ID, date) unique
- [ok] daily grid gapless (precondition for all shift features) - 153 groups gapless
- [ok] no negative measurements - 10 columns checked
- [ok] total equals HeatPump + Other where submetering exists - 3355 rows with submetering, maximum deviation 0.00 kWh, 0 rows above the tolerance of 0.5 kWh
- [ok] submetering coverage as documented - 7 households (10 in the raw data - the three removed households meter the heat pump only)

### Extend the master data with quality metrics

| Metric | Value |
|---|---|
| Median days per household | 488 |
| Households with fewer than 365 days | 57 |
| Longest single gap across all households | 333 days |
| Mean missing rate of the target value | 1.77 % |

- [ok] enrichment multiplies no rows - master data x quality statistics: 153 -> 153 rows

### Validate the weather data hourly

- [ok] (Weather_ID, Timestamp) unique
- [ok] hourly grid gapless (precondition for the daily aggregation) - 8 stations gapless hourly
- [ok] weather values within plausible bounds - 9 value ranges checked

### Remove redundant pressure channels

| Metric | Value |
|---|---|
| Stations with values in Pressure_BarometricHeight_avg_hourly | 5 |
| Stations with values in Pressure_SeaLevelStandardAtmosphere_avg_hourly | 5 |
| Stations with values in Pressure_SeaLevel_avg_hourly | 4 |

- Pressure_BarometricHeight_avg_hourly is carried forward; the other channels are conversions of the same measurement and carry no additional information at equal or worse coverage

### Forward-fill short hourly gaps

| Metric | Value |
|---|---|
| Hourly values filled in total | 447 |
|   Temperature_avg_hourly | 88 |
|   DewPoint_hourly | 166 |
|   Humidity_avg_hourly | 91 |
|   WindSpeed_hourly | 102 |
| Structurally not measured (station does not carry the channel) | 135,792 |
| Genuine remaining gaps (station measures, value missing) | 3,730 |

- Forward fill with a limit of 3 h, exclusively with values before the gap. Precipitation and sunshine are not filled - they are spiky, and carrying them forward would invent rain that never fell

### Aggregate the weather to daily level

| Metric | Value |
|---|---|
| Hourly rows in | 362,112 |
| Daily rows out | 15,088 |
| Stations | 8 |
| Days with a full 24 hourly rows | 15,088 |
| Temperature_avg_hourly: full-day outages / partial outages | 10 / 22 |
| DewPoint_hourly: full-day outages / partial outages | 10 / 24 |
| Humidity_avg_hourly: full-day outages / partial outages | 10 / 24 |
| WindSpeed_hourly: full-day outages / partial outages | 61 / 45 |
| Pressure_BarometricHeight_avg_hourly: channel not carried at the station | 5,658 station days |
| Precipitation_total_hourly: full-day outages / partial outages | 45 / 53 |
| Sunshine_duration_hourly: full-day outages / partial outages | 0 / 1 |
| Sunshine_duration_hourly: channel not carried at the station | 5,658 station days |
| Daily rows with an incomplete data basis | 218 |
| Heating degree days mean | 6.01 |
| Days with HDD equal to 0 | 4,566 |
| Stations without sunshine | 3 |
| Stations without pressure | 3 |

- A daily value is only formed from at least 20 valid hours, otherwise NaN. This also catches a trap of sum aggregation: `sum` over all-missing hours returns 0.0, not NaN - without the mask the three stations without sunshine measurement would show exactly zero minutes of sun every day, an invented measurement
- 11316 station days concern channels the respective station does not carry at all (sunshine and pressure at three stations) - a known property, marked via station_has_*. To be distinguished from those are 136 genuine full-day outages and 169 partial outages at stations that do carry the channel; only these set weather_day_incomplete
- hdd_15 = max(0, 15 - daily mean temperature); NaN parity with the temperature, no filling. The base temperature is part of the column name and changeable in config.py in one place - the name follows along

- [ok] every day has 24 hourly rows - 0 days with a deviating hour count
- [ok] (Weather_ID, date) unique in the daily aggregate

### Write results as parquet

| Metric | Value |
|---|---|
| smart_meter_daily.parquet | 86,811 rows x 20 columns |
| households.parquet | 153 rows x 39 columns |
| weather_hourly.parquet | 362,112 rows x 10 columns |
| weather_daily.parquet | 15,088 rows x 16 columns |

- Metrics machine-readable in data\interim\quality_report.json

- [ok] Parquet round trip without dtype drift - verified for all four tables

---

## Stage 3 - Panel, Features & Split

_Run: 2026-08-01T07:18:24+00:00 UTC - status: successful_

### Read the results of stage 2

| Metric | Value |
|---|---|
| Smart meter rows | 86,811 |
| Households | 153 |
| Weather daily rows | 15,088 |

- Source: data\interim\02_clean (stage-2 output only)

### Date the weather to the forecasting point in time

| Metric | Value |
|---|---|
| Weather daily rows | 15,088 |
| Shifted weather columns | 13 |
| of which rolling statistics | 2 |
| Shift | 1 days |
| Valid for target days from | 2019-01-02 |
| Valid for target days to | 2024-03-01 |

- The weather columns keep the name of their daily aggregate and contain the observation from d-1. The shift is therefore no longer readable from the name - it is proven in prove_leakage_free for each column individually against an independent self-join, including a counter-check against the target-day value
- No target-day weather is carried along: only observed values enter, no forecast. A perfect-forecast assumption is not made

### Assemble the panel

| Metric | Value |
|---|---|
| Panel rows | 86,811 |
| Panel columns | 52 |

- Household-wide metrics (n_days, target_missing_rate, ...) are deliberately NOT joined into the panel - they are computed over the entire period and would carry information from the test window into the training rows

- [ok] join with the master data multiplies no rows - panel x master data: 86811 -> 86811 rows
- [ok] join with the weather multiplies no rows - panel x shifted weather: 86811 -> 86811 rows
- [ok] join with the station properties multiplies no rows - panel x station properties: 86811 -> 86811 rows
- [ok] station_has_sunshine populated on all rows - 0 rows without a value
- [ok] station_has_pressure populated on all rows - 0 rows without a value
- [ok] (Household_ID, date) unique after the joins

### Trim the panel to the usable time window

| Metric | Value |
|---|---|
| Trim active | yes |
| Window from | 2019-01-02 |
| Window to | 2024-03-01 |
| Rows before | 86,811 |
| Rows after | 83,398 |
| Discarded rows | 3,413 |
| of which with a target value | 3,413 |
| Households before | 153 |
| Households after | 153 |
| Households affected | 100 |

- The window is the weather window (2019-01-01 to 2024-02-29) moved back by 1 day(s), because every target day needs the observation from d-1

- [ok] no date outside the window
- [ok] daily grid still gapless after the trim - 153 groups gapless

### Autoregressive features (leakage firewall)

| Metric | Value |
|---|---|
| Lag columns | 5 |
| Rolling columns | 4 |
| Active lags | d-1, d-7 |
| Smallest lag used | 1 days |
| Shift before the rolling | 1 days |
| min_periods in the 7-day window | 4 |
| Rows without a lag-7 value (edges and gaps) | 3,358 |
| Rows without a lag-1 value | 2,464 |

- Edges stay NaN: no backfill (would be leakage), no forward fill (would be invented). Filtering these rows is left to the modeling stage so that the panel keeps its complete calendar structure
- After a calendar gap the lags are NaN as well, because the target value is missing in the gap rows - exactly the desired behaviour

### Calendar features

| Metric | Value |
|---|---|
| Calendar columns | 7 |
| Holidays in the panel | 1,991 |
| Distinct holiday dates | 45 |
| Weekend rows | 23,785 |

- Holidays taken nationally (holidays.Germany without subdiv). The household locations are only known through anonymised weather stations, a federal state cannot be assigned - state-specific holidays would be guesswork
- Day length was deliberately left out: at a fixed latitude it is a deterministic function of the day of year and therefore already covered by doy_sin/doy_cos; computing it would require a latitude assumption the data does not support

### Feature selection

| Metric | Value |
|---|---|
| Features autoregressive | 4 active, 5 in reserve |
| Features weather | 9 active, 4 in reserve |
| Features calendar | 5 active, 2 in reserve |
| Features regime | 1 active, 2 in reserve |
| Features static | 1 active, 17 in reserve |
| Active features in total | 20 |
| Reserve columns in total | 30 |

- Reserve autoregressive: recv_lag3, recv_lag9, recv_lag14, recv_roll28_mean, recv_roll28_std - Lags 1 and 7 cover the daily and weekly rhythm, roll7 the level. Lags 3, 9, 14 and roll28 are strongly correlated with them and cost additional edge rows: roll28 needs 14 populated days of lead-in.
- Reserve weather: WindSpeed_hourly_max, Pressure_BarometricHeight_avg_hourly_mean, hdd_15_roll7_mean, Temperature_avg_hourly_mean_roll7_mean - Pressure is structurally missing at 3 of 8 stations (37.5 percent) and is of secondary importance for heating demand. The wind maximum is highly correlated with the mean. The rolling weather windows represent building inertia - a hypothesis to be tested against the baseline, not to be assumed up front.
- Reserve calendar: doy_sin, doy_cos - doy_sin and doy_cos encode the yearly seasonality, which is already in the set via month and season. They remain available as a smooth alternative for linear models.
- Reserve regime: is_visit_day, days_since_visit - days_since_visit cannot be determined for 98 of 153 households (40 percent of the rows NaN). is_visit_day affects 56 rows in the whole panel - too few for a pooled model. The intervention state itself stays active.
- Reserve static: pv_flag_imputed, has_meta_survey, has_heatpump_submeter, station_has_sunshine, station_has_pressure, Survey_Building_Type, Survey_HeatPump_Installation_Type, Survey_Building_LivingArea, Survey_Building_Residents, Survey_HeatDistribution_System_FloorHeating, Survey_HeatDistribution_System_Radiator, Survey_DHW_Production_ByHeatPump, Survey_DHW_Production_ByElectricWaterHeater, Survey_DHW_Production_BySolar, Survey_Installation_HasDryer, Survey_Installation_HasFreezer, Survey_Installation_HasElectricVehicle - Survey attributes and equipment flags are time-invariant and can only shift the level in the pooled model that recv_lag1 and recv_roll7_mean already carry. Four survey columns additionally have 44 to 95 percent non-responses. Their contribution is the question of the ablation experiment.
- The reserve columns stay in the panel so that a comparison model using them is possible without a new pipeline run. They are listed in the schema under 'deselected', not under 'feature_groups' - a modeling script that follows the schema does not see them

- [ok] all active features exist in the panel - []
- [ok] no column twice in the selection - []
- [ok] no passthrough or target column in the selection - 20 features checked
- [ok] no row quality flag used as a feature - []

### Leakage proofs

| Metric | Value |
|---|---|
| Weather columns passing the shift proof | 11 of 11 |

- The weather columns no longer carry a lag suffix but the name of the daily aggregate. The shift by 1 day(s) is therefore evidenced exclusively here - per column against an independent self-join, with a counter-check against the target-day value. Whoever reads the names must mind forecast_lag_days in the schema: it is an observation, not a target-day value

- [ok] recv_lag1 carries the target value of d-1 - 200 samples, 0 deviations, 0 without a counterpart
- [ok] recv_lag7 carries the target value of d-7 - 200 samples, 0 deviations, 0 without a counterpart
- [ok] first row of every household without lag values (groupby takes effect) - 153 households, all lag columns empty at the start of the series
- [ok] Temperature_avg_hourly_mean carries the observation from d-1 - 2000 samples, 0 deviations
- [ok] Temperature_avg_hourly_mean is not the target-day value - 2000 of 2000 samples differ from the target-day value
- [ok] Temperature_avg_hourly_min carries the observation from d-1 - 2000 samples, 0 deviations
- [ok] Temperature_avg_hourly_min is not the target-day value - 1971 of 2000 samples differ from the target-day value
- [ok] Temperature_avg_hourly_max carries the observation from d-1 - 2000 samples, 0 deviations
- [ok] Temperature_avg_hourly_max is not the target-day value - 1957 of 2000 samples differ from the target-day value
- [ok] DewPoint_hourly_mean carries the observation from d-1 - 2000 samples, 0 deviations
- [ok] DewPoint_hourly_mean is not the target-day value - 1995 of 2000 samples differ from the target-day value
- [ok] Humidity_avg_hourly_mean carries the observation from d-1 - 2000 samples, 0 deviations
- [ok] Humidity_avg_hourly_mean is not the target-day value - 1999 of 2000 samples differ from the target-day value
- [ok] WindSpeed_hourly_mean carries the observation from d-1 - 2000 samples, 0 deviations
- [ok] WindSpeed_hourly_mean is not the target-day value - 1986 of 2000 samples differ from the target-day value
- [ok] WindSpeed_hourly_max carries the observation from d-1 - 2000 samples, 0 deviations
- [ok] WindSpeed_hourly_max is not the target-day value - 1950 of 2000 samples differ from the target-day value
- [ok] Pressure_BarometricHeight_avg_hourly_mean carries the observation from d-1 - 2000 samples, 0 deviations
- [ok] Pressure_BarometricHeight_avg_hourly_mean is not the target-day value - 1995 of 2000 samples differ from the target-day value
- [ok] Precipitation_total_hourly_sum carries the observation from d-1 - 2000 samples, 0 deviations
- [ok] Precipitation_total_hourly_sum is not the target-day value - 1260 of 2000 samples differ from the target-day value
- [ok] Sunshine_duration_hourly_sum carries the observation from d-1 - 2000 samples, 0 deviations
- [ok] Sunshine_duration_hourly_sum is not the target-day value - 1775 of 2000 samples differ from the target-day value
- [ok] hdd_15 carries the observation from d-1 - 2000 samples, 0 deviations
- [ok] hdd_15 is not the target-day value - 1441 of 2000 samples differ from the target-day value

### Remove the inserted calendar gap rows

| Metric | Value |
|---|---|
| Rows before | 83,398 |
| Gap rows removed | 1,347 |
| Rows after | 82,051 |
| Households affected | 39 |
| Households before / after | 153 / 153 |

- The gap rows only ever served the correctness of shift and rolling on a gapless daily grid. Now that the features exist they carry no information: not one of the 10 measurement columns is populated on them, the target value included
- Consequence for downstream stages: the panel is deliberately NO LONGER gapless per household. Any further time series operation on the model table would have to reindex first - the features built here are unaffected, they were computed on the complete grid

- [ok] gap rows carry no measurement at all - 10 meter columns checked, all empty on the gap rows
- [ok] no row without a target value left over from the gaps

### Assign the temporal train/test split

| Metric | Value |
|---|---|
| Cutoff (last training day) | 2023-06-30 |
| Rows train | 66,400 |
| Rows test | 15,651 |
| Test share of all rows | 19.07 % |
| Rows with a target value train | 65,502 |
| Rows with a target value test | 15,583 |
| Test share of the labelled rows | 19.22 % |
| Training period | 2019-01-02 to 2023-06-30 |
| Test period | 2023-07-01 to 2024-03-01 |
| Households in training | 146 |
| Households in test | 71 |

- Households only in the test set (without training history): ['109104', '412211', '731027', '758039', '768113', '841211', '877881']
- 82 households appear only in training - their recording ends before the cutoff
- A fleet-wide cutoff instead of 'the last X percent per household': otherwise training rows of one household would lie calendrically after test rows of another

- [ok] test starts strictly after the end of training - 2023-06-30 < 2023-07-01
- [ok] boundary day belongs to train
- [ok] split column fully populated

### Usability of the panel

| Metric | Value |
|---|---|
| Panel rows | 82,051 |
| of which with a target value | 81,085 |
| Share of modelable rows | 98.82 % |
| Modelable rows without recv_lag1, recv_lag7 | 1,315 |
| Modelable rows without weather (station outage) | 107 |
| Households without a single modelable row | 0 |
| Median modelable rows per household | 428 |

- Neither lags nor weather are a condition of is_modelable. A missing lag follows a meter outage, a missing weather value a station outage - both happen in production, and a fleet that has to bid every day cannot skip those days. The model has to handle the NaN (tree models do so natively) instead of having the rows removed from its evaluation
- Feature availability stays readable per row from the columns themselves (recv_lag1, recv_lag7, Temperature_avg_hourly_mean). A modeling script that needs the strict subset can reproduce it in one line - the reverse, recovering rows a flag already discarded, is not possible
- The column is_modelable marks rows with a target value - nothing else. That makes the evaluation set model-independent: models with different feature requirements are scored on the same rows and stay comparable

### Final feature pre-selection

| Metric | Value |
|---|---|
| Renamed columns | 2 |
| Target | gross_load |
| Keys | Household_ID, date |
| Categorical dtype | weather_id (8 levels), season (4 levels) |
| Contract features | 21 |
| Rows train (modelable) | 65,502 |
| Exact functional dependencies | 3 |
| Correlated pairs (|r| >= 0.9) | 10 |

- The rename happens at the very end of stage 3, after the leakage proofs and the split. Everything upstream keeps the source names, so the report and docs/decisions.md stay readable against the raw data; the mapping is recorded in the schema under preselection.renamed
- kWh_received_Total becomes gross_load: the quantity is the gross draw from the grid, before any netting against PV self-consumption. The name states what it is rather than how it was metered
- weather_id enters as a feature and is cast to category. With 8 levels it carries the regional offset the weather columns do not capture - but it is invariant per household, so it also encodes fleet structure. See docs/decisions.md D-21
- The pre-selection is a declaration, not a search: it does not shorten the list. It proves the list is sound and reports what a reader would otherwise have to rediscover. Anything computed against the target belongs in the modeling stage, inside the cross-validation - otherwise the selection error appears in no metric
- Not fully populated on train (kept deliberately - a missing value is a meter or station outage, a state the model has to handle rather than be spared from, see D-19): Sunshine_duration_hourly_sum 90.83%, recv_lag7 98.16%, recv_roll7_mean 98.99%, recv_roll7_std 98.99%, recv_lag1 99.70%, WindSpeed_hourly_mean 99.71%, Precipitation_total_hourly_sum 99.75%, Humidity_avg_hourly_mean 99.92%, DewPoint_hourly_mean 99.92%, Temperature_avg_hourly_mean 99.93%, Temperature_avg_hourly_min 99.93%, Temperature_avg_hourly_max 99.93%, hdd_15 99.93%
- Exact functional dependencies among the features: is_weekend = f(dow); season = f(month); hdd_15 = f(Temperature_avg_hourly_mean). Tree models are invariant to a monotone transform of a single feature, so these carry no additional information for RF or LightGBM - they do for a linear model, where the kink is real. Reported, not removed: the choice belongs to the model, not to the panel
- Feature pairs with |r| >= 0.9: Temperature_avg_hourly_mean/Temperature_avg_hourly_max 0.973; Temperature_avg_hourly_mean/hdd_15 0.958; recv_lag7/recv_roll7_mean 0.951; recv_lag1/recv_roll7_mean 0.951; Temperature_avg_hourly_mean/Temperature_avg_hourly_min 0.950; Temperature_avg_hourly_min/DewPoint_hourly_mean 0.949; Temperature_avg_hourly_max/hdd_15 0.927; Temperature_avg_hourly_min/hdd_15 0.923; Temperature_avg_hourly_mean/DewPoint_hourly_mean 0.916; DewPoint_hourly_mean/hdd_15 0.902. Deliberately not filtered: multicollinearity costs tree models interpretability of the importances, not accuracy. Dropping the temperature extremes would cost exactly the cold days that matter most for procurement

- [ok] all columns to be renamed exist in the panel - kWh_received_Total -> gross_load, Weather_ID -> weather_id
- [ok] no contract name is already occupied
- [ok] feature_groups and preselection.features describe the same set - 21 columns in both
- [ok] the configured HDD column (hdd_15) is part of the contract - HDD_BASE_C=15 produces hdd_15
- [ok] all contract features exist in the panel - missing: []
- [ok] no feature listed twice - []
- [ok] target and keys exist - missing: []
- [ok] no target, passthrough or row flag among the features - 16 forbidden columns checked
- [ok] no feature constant on train - 21 features checked
- [ok] every feature at least 80% populated on train - lowest: Sunshine_duration_hourly_sum 90.8%

### Reduce the panel to the contract columns

| Metric | Value |
|---|---|
| Slim panel | yes |
| Columns before | 70 |
| Columns dropped | 44 |
| Columns kept | 26 |
| Kept | 2 keys, 1 target, 21 features, split and is_modelable |
| dropped - reserve (D-17) | 30 |
| dropped - passthrough | 9 |
| dropped - row flags | 3 |
| dropped - other | 2 |

- Dropped, reserve (D-17): Pressure_BarometricHeight_avg_hourly_mean, Survey_Building_LivingArea, Survey_Building_Residents, Survey_Building_Type, Survey_DHW_Production_ByElectricWaterHeater, Survey_DHW_Production_ByHeatPump, Survey_DHW_Production_BySolar, Survey_HeatDistribution_System_FloorHeating, Survey_HeatDistribution_System_Radiator, Survey_HeatPump_Installation_Type, Survey_Installation_HasDryer, Survey_Installation_HasElectricVehicle, Survey_Installation_HasFreezer, Temperature_avg_hourly_mean_roll7_mean, WindSpeed_hourly_max, days_since_visit, doy_cos, doy_sin, has_heatpump_submeter, has_meta_survey, hdd_15_roll7_mean, is_visit_day, pv_flag_imputed, recv_lag14, recv_lag3, recv_lag9, recv_roll28_mean, recv_roll28_std, station_has_pressure, station_has_sunshine
- Dropped, passthrough: kWh_received_HeatPump, kWh_received_Other, kWh_returned_Total, kvarh_received_capacitive_HeatPump, kvarh_received_capacitive_Other, kvarh_received_capacitive_Total, kvarh_received_inductive_HeatPump, kvarh_received_inductive_Other, kvarh_received_inductive_Total
- Dropped, row flags: is_gap, kWh_spike_flag, returned_was_substituted
- Dropped, other: Timestamp, visit_date
- The dropped columns were computed and checked as before - the run is identical up to this point, only the writing is conditional. config.PANEL_SLIM = False plus one run (about two seconds) restores them, which is what makes the ablation experiment from D-17 affordable despite the reduction
- The survey attributes remain available without any rerun: they live in 02_clean/households.parquet with one row per household (153 x 39) and join back over Household_ID. That is also the better source for segmentation, because it weights every household once instead of once per day - see D-20
- Not recoverable by a join, only by a rerun: the computed reserve features (recv_lag3/9/14, recv_roll28_*, doy_sin/cos, the rolling weather windows, pressure, WindSpeed_hourly_max, days_since_visit, is_visit_day) and the passthrough measurements used for the PV cross-check in D-20

- [ok] every contract column exists before the reduction - missing: []
- [ok] no forbidden column left in the panel - the measurement columns that sum to the target are gone
- [ok] row count unchanged by the reduction - 82,051 rows

### Write the panel

| Metric | Value |
|---|---|
| model_table.parquet | 82,051 rows x 26 columns |

### Write the split frames

| Metric | Value |
|---|---|
| panel_train.parquet | 65,502 rows x 24 columns |
| panel_test.parquet | 15,583 rows x 24 columns |
| Rows dropped as unlabelled | 966 |

- Rows are restricted to is_modelable - the target value is present (D-19). The flag itself is not carried along, so the filter has to be applied here: a y with holes and no column left to detect them would be worse than the 966 missing rows
- split is not a column of these files - it is the file name. The panel keeps both it and is_modelable, so the two frames stay derivable from it and nothing is stored twice for a different purpose
- Categorical levels were checked for equality across the two files. Derived per frame they could diverge, and a code would then mean a different station in train than in test - a failure that shows up as a slightly worse metric, never as an error

- [ok] every contract column exists for the split frames - missing: []
- [ok] panel_train.parquet without a gap in gross_load - 65,502 rows, all labelled
- [ok] panel_test.parquet without a gap in gross_load - 15,583 rows, all labelled
- [ok] the test frame starts strictly after the training frame - 2023-06-30 < 2023-07-01
- [ok] weather_id carries the same categories in both files - 8 levels
- [ok] season carries the same categories in both files - 4 levels

### Write the schema

| Metric | Value |
|---|---|
| model_table_schema.json | 5 feature groups, 21 active features |

- The modeling stage builds its feature list from preselection.features in the schema, never from panel.columns: kWh_received_HeatPump and kWh_received_Other sum to the target exactly, so a naive 'everything except gross_load' would be reading the answer
- Output directory: data\processed
