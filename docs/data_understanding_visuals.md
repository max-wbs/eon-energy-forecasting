# Data Understanding — Visualisierungsentscheidungen

_Entscheidungsgrundlage für die Abbildungen des Report-Kapitels „Data
Understanding". Jede Entscheidung ist an einem Befund aus den echten Daten
festgemacht (verifiziert gegen `data/raw/` bzw. `data/processed/`), nicht an
der Projektdokumentation. Stand 2026-07-31: die EDA ist in **einem**
konsolidierten Notebook zusammengeführt (`03_eda.ipynb`, ersetzt die frühere
Fassung gleichen Namens); die früheren Notebooks
`03b_eda_household_dynamics` und `eda_extern` sind entfernt._

**Artefakte:**

| Was | Wo |
|---|---|
| Notebooks (ausgeführt, Abbildungen eingebettet) | `notebooks/data_understanding/01_delivered_data.ipynb`, `02_data_quality.ipynb`, `03_eda.ipynb` |
| Abbildungen (Vektor-PDF für den Report + PNG-Vorschau) | `images/data_understanding/` — 12 Abbildungen: 2 aus Notebook 01, 10 aus Notebook 03 |
| Berechnete Data-Quality-Kennzahlen | `docs/data_quality_summary.md` (generiert von Notebook 02) |

Zonenaufteilung nach D-23: Notebooks 01 + 02 arbeiten auf `raw` (die
*Lieferung* ist Gegenstand), Notebook 03 auf `processed`/`02_clean` (die
*Inhalte* sind Gegenstand — `gross_load` und `is_modelable` existieren nur
dort). Alle Pfade relativ, alle Zahlen zur Laufzeit berechnet (D-15). Die
Abbildungsnamen mit Präfix `03b_` stammen historisch aus dem früheren
Haushalts-Notebook, werden aber vom konsolidierten Notebook exportiert.

---

## Unterkapitel 1 — The delivered data: **Plot ja** (zwei Abbildungen)

**Gewünscht war „ein Plot zur Smart-Meter-Abdeckung". Hinterfragt:**

- **Abdeckung wovon?** Räumlich (Region/Netzgebiet) ist nicht darstellbar —
  es gibt keine Geo-Dimension, nur 8 anonymisierte Stations-IDs mit extrem
  schiefer Zuordnung (Hg: 59, 8jB: 56, … sV3mR: 2 Haushalte). Das ist ein
  Satz oder eine Mini-Tabelle, kein Plot. Abdeckung gegen das Gesamtprogramm
  (156 von 1.298 Haushalten der Overview-Datei) ist ebenfalls ein Satz.
- **Was die Daten tatsächlich hergeben — und was nicht trivial ist:** die
  **zeitliche Abdeckung der 156 gelieferten Zählpunkte**. Befunde: Starts und
  Enden verteilt über 2018–2024 (rollierendes Programm, kein Paneldesign);
  **nie mehr als 67 Haushalte liefern gleichzeitig** (Tagesabdeckung 25–67);
  41 Historien mit inneren Kalenderlücken bis 333 Tage; 3 Haushalte liefern
  ausschließlich Zeilen ohne Zielwert.

**Gewählt:** Zwei separate Abbildungen mit identischer Zeitachse (statt der
früheren Zwei-Panel-Abbildung — im Report einzeln platzier- und zitierbar):

| Abbildung | Inhalt |
|---|---|
| `01_delivered_daily_active_households` | Anzahl aktiv liefernder Haushalte je Kalendertag, Peak (67) annotiert, Train/Test-Cutoff 2023-06-30 markiert — erklärt, warum nur 71 von 153 modellierten Haushalten Testzeilen haben |
| `01_delivered_recording_coverage` | Eine Zeile je Haushalt, sortiert nach Lieferbeginn (früheste unten): dunkle Segmente = gelieferte Tage, weiß = keine Lieferung; innere Kalenderlücken erscheinen als weiße Unterbrechungen |

Zeilen ohne Zielwert werden nicht separat kodiert (betrifft im Kern 3
Haushalte — Kennzahl statt dritter Farbe).

**Verworfene Alternativen:** Heatmap Haushalt × Monat (verschmiert
Lückenkanten), kumulative Enrollment-Kurve (zeigt Abgänge nicht), Stacked
Area je Station (IDs tragen nichts).

## Unterkapitel 2 — Data quality: **Plot nein**

Alle üblichen Data-Quality-Visualisierungen wurden an den echten Daten
geprüft und scheitern inhaltlich:

- **Missing-Value-Matrix:** Die 4.293 fehlenden Zielwerte konzentrieren sich
  auf **5 von 156 Haushalten** (Top 5 = 100 %; drei davon sind die komplett
  leeren, in Stufe 1 entfernten Haushalte). Eine Matrix zeigt drei volle
  Zeilen und sonst nichts.
- **Vollständigkeit über Zeit:** identisch mit `01_delivered_recording_coverage`
  → Querverweis statt Doppelplot.
