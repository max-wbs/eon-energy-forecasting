# Evaluation der konsolidierten EDA — Vorauswahl für das Kapitel „Data Understanding"

_Unabhängiges Reviewer-Dokument, 2026-07-31. Grundlage: das ausgeführte
konsolidierte Notebook `03_eda.ipynb` (§1–§6, zehn Abbildungen),
Notebook `01_delivered_data.ipynb` (drei Abbildungen), die gerenderten
Abbildungen in `images/data_understanding/` und die Zellen-Outputs. Alle
zitierten Zahlen wurden gegen die berechneten Outputs geprüft, nicht aus den
Takeaway-Texten übernommen. Frühere Arbeitsstände (u. a. eine Aufteilung in
`03_eda` plus `03b`, an die die `03b_`-Präfixe zweier Abbildungsdateien noch
erinnern) wurden vor dem Commit gelöscht und liegen nicht im Repository;
dieses Dokument stützt sich ausschließlich auf den konsolidierten Stand —
Achtung: ältere Notizen können abweichende Kennzahlen zitieren (Abschnitt 5,
Punkt 2)._

## 1 · Empfehlungstabelle

Verdikte: **aufnehmen** · **mit Änderung** (Abbildung ja, Caption/Text
korrigieren) · **zu Satz/Kennzahl herabstufen**.

