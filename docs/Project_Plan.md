# Projektplan: Data Understanding & Data Preparation

_E.ON Day-Ahead Energy Forecasting — TUM SS26, CRISP-DM_
_Ergänzt die Gedankensammlung in [Data_Preparation.md](Data_Preparation.md) um einen umsetzbaren Plan._

> **Hinweis:** Dieses Dokument ist der **Entwurf** und wird als Entstehungs­geschichte
> bewusst nicht rückwirkend umgeschrieben. Vier Festlegungen wurden nach dem Entwurf
> geändert; maßgeblich ist in diesen Punkten [decisions.md](decisions.md):
>
> | Entwurf sagt | Umgesetzt ist | Eintrag |
> |---|---|---|
> | `FORECAST_LAG = 2`, letzter beobachteter Tag *d−2* | **`FORECAST_LAG = 1`**, Gebot am Ende von *d−1* | D-05 |
> | `HDD = max(0, 18 − Temperature_mean)`, Spalte `hdd` | **Basis 15 °C**, Spalte `hdd_15` | D-10 |
> | Wetterspalten mit Suffix `_lag2`, Namensprüfung | **Aggregatnamen ohne Suffix**, Shift-Beweis je Spalte | D-16 |
> | alle gebauten Spalten sind Features (50) | **20 aktive Features**, 30 in Reserve | D-17 |
>
> Ebenfalls umbenannt: `after_visit` → `is_post_visit`, `dayofweek` → `dow`, die
> Wetter-Tagesaggregate nach dem Muster `<Rohspalte>_<Aggregatfunktion>`.
> Das Panelfenster ist damit **2019-01-02 bis 2024-03-01**.

---

## 1. Ziel und Rahmen

Für die Day-ahead-Beschaffung soll der Tagesstromverbrauch von Haushalten mit Wärmepumpe prognostiziert werden. Aus vier Rohquellen entsteht ein modellfertiges, leakage-sicheres **Haushalts-Tages-Panel** mit temporalem Train/Test-Split.

| Festlegung | Wert |
|---|---|
| Zielvariable | `kWh_received_Total` (Brutto-Netzbezug, kWh/Tag) |
| Prognosehorizont | Tag *d*, Gebotsabgabe am Tag *d−1* |
| Panel-Granularität | eine Zeile pro (`Household_ID`, `date`) |
| Zeitliche Auflösung | Tag (UTC-Kalendertag) |
| `kWh_returned_Total` | wird durchgereicht, ist **kein** Modell-Input |

---

## 2. Datenbasis (verifizierter Ausgangszustand)

| Quelle | Umfang | Kernbefunde |
|---|---|---|
| `smart_meter_daily/*.csv` | 156 Dateien, 88.791 Zeilen | 5–1.846 Tage je Haushalt (Median 492); 57 Haushalte < 365 Tage; 41 Haushalte mit Kalenderlücken > 1 Tag (max. 334 Tage); 4.293 fehlende Zielwerte; keine Duplikate, keine Negativwerte |
| `smart_meter_meta_data/households.csv` | 156 Zeilen | alle Gruppe `treatment`; 39 Haushalte mit PV, 1 PV-Flag fehlt; `Weather_ID` verweist auf 8 Stationen |
| `smart_meter_meta_data/meta_data.csv` | **142** Zeilen | Survey-Merkmale; deckt nur 142 der 156 Haushalte ab; leere Boolean-Zellen bedeuten *unbekannt*, nicht *False* |
| `weather_data_hourly/*.csv` | 8 Stationen, je 45.264 Zeilen | stündlich **lückenlos** 2019-01-01 bis 2024-02-29; NaN-Anteil < 1,1 %; 3 Stationen ohne Sunshine und Pressure |

**Zwei strukturelle Konsequenzen:**

1. **3 Haushalte ohne jeden Zielwert** (`747511`, `768498`, `996610`) — sie werden in Stufe 1 entfernt, es bleiben **153 Haushalte**. Drei weitere Haushalte haben unter 30 Messwerte (`109104`, `461104`, `7086681`); sie bleiben erhalten, werden aber über `n_days` ausgewiesen.
2. **Zeitraum-Mismatch:** Smart-Meter-Daten reichen von 2018-11-02 bis 2024-03-20, Wetterdaten nur von 2019-01-01 bis 2024-02-29. Das finale Panel wird auf die Schnittmenge beschnitten; der Verlust wird im Report beziffert.
3. **`AffectsTimePoint` hat vier Zustände, nicht zwei** (in Stufe 1 verifiziert): `before visit` (65.364 Zeilen), `after visit` (23.355), `during visit` (56) und `unknown` (16). `during visit` tritt je Haushalt **genau einmal** auf — es ist der Besuchstag selbst und damit ein Übergangstag, der zu keinem der beiden Regime gehört. Die Abfolge ist bei allen Haushalten monoton. Es gibt vier Verlaufsmuster:

