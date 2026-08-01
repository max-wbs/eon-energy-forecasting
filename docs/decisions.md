# Annahmen-Log

Jede Entscheidung, die sich nicht zwingend aus den Daten ergibt, steht hier mit
Begründung. Der Zweck ist doppelt: die Pipeline bleibt nachvollziehbar, und der
Report kann sich auf eine belegte Argumentationskette stützen statt auf
stillschweigende Konventionen.

Aufbau je Eintrag: **Entscheidung** — Begründung — wo sie im Code steht.

---

## D-01 · Tagesgrenze ist die UTC-Mitternacht

Die Zählerstände tragen den Zeitstempel `23:59:59+00:00`, also das Ende des
UTC-Tages. Das Wetter wird auf denselben UTC-Tag aggregiert (Stunden 00:00 bis
23:00). Beide Seiten decken damit dasselbe physische Intervall ab und lassen
sich exakt joinen.

Die Alternative wäre `Europe/Berlin`. Sie wäre physikalisch näher am
Tagesverbrauch eines Haushalts, erfordert aber eine Sommerzeit-Behandlung mit
23- und 25-Stunden-Tagen. Der Versatz beträgt eine Stunde (CET) bzw. zwei
Stunden (CEST); der Zählerstempel 23:59:59 UTC liegt lokal bei 00:59:59
bzw. 01:59:59.

Was die Fensterwahl kostet, ist gemessen, soweit die Daten es zulassen
(Notebook `02_data_quality`, Abschnitt „UTC-Tagesgrenze"; Kennzahlen in
`docs/data_quality_summary.md`): Auf den Wetterstundendaten unterscheiden sich
die Tagesmittel der Temperatur zwischen UTC- und Berlin-Fenster im Mittel um
0,000 K (mittlere absolute Differenz 0,145 K, P95 0,41 K) bei einer Korrelation
von r = 0,9996; `hdd_15` weicht nur an 1,25 % der Stations-Tage um mehr als
0,5 K ab. Die Fensterwahl verändert Niveau und Struktur der Wetteraggregate
also nicht messbar. Für die **Last** ist der Effekt prinzipiell nicht
nachmessbar: sie ist ausschließlich als Tageswert geliefert und lässt sich
nicht auf lokale Tage umaggregieren. Für einen Tagesprognose-Horizont ist die
UTC-Grenze damit belegt vertretbar.

*Code:* `utils/io.py::_to_utc_date`; Messung:
`notebooks/data_understanding/02_data_quality.ipynb`

## D-02 · IDs sind Strings, nie Integer

`Household_ID` und `Weather_ID` sind Bezeichner. Als Integer gelesen würden sie
in arithmetische Operationen geraten können, und ein Join zwischen `int64` und
`string` schlägt still fehl statt laut.

*Code:* `utils/io.py`, Dtype-Maps

## D-03 · Leere Survey-Booleans bedeuten *unbekannt*, nicht *False*

In `meta_data.csv` sind boolesche Felder teils leer. Eine unbeantwortete
Umfragefrage ist keine Verneinung: „hat kein E-Auto" und „hat die Frage nicht
beantwortet" sind unterschiedliche Zustände. Die Spalten werden dreiwertig als
`boolean` mit `pd.NA` geführt.

Das Bild ist dabei nicht einheitlich, was die konservative Lesart stützt:
`Survey_HeatDistribution_System_FloorHeating` hat 103 mal `True`, 24 mal `False`
und 26 Leerzellen — die Quelle schreibt also durchaus explizit `False`.
`Survey_DHW_Production_ByHeatPump` hingegen hat 97 mal `True`, **kein** `False`
und 56 Leerzellen, was auf eine Auswahlliste hindeutet, bei der nur die
zutreffende Option gesetzt wurde. Beide Muster in einem Datensatz heißen: aus
einer leeren Zelle lässt sich nicht zuverlässig auf `False` schließen. Das
Insight-Notebook prüft, ob sich die Warmwasser-Felder gegenseitig ausschließen
und die Leerzellen damit doch auflösbar sind.

*Code:* `utils/io.py::to_nullable_bool`

## D-04 · Haushalte ohne einen einzigen Zielwert werden entfernt

Drei Haushalte (`747511`, `768498`, `996610`, zusammen 3.327 Zeilen) haben
durchgängig keinen Wert in `kWh_received_Total`. Sie können weder trainiert noch
bewertet werden und würden nur NaN-Zeilen durch die Pipeline tragen. Es
verbleiben 153 Haushalte.

Haushalte mit *kurzer*, aber vorhandener Historie bleiben erhalten
(`109104` mit 22, `461104` mit 21, `7086681` mit 5 Zielwerten). Ob sie
modellierbar sind, entscheidet das Modeling anhand der Pflicht-Prädiktoren —
nicht die Data Preparation.

*Code:* `utils/loading.py::drop_households_without_target`

## D-05 · Forecast-Lag von einem Tag, ohne Forecast-Proxy

Das Gebot für Zieltag *d* wird am **Ende des Tages *d−1*** abgegeben. Tag *d−1*
ist zu diesem Zeitpunkt vollständig gemessen — wer heute Strom für morgen
einkauft, kennt die Zählerstände von heute. Letzter vollständig beobachteter
Tag ist damit *d−1*.

Dieser Shift gilt für **alle** zeitveränderlichen Größen, Messwerte *und*
Wetter. Es wird ausdrücklich **keine** Perfect-Forecast-Annahme getroffen: auch
das Wetter geht nur als *Beobachtung* von *d−1* ein, nicht als Prognose für den
Zieltag. Kein Ergebnis ruht auf einer Wetterprognose, die im Datensatz nicht
existiert.