| Artefakt (§ im Notebook) | Kernbefund (verifiziert) | Verdikt | Begründung |
|---|---|---|---|
| `01_delivered_recording_coverage` | Rollierendes Programm 2018–2024, eine Zeile je Haushalt: gestaffelte Starts/Enden, 41 Historien mit Lücken bis 333 Tage, Cutoff 2023-06-30 markiert. | **aufnehmen** | Einzige Abbildung der Datenstruktur selbst; ohne sie sind Kompositions-Caveat (§1), Kohortenzahlen und die ungleiche Testabdeckung (71 von 153) nicht verständlich. |
| `01_delivered_daily_active_households` | Tagesabdeckung schwankt 18–67 Haushalte, Peak 67, Einbruch 2021. | **aufnehmen, fällt zuerst** | Ergänzt die Coverage-Zeilen um die aggregierte Lesart; bei knappem Budget trägt ein Satz („never more than 67 of 156 delivering simultaneously") den Befund fast vollständig. |
| §1 `03_eda_load_seasonality` | Saisonhub Faktor 3,2 (DJF 48,4 vs. JJA 15,3 kWh/Tag), Peak-Tagesmittel 70,4 kWh (14.02.2021), wiederkehrende Kältespitzen. | **mit Änderung** | Zeigt die Dynamik, die die Beschaffung tragen muss, inkl. Wiederholbarkeit der Spitzen. Kompositions-Caveat (17–66 aktive Haushalte/Tag auf dem Panel) steht im Notebook-Fließtext und muss in die Caption; die Takeaway-Zahl zum Sommerniveau ist im Notebook inzwischen als JJA-Mittel 15,3 benannt, einzelne Tage bis ~11 (korrigiert 2026-08-01). |
| §2.1 `03_eda_household_heterogeneity` | Haushaltsmittel p5 12,2 / Median 29,0 / p95 56,9, Max 93,7 — Faktor 4,6, rechtsschief. | **aufnehmen** | Die zentrale Panel-Eigenschaft (Spreizung + Schiefe) in der einfachsten ehrlichen Form; die Verteilungsform ist der Befund, nicht nur die Quantile. Erklärt, warum Fehlermetriken je Haushalt streuen werden. |
| §2.2 `03_eda_household_levels_sorted_pv` | PV/Nicht-PV durchmischen sich über die gesamte Spanne 6,5–93,7; PV im Mittel 25,1 vs. 34,5; 67 % der PV-Haushalte unter dem Gesamtmedian. | **zu Satz herabstufen** | Der Befund („PV ist kein Niveau-Separator") ist wichtig, aber zwei Zahlen tragen ihn vollständig; als Abbildung dupliziert sie §2.1 in anderer Sortierung. Falls doch als Abbildung: das ausgegebene „factor 14" (Extremwerte) nicht in die Caption — p5–p95 verwenden. |
| §3.1 `03_eda_temperature_load_curve` | WP-Signatur: Knick ~15 °C, Sommerplateau 14–16 kWh, Anstieg auf ~70 kWh im kältesten gut besetzten Bin; gepoolt r = −0,63; y gekappt bei 130 (0,42 %, Max 250). | **mit Änderung** | Beantwortet die Treiberfrage direkt und stützt `hdd_15` (D-10). Der frühere Takeaway-/§6-Text „~68 kWh/day at −15 °C" war durch die n≥30-Binkurve nicht gedeckt (endet nachweislich bei ~−9 °C, geprüft am gerenderten PDF/PNG) — im Notebook korrigiert (2026-08-01). |
| §3.2 `03_eda_temperature_scatter_daily` | Über Haushalte gemittelt: r = −0,95, R² = 0,91, −1,9 kWh je +1 °C; Saisons liegen auf einer Linie. | **zu Kennzahl herabstufen** | R² = 0,91 ist die stärkste Einzelzahl des Kapitels und gehört in den Text — aber die Abbildung wiederholt die Botschaft von §3.1 auf aggregierter Ebene; zwei Temperatur-Abbildungen sind eine zu viel, und §3.1 zeigt zusätzlich Nichtlinearität und Streuung. |
| §3.3 `03b_eda_household_temperature_response` | Median r = −0,84, IQR −0,91 bis −0,72, 78 % < −0,7; 7 von 153 schwach, davon ≤ 2 echte Ausnahmen (Diagnose-Tabelle im Notebook). | **zu Satz herabstufen** | Der Befund (kein Aggregationsartefakt: je Haushalt stärker als gepoolt −0,63) ist berichtenswert, aber drei Zahlen tragen ihn; das Histogramm ist ein einseitiger Klumpen, und der r = +1,00-Ausreißer (Haushalt mit 2 Tagen) würde in einer Report-Abbildung nur Fragen provozieren. |
| §4.1 `03_eda_pv_monthly_profile_median` (Variante 1, ohne Einspeisung) | PV zieht im Median durchgängig weniger: −30 % Sommer, −17 % Winter. | **durch Variante 2 ersetzen** | Variante 1 zeigt nur den Abstand und lädt zur kausalen Überinterpretation ein („PV drückt 17–30 %"); erst die Einspeisekurve trennt Mechanismus von Kohortenunterschied. |
| §4.1 `03_eda_pv_monthly_profile_median_feedin` (Variante 2) | Einspeisung spiegelt die Saison (Median ~20 Sommer vs. ~1 Winter, Juni-Peak 23,4); Jun–Sep Netto-Export im Median; Winterlücke 7,9 kWh bei minimalem Ertrag → strukturell. | **mit Änderung** | Die stärkste PV-Abbildung: sie zeigt *warum* der Sommerabstand solar ist und der Winterabstand nicht — genau die Unterscheidung, die Variante 1 schuldig bleibt. Caption braucht: n = 39/114, Median-Profile, Messlücken-Caveat (47 % der PV-Haushaltstage ohne Einspeisewert, D-12). |
| §4.2 `03b_eda_sunshine_grid_draw_pv` | PV-p10 fällt Mai–Sep von ~6 auf ~2 kWh, Tage < 1 kWh steigen auf 9 %; ohne PV nie < 1 kWh (Min 1,34); ganzjährig 2,8 % der PV-Tage < 1 kWh. | **mit Änderung** | Einzige Abbildung einer Eigenschaft der *Zielvariablen*, die man kennen muss: Zensierung, nicht bloß „niedriger". Quantildarstellung sauber begründet (Sonne↔Wärme-Konfundierung: beide Gruppen fallen). Caption muss das Subset vollständig tragen: Mai–Sep, 5 von 8 Stationen mit Sensor, 32 PV / 85 ohne, 29.590 Haushaltstage. |
| §4.3 `03_eda_daily_volatility_pv_box` | CV-Median 0,60 (PV) vs. 0,45; IQRs 0,51–0,69 vs. 0,33–0,57; 20 % / 10 % Überlappung; PV-Ausreißer CV > 1 einzeln sichtbar. | **aufnehmen** | Zweite Heterogenitätsdimension (Unruhe) neben §2.1 (Niveau); „Tendenz, keine Klasse" ist nur in der Punktverteilung sichtbar — Box + Jitter löst das alte Dilemma (Boxplot versteckt Einzelfälle, Histogramm zu grob) sauber. |
| §5 Kennzahlen | Wochenende +5,3 %, Feiertage −3,4 %; r(lag1) = 0,94, lag7 = 0,87; Visit naiv +28 % vs. gematcht −8 %; T-Persistenz 0,95–0,96 vs. Sonnenschein 0,54–0,62; T-Familie \|r\| 0,87–0,97, Feuchte/Wind/Niederschlag ≈ 0 nach T-Kontrolle. | **als Sätze aufnehmen** | Durchweg richtig als „bewusst kein Plot" entschieden. Der Visit-Effekt ist ein Lehrstück Saison-Konfundierung (Vorzeichen kippt nach Matching) und darf nur als Kontrollvariable erscheinen; die Persistenz-Zahlen rahmen die gesamte Day-ahead-Aufgabe. |

## 2 · Priorisierte Rangliste mit Schnittkanten

Rang: **1. §3.1 T-Kurve · 2. 01_recording_coverage · 3. §4.2 Nullgrenze ·
4. §1 Saisonalität · 5. §2.1 Heterogenität · 6. §4.1 Variante 2 ·
7. §4.3 CV-Box · 8. 01_daily_active · 9. §2.2 · 10. §3.2 · 11. §3.3**

- **Budget 4:** §3.1, Coverage, §4.2, §1. §2.1 wird Mini-Tabelle
  (p5/Median/p95/Max), §4.1 und §4.3 werden Sätze mit den Kernzahlen,
  §3.2/§3.3 ohnehin Kennzahlen. Ergibt ein kohärentes Kapitel:
  Struktur → Treiber → Zieleigenschaft → Dynamik.
- **Budget 5:** + §2.1 (die Schiefe verdient die Grafik).
- **Budget 6:** + §4.1 Variante 2 (der PV-Mechanismus verdient die Grafik,
  sobald Platz ist — sie ersetzt zwei Absätze Erklärtext).
- **Budget 7:** + §4.3.
- **Budget 8:** + 01_daily_active_households (oder stattdessen §2.2, wenn das
  Kapitel die PV-Durchmischung visuell zeigen soll).
- §3.2 und §3.3 bleiben in jeder Budgetstufe Text — ihre Zahlen (R² = 0,91;
  −0,84 / 78 % / ≤ 2 Ausnahmen) tragen die Befunde allein.

## 3 · Änderungsvorschläge (nur „mit Änderung")

- **§3.1 / §6:** „rises to ~68 kWh/day at −15 °C" ersetzt durch „~70 kWh/day
  in the coldest well-populated bins (≈ −9 °C)" — die n≥30-Kurve deckt
  −15 °C nicht (*im Notebook umgesetzt, 2026-08-01*). Offen bleibt:
  Kappungshinweis (0,42 % > 130 kWh, Max 250) aus dem Zellen-Output in die
  Caption übernehmen.
- **§1:** Caption-Caveat Komposition: „fleet mean over a changing subset
  (17–66 active households per day, see coverage figure); the seasonal shape,
  not year-to-year levels, is the robust finding." Takeaway-Präzisierung
  (*im Notebook umgesetzt, 2026-08-01*): benannt ist jetzt das JJA-Mittel
  15,3 kWh/Tag, einzelne Sommertage bis ~11.
- **§4.1 (Variante 2):** In der Caption rahmen als Gruppenvergleich + Mechanismus:
  n = 39/114, monatliche **Mediane**; Winterlücke ~8 kWh/Tag als strukturellen
  Kohortenunterschied benennen (Ertrag minimal), Sommerabstand + Netto-Export
  als Solareffekt; Messlücken-Caveat: 47 % der PV-Haushaltstage ohne
  Einspeisewert (5/39 Haushalte > 90 %, D-12), Mediane laufen über verfügbare
  Werte. Den naiven Erzeugungsschätzer (~25 kWh/Tag Sommer) nur als
  Obergrenze zitieren.
- **§4.2:** Subset vollständig in die Caption (Mai–Sep, 5 Stationen mit
  Sonnenschein-Sensor, 32 PV / 85 ohne, 29.590 Haushaltstage); die Kennzahl
  „share of days < 1 kWh: 4 % → 9 % with PV; never without PV (min 1.34)"
  als Annotation oder Caption-Satz mitgeben; leeren x-Bereich rechts des
  letzten Bins (> 16 h) beschneiden, sofern die Endbeschriftungen es zulassen.

## 4 · Überleitung ins Modelling (kompakt)

Direkteste Evidenz je Modellentscheidung:

- **`hdd_15` (D-10):** §3.1 (Form + Knick 15 °C); §3.3 als Absicherung, dass
  der Zusammenhang je Haushalt gilt (−0,84 Median) und kein Artefakt der
  Aggregation ist; §5-Redundanzbefund stützt den einzelnen Temperaturkanal.
- **Lag-Features / Persistenz-Baselines (Level 0, Notebook 07):**
  r(y, lag1) = 0,94 und lag7 = 0,87 begründen sowohl die aktiven Features als
  auch die Wahl von Persistenz-Baselines als Referenz; §2.1 erklärt, *warum*
  Autoregression nötig ist (Niveauspreizung Faktor 4,6, die ein gepooltes
  Modell sonst raten müsste).
- **PV-Flag und Segmentierung (D-20/D-21):** §4.2 (Zensierung = Mechanismus),
  §4.1 Variante 2 (Saisonprofil + strukturelle Winterlücke), §4.3 (höhere
  Tag-zu-Tag-Unruhe, CV 0,60 vs. 0,45).
- **Day-ahead-Rahmen (D-05):** T-Persistenz r ≈ 0,95 vs. Sonnenschein ≈ 0,6
  erklärt, warum Vortagswetter für die Flotte fast verlustfrei trägt, für die
  PV-Subgruppe aber strukturell weniger — die PV-Haushalte, nicht die
  temperaturgetriebene Mehrheit, begrenzen die erreichbare Genauigkeit.

**Brücken-Bullets** (Englisch, für den Kapitelschluss):

- Temperature is the single dominant driver, with a heating threshold near
  15 °C — and it is almost fully knowable a day ahead (persistence r ≈ 0.95),
  which is what makes a day-ahead forecast from yesterday's weather viable.
- Household levels spread by a factor of ~4.6 and daily draw is highly
  persistent (r(lag1) = 0.94): a household's own recent history, not any
  weather channel, carries its level in a pooled model.
- For the PV quarter of the fleet (39 of 153), grid draw is censored at zero
  on sunny days, day-to-day variability is higher, and sunshine persists far
  less than temperature (r ≈ 0.6) — this subgroup bounds day-ahead accuracy.
- Beyond temperature there is no second fleet-wide weather driver, and
  calendar effects are single-digit percent — the data leave little room for
  further external signals.

## 5 · Offene Punkte für das Report-Team

1. ~~**„−15 °C"-Behauptung** in §3.1-Takeaway *und* §6-Key-Findings nicht durch
   die gezeigte Kurve gedeckt (endet ~−9 °C) — an beiden Stellen korrigieren
   (Abschnitt 3).~~ *Erledigt 2026-08-01: beide Stellen im Notebook
   korrigiert.*
2. **Verbindlicher Zahlenstand:** Das konsolidierte Notebook rechnet mit
   `min_days = 0`, also allen 153 modellierbaren Haushalten; frühere, vor dem
   Commit gelöschte Arbeitsstände filterten Kurzhistorien heraus und lieferten
   dadurch leicht abweichende Kennzahlen. Deren Werte sind nicht mehr
   nachprüfbar und werden hier bewusst nicht zitiert. Ältere Reportentwürfe,
   Folien oder Notizen, deren Zahlen vom konsolidierten Stand abweichen
   (Temperaturresponse-Median **−0,84**, Anteil < −0,7 **78 %**, CV-Mediane
   **0,60/0,45**), sind auf diesen Stand zu ziehen — allein die Outputs von
   `03_eda.ipynb` sind Referenz.
3. **Kohorten-Ledger in die Captions:** 156 geliefert → **153** modellierbar
   (39 PV / 114 ohne; §1–§4.1, §4.3) → **117** im Sonnenschein-Subset Mai–Sep
   (32/85; §4.2). Alle Abweichungen sind Filter, keine Fehler; n je Caption
   ausweisen und Zahlen nie über Kohorten hinweg mischen.
4. **Feed-in-Messlücken:** 47 % der PV-Haushaltstage ohne Einspeisewert
   (Median je Haushalt 9 %, 5/39 > 90 %) — ohne Caption-Caveat ist die
   Einspeisekurve in Variante 2 eine offene Angriffsfläche.
5. **§2.2-Output „factor 14":** Extremwert-Framing (6,5 → 93,7); im Report
   durchgängig p5–p95 (Faktor 4,6) verwenden, sonst widersprechen sich §2.1
   und §2.2 scheinbar.
6. ~~**Sommer-Niveau in §1:** „~11 kWh/day" (Rolling-Minimum) vs. 15,3 kWh/Tag
   (JJA-Mittel) — im Report eine Größe wählen und benennen.~~ *Erledigt
   2026-08-01: Takeaway benennt jetzt das JJA-Mittel 15,3 (einzelne Tage
   bis ~11).*
7. **§3.3-Ausreißer r = +1,00** (Haushalt mit 2 Liefertagen) ist im Notebook
   diagnostiziert; falls das Histogramm doch in den Report kommt, braucht der
   Ausreißer eine Fußnote, sonst wirkt er wie ein Datenfehler.