- **Regelmäßigkeit der Zeitstempel:** alle 88.791 Timestamps exakt
  `23:59:59+00:00`, 0 Duplikate, 0 Negativwerte — nichts zu zeigen.
- **Wetter:** Stundenraster aller 8 Stationen lückenlos; NaN je Kanal
  ≤ 2,6 % (ceOxS); 3 Stationen strukturell ohne Sunshine/Pressure — Tabelle.
- **Ausreißer-/Verteilungsplots:** gehören inhaltlich in die EDA (dort
  behandelt: Heterogenität, gekappte Achse mit ausgewiesenem Anteil).

Die Qualität dieses Datensatzes ist **strukturell, nicht diffus** (Lücken
sind Haushalts- oder Stationseigenschaften) — deshalb trägt die kompakte
Tabelle in `docs/data_quality_summary.md` mehr als jede Grafik.

## Unterkapitel 3 — Exploratory data analysis: **Plot ja** (zehn Abbildungen)

Das konsolidierte Notebook leitet zuerst **sieben Fragen** aus dem
Projektziel ab (Day-ahead-Prognose `gross_load`, gepooltes Flottenmodell)
und entscheidet dann Plot vs. Kennzahl. Eine Frage, die eine einzelne Zahl
beantwortet, bekommt keinen Plot (§5).

| Frage | Antwort (berechnet, Panel: 81.085 modelbare Zeilen, 153 Haushalte) | Abbildung |
|---|---|---|
| Q1 Welche Dynamik muss die Prognose tragen? | Saisonhub Faktor ~3 (Wintermittel 48,4 vs. Sommermittel 15,3 kWh/Tag), Kältespitzen bis 70,4 kWh/Tag (14.02.2021) = Beschaffungsrisiko | `03_eda_load_seasonality` (§1) |
| Q2 Wie heterogen sind die Niveaus? | Haushaltsmittel p5 12,2 / Median 29,0 / p95 56,9 kWh/Tag (Faktor ~5), rechtsschief bis 93,7 | `03_eda_household_heterogeneity` (§2.1) |
| Q2 Trennt PV die Niveaus? | Nein — PV- und Nicht-PV-Haushalte durchmischen sich über die gesamte Spanne 6,5–93,7 (PV im Mittel 25,1 vs. 34,5) | `03_eda_household_levels_sorted_pv` (§2.2) |
| Q3 Wie stark/nichtlinear ist die Temperaturabhängigkeit? | WP-Signatur mit Heizgrenze ~15 °C (stützt `hdd_15`, D-10), Sommerplateau 14–16 kWh, Anstieg auf ~70 kWh im kältesten gut besetzten Bin (~−9 °C); gepoolt r = −0,63 | `03_eda_temperature_load_curve` (§3.1) |
| Q3 Wie viel erklärt Temperatur im Tagesmittel? | Über Haushalte gemittelt r = −0,95, R² = 0,91, ≈ −1,9 kWh je +1 °C — die Niveaustreuung mittelt sich heraus | `03_eda_temperature_scatter_daily` (§3.2) |
| Q4 Trägt jeder Haushalt die Kurve? | Fast ausnahmslos: Median r = −0,84, 78 % < −0,7; nur 7 von 153 schwach (r > −0,3), davon höchstens 2 echte Ausnahmen (Rest ohne Kältekontrast oder mit Kurzhistorie — im Notebook diagnostiziert) | `03b_eda_household_temperature_response` (§3.3) |
| Q5 Verzerrt PV das Ziel — monatlich? | PV-Haushalte beziehen im Median ~30 % (Sommer) / ~17 % (Winter) weniger; Einspeisung spiegelt die Saison (Median ~20 vs. ~1 kWh/Tag), Jun–Sep Netto-Export | `03_eda_pv_monthly_profile_median` + Variante `_feedin` (§4.1) |
| Q5 …und am einzelnen Tag? | An sonnigen Tagen fällt das PV-p10 von ~6 auf ~2 kWh, Anteil Tage < 1 kWh steigt auf ~9 %; ohne PV nie < 1 kWh (Min. 1,34) → Ziel bei PV **zensiert** | `03b_eda_sunshine_grid_draw_pv` (§4.2) |
| Q6 Macht PV den Bezug unruhiger? | Tendenz ja: CV-Median 0,60 vs. 0,45, aber stark überlappend (20 % / 10 %) — Tendenz, keine Klasse | `03_eda_daily_volatility_pv_box` (§4.3) |
| Q7 Sekundäreffekte | nur Kennzahlen, siehe unten | — (§5) |

**Bewusst ohne Plot (§5, Kennzahl genügt):**

- Wochenrhythmus +5,3 % Wochenende; Feiertage −3,4 % (monats-gematcht).
- Autokorrelation r(y, lag1) = 0,94, lag7 = 0,87 — stärkste Einzelprädiktoren,
  tragen das Niveau je Haushalt im gepoolten Modell.
- Visit-Effekt: naiv +28 %, monats-gematcht **−8 %** (n = 54) — Vorzeichen
  kippt nach Matching, Saison-Konfundierung; nur Kontrollvariable.