Die Alternative wäre ein Lag von zwei Tagen (Gebotsabgabe am Vormittag von
*d−1*, wenn *d−1* noch unvollständig ist). Sie wäre für ein Vormittags-Gebot
korrekt, verschenkt aber den informativsten Prädiktor überhaupt: der Verbrauch
von gestern ist der beste Einzelschätzer für den Verbrauch von morgen. Der
gewählte Lag von 1 setzt voraus, dass die Zählerdaten des Vortags zum
Gebotszeitpunkt vorliegen — bei täglicher Fernauslesung eine realistische
Annahme, bei manueller Ablesung nicht.

Da `FORECAST_LAG` die einzige Stelle ist, an der der Horizont festgelegt wird,
ist eine Vergleichsvariante mit Lag 2 ein Ein-Zeilen-Wechsel plus
Pipeline-Lauf. Lags, Rolling-Fenster und die Umdatierung des Wetters folgen
automatisch.

*Code:* `utils/config.py::FORECAST_LAG`

## D-06 · Imputation nur strikt kausal

Es wird an genau einer Stelle imputiert: kurze stündliche Wetterlücken per
Forward-Fill mit Limit 3 Stunden. Forward-Fill verwendet ausschließlich Werte
*vor* der Lücke. Eine lineare Interpolation wäre für glatte Größen wie
Temperatur genauer, würde aber Werte *nach* der Lücke einbeziehen — verzichtbar,
und der Verzicht macht die Kausalität der Pipeline unbestreitbar.

Niederschlag und Sonnenscheindauer werden **nicht** gefüllt: sie sind spikig,
ein Forward-Fill würde Regen erfinden, der nicht gefallen ist.

Die Zielvariable wird nie imputiert. Globale Statistiken (Mittelwert, Median über
den Gesamtdatensatz) kommen in der Data Preparation nicht vor; falls das Modell
Imputation braucht, wird der Imputer ausschließlich auf `train` gefittet.

*Code:* `utils/config.py::WEATHER_FFILL_COLUMNS`, `WEATHER_FFILL_LIMIT_H`

## D-07 · Reindexing je Haushalt, kein globaler Flottenkalender

`shift(k)` ist nur dann korrekt, wenn die Zeile *k* Positionen zurück auch dem
Tag *d−k* entspricht. 39 der 153 verbleibenden Haushalte haben Kalenderlücken
von bis zu 333 fehlenden Tagen (im Rohbestand vor D-04: 41 von 156) — ohne
Reindexing würde ein `shift(1)` dort über die Lücke springen und einen Wert von
vor Wochen als „gestern" ausgeben.

Reindiziert wird je Haushalt auf dessen eigene Spanne `[first_date, last_date]`,
nicht auf einen flottenweiten Kalender. Ein globaler Kalender würde Zeilen für
Zeiträume erzeugen, in denen der Zähler nachweislich nicht lief.

Die Lückenzeilen dienen der Korrektheit der Shift-Operationen, nicht dem Füllen:
der Zielwert bleibt dort NaN, die Zeile wird mit `is_gap` markiert.

**Sie werden am Ende von Stufe 3 wieder entfernt.** Ihr Zweck endet in dem
Moment, in dem die Features gebaut sind — danach sind es 1.347 Zeilen ohne einen
einzigen Messwert, die nur das Artefakt und jede daraus gerechnete Kennzahl
aufblähen würden. Vor dem Entfernen wird belegt, dass sie tatsächlich leer sind:
alle 10 Messspalten (`kWh_*`, `kvarh_*`) sind auf ihnen unbelegt. Wären sie es
nicht, hätte der Reindex beobachtete Daten überschrieben — dann müsste der Lauf
laut scheitern statt still zu löschen.

Die Reihenfolge ist zwingend: **erst Features, dann Entfernen.** Umgekehrt
entstünden genau die Lücken wieder, die der Reindex schließen sollte, und die
Lags würden still über sie hinweggreifen. Der Preis ist, dass das Panel danach
je Haushalt **nicht mehr lückenlos** ist; wer weitere Zeitreihenoperationen
darauf rechnet, muss zuerst neu reindizieren. Das Schema hält das unter
`gap_rows_note` fest.

*Code:* `utils/cleaning/smart_meter.py` (Stufe 2),
`scripts/03_build_panel.py::drop_gap_rows` (Stufe 3)

## D-08 · Vier Zustände in `AffectsTimePoint`

Verifiziert in Stufe 1: die Spalte kennt `before visit`, `after visit`,
`during visit` (je Haushalt genau ein Tag) und `unknown` (16 Zeilen, ein
Haushalt). Der Besuchstag gehört zu keinem der beiden Regime und erhält ein
eigenes Flag.

`visit_date` ist nur für die 56 Haushalte mit `during visit` bestimmbar. 21
Haushalte hatten ihren Besuch vor Aufzeichnungsbeginn (nur `after visit`), 78
innerhalb des Datenfensters gar keinen (nur `before visit`). `days_since_visit`
bleibt für alle Haushalte ohne bekanntes Besuchsdatum NaN — ein `0` wäre eine
Erfindung.

*Code:* `utils/config.py::AFFECTS_TIME_POINT_VALUES`, `utils/loading.py::_check_visit_states`

## D-09 · Ein Druckkanal, nicht drei

Die Rohdaten enthalten drei Druckvarianten. `Pressure_BarometricHeight` und
`Pressure_SeaLevelStandardAtmosphere` liegen für 5 der 8 Stationen vor,
`Pressure_SeaLevel` nur für 4. Weitergetragen wird `BarometricHeight`; die
anderen beiden tragen bei gleicher oder schlechterer Abdeckung keine zusätzliche
Information (sie sind Umrechnungen derselben Messung).

*Code:* `utils/config.py::WEATHER_PRESSURE_KEEP`

## D-10 · Heizgradtage mit Basis 15 °C, Basis im Spaltennamen