| Haushalte | Muster | Bedeutung |
|---|---|---|
| 78 | nur `before visit` | Besuch fällt nicht ins Datenfenster |
| 56 | `before visit → during visit → after visit` | sauberer Übergang, Besuchsdatum bekannt |
| 21 | nur `after visit` | Besuch liegt vor Aufzeichnungsbeginn, Datum unbekannt |
| 1 | `before visit → unknown` | Status am Ende der Reihe unklar |

Konsequenz für die Regime-Features: `visit_date` ist nur für die 56 Haushalte mit `during visit` bestimmbar. `after_visit` wird dreiwertig geführt (`False` / `True` / `<NA>` für `unknown`), der Besuchstag erhält ein eigenes Flag `is_visit_day`, und `days_since_visit` bleibt für die 99 Haushalte ohne bekanntes Besuchsdatum NaN.

Die Datei `smart_meter_data_daily_overview.csv` enthält 1.298 Zeilen und damit mehr Haushalte als geliefert. Sie dient ausschließlich als Cross-Check und wird nicht gejoint.

---

## 3. Entscheidungen zu den offenen Fragen

### 3.1 Warum drei Stufen — und was gehört wohin?

Drei Datenzonen (`raw` → `interim` → `processed`), drei ausführbare Skripte. Die Aufteilung folgt dem Prinzip **eine Stufe, eine Art von Eingriff**:

| Stufe | Eingriffsart | Was hier *nicht* passiert |
|---|---|---|
| 1 — Laden | Einlesen, typisieren, Haushalte ohne Zielwert entfernen, Stammdaten zusammenführen | keine inhaltliche Korrektur, keine Aggregation |
| 2 — Cleaning & Validierung | Kalenderstruktur herstellen, flaggen, Wetter aggregieren, Sanity Checks | keine Feature-Bildung, kein Join aufs Panel |
| 3 — Panel | Merge, Feature Engineering, Leakage-Shift, Split | keine Datenkorrektur mehr |

Schema- und Parsing-Prüfungen laufen bereits in Stufe 1 (*fail fast* — ein falscher Header soll nicht erst nach Minuten auffallen). Die inhaltliche Validierung (Wertebereiche, Kalendervollständigkeit, Konsistenz) gehört in Stufe 2, weil sie die dort hergestellte Struktur prüft.

### 3.2 Wetter: erst cleanen oder erst auf Tagesebene aggregieren?

**Erst cleanen (stündlich), dann aggregieren.** Drei Gründe:

- Kurze Lücken lassen sich nur auf Stundenebene sinnvoll füllen — nach der Aggregation ist die fehlende Stunde nicht mehr adressierbar.
- Die Vollständigkeitsprüfung (24 Stunden pro Tag) ist definitionsgemäß nur stündlich möglich.
- Wer zuerst aggregiert, verschmiert fehlende Stunden unsichtbar in die Tageswerte: eine Tagesmitteltemperatur aus 18 statt 24 Stunden sieht aus wie ein gültiger Wert.

### 3.3 Um wie viele Tage wird verschoben?

Das Gebot für Zieltag *d* wird am Tag *d−1* vormittags abgegeben. Zu diesem Zeitpunkt ist Tag *d−1* noch nicht vollständig gemessen. **Der letzte vollständig beobachtete Tag ist also *d−2*.**