- Wetterpersistenz: r(T_d, T_d−1) = 0,95–0,96 (8 Stationen), Sonnenschein nur
  0,54–0,62 (5 Stationen) — rahmt die Day-ahead-Aufgabe.
- Wetterkanal-Redundanz: T-Familie paarweise |r| = 0,87–0,97; Feuchte/Wind/
  Niederschlag nach Temperaturkontrolle ≈ 0 — kein zweiter flottenweiter
  Treiber.

### Hinterfragt und verworfen (je Abbildung)

**Saisonalität (§1):** Monatsboxplots (verstecken die Kältespitzen — genau
das Beschaffungsrisiko), Jahresüberlagerung (verdeckt, dass die Abdeckung
25–67 Haushalte je Tag mischt; der Kompositions-Caveat steht im Notebook und
gehört in die Caption). Gewählt: Tagesmittel + 14-Tage-Rolling + IQR-Band.

**Temperaturkurve (§3.1):** reine Scatterwolke (80.912 Punkte, unlesbar) und
reine Binkurve (versteckt die Streuung) → Kombination: rasterisiertes Sample
als Kontext, Binmittel (n ≥ 30) + IQR als Signal; y-Achse bei 130 kWh gekappt,
Anteil (0,42 %, Max. 250) im Notebook ausgewiesen.

**Temperaturresponse (§3.3):** Small multiples je Haushalt (153 fast gleiche
Panels), Steigungsverteilung (kWh/°C mischt Niveau und Reaktionsstärke —
Korrelation ist einheitenfrei), PV-Split (Mediane praktisch gleich). Statt
Haushalte mit Kurzhistorie stillschweigend zu filtern (früher `min_days = 60`),
behält die konsolidierte Fassung **alle 153** (`min_days = 0`) und
diagnostiziert die 7 schwachen Responder explizit in einer Tabelle.

**PV-Monatsprofil (§4.1):** Median statt Mittel (robust gegen die
Rechtsschiefe aus §2); **zwei exportierte Varianten** — pure Zielgröße vs.
mit überlagerter Einspeisekurve und Netto-Bezugs-Band — damit der Report
wählen kann, ohne neu zu rechnen. Energiebilanz-Lesart im Notebook:
Erzeugung = Eigenverbrauch + Einspeisung; der naive Erzeugungsschätzer
(Bezugslücke + Einspeisung ≈ 25 kWh/Tag Sommer) ist eine Obergrenze, weil die
Winterlücke (~8 kWh/Tag bei minimalem Ertrag) strukturell ist. Caveat D-12:
47 % der PV-Haushaltstage ohne Einspeisewert (5/39 Haushalte > 90 %).

**Sonnenschein (§4.2):** Mittelwertkurven unterschätzen den Effekt
systematisch — sonnige Tage sind auch wärmere Tage (Bin-Mittel 14→20 °C),
beide Gruppen fallen; der PV-Effekt sitzt im unteren Rand → Median, IQR-Band
und 10. Perzentil je Gruppe. Ganzjahresdarstellung verworfen (WP-Last
überdeckt den Solareffekt) → Mai–September, 5 Stationen mit Sensor, 32 PV- /
85 Nicht-PV-Haushalte, 29.590 Haushaltstage.

**Volatilität (§4.3):** Standardabweichung statt CV verworfen (mischt Niveau
und Streuung), überlagerte Histogramme verworfen (Binwahl dominiert bei
n = 39). Gewählt: Boxplot je Gruppe **plus** alle Haushalte als gejitterte
Punkte — Quartilstruktur und Einzelhaushalte (inkl. PV-Ausreißer CV > 1)
bleiben gleichzeitig sichtbar.

### Methodische Konstanten

- EDA auf dem leakage-sicheren Panel (`model_table.parquet`, nur
  `is_modelable`-Zeilen), nicht auf `raw` (D-23).
- Physikalische Fragen (§3, §4.2) nutzen **Zieltags**-Wetter aus
  `weather_daily.parquet` — die Panelspalten tragen aus Leakage-Gründen den
  Vortag; die Abweichung ist für Tagesmittel klein und im Notebook begründet.
- Einspeisung (`kWh_returned_Total`) kommt aus der Clean-Zone, ist bewusst
  **kein** Panel-Feature (D-20/D-05) und dient nur der deskriptiven Lesart.

## Gestaltung

Abbildungsbeschriftungen auf **Englisch** (Report-Sprache); ohne eingebaute
Titel, damit sie sich mit LaTeX-/Word-Captions nicht doppeln. Farben aus der
CVD-validierten Referenzpalette: Blau = Flotte/ohne PV, Orange = mit PV
(konsistent über §2.2, §4.1–4.3), Aquamarin = Einspeisung, Grau = Kontext.
Gruppen werden direkt am Linienende beschriftet statt über lange Legenden;
Referenzlinien gestrichelt und direkt annotiert. Eine Achse pro Plot. PDF =
Vektor (Scatter rasterisiert eingebettet), PNG mit 200 dpi.