`hdd_15 = max(0, 15 − Temperature_avg_hourly_mean)`. 15 °C ist die Basis der
Gradtagzahl nach deutscher Konvention (G15): unterhalb von 15 °C Tagesmittel
wird geheizt. Die Rohdaten dokumentieren zwar Tagesvarianten (SIA 12/20,
US-HDD), liefern sie aber nicht mit — die Größe wird daher selbst berechnet.

Die Basis steckt bewusst im **Spaltennamen**. Eine Spalte `hdd` würde die
Annahme unsichtbar machen: zwei Läufe mit unterschiedlicher Basis wären in
Ergebnistabellen nicht unterscheidbar. `HDD_COLUMN` wird aus `HDD_BASE_C`
abgeleitet, ein Wechsel auf 18 °C erzeugt also automatisch `hdd_18`.

Die Basis ist eine Annahme, keine Messung. Ob 15 °C für diese Flotte optimal
ist, prüft das Insight-Notebook anhand der Temperatur-Last-Kurve. Für
Wärmepumpen-Haushalte ist die niedrigere Basis plausibler als 18 °C: die
Heizgrenze eines gut gedämmten Neubaus liegt unter der eines Altbaus, und die
Flotte besteht zu 99 % aus Einfamilienhäusern mit Wärmepumpe.

*Code:* `utils/config.py::HDD_BASE_C`, `HDD_COLUMN`

## D-11 · Ausreißer werden markiert, nicht korrigiert

Auffällige Tagesverbräuche werden je Haushalt robust erkannt
(Median + 5·MAD) und geflaggt. Der Wert selbst bleibt unangetastet: ein hoher
Verbrauch an einem kalten Tag ist echt, und ein Cap würde genau die Spitzen
glätten, deren Prognose für die Beschaffung am wichtigsten ist.

*Code:* `utils/config.py::SPIKE_MAD_K`

## D-12 · Strukturelle NaN in `kWh_returned_Total` werden zu Null

Haushalte ohne *jede* positive Einspeisung sind strukturell keine Einspeiser;
ihre leeren Zellen bedeuten „keine Einspeisung", nicht „Messwert fehlt". Sie
werden auf `0.0` gesetzt und mit `returned_was_substituted` markiert. Aktive
Einspeiser behalten ihre NaN als echte Messlücken.

Die Unterscheidung ist die Grundlage für die PV-Erkennung in Level 1. Die Spalte
bleibt in jedem Fall Passthrough und wird nie Prädiktor.

*Code:* `utils/cleaning/smart_meter.py` (Stufe 2)

## D-13 · Flottenweiter Kalender-Cutoff für den Split

Ein festes Datum trennt `train` von `test`, für alle Haushalte dasselbe. Der
Grenztag gehört zu `train`, der Test ist strikt Zukunft.

Die Alternative „letzte X Prozent je Haushalt" würde dazu führen, dass
Trainingsdaten eines Haushalts kalendarisch nach Testdaten eines anderen liegen.
Das Modell hätte damit Zugang zu Informationen über einen Zeitraum, den es
vorhersagen soll — ein Vorsprung, den es in der Realität nicht gibt. Day-ahead
beschafft ohnehin die gesamte Flotte für ein gemeinsames Zukunftsfenster.

*Code:* `utils/config.py::SPLIT_CUTOFF`

## D-14 · Getrennte Verzeichnisse je Pipeline-Stufe

Stufe 1 schreibt nach `data/interim/01_ingested/`, Stufe 2 nach
`data/interim/02_clean/`. Jede Stufe liest ausschließlich das Verzeichnis ihrer
Vorstufe. Damit ist die Scope-Firewall mechanisch prüfbar statt nur
konventionell, und der Zustand nach jeder Stufe bleibt für die Fehlersuche
erhalten.

*Code:* `utils/config.py::INGESTED`, `CLEAN`

## D-15 · Zahlen im Report werden gerechnet, nicht abgeschrieben

Jede Kennzahl im Report entsteht zur Laufzeit aus dem aktuellen DataFrame. Die
in `config.py::EXPECTED` hinterlegten Werte sind ausschließlich
Regressions-Erwartungen: weicht ein Lauf ab, haben sich die Rohdaten geändert.
Sie werden nie in den Report kopiert.

*Code:* `utils/reporting.py`, `utils/config.py::EXPECTED`

## D-16 · Wetterspalten heißen nach ihrem Aggregat, nicht nach ihrem Lag

Die Tagesaggregate tragen den Namen `<Rohspalte>_<Aggregatfunktion>`, also
`Temperature_avg_hourly_min` statt `temp_min_lag2`. Der Rohname bleibt damit
sichtbar, und die Aggregatfunktion ist aus dem Spaltennamen ablesbar statt nur
aus der Dokumentation.

Der Preis ist real: die Verschiebung ist am Namen **nicht mehr erkennbar**. Wer
`Temperature_avg_hourly_mean` liest, könnte die Temperatur des Zieltags
vermuten. Vorher war das durch die Konvention „jede Wetterspalte endet auf
`_lag2`" mechanisch ausgeschlossen.

Der Ersatz ist stärker als die Konvention, die er ablöst. Statt zu prüfen, ob
der Name ein Suffix trägt, wird für **jede** Wetterspalte einzeln gegen einen
unabhängigen Self-Join nachgewiesen, dass sie die Stationsbeobachtung von
*d−FORECAST_LAG* enthält — und zusätzlich, dass sie **nicht** dem Zieltagswert
entspricht. Die zweite Hälfte ist der eigentliche Fortschritt: ein
versehentlicher Shift von 0 Tagen hätte den alten Namenstest bestanden, solange
der Name stimmte, und wäre auch einer Gleichheitsprüfung entgangen. Er fällt
jetzt auf.

Damit die Namen niemanden in die Irre führen, hält das Schema
`weather_shift_days` und einen erklärenden `weather_naming_note` fest.

