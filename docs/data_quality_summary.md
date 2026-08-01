# Data quality — berechnete Kennzahlen

_Automatisch erzeugt von `notebooks/data_understanding/02_data_quality.ipynb`
aus `data/raw/`. Zahlen werden bei jedem Lauf neu berechnet._

## Strukturelle Regelmäßigkeit

| Prüfung | Wert |
|---|---|
| Zeitstempel exakt 23:59:59 UTC | 100.0% |
| Duplikate (Household_ID, date) | 0 |
| negative Messwerte (alle 10 Kanäle) | 0 |
| leere Household_ID / Timestamp | 0 |

## Zielvariable `kWh_received_Total`

Fehlend in 4,293 von 88,791 gelieferten Zeilen
(4.83%) — konzentriert auf 5 von 156 Haushalten:

| Household_ID | fehlende Zielwerte | Anteil an allen Lücken | Anteil an eigener Historie |
|---|---|---|---|
| 996610 | 1823 | 42.5% | 100.0% |
| 816910 | 957 | 22.3% | 92.6% |
| 747511 | 770 | 17.9% | 100.0% |
| 768498 | 734 | 17.1% | 100.0% |
| 610891 | 9 | 0.2% | 5.8% |

## Kalenderlücken

41 von 156 Haushalten haben innere Kalenderlücken
(1,356 fehlende Tage, Maximum 333
Tage am Stück). Sichtbar in `images/data_understanding/01_delivered_recording_coverage`.

## Kanal-Verfügbarkeit (je Haushalt quasi binär)

| Kanal | Haushalte mit Kanal | davon > 95 % gefüllt | Zeilen-Füllgrad gesamt |
|---|---|---|---|
| kWh_received_Total | 153 | 151 | 95.2% |
| kWh_received_HeatPump | 10 | 9 | 7.5% |
| kWh_received_Other | 7 | 6 | 4.9% |
| kWh_returned_Total | 37 | 9 | 16.0% |
| kvarh_received_capacitive_Total | 101 | 91 | 56.1% |
| kvarh_received_capacitive_HeatPump | 5 | 3 | 2.6% |
| kvarh_received_capacitive_Other | 4 | 3 | 1.9% |
| kvarh_received_inductive_Total | 97 | 66 | 49.1% |
| kvarh_received_inductive_HeatPump | 5 | 3 | 2.9% |
| kvarh_received_inductive_Other | 4 | 3 | 1.8% |

## Wetterdaten (8 Stationen, stündlich)

| Station | Zeilen | Raster lückenlos | fehlende Kanäle | max. NaN-Rate übrige Kanäle |
|---|---|---|---|---|
| 8jB | 45264 | True | 0 | 0.35% |
| ceOxS | 45264 | True | 4 | 2.57% |
| HbsbG | 45264 | True | 4 | 1.87% |
| Hg | 45264 | True | 0 | 0.11% |
| MqO | 45264 | True | 1 | 0.11% |
| sV3mR | 45264 | True | 4 | 0.75% |
| wDD | 45264 | True | 0 | 0.11% |
| z6I | 45264 | True | 0 | 0.37% |

## UTC-Tagesgrenze (D-01)

Messung auf den Wetterstundendaten — die Last ist nur als Tageswert geliefert,
dort ist die Fensterwahl nicht nachmessbar:

| Kennzahl | Wert |
|---|---|
| Stations-Tage im Vergleich | 15,070 |
| Zählerstempel 23:59:59 UTC in Lokalzeit | 00:59:59 (CET, 43.2%) / 01:59:59 (CEST, 56.8%) |
| Tagesmittel-Temperatur: r (UTC- vs. Berlin-Fenster) | 0.9996 |
| Tagesmittel-Temperatur: mittlere Differenz | +0.000 K |
| Tagesmittel-Temperatur: mittlere absolute Differenz | 0.145 K |
| Tagesmittel-Temperatur: P95 / Maximum der absoluten Differenz | 0.41 K / 2.20 K |
| hdd_15: mittlere absolute Differenz | 0.094 K |
| hdd_15: Anteil Tage mit absoluter Differenz > 0,5 K | 1.25% |