Da bewusst **keine Forecast-Proxy-Annahme** getroffen wird (kein „wir tun so, als kennten wir das Wetter von morgen"), gilt dieser Shift für **alle** zeitveränderlichen Größen — Messwerte *und* Wetter. Nur was für den Zieltag deterministisch bekannt ist, geht ungeschoben ein.

| Spaltengruppe | Shift | Begründung |
|---|---|---|
| Ziel-Lags und Rollings aus `kWh_received_Total` | **≥ 2 Tage** | autoregressiv; Tag *d−1* ist bei Gebotsabgabe unvollständig |
| **Alle Wetter-Features** (Temperatur, HDD, Sunshine, Wind, …, inkl. Wetter-Rollings) | **≥ 2 Tage** | ohne Forecast-Proxy sind nur beobachtete Werte verfügbar; gleiche Verfügbarkeitslogik wie Messwerte |
| Kalender, Feiertage, Tageslänge | 0 | für den Zieltag deterministisch bekannt |
| Statische Haushaltsmerkmale, `after_visit`, `days_since_visit` | 0 | zum Gebotszeitpunkt bekannt |
| `kWh_returned_Total`, `kvarh_*`, Submetering, Flags | — | Passthrough, nie Feature |

Eine Forecast-Proxy-Variante (Zieltags-Wetter als exogener Prädiktor) kann später als **klar gekennzeichnetes Vergleichsexperiment** ergänzt werden — sie ist nicht Teil der Basis-Pipeline.

### 3.4 Ränder bei Lag-Features

Lags und Rollings werden **pro Haushalt** (`groupby`) auf dem lückenlosen Kalender gebildet. Dabei entstehen zwangsläufig NaN:

- die ersten `max_lag` Tage jeder Haushaltshistorie,
- die Tage direkt nach einer Kalenderlücke.

**Diese NaN bleiben stehen.** Backfill wäre Leakage (Zukunftswerte), Forward-Fill würde Werte erfinden. Rolling-Fenster werden mit explizitem `min_periods` konfiguriert, damit die Politik nachvollziehbar ist statt implizit. Zeilen ohne vollständige Pflicht-Prädiktoren werden erst im Modeling gefiltert — so bleibt das Panel-Artefakt vollständig und der Verlust nachvollziehbar. Der Report beziffert je Haushalt, wie viele Zeilen dadurch unbrauchbar sind.

### 3.5 Leakage beim Imputieren

Die Imputationsregeln sind **strikt kausal** — es werden ausschließlich Werte verwendet, die *vor* dem Imputationszeitpunkt liegen:

1. **Die Zielvariable wird nie imputiert.** Fehlende Zielwerte bleiben NaN.
2. **Einzige Zeitreihen-Imputation:** kurze stündliche Wetterlücken per **Forward-Fill mit Limit 3 Stunden**. Keine Interpolation, da diese Werte *nach* der Lücke einbeziehen würde. Längere Lücken bleiben NaN.
3. **Keine globalen Statistiken** (Mittelwert, Median über den Gesamtdatensatz) in der Data Preparation. Falls das Modell später Imputation statischer Merkmale braucht, wird der Imputer **ausschließlich auf dem Train-Split gefittet** (Modeling-Phase).
4. **Kategoriale Lücken** werden nicht imputiert, sondern als explizite Kategorie `"unknown"` geführt.

### 3.6 Vollständigkeit der Zeitreihe vor temporalen Features

Ein `shift(k)` ist nur dann semantisch korrekt, wenn die Zeile *k* Positionen zurück tatsächlich dem Tag *d−k* entspricht. Bei 41 Haushalten mit Kalenderlücken ist das ohne Vorbereitung **nicht** gegeben — ein `shift(2)` würde dort über die Lücke springen und einen Wert von vor Wochen als „vorgestern" ausgeben.

Daher als **harte Vorbedingung** vor jedem Feature-Bau:

1. Kalender-Reindexing in Stufe 2: jeder Tag zwischen `first_date` und `last_date` jedes Haushalts existiert als Zeile (fehlende Tage als NaN-Zeilen mit `is_gap = True`).
2. Assert: `date.diff() == 1 Tag` innerhalb jedes Haushalts, und `(Household_ID, date)` eindeutig.
3. Wetter analog: stündlich lückenlos vor der Aggregation, per Assert bewiesen.

Verletzung dieser Asserts bricht die Pipeline ab. Kein globaler Flottenkalender — reindiziert wird nur innerhalb der echten Abdeckung jedes Haushalts, damit keine Zeilen für Zeiträume entstehen, in denen der Zähler nachweislich nicht lief.

### 3.7 Weitere Punkte aus der Gedankensammlung

- **Datentypen konvertieren:** in Stufe 1, zentral über Dtype-Maps in `utils/io.py`. IDs bleiben Strings (keine Integer — führende Nullen und Vergleichbarkeit).
- **Metadaten-Merge:** die *statische* Zusammenführung `households` + `meta_data` passiert in Stufe 1 (ergibt eine Stammtabelle). Der Join auf das Panel erst in Stufe 3.
- **Data Understanding und Data Preparation:** getrennte Artefakte, iterativer Prozess — diagnostisches DU (Notebook 01) begründet die Pipeline, die Pipeline erzeugt das Panel, Insight-EDA (Notebook 02) auf dem Panel liefert Hypothesen, die als Features zurückfließen. Genau die in der Gedankensammlung vermutete Reihenfolge.

---

## 4. Zielstruktur des Repositories

```
data/
├── raw/                          # unangetastet, read-only
├── interim/
│   ├── smart_meter_daily.parquet
│   ├── households.parquet        # households + meta_data + Qualitätsstatistiken
│   ├── weather_hourly_clean.parquet
│   ├── weather_daily.parquet
│   └── quality_report.json       # maschinenlesbare Check-Ergebnisse
└── processed/
    └── model_table.parquet       # Panel mit Features, Target, split-Spalte

utils/                            # Poetry-Paket
├── config.py                     # Pfade, FORECAST_LAG=2, SPLIT_CUTOFF, Spaltenlisten
├── io.py                         # Loader je Quelle + Dtype-Maps, Parquet-Round-Trip
├── reporting.py                  # strukturiertes Konsolen-Logging + Markdown-Report
├── loading.py                    # Stufe 1
├── cleaning/
│   ├── smart_meter.py            # Reindexing, Flags, visit_date, returned-Substitution
│   └── weather.py                # stündliches Cleaning, Tagesaggregation, HDD
├── checks.py                     # Sanity Checks, geben Report-Einträge zurück
├── merge.py                      # Stufe 3: Joins mit m:1-Asserts
├── features.py                   # Lags, Rollings, Kalender, Leakage-Shift
└── splits.py                     # globaler temporaler Cutoff

scripts/
├── 01_load.py                    # raw → interim (ingested)
├── 02_clean_validate.py          # interim → interim (clean) + Checks
└── 03_build_panel.py             # interim → processed

notebooks/
├── 01_du_diagnostic.ipynb        # Struktur, Qualität, Beziehungen (auf raw/interim)
└── 02_du_insights.ipynb          # inhaltliche EDA (auf processed)

docs/
├── Data_Preparation.md           # Gedankensammlung (unverändert)
├── Project_Plan.md               # dieses Dokument
└── decisions.md                  # Annahmen-Log (Shift-Regel, UTC-Grenze, Drops)

reports/
└── data_prep_report.md           # generiert, pro Lauf aktualisiert
```

**Leitprinzip: Notebooks erzählen, Module rechnen.** Jede Transformation ist eine Funktion in `utils/`; Notebooks importieren nur und visualisieren. Das ist Voraussetzung dafür, dass die Pipeline beim Code-Review reproduzierbar durchläuft:

```bash
poetry run python scripts/01_load.py
poetry run python scripts/02_clean_validate.py
poetry run python scripts/03_build_panel.py
```

Jedes Skript ist idempotent und einzeln lauffähig. Jede Stufe liest ausschließlich den Output der Vorstufe — keine Rohdaten-Re-Reads in Stufe 2 oder 3.

---

## 5. Die drei Stufen im Detail

### Stufe 1 — Laden (`scripts/01_load.py`)

1. **Einlesen:** 156 Haushalts-CSVs (Semikolon-getrennt), 8 Wetterdateien, 2 Metadaten-Dateien. Header wird gegen die erwartete Spaltenliste geprüft; Abweichung → `ValueError` mit Dateinamen. Dateizahl-Gate: exakt 156 und 8.
2. **Typisieren:** `kWh_*` und `kvarh_*` → `float64` (leere Felder → NaN, keine Imputation); `Household_ID`, `Weather_ID`, `Group`, `AffectsTimePoint` → String bzw. Kategorie; `Timestamp` → tz-aware UTC. Einzige Projektion: `date = Timestamp.dt.normalize()`, danach `Timestamp` entfernen.
3. **Drop der 3 Haushalte ohne jeden Zielwert** (`747511`, `768498`, `996610`) — geloggt und im Report ausgewiesen. Verbleiben 153 Haushalte.
4. **Statische Stammtabelle:** `households` ⟵ Left Join `meta_data` auf `Household_ID`, mit Flag `has_meta_survey`. Leere Boolean-Zellen werden zu `<NA>` bzw. `"unknown"` — ausdrücklich **nicht** zu `False`.

### Stufe 2 — Cleaning & Validierung (`scripts/02_clean_validate.py`)

**Smart Meter:**

1. **Kalender-Reindexing** je Haushalt auf die eigene `[first_date, last_date]`-Spanne; innere Lücken als NaN-Zeilen mit `is_gap = True`. Dient der Korrektheit von `shift`/`rolling`, **nicht** dem Füllen.
2. **Vollständigkeits-Assert:** Tagesdifferenz == 1 und Eindeutigkeit von (`Household_ID`, `date`).
3. **Regime-Features ableiten:** `visit_date` = der eine Tag mit `AffectsTimePoint == "during visit"` (nur bei 56 Haushalten vorhanden); `after_visit` dreiwertig; `is_visit_day` als eigenes Flag; `days_since_visit` nur bei bekanntem Besuchsdatum. Konsistenzprüfung: höchstens ein Besuchstag je Haushalt, Abfolge monoton.
4. **`kWh_returned_Total`:** Haushalte ohne *jede* positive Einspeisung sind strukturell keine Einspeiser — deren NaN werden zu `0.0` mit Marker `returned_was_substituted`. Aktive Einspeiser behalten ihre NaN (echte Messlücken). Kein Doppel-Fill. Abgleich mit dem PV-Flag als Sanity Check, Abweichler werden gelistet.
5. **Ausreißer flaggen, nicht korrigieren:** robuster Marker je Haushalt auf `kWh_received_Total` (Median + k·MAD), berechnet auf den beobachteten Zeilen vor dem Reindex. Der Wert bleibt unangetastet.

**Wetter (erst cleanen, dann aggregieren):**

6. Stündliches Cleaning: Forward-Fill ≤ 3 h für glatte Größen; Wertebereichsprüfung; Assert lückenloses Stundenraster.
7. Tagesaggregation auf UTC-Tagesgrenze (identischer Dtype wie `date` im Meter-Frame → exakter Join): Temperatur mean/min/max, Humidity/DewPoint/Wind/Pressure mean, Precipitation/Sunshine sum.
8. Abgeleitet: `HDD = max(0, 18 − Temperature_mean)` — Heizgradtage als das für Wärmepumpen physikalisch wichtigste Signal. Die im `weather_data_overview` dokumentierten Daily-Varianten sind in den Rohdaten nicht enthalten und werden hier selbst berechnet.
9. Flag `weather_day_incomplete`, wenn ein Tag weniger als 20 der 24 Stunden gültig hat.

**Validierung und Anreicherung:**

10. Sanity Checks (Abschnitt 7) → `quality_report.json`. Harte Verstöße brechen ab, **nachdem** der Report geschrieben wurde, damit auch fehlgeschlagene Läufe ein vollständiges Protokoll hinterlassen.
11. Stammtabelle anreichern um `n_days`, `n_gaps`, `max_gap_days`, `target_missing_rate`, `returned_coverage`, `has_heatpump_submeter`, `visit_date`. Diese Tabelle ist gleichzeitig das Dateninventar für den Report.

### Stufe 3 — Finales Panel (`scripts/03_build_panel.py`)

1. **Merge** in fester Reihenfolge, jeder Join mit m:1-Assert (Zeilenzahl darf sich nicht ändern):
   `smart_meter_daily` ⟵ `households` (auf `Household_ID`) ⟵ verschobenes `weather_daily` (auf `Weather_ID`, `date`) ⟵ Stationseigenschaften (nur auf `Weather_ID`).
   Das Wetter wird dabei **umdatiert statt verschoben**: die Beobachtung vom Tag *D* erhält das Label *D+2*, dann joint man auf `date`. Das ist nicht nur kürzer als ein `groupby().shift(2)` nach dem Join, es verliert auch weniger Daten — ein Haushalt, dessen Reihe mitten im Wetterzeitraum beginnt, bekommt auch für seine ersten beiden Tage echte Wetterwerte.
2. **Zeitraum beschneiden** auf **2019-01-03 bis 2024-03-02**. Das ist das Wetterfenster (2019-01-01 bis 2024-02-29) um `FORECAST_LAG` Tage nach hinten versetzt, weil jeder Zieltag *d* die Beobachtung von *d−2* braucht. Verworfen werden 3.383 Zeilen; der Verlust wird im Report beziffert.
3. **Feature Engineering** je Haushalt auf dem lückenlosen Kalender:
   - Ziel-Lags: 2, 3, 7, 9 (= Vorwoche zum Lag-2-Zeitpunkt), 14
   - Rollings: mean/std über 7 und 28 Tage, **shift-before-rolling** (erst `shift(2)`, dann Fenster)
   - Wetter: alle Tagesaggregate mit `shift(2)`, zusätzlich Wetter-Rollings (z. B. HDD-7-Tage-Mittel) auf der geschobenen Reihe
   - Kalender: Wochentag, Monat, Jahreszeit, Wochenende, Feiertag (national), Tageslänge, zyklische Sinus/Kosinus-Terme
   - Regimewechsel: `after_visit`, `days_since_visit`
   - Statische Merkmale: PV-Flag, Wärmepumpentyp, Wohnfläche, Bewohner, Heizungsverteilung — kategoriale Lücken als `"unknown"`
4. **Leakage-Kontrolle:** `config.py` führt die Listen `FEATURE_COLS`, `TARGET_COL`, `PASSTHROUGH_COLS`; Assert `FEATURE_COLS ∩ PASSTHROUGH_COLS == ∅`. Zusätzlich Stichprobenbeweise: `lag_2` bei Tag *d* == Zielwert von *d−2*; Wetter-Feature bei *d* == Beobachtung von *d−2*.
5. **Temporaler Split:** ein **globaler Kalender-Cutoff** für die gesamte Flotte, aus `config.py`, so gewählt, dass etwa 20 % der Panel-Zeilen in den Test fallen. Grenztag → `train`, Test ist strikt Zukunft. Ergebnis: Spalte `split ∈ {train, test}`.
   *Begründung:* Day-ahead beschafft die gesamte Flotte für ein fixes Zukunftsfenster. Ein Split „letzte X % je Haushalt" würde bedeuten, dass Trainingsdaten eines Haushalts kalendarisch nach Testdaten eines anderen liegen — ein Informationsvorsprung, den es in der Realität nicht gibt. Ein Random Split ist ohnehin ausgeschlossen (Vorgabe der Case Study).
6. **Output** `model_table.parquet` mit Flag `target_available`. Zeilen mit fehlendem Ziel bleiben enthalten, damit die Kalenderstruktur intakt bleibt; gefiltert wird erst im Modeling.

---

## 6. Variablen und Missing-Value-Strategie je Tabelle

### 6.1 `smart_meter_daily` (153 Haushalte, Long-Format)

| Variable | Rolle | Umgang mit fehlenden Werten | Flag |
|---|---|---|---|
| `Household_ID`, `date` | Keys | dürfen nie fehlen (Assert); fehlende Kalendertage werden als Reindex-Zeilen ergänzt | `is_gap` |
| `Group` | konstant `treatment` | nach Prüfung entfernen (keine Information) | — |
| `AffectsTimePoint` | Quelle für die Regime-Features | darf nicht fehlen (Assert); nach Ableitung entfernen; Zustand `unknown` → `after_visit = <NA>` | `after_visit`, `is_visit_day` (abgeleitet) |
| `kWh_received_Total` | **Zielvariable** | **nie imputieren** — NaN bleibt NaN | `target_available` |
| `kWh_received_HeatPump` / `_Other` | Passthrough (nur 10 Haushalte) | NaN belassen | `has_heatpump_submeter` (je Haushalt) |
| `kWh_returned_Total` | Passthrough | Nie-Einspeiser: NaN → `0.0`; aktive Einspeiser: NaN belassen | `returned_was_substituted`, `returned_coverage` |
| `kvarh_*` (6 Spalten) | Passthrough | NaN belassen | — |

### 6.2 `households` ⟵ `meta_data` (Stammtabelle, 153 Haushalte)

| Variable | Rolle | Umgang mit fehlenden Werten | Flag |
|---|---|---|---|
| `Household_ID` | Key | darf nicht fehlen | — |
| `Weather_ID` | Join-Key Wetter | darf nicht fehlen (Assert — sonst verliert der Join Haushalte) | — |
| `Installation_HasPVSystem` | Feature (Level 1) | 1 fehlender Wert → `"unknown"`; ggf. über `kWh_returned > 0`-Evidenz auflösen und dokumentieren | `pv_flag_imputed` |
| `Protocols_*`, `SmartMeterData_Available_*`, `Group` | nur Cross-Check | nach Prüfung entfernen | — |
| `Survey_Building_Type`, `Survey_HeatPump_Installation_Type` | kategoriale Features | NaN → Kategorie `"unknown"` | `has_meta_survey` |
| `Survey_Building_LivingArea`, `Survey_Building_Residents` | numerische Features | NaN belassen (keine globale Imputation; falls nötig train-only im Modeling) | `has_meta_survey` |
| `Survey_HeatDistribution_*`, `Survey_DHW_*`, `Survey_Installation_Has*` | boolesche Features | leer ≠ `False` → dreiwertig `True` / `False` / `"unknown"` | `has_meta_survey` |
| abgeleitet: `n_days`, `n_gaps`, `max_gap_days`, `target_missing_rate`, `returned_coverage`, `visit_date` | Qualitäts- und Reporting-Spalten | — | — |

### 6.3 `weather_hourly` → `weather_daily` (8 Stationen)

| Variable | Tagesaggregation | Umgang mit fehlenden Werten (stündlich) | Flag |
|---|---|---|---|
| `Weather_ID`, `Timestamp` | Keys | lückenloses Stundenraster (Assert) | — |
| `Temperature_avg_hourly` | mean, min, max, → HDD | glatte Größe: Forward-Fill ≤ 3 h (nur Vergangenheitswerte), längere Lücken NaN | `weather_day_incomplete` bei < 20/24 gültigen Stunden |
| `DewPoint_hourly`, `Humidity_avg_hourly`, `WindSpeed_hourly` | mean | wie Temperatur (Forward-Fill ≤ 3 h) | dito |
| `Precipitation_total_hourly` | sum | **nicht füllen** (spikige Größe); Tagessumme NaN bei zu vielen fehlenden Stunden | dito |
| `Sunshine_duration_hourly` | sum | nicht füllen; 3 Stationen haben die Spalte gar nicht → Tageswert NaN | `station_has_sunshine` |
| `Pressure_*` (3 Varianten) | eine Variante wählen (beste Abdeckung), mean; übrige entfernen | 3 Stationen ohne Werte → NaN | `station_has_pressure` |
| abgeleitet: `HDD` | `max(0, 18 − Temperature_mean)` | NaN-Parität mit der Temperatur, kein `fillna` | — |

**Prinzip über alle Tabellen:** Imputiert wird nur, wo es physikalisch vertretbar *und* strikt kausal ist — also ausschließlich kurze stündliche Wetterlücken per Forward-Fill. Alles andere bleibt NaN plus Flag; die Entscheidung wandert ins Modeling, wo sie train-only getroffen werden kann.

---

## 7. Sanity Checks

Implementiert in `utils/checks.py`; Ergebnisse als strukturierte Einträge (pass/fail + Kennzahlen) in `data/interim/quality_report.json`.

**Stufe 1 — Laden**
1. Exakt 156 Haushalts-CSVs und 8 Wetterdateien vorhanden.
2. Header jeder Datei entspricht der erwarteten Spaltenliste.
3. `Household_ID` im Dateiinhalt stimmt mit dem Dateinamen überein.
4. Keine stillen `object`-Fallbacks nach der Typisierung (Round-Trip-Dtype-Check nach Parquet-Schreiben).
5. Alle Meter-Timestamps exakt `23:59:59+00:00`.

**Stufe 2 — Cleaning & Validierung**
6. `(Household_ID, date)` eindeutig; `(Weather_ID, Timestamp)` eindeutig.
7. **Kalender lückenlos nach Reindex** (Tagesdifferenz == 1 je Haushalt) — Voraussetzung für alle Shift-Features.
8. Alle `kWh_*` und `kvarh_*` ≥ 0 (keine Obergrenze — Ausreißer werden geflaggt, nicht abgeschnitten).
9. Wo Submetering vorliegt: `|Total − (HeatPump + Other)| ≤ Toleranz`; Verletzungen loggen.
10. `AffectsTimePoint`: nur die vier bekannten Zustände; höchstens ein `during visit` je Haushalt; Abfolge je Haushalt monoton (kein Rückfall in den Vor-Besuch-Zustand); Verlaufsmuster wie dokumentiert.
11. Wetter: Stundenraster lückenlos; Wertebereiche plausibel (Temperatur −30…45 °C, Humidity 0…100 %, Precipitation ≥ 0); 24 Stunden je Tag vor der Aggregation.
12. Referentielle Integrität: jede `Weather_ID` aus der Stammtabelle hat eine Wetterdatei; jede `Household_ID` aus dem Meter-Frame existiert in der Stammtabelle.
13. Regressions-Checks gegen die dokumentierten Befunde: 153 Haushalte nach Drop, davon 139 mit Survey-Daten (im Rohstand 142 von 156 — drei der entfernten Haushalte hatten einen Survey-Datensatz), 39 PV-Flags plus 1 unbekannt, rund 4.293 fehlende Zielwerte. Abweichung heißt: die Rohdaten haben sich geändert.

**Stufe 3 — Panel**
14. Jeder Join m:1 — Zeilenzahl nach dem Join unverändert.
15. Kein Datum außerhalb 2019-01-03…2024-03-02; Tagesraster nach dem Beschneiden weiterhin lückenlos.
16. Leakage-Beweise über einen **unabhängigen Self-Join** statt über die Feature-Logik selbst: jeder `recv_lag{k}` bei Tag *d* == Zielwert von *d−k* (für alle fünf Lags); `temp_mean_lag2` == Wetterbeobachtung von *d−2*; kein unverschobener Wettername im Panel.
17. Erste Zeile jedes Haushalts hat NaN in allen Lag-Spalten (Beweis, dass `groupby` greift und nicht über Haushaltsgrenzen geschoben wird).
18. `FEATURE_COLS ∩ PASSTHROUGH_COLS == ∅`; Split-Spalte vollständig belegt, Cutoff korrekt angewendet.

Harte Verstöße (Header-Drift, Duplikate, Kalenderlücken nach Reindex, Join-Vermehrung, Dtype-Drift) brechen die Pipeline ab. Weiche Befunde (Ausreißer, Missingness-Raten, Submetering-Abweichungen) werden protokolliert und weitergegeben.

---

## 8. Logging und Reporting

`utils/reporting.py` stellt einen Recorder bereit, den jede Pipeline-Funktion nutzt. Jede Aktion wird **strukturiert in die Konsole** geschrieben — Schritt-Banner plus Kennzahlen:

- Zeilen und Haushalte vor/nach jedem Schritt
- entfernte Haushalte mit ID und Grund
- Anzahl der per Forward-Fill gefüllten Stunden, je Station und Variable
- Anzahl der Reindex-Zeilen und geflaggten Ausreißer
- Ergebnis jedes Sanity Checks (pass/fail plus Kennzahl)

Dieselben Einträge werden gesammelt und am Ende jedes Skripts nach **`reports/data_prep_report.md`** geschrieben — ein durchgehender, menschenlesbarer Report über alle drei Stufen, bei jedem Lauf aktualisiert. `quality_report.json` ist das maschinenlesbare Pendant für Regressions-Checks.

Zwei Prinzipien dabei:
- **Report-then-raise:** Der Report wird immer geschrieben, bevor ein harter Abbruch erfolgt. Auch ein fehlgeschlagener Lauf hinterlässt ein vollständiges Protokoll.
- **Compute, don't transcribe:** Jede Zahl im Report wird zur Laufzeit aus dem aktuellen DataFrame berechnet, nie aus dem Plan oder einem früheren Lauf übernommen.

---

## 9. Arbeitsreihenfolge

| # | Schritt | Deliverable |
|---|---|---|
| 1 | Diagnostisches Data Understanding auf den Rohdaten: Datei-Inventar, Schemata, Missingness, Lücken- und Historienverteilung, Konsistenz `Total` vs. `HeatPump + Other`, PV-Flag vs. Einspeisedaten, Zeitraum-Überlapp | `notebooks/01_du_diagnostic.ipynb`, `docs/decisions.md` |
| 2 | Fundament und Stufe 1 | `utils/config.py`, `io.py`, `reporting.py`, `loading.py`, `scripts/01_load.py` |
| 3 | Stufe 2 | `utils/cleaning/*`, `utils/checks.py`, `scripts/02_clean_validate.py`, `quality_report.json` |
| 4 | Stufe 3 | `utils/merge.py`, `features.py`, `splits.py`, `scripts/03_build_panel.py`, `model_table.parquet` |
| 5 | Insight-EDA auf dem Panel: Saisonalität, Temperatur-Last-Kurve (Wärmepumpen-Signatur), Wochentagsprofile, Heterogenität zwischen Haushalten (Hypothesen für Level 1), Visit-Effekt, PV-Signaturen | `notebooks/02_du_insights.ipynb`; Erkenntnisse fließen als Iteration zurück in `features.py` |

Das diagnostische Notebook endet mit einer Entscheidungstabelle, die jede Pipeline-Regel an einen konkreten Datenbefund bindet — das ist der Kern des mit 20 % gewichteten Report-Abschnitts „Data Understanding & Data Preparation".

---

## 10. Ausblick Modeling

Nicht Teil dieses Plans, aber durch ihn vorbereitet:

- Baselines auf `model_table.parquet` über die `split`-Spalte; innerhalb von `train` Expanding-Window-Kreuzvalidierung statt K-Fold.
- Imputer, Encoder und Scaler werden **ausschließlich auf `train` gefittet** — die Data Preparation hat bewusst keinen davon angefasst.
- Optionales Vergleichsexperiment: Zieltags-Wetter als exogener Prädiktor unter expliziter Perfect-Forecast-Annahme, klar gegen die Shift-2-Basisvariante abgegrenzt.
- Level 1 (Gruppierung bzw. PV-Erkennung) nutzt die in der Preparation erhaltenen Signale: `returned_coverage`, PV-Flag, Verbrauchsheterogenität.