*Code:* `utils/config.py::daily_name`, `utils/merge.py::weather_panel_columns`,
`scripts/03_build_panel.py::_prove_weather_shift`

## D-17 · Schmale aktive Auswahl, breite Reserve

Das Panel berechnet 50 Featurekandidaten, die aktive Auswahl dieser Stufe
umfasst **20**. Die übrigen 30 bleiben als Spalten im Panel, stehen aber im
Schema unter `deselected` statt unter `feature_groups` — ein Modeling-Skript,
das dem Schema folgt, sieht sie nicht. (**Nachtrag zu D-21:** der
Übergabevertrag, den das Modell tatsächlich liest, umfasst **21** Features —
Schritt 10.5 ergänzt `weather_id`, siehe D-21. Die 20 hier beschreiben die
Auswahl aus den 50 berechneten Kandidaten.)

Aktiv sind: 4 autoregressive (`recv_lag1`, `recv_lag7`, `recv_roll7_mean`,
`recv_roll7_std`), 9 Wetter (Temperatur mean/min/max, Feuchte, Wind, Taupunkt,
Niederschlag, Sonnenschein, `hdd_15`), 5 Kalender (`dow`, `month`, `season`,
`is_weekend`, `is_holiday`), 1 Regime (`is_post_visit`) und 1 statisch
(`Installation_HasPVSystem`).

Die Begründung ist methodisch, nicht inhaltlich: ein schmales Baseline-Modell
ist interpretierbar, schnell und liefert den Maßstab, gegen den jede Erweiterung
ihren Beitrag belegen muss. Der Satz deckt die Physik des Problems ab —
Autoregression für das Niveau, Temperatur und Heizgradtage für den Heizbedarf,
Kalender für den Wochenrhythmus. Alles darüber ist eine Hypothese.

Nicht ausgewählt zu werden ist kein Urteil über eine Spalte. Die Reserve
existiert genau deshalb: der Vergleich „Modell mit Meta-Daten gegen Modell ohne"
kostet eine Zeile in `feature_selection.ACTIVE`. (**Nachtrag zu D-22:** seit das
Panel schmal geschrieben wird, kostet er zusätzlich einen Pipeline-Lauf von rund
zwei Sekunden. Die Reserve wird weiterhin gerechnet und geprüft, nur nicht mehr
mitgeschrieben.) Für die
Survey-Merkmale ist dieses Ablationsexperiment ausdrücklich vorgesehen — die
Erwartung ist, dass zeitinvariante Gebäudemerkmale im gepoolten Modell wenig
beitragen, weil `recv_lag1` und `recv_roll7_mean` das Haushaltsniveau schon
tragen. Erwartung, nicht Befund.

Jede Nicht-Auswahl steht mit Begründung in
`feature_selection.DESELECTED_REASONS` und wird von dort in Report und Schema
übernommen, damit sie nicht an drei Stellen auseinanderlaufen kann.

*Code:* `utils/feature_selection.py`

## D-18 · Fehlendes Wetter *außerhalb* des Fensters droppt, *innerhalb* nicht

Zwei Sachverhalte führen zu einer Zeile ohne Wetterwert. Sie sehen im DataFrame
identisch aus — beide sind NaN — bedeuten aber Gegensätzliches, und deshalb
werden sie gegensätzlich behandelt.

**Außerhalb des Fensters: droppen.** Die Zählerdaten reichen von 2018-11-02 bis
2024-03-20, das Wetter nur von 2019-01-01 bis 2024-02-29. Um `FORECAST_LAG`
verschoben ergibt das ein nutzbares Panelfenster von 2019-01-02 bis 2024-03-01;
die 3.413 Zeilen außerhalb werden entfernt. Der Grund ist, dass dort schlicht
**nichts geliefert wurde** — das ist eine Eigenschaft dieses Datensatzes, nicht
der Betriebssituation. Im Betrieb liegt die Wetterbeobachtung von *d−1* zum
Gebotszeitpunkt vor; sie ist eine Messung, keine Prognose, und längst
aufgezeichnet. Diese Zeilen mitzuschleppen hieße, einen dauerhaften NaN-Block
zu führen, der eine Lücke der Datenlieferung als Modellierungsproblem tarnt.
Der Preis ist bekannt und wird im Report beziffert: alle 3.413 haben einen
Zielwert, 100 Haushalte sind betroffen, keiner verliert seine gesamte Historie.

**Innerhalb des Fensters: behalten.** 107 Zeilen an 28 Tagen bei den Stationen
`HbsbG` und `ceOxS` haben trotz Fenster kein Wetter. Das ist ein
**Stationsausfall** — und der passiert im Betrieb genauso. Ein Modell, das
täglich für die gesamte Flotte bieten muss, hat keine Möglichkeit zu schweigen,
wenn eine Wetterstation ausfällt. Diese Zeilen aus der Bewertung zu entfernen
würde die gemessene Genauigkeit besser aussehen lassen als die betriebliche
Wirklichkeit.

Daraus folgt für diese Zeilen: Wetter ist ausdrücklich **keine** Bedingung von
`is_modelable`. Die Definition selbst ist allein **Zielwert vorhanden** — auch
Pflicht-Lags sind keine Bedingung, siehe D-19. Ein
Wettermodell muss die 107 Zeilen selbst behandeln (Bäume mit nativer
NaN-Behandlung, Rückgriff auf eine Nachbarstation oder ein Fallback ohne
Wetter). Der Nebeneffekt ist methodisch wichtig: weil `is_modelable` nicht von
den Featureanforderungen eines bestimmten Modells abhängt, werden ein rein
autoregressives und ein wetterbasiertes Modell auf **denselben Zeilen**
bewertet. Andernfalls entstünden zwei Kennzahlen auf zwei verschiedenen
Teilmengen, die sich nicht vergleichen lassen.

Der Zuschnitt ist über `config.TRIM_TO_WEATHER_WINDOW` abschaltbar. Aus ist er
sinnvoll, wenn ausschließlich autoregressiv modelliert werden soll: dann sind
die 3.413 Zeilen nutzbar, weil kein Wetter gebraucht wird.

*Code:* `utils/config.py::TRIM_TO_WEATHER_WINDOW`, `utils/merge.py::trim_to_window`,
`scripts/03_build_panel.py::report_usability`

## D-19 · `is_modelable` verlangt nur den Zielwert, kein Feature

Eine Zeile gilt als modellierbar, wenn `kWh_received_Total` gesetzt ist —
**sonst nichts**. Weder fehlende Lags noch fehlendes Wetter disqualifizieren
sie. Das betrifft 81.085 der 82.051 Panelzeilen (98,8 %).

Die Begründung ist der Unterschied zwischen einem fehlenden **Label** und einem
fehlenden **Feature**.

Ohne Label gibt es keinen Gradienten und keine Metrik — die Zeile ist für
Training wie Bewertung wertlos. (Eine Prediction wäre dort möglich, alle
Features stehen; man erfährt nur nie, ob sie gut war.) Das ist der einzige
zwingende Ausschluss.

Ein fehlendes Feature ist etwas anderes: es ist ein **Betriebszustand**. Ein
fehlender `recv_lag1` ist die Folge eines Zählerausfalls, ein fehlender
Wetterwert die Folge eines Stationsausfalls. Beides passiert im Betrieb, und
day-ahead muss für den betroffenen Tag trotzdem ein Gebot abgegeben werden — die
Flotte kann nicht schweigen, weil ein Zähler stumm ist. Diese Zeilen aus der
Bewertung zu nehmen hieße, das Modell nur an den Tagen zu messen, an denen alles
funktioniert hat, und eine Genauigkeit auszuweisen, die im Betrieb nicht
eintritt. Konkret ginge es um 1.315 Zeilen ohne Pflicht-Lags und 107 ohne
Wetter — alle mit Label, alle bewertbar.

Die Konsequenz trägt das Modell, nicht die Data Preparation: es muss die NaN
aushalten. Gradient-Boosting-Verfahren tun das nativ (LightGBM und XGBoost
lernen je Split eine Default-Richtung, das Modell lernt also explizit das
Verhalten bei fehlender Historie). Ein lineares Modell braucht stattdessen einen
Imputer — auf `train` gefittet, siehe D-06 — oder ein Fallback ohne Lags.

Ein methodischer Nebeneffekt ist der eigentliche Gewinn: weil die Bedingung
keine Featureanforderung enthält, ist die Bewertungsmenge
**modellunabhängig**. Ein rein autoregressives und ein wetterbasiertes Modell
werden auf denselben Zeilen bewertet und bleiben vergleichbar. Hinge
`is_modelable` an den Features, bekäme jedes Modell seine eigene Teilmenge und
zwei RMSE-Werte ließen sich nicht mehr gegeneinander lesen.

Die Richtung ist außerdem die einzig umkehrbare. Die Verfügbarkeit jedes
Features bleibt zeilenweise an den Spalten selbst ablesbar
(`recv_lag1.isna()`), eine strengere Teilmenge ist also eine Zeile Code im
Modeling. Zeilen zurückzuholen, die eine Flag bereits verworfen hat, geht nicht.

Nebenbefund für das Modeling-Log: von den 966 Zeilen ohne Zielwert gehören 957
zu Haushalt `816910` — 93 % seiner Zeilen über zweieinhalb Jahre, es bleiben 77
verwertbare Tage. Der Unterschied zu den drei in D-04 entfernten Haushalten ist
nur graduell (0 % gegen 7 % Abdeckung). Ob er ins Modell gehört, ist eine
Modeling-Entscheidung; die Data Preparation entfernt ihn nicht.

*Code:* `scripts/03_build_panel.py::report_usability`

## D-20 · `Installation_HasPVSystem` ist die PV-Segmentierungsvariable

Für jede Aufteilung der Flotte in PV- und Nicht-PV-Haushalte — Level 1b, Gruppenmodelle, Auswertungen nach Segment — ist **`Installation_HasPVSystem`** die maßgebliche Variable. Sie ist eine Haushaltseigenschaft aus den Stammdaten (`households.csv`), im Panel zu 100 % belegt und trennt **39 PV-Haushalte von 114 ohne**.

Der Grund, sie und nicht das Zählerverhalten zum Maßstab zu machen, ist, dass sie eine **gemeldete Eigenschaft der Installation** ist und keine Eigenschaft des Messfensters. Ob eine Anlage im beobachteten Zeitraum tatsächlich eingespeist hat, hängt an Wetter, Anlagengröße, Ausfällen und dem Installationsdatum. Ob sie existiert, hängt daran nicht.

### Die Meldung ist gegen die Daten geprüft

Der Abgleich je Haushalt zwischen Flag und tatsächlicher Einspeisung (`max(kWh_returned_Total) > 0`):

| | speist nie ein | speist ein |
|---|---:|---:|
| **PV = False** (114) | 114 | 0 |
| **PV = True** (39) | 2 | 37 |

Die entscheidende Zelle ist die Null oben rechts: **kein Haushalt speist ein, ohne als PV-Besitzer geführt zu sein.** Das ist die Richtung, in der ein Fehler das Label unbrauchbar machen würde, und sie ist leer. Die Meldung ist damit belastbar.

Die zwei Abweichungen in der anderen Richtung sind erklärbar: `1211151` (766 Tage, endet 2021-04-05) und `7374981` (657 Tage, endet 2020-12-17) sind als PV-Besitzer geführt, speisen aber an keinem einzigen Tag ein. Beide Zeitreihen enden früh — plausibel ist eine Anlage, die nach dem Messzeitraum installiert wurde. Sie bleiben im PV-Segment, weil das Label die Installation beschreibt und nicht das Messfenster.

`pv_flag_imputed` markiert den einen Haushalt, bei dem das Flag *abgeleitet* statt gemeldet ist: `877881` stand auf `unknown` und wurde auf `False` gesetzt, weil über seine gesamte Messhistorie von 170 Tagen (2023-10-03 bis 2024-03-20) keine einzige Einspeisung beobachtet wurde — die durchgängig leeren `kWh_returned_Total`-Zellen wurden nach D-12 auf `0.0` substituiert. 151 dieser Tage liegen im Panelfenster. Wer die Segmentierung strikt auf gemeldete Werte stützen will, schließt diesen einen Haushalt über die Flag aus.

### Was ausdrücklich *nicht* die Segmentierungsvariable ist

`kWh_returned_Total` und `returned_was_substituted` beschreiben dieselbe Sache aus der Messung heraus — und genau deshalb sind sie ungeeignet.

Für **Level 1b** („PV-Besitzer am Verbrauchsmuster erkennen") sind sie die **Antwort, nicht das Merkmal**. Ein Klassifikator, der die Einspeisung sieht, erreicht trivial 100 % und zeigt nichts. Auf Haushaltsebene ist `returned_was_substituted` mit der Einspeisung sogar exakt deckungsgleich — die Kreuztabelle ist perfekt diagonal (116 Nicht-Einspeiser durchgehend `True`, 37 Einspeiser durchgehend `False`, keine Abweichung). Die Spalte ist ein Herkunfts-Flag aus D-12 ohne jede Variation innerhalb eines Haushalts, also faktisch ein zweites PV-Label. Beide gehören auf die Sperrliste jedes verbrauchsseitigen Detektors und sind deshalb als `passthrough` bzw. `flags` geführt, nie als Feature.

Daraus folgt die Obergrenze für einen solchen Detektor: **37 von 39** erkennbaren PV-Haushalten. Die zwei Haushalte ohne Einspeisung im Messfenster verhalten sich in den Verbrauchsdaten wie Nicht-PV-Haushalte, weil sie es dort faktisch waren. Ein Recall von 95 % gegen dieses Label ist damit kein Modellfehler, sondern die Datengrenze — sie gehört in die Bewertung, nicht in die Fehlerdiskussion.

`kWh_returned_Total` scheidet zusätzlich aus einem zweiten Grund aus: es ist der Wert des **Zieltags** und zum Gebotszeitpunkt nicht bekannt (D-05).

### Segmentierung arbeitet auf Haushalten, nicht auf Panelzeilen

Ausgangsframe ist `data/interim/02_clean/households.parquet` (153 × 39), nicht das Panel. Dort steht jedes Merkmal einmal je Haushalt statt 82.051-mal ausgerollt, und die Aggregate für Gruppenbildung liegen bereits vor (`target_mean`, `returned_coverage`, `n_returned_observed`, `n_days`, `max_gap_days`). Wer auf dem Panel gruppiert, gewichtet jeden Haushalt implizit mit seiner Historienlänge — ein Haushalt mit 1.900 Tagen zählt dann 380-mal so viel wie einer mit 5.

*Code:* `utils/cleaning/smart_meter.py::cross_check_pv_flag` (Abgleich und `pv_flag_imputed`),
`utils/cleaning/smart_meter.py::substitute_returned` (D-12),
`utils/feature_selection.py::STATIC_ACTIVE`

## D-21 · Finale Vorselektion als Schritt 10.5, mit eigenem Vokabular

Am Ende von Stufe 3 steht ein Übergabevertrag: **21 Features, `gross_load` als Ziel, `Household_ID` und `date` als Schlüssel**. Er liegt in `utils/preselection.py::FEATURES` und im Schema unter `preselection`.

### Warum genau nach Schritt 10

Der Schritt braucht zwei Spalten, die vorher nicht existieren. `split`, weil jede Statistik ausschließlich auf Trainingszeilen gerechnet wird — das Testfenster darf die Modellspezifikation nicht mitbestimmen, auch nicht über eine Belegungszahl. Und `is_modelable`, damit die Belegung nicht über 966 Zeilen läuft, die kein Modell je sieht. Gerechnet wird auf **65.502 Zeilen** (`train` und `is_modelable`).

Die Split-Maske vor Schritt 9 inline zu bilden wäre technisch möglich, würde die Split-Logik aber an zwei Stellen führen. Ein Cutoff, zwei Definitionen — genau die Drift, die `config` als Einzelquelle verhindern soll.

### Zwei Vokabulare, eine Grenze

Stromaufwärts trägt jede Spalte ihren Quellnamen. Das ist die Grundlage der Prüfbarkeit: die Leakage-Beweise, alle Checks und jeder Eintrag in diesem Dokument beziehen sich darauf, und jede Spalte lässt sich ohne Übersetzungstabelle bis in die gelieferte CSV zurückverfolgen.

Stromabwärts bekommt das Modell die Begriffe der Modellierung:

| Quellname | Vertragsname |
|---|---|
| `kWh_received_Total` | `gross_load` |
| `Weather_ID` | `weather_id` |

`gross_load` sagt, **was** die Größe ist — Bruttobezug aus dem Netz, vor jeder Verrechnung mit PV-Eigenverbrauch — statt wie sie gemessen wurde. Das ist bei einem Datensatz mit 39 PV-Haushalten keine Kosmetik: „received Total" verleitet zu der Annahme, es handle sich um einen Nettowert.

Umbenannt wird deshalb erst hier, als letzte Transformation vor dem Schreiben. Alles davor bleibt im Quellvokabular und damit gegen Report und Rohdaten lesbar. Die Abbildung steht im Schema unter `preselection.renamed`, ist also maschinell auflösbar und nicht nur dokumentiert.

### `weather_id` wird Feature — mit bekanntem Preis

Neu im Satz gegenüber D-17. Die Station trägt den regionalen Versatz, den die acht Wetterspalten nicht abbilden: Höhenlage, Stadt gegen Land, Bausubstanz des Einzugsgebiets. Als `category` mit 8 Stufen übergeben, damit ein Baum sie nicht als Ordinalzahl liest.

Der Preis ist derselbe wie bei den Survey-Merkmalen aus D-17: die Spalte ist je Haushalt invariant und kodiert damit auch Flottenstruktur, nicht nur Klima. Sie ist aber deutlich unkritischer — **8 Stufen auf 153 Haushalte** gegen 139 unterscheidbare Survey-Profile. Ein Split auf `weather_id` fasst im Schnitt 19 Haushalte zusammen und kann keine Haushaltsidentität memorieren. Genau das war der Einwand gegen die Survey-Merkmale, und er greift hier nicht.

### Die Vorselektion deklariert, sie sucht nicht

`FEATURES` ist eine Festlegung. Der Schritt kürzt die Liste nicht, er beweist, dass sie tragfähig ist, und berichtet, was ein Leser sonst selbst herausfinden müsste.

Hart geprüft: alle 21 Spalten vorhanden, keine doppelt, Ziel und Schlüssel vorhanden, keine der 16 gesperrten Spalten dabei, keine auf `train` konstant. Zusätzlich prüft der Schritt, dass `config.HDD_COLUMN` Teil des Vertrags ist — ein Wechsel von `HDD_BASE_C` auf 18 erzeugt `hdd_18` und würde das Feature sonst still aus dem Satz fallen lassen.

Die Trennlinie: **zielunabhängige** Kriterien gehören hierher, **zielabhängige** ins Modeling. Wer in der Data Preparation nach `corr(feature, target)` aussortiert, hat ein Modell angepasst und es nicht validiert — der Selektionsfehler taucht danach in keiner Kennzahl auf, weil die Kreuzvalidierung ihn nicht sieht.

### Drei funktionale Abhängigkeiten, bewusst behalten

Exakt verifiziert, nicht per Schwellwert erkannt:

```
is_weekend == (dow >= 5)
season     == f(month)
hdd_15     == max(0, 15 − Temperature_avg_hourly_mean)
```

Für **Bäume** sind alle drei redundant: RF und LightGBM sind gegen monotone Transformationen einer Einzelvariable invariant, ein Split auf `hdd_15 > x` ist identisch mit `Temperature_avg_hourly_mean < 15−x`. Für ein **lineares** Modell sind sie es nicht — dort trägt der Knick bei 15 °C echte Information, und `season` als Gruppierung ist etwas anderes als `month` als Zahl.

Deshalb bleiben sie im Vertrag und werden im Report benannt. Die Entscheidung, sie für ein Baummodell wegzulassen, ist eine Modellentscheidung und kostet eine Zeile im Modeling. Sie im Panel zu treffen hieße, ein lineares Vergleichsmodell ohne Not zu beschneiden.

### Kein Korrelations- und kein Varianzfilter

Beide wären hier schädlich, deshalb sind die Schwellwerte in `config` reine **Berichtsschwellen**.

Zehn Featurepaare liegen über |r| = 0,90, der Wetterblock ist ein Cluster (`Temperature_mean` ↔ `Temperature_max` bei 0,973). Multikollinearität kostet Baummodelle die Interpretierbarkeit der Importances, nicht die Genauigkeit. `Temperature_max` zu streichen kostet die Extremtage — also genau die, auf die es in der Beschaffung ankommt.

Ein Near-Zero-Variance-Filter würde `is_holiday` treffen: 97,5 % derselbe Wert. Die 2,5 % sind die Tage, an denen das Lastprofil kippt.

Berichtet wird außerdem die Belegung. Niedrigster Wert ist `Sunshine_duration_hourly_sum` mit 90,83 % (die drei Stationen ohne Sensor, D-09), alles andere über 98 %. Behalten nach der Logik von D-19: eine Lücke ist ein Ausfall, den das Modell aushalten muss, kein Grund, die Zeile aus der Bewertung zu nehmen.

### `preselection.features` ist der Vertrag

Das Schema führt zwei Sichten auf denselben Satz — `feature_groups` nach Herkunft gruppiert, `preselection.features` als flache geordnete Liste. Dass sie identisch sind, wird geprüft und nicht angenommen (`_sync_groups`), sonst laufen sie beim nächsten Eingriff auseinander.

Das Modeling liest `preselection.features`, **nie** `panel.columns`. Der Grund ist messbar: `kWh_received_HeatPump + kWh_received_Other == gross_load` gilt exakt auf allen 3.172 Zeilen mit beiden Submetern. Ein `df.drop(columns=["gross_load"])` liefert ein R² von 1,0 auf 4 % der Zeilen. Die Sperrliste in `preselection.forbidden_columns()` macht diese Trennung mechanisch statt konventionell.

*Code:* `utils/preselection.py`, `utils/config.py::PRESELECT_*`,
`scripts/03_build_panel.py::run` (Schritt 10.5)

## D-22 · Das Panel wird schmal geschrieben — 26 statt 70 Spalten

Geschrieben wird nur noch der Vertrag: **2 Schlüssel, 1 Ziel, 21 Features, `split`, `is_modelable`**. 44 Spalten fallen weg.

Die vier Nicht-Features gehören dazu, weil die Tabelle ohne sie nicht benutzbar wäre: ohne Schlüssel ist eine Zeile nicht identifizierbar, ohne Ziel nichts trainierbar, und ohne `split` und `is_modelable` lassen sich die beiden Pflichtfilter nicht anwenden.

### Der eigentliche Gewinn ist strukturell

Vorher war die Trennung zwischen Feature und Nicht-Feature eine **Konvention im Schema**. Wer `df.drop(columns=[target])` schrieb, bekam 69 Spalten, davon 14 gesperrte — darunter `kWh_received_HeatPump` und `kWh_received_Other`, die exakt zu `gross_load` summieren. Das Ergebnis wäre ein R² von 1,0 auf 4 % der Zeilen gewesen, und zwar ohne Fehlermeldung.

Jetzt liefert derselbe Aufruf 25 Spalten, und die beiden gefährlichen sind physisch nicht mehr da. Übrig bleiben `split` und `is_modelable`, die kein Signal über den Zielwert tragen. Die Falle ist damit nicht mehr durch Disziplin vermieden, sondern durch Abwesenheit.

### Was es kostet, und was nicht

Aufgegeben werden 30 Reservespalten (D-17), 9 Passthrough-Messungen, 3 Zeilenflags (`is_gap` — ohnehin durchgehend `False`, `kWh_spike_flag`, `returned_was_substituted`) und 2 Restspalten (`Timestamp`, `visit_date`).

Die Argumentation in D-17 stimmt damit nicht mehr wörtlich: der Ablationsversuch kostet jetzt einen Pipeline-Lauf. Der wiegt allerdings weniger als das Argument unterstellt — **Stufe 3 läuft in rund zwei Sekunden**. Gerechnet und geprüft werden die Reservespalten unverändert; nur das Schreiben ist bedingt. Genau deshalb ist es ein Schalter und keine Löschung.

Drei Rückwege, unterschiedlich teuer:

| Was | Wie | Kosten |
|---|---|---|
| Survey-Merkmale | Join über `Household_ID` auf `02_clean/households.parquet` (153 × 39) | kein Lauf |
| berechnete Reserve (`recv_lag3/9/14`, `recv_roll28_*`, `doy_sin/cos`, rollende Wetterfenster, Druck, `WindSpeed_hourly_max`, `days_since_visit`, `is_visit_day`) | `PANEL_SLIM = False` | ein Lauf, ~2 s |
| Passthrough (PV-Gegenprobe aus D-20) | `PANEL_SLIM = False` | ein Lauf, ~2 s |

Der erste Rückweg ist der wichtigste und war schon vor dieser Entscheidung der bessere: für Segmentierung ist `households.parquet` ohnehin die richtige Quelle, weil dort jeder Haushalt einmal zählt und nicht einmal pro Tag (D-20).

### Nebenwirkung auf das Schema

`passthrough` und `flags` werden aus den tatsächlich vorhandenen Spalten gebildet und schrumpfen automatisch auf `[]` bzw. `["is_modelable"]` — das Schema beschreibt das Artefakt, nicht die Absicht. `deselected` bleibt vollständig erhalten, inklusive aller Begründungen, ergänzt um `present_in_panel: false`. Die Nicht-Auswahl bleibt damit dokumentiert, auch wenn die Spalte nicht mehr im File liegt.

Die Datei fällt von 5,8 auf **2,7 MB**.

*Code:* `utils/config.py::PANEL_SLIM`, `utils/preselection.py::slim`,
`utils/preselection.py::contract_columns`

## D-23 · Data Understanding liest zwei Datenzonen: Lieferung auf `raw`, EDA auf dem Panel

Das Kapitel Data Understanding ist zweistufig. Die Unterkapitel *Delivered
data* (Notebook 01) und *Data quality* (Notebook 02) arbeiten auf `data/raw/`:
Gegenstand ist die **Lieferung selbst**, und jeder Befund zu Abdeckung, Lücken
und Qualität muss auf den unveränderten Dateien stehen — sonst beschreibt er
die Pipeline statt der Daten. Das Unterkapitel *Exploratory data analysis*
(Notebook 03) arbeitet dagegen auf `data/processed/model_table.parquet` und
den bereinigten Tabellen aus `02_clean/`: Gegenstand sind die **inhaltlichen
Zusammenhänge** — Temperatur-Last-Kurve, Saisonalität, Heterogenität,
PV-Effekt.

Der scheinbare Konflikt mit der CRISP-DM-Reihenfolge — Data Understanding vor
Data Preparation — ist keiner: Der Prozess ist ausdrücklich iterativ, die
Rücksprünge zwischen beiden Phasen sind Teil des Modells. Entscheidend ist die
Arbeitsteilung. Qualitätsprobleme werden auf `raw` **entdeckt und
dokumentiert** (Notebook 02), bevor die Bereinigung sie behandelt — die EDA
versteckt also nichts, was nicht vorher belegt wäre. Eine EDA direkt auf `raw`
würde umgekehrt Verteilungen und Korrelationen durch genau die Befunde
verzerren, die Notebook 02 dokumentiert.

Der zweite Grund ist inhaltlich: Die EDA-Fragen Q1–Q7 fragen nach der
**Modellierungsgrundlage**, und die ist das Panel, nicht die gelieferten CSVs.
`gross_load` ist erst dort definiert (D-21), und `is_modelable` grenzt die
Zeilen ab, die ein Modell überhaupt sieht (D-19). Dieselben Fragen auf `raw`
zu beantworten hieße, die Join-, Shift- und Bereinigungslogik der Pipeline im
Notebook zu duplizieren — mit dem Risiko, dass beide Fassungen auseinanderlaufen.

Der Preis: Die EDA erbt jede Preparation-Entscheidung (etwa D-04, D-18). Wer
einen EDA-Befund anzweifelt, muss die Kette bis zur betreffenden Entscheidung
zurückverfolgen können — deshalb verweisen die Lesarten in Notebook 03 auf die
D-Einträge, auf denen sie stehen.

*Code:* `notebooks/data_understanding/01_delivered_data.ipynb`,
`02_data_quality.ipynb`, `03_eda.ipynb`;
Kurzfassung der Zonenaufteilung in `docs/data_understanding_visuals.md`
