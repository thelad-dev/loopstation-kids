# Loopstation Kids — Verbesserungsplan

Stand: 20. November 2026 (Europe/Berlin). Finale Fassung.
Ausgangslage: Plan vom 20. November 2026 (Gespräch Sebastian / Aurora), Abgleich mit dem Code, Überarbeitung (v2) und Ergänzungen aus dem Voice-Chat (Sets, Plattformen, Windows-Backends, Export-Summe, Session-View-Rahmen).
Repo: [thelad-dev/loopstation-kids](https://github.com/thelad-dev/loopstation-kids) (Python, PySide6, sounddevice/PortAudio), zuletzt gegen Commit-Stand vor dieser Fassung und gegen den Code (u. a. Controller, Event-Store, Audio-Backend) geprüft.

Ziel: Aus dem bestehenden Kinderspielzeug eine richtig gute Loopstation machen — einfach für Kinder (auch mit neurodiversen Bedürfnissen: Reizempfindlichkeit, Vorhersehbarkeit, motorische Unterschiede), mit genug Eltern-Einstellungen für ein ordentliches Produkt. Die Kindseite bleibt strikt dünn (Pad-Raster, Puls, sichtbares Zurück, Lautstärke, fertig); alles andere gehört hinter den Eltern- bzw. Erweitert-Bereich.

Diese Datei ist der alleinige, vollständige Plan im Repository. Eine frühere Fehleranalyse (`review.md`) und eine ausführliche Quellenrecherche (`recherche.md`) entstanden bei der Überarbeitung, liegen aber **nicht in diesem Repo**. Die für die Arbeit nötigen Recherche-Kernpunkte und Quellen-URLs stehen in Abschnitt 17.

---

## 0. Ist-Stand (damit der Plan nicht ins Leere plant)

Was die App **bereits** kann:

- 12 große Pads, Modi Spielen / Aufnehmen / Loop / Löschen / Verlauf, „Zurück“ (Strg+Z), „Alles still“, „Alle löschen“.
- Event-Store (`events.jsonl`) mit festem Typensatz, Snapshots, Archiv. Undo ist ein Event `undo` mit Ziel-`seq`; der Stack lebt in `AppState` (Limit 1000). Verlauf nutzt `restore_pad`. **Redo gibt es nicht.**
- Loop-Sync: Die **gesamte Länge** der ersten Aufnahme einer Sitzung wird als `master_set` gespeichert. Weitere Aufnahmen werden mit `fit_to_grid` auf ein Vielfaches geschnitten oder mit Stille aufgefüllt (Grace 150 ms, höchstens 1/8 der Loop-Länge). Start/Stopp am Grid, Aufnahme wartet auf den nächsten Loop-Anfang. `loop_sync = false` schaltet das ab.
- Audio: getrennte PortAudio-Input- und Output-Streams, Mono float32, hartes `np.clip` auf den Mix, `latency_ms = "auto"` addiert gemeldete Ein- und Ausgangslatenz. Keine Gerätewahl, kein Regler, keine Peak-Anzeige. Die Loop-Naht springt in `_mix_voice` hart von Ende auf Position 0.
- Einstellungen nur als kommentiertes `settings.toml`; Änderung verlangt laut Dateikommentar einen Neustart. Es gibt noch keine Kind/Eltern-Trennung in der GUI.
- Komplett lokal, ohne Konto und ohne Internet. Start-/Stopp-Pieps sind über `sound_effects` abschaltbar, der Start-Ton zusätzlich über `record_start_tone` (Elternbereich, Lautstärke & Pegel).
- Unterstützte Paketierung heute: Windows-Installer (PyInstaller + Inno Setup) und Linux-Installskript. Kein offizielles macOS-Bundle.

Der Plan erweitert dieses Fundament; er ersetzt es nicht durch eine DAW.

---

## 1. Audio-Verbesserungen (greifen ineinander)

### 1.1 Rubber Band Library (Time-Stretching) — nachrangig, mit klarer Anwendungsgrenze

- Engine hinter Audacity, C++ mit Python-Bindings, pitch-erhaltendes Time-Stretching in guter Offline-Qualität. „Echtzeitfähig“ meint hier die Qualität des Algorithmus, **nicht** den Aufruf im PortAudio-Callback. Der Stretch läuft beim Stopp der Aufnahme im Controller- oder einem Worker-Thread; der Audio-Callback bleibt kurz (Mix, Fade, Peak).
- Sauber hinter den bestehenden `fit_to_grid`-Pfad: ein Modul, das `data` plus `grid` nimmt und gestrecktes `data` zurückgibt — **nur wenn** die Aufnahme bereits ungefähr eine oder n Perioden lang ist (z. B. Abweichung unter 8–10 %). Eine deutlich zu kurze Aufnahme (einzelner Klatscher in einem stehenden Grid) wird weiter mit Stille aufgefüllt, eine deutlich zu lange weiter auf ein Vielfaches geschnitten. Sonst wird aus einem Klatscher eine unkenntliche Dehnung.
- Das harte Grid bleibt als Garantie erhalten; nur knappe Abweichungen werden weich in den Takt gezogen.
- Priorität: **nicht** der erste Punkt. Größerer Frust-Hebel für Sechsjährige sind Undo in Reichweite, fehlende Klicks (Crossfade) und übersteuerte Schreie (Pegel). Rubber Band kommt, wenn Naht, Pegel und Grid-Fallbacks stehen.
- Packaging bleibt ein offener Punkt (Bindings, PyInstaller-Hook auf Windows). Solange das nicht sitzt, ist ein einfacherer, gut begrenzter Stretch-Fallback zulässig; Qualität darf dann nicht als „Rubber-Band-Niveau“ verkauft werden.

### 1.2 Crossfade an den Loop-Nähten (proportional)

- Wenn ein Loop vom Ende zurück zum Anfang springt und die Samples dort nicht phasenkontinuierlich sind, gibt es einen Klick. Der Sprung sitzt heute in `_mix_voice`.
- Statt eines fixen Werts: Fade-Länge **proportional zur Loop-Länge**, mit Grenzen, damit kurze Loops nicht aufgefressen werden.
  - Vorschlag: 2 % der Loop-Länge, mindestens 2 ms, höchstens 25 ms, und niemals mehr als 10 % der Loop-Länge (die 10-%-Kappe sticht den 25-ms-Wert bei sehr kurzen Loops).
  - 5–10 % als fester Anteil (eine Zwischenfassung des Plans) wäre für kurze Loops zu lang: bei 150 ms Loop wären 10 % schon 15 ms, 5 % oft schon hörbar „weichgespült“. Deshalb die niedrigere typische Rate plus harte Kappe.
  - Beispiel: 150-ms-Loop → max. 15 ms (10 %), typisch 3 ms (2 %). 8-s-Loop → 25 ms Kappe, nicht 160 ms.
- Implementierung: im Output-Callback Ende und Anfang überlappen, unter dem bestehenden Lock, ohne neue Allokationen im Callback (Fenster vorab berechnen, wenn sich Grid oder Sample ändert).
- Elternseitig optional ein Schalter „Naht weich zeichnen“ (Standard an); die Parameter selbst gehören nicht auf die Kindseite.

### 1.3 Onset-Detection beim Stopp

- Ziel: Der Loop soll auf einem musikalischen Ereignis **beginnen**, nicht auf einem zufälligen Frame vor dem ersten Klatscher.
- Technische Klärung: Standard ist eine **zirkuläre Verschiebung** — der Puffer behält seine Länge, der erste belastbare Onset wandert an den Anfang, das Material davor an das Ende. So bleibt die vom Kind (oder vom Grid) gemeinte Periode erhalten, und die Naht liegt hinter dem Einschlag. Ein hartes Abschneiden der Vorpause ändert die Länge und wird nur verwendet, wenn Eltern „Vorpause entfernen“ in der erweiterten Ansicht wählen.
- Die Detektion läuft **vor** `fit_to_grid` und vor einem evtl. Stretch.
- Reine Energie-Schwelle reicht für Klatschen und Stampfen. Für Summen/Melodien ist sie unzuverlässig; dann kein erzwungenes Verschieben, sondern die Aufnahme lassen, wie sie ist (oder später spektraler Flux, wenn Tests mit echtem Kind-Material das tragen).
- Sehr frühe Schein-Onsets (Rauschen, Pieps-Übersprechen des Start-Beeps) ignorieren: Mindestabstand vom Start, Schwelle relativ zum Aufnahme-Peak.

---

## 2. Takt-Philosophie: Grid aus dem Kind, nicht heimlich aus einem Ratespiel

### 2.1 Das Problem

Hartes Grid-Snapping ist fragil, wenn das Kind den Takt vorgibt:

- Ein Kind, das nur klatscht oder ruft, hat oft keinen sauberen Takt drin.
- Heute wird die **gesamte** erste Aufnahme zur Loop-Länge — inklusive Vor- und Nachlauf bis zur Stopp-Taste. Das ist für „ich halte einen Takt lang“ richtig und für „zwei Klatscher in einer langen Aufnahme“ oft zu lang.
- BPM oder Periode aus unklarem Input zu raten kann ein kaputtes Grid erzeugen und das gemeinsame Loop-Gefühl zerstören.

### 2.2 Die Lösung: Onset-Messung mit ausdrücklichen Fallbacks

- Onset-Detection auf die erste Grid-stiftende Aufnahme: wo sitzen belastbare Schläge?
- Der Abstand zwischen Onsets **kann** das Grid werden — aber nur, wenn er plausibel ist. Sonst gilt eine Fallback-Regel, niemals ein stilles Raten.

**Plausibilitätsfenster (in settings.toml justierbar, nicht auf der Kindseite):**

- Erlaubtes Tempo: **40–200 BPM**, also Perioden von 0,30 s bis 1,50 s für einen angenommenen Viertelschlag. Werte außerhalb sind kein Grid. (Nicht 60–240: 40 BPM lässt ruhige, kindliche Pulse zu; 240 BPM wäre ein 250-ms-Raster, das mit Crossfade und Motorik leicht kollidiert.)
- Mindestloop zusätzlich durch `max(0,30 s, 2 × Crossfade-Länge + 50 ms)` begrenzt, damit Naht und Inhalt koexistieren.
- Maximallänge der ersten Loop: `max_record_seconds` (heute 10 s). Ein einzelner 3-s-Abstand liegt bei 20 BPM und ist **kein** plausibler Vierteltakt.

**Fallback-Regeln bei zwei (oder n) Onsets:**

1. **Zwei Onsets, Abstand im Fenster (0,30–1,50 s):** Grid = Abstand, verstanden als **ein Schlag** (Viertel). Das Session-Grid (ein Takt) wird daraus mit der Taktart gebildet (Default 4/4: ein Takt = 4 Schläge). Die Aufnahme wird zirkulär so gelegt, dass sie am ersten Onset beginnt.
2. **Zwei Onsets, Abstand zu klein (< 0,30 s):** eher Doppelschlag/Prelller, kein Grid aus diesem Paar. Weitere Onsets suchen; sonst Fallback 5.
3. **Zwei Onsets, Abstand zu groß (z. B. 3 s):** Das ist **kein** stillschweigender 3-s-Takt. Entweder die **Tasten- bzw. Aufnahmelänge** (bisheriges Verhalten) als **einen Takt** verwenden, wenn diese Länge musikalisch sinnvoll ist, oder — wenn auch die Gesamtlänge unplausibel ist — **kein Grid**, freier Modus, Hinweis an Eltern.
4. **Mehr als zwei Onsets:** Median der Inter-Onset-Intervalle, nachdem Ausreißer außerhalb des Fensters verworfen wurden. Bleiben weniger als zwei plausible Intervalle, Fallback wie bei zwei Onsets.
5. **Ein Onset oder keiner:** Kein Onset-Grid. Fallback: bisheriges Verhalten — die **Aufnahmelänge bis zum Stopp** wird ein Takt, sofern ≥ 0,30 s (und ≤ Maximum). Ist die Aufnahme zu kurz (`MIN_RECORD_SECONDS`, heute 0,3 s), wird sie verworfen („Zu kurz – nochmal!“), wie heute.
6. **Timeout:** Trifft innerhalb von z. B. 2 s nach dem ersten Onset kein zweiter plausibler Onset ein *und* das Kind stoppt nicht, bleibt es bei Regel 5, sobald gestoppt wird. Es wird nicht im Hintergrund ein Tempo „fertig geschätzt“.
7. **Bestätigung / Sichtbarkeit:** Wenn ein Grid gesetzt wird, zeigt die Kindseite kurz und nonverbal den Puls (den es beim Warten auf den Loop-Anfang schon gibt). In der Elternansicht stehen BPM, Taktart und Quelle (`aufnahme_laenge` | `onset` | `eltern_bpm`). Ein per Onset gesetztes, aber grenzwertiges Grid können Eltern dort korrigieren, ohne dass das Kind einen Dialog bekommt.
8. **Eltern-BPM hat Vorrang**, sobald gesetzt: Onsets stiften dann kein neues Grid mehr (sie dürfen weiter für die zirkuläre Ausrichtung der jeweiligen Aufnahme genutzt werden).

Das bleibt im Kern „Periode messen, nicht Tempo erfinden“ — aber nur mit einem Sicherheitsnetz. Ein Kind, das nur einmal klatscht und sofort loslässt, bekommt weiterhin kein Onset-Grid; hält es die Aufnahme bewusst länger, stiftet die Länge den Takt (Ist-Verhalten, für Kinder vorhersehbarer als „wir haben deinen einen Klatscher ignoriert“).

**Begriffsklärung für Export und Metronom:** In dieser App ist das gespeicherte Session-Grid (`master.frames`) **ein Takt** (eine Bar). Ein aus zwei Klatschern gemessener Onset-Abstand ist ein Schlag und wird mit der Taktart (Default 4/4) zum Takt verrechnet. BPM = `Schläge_pro_Takt × 60 × Samplerate / frames_pro_Takt`.

### 2.3 Freier Modus pro Pad

- Das Kind kann ein Pad explizit in den freien Modus stellen (z. B. eine Melodie summen). Der Einstieg muss grobmotorisch und sichtbar sein (z. B. langes Halten mit klarer Form-Änderung, nicht nur Farbwechsel) und rückgängig gemacht werden können.
- Das taktfreie Sample wird nicht durch das Grid zerschnitten oder gestreckt. Es läuft in seiner eigenen Länge; optional startet es trotzdem am nächsten Grid-Punkt, damit es sich einordnet, ohne die Länge zu verlieren (Elternschalter).
- Tempo stiften darf ein freies Pad nur, wenn noch kein Grid existiert **und** die Fallback-Regeln aus 2.2 erfüllt sind. Sobald die Sitzung einen Takt hat, ist das Summen nur noch Klang.
- Im Event-Log nicht als paralleler Typ `grid_seed` neben `master_set`, sondern als `master_set` mit Herkunft im `data`-Feld, z. B. `{frames, rate, source: "onset"|"duration"|"parent_bpm"|"free_pad", pad}`. So bleiben alte Logs lesbar, und die Historie zeigt, woher der Takt kam.

### 2.4 Pädagogischer Nebeneffekt

Das Kind lernt intuitiv, dass Rhythmus etwas ist, das man vorgibt — nicht etwas, das die Maschine heimlich erfindet. Deshalb: lieber kein Grid als ein falsches Grid.

---

## 3. Elternseite: Einstellungen, erweiterte Ansicht

Es braucht eine klare Trennung:

- **Kindbereich:** Pads, Modi, Zurück, Alles still, Lautstärke rechts oben, Puls/Countdown. Keine Wellenform, kein Geräte-Menü, kein Limiter, kein Export, kein Set-Dialog.
- **Elternbereich:** hinter einem einfachen Parental Gate (z. B. kurze Additionsaufgabe oder eine zwei-Schritt-Geste, die ein Sechsjähriger nicht nebenbei trifft). Ein Gate ist **kein** Ersatz für datenschutzrechtliche Einwilligung, falls später Daten das Gerät verlassen.
- Die Settings-GUI schreibt `settings.toml` und übernimmt **live**, was live gehen muss (Lautstärke, Limiter, Auto-Gain, Geräte, Host-API/Backend, Loop-Sync, Sound-Effekte, Crossfade, Onset/Auto-Grid). Weiterhin neustartpflichtig: `sample_rate`, `rows`, `cols` (und ggf. `data_dir`). Die Datei-Kommentare müssen das unterscheiden; der heutige Satz „Nach einer Änderung neu starten“ wäre sonst falsch.

### 3.1 Einstellungsseite (settings.toml-GUI, beide Bereiche)

Gemeinsame, wiederverwendbare Oberfläche, die im Kind- und Elternbereich *unterschiedliche Felder* zeigt.

**In beiden Oberflächen (Kind nur das Nötigste):**

- **Lautstärkeregler rechts oben** (Abschnitt 9). Immer erreichbar, großes Ziel, keine plötzlichen Sprünge.
- Anzeige, wenn das Eingangssignal clippt (Kind: einfaches rotes „zu laut“-Zeichen an der Aufnahme, nicht nur Farbe).

**Nur Elternbereich, zusätzlich zu den schon in der TOML angelegten Werten:**

- Auto-Grid / Beat-Detection (Onset-Pfad) an/aus; bei aus gilt das heutige Längen-Grid.
- `loop_sync`, `sound_effects`, `latency_ms` (auto oder Millisekunden) mit kurzem Hinweis, dass der Auto-Wert geräteabhängig ist und mit Mikro + Kopfhörer gegengehört werden sollte.
- **Auto-Gain an/aus** (Standard: **aus**). Siehe Abschnitt 7.
- **Geräte:** Aufnahme- und Wiedergabegerät getrennt (Abschnitt 8) sowie Host-API/Backend (Abschnitte 11–12).
- **Audio-Limiter / Maximalpegel** nur Eltern (Abschnitt 9).
- Input-Trim / Headroom, optionale Peak-Anzeige.
- Hinweistext: Lautsprecher + Mikro erzeugen Echo; Bluetooth-Kopfhörer sind fürs Mitschnitt-Looping meist zu träge; bitte kabelgebundene Kopfhörer.

### 3.2 Erweiterte Ansicht („Erweitert“)

- Einzelne Loops anschauen (Wellenform).
- Marker setzen: beat-awares Time-Stretching zwischen Markern statt über den ganzen Puffer (Ableton-Prinzip, ohne Arrangement-Komplexität). Marker als Event z. B. `marker_set` mit Pad, Position, Label — oder zunächst in einer Datei neben dem WAV, wenn das Event-Modell nicht unnötig wachsen soll. Entscheidung in der Umsetzung, mit Abwärtskompatibilität.
- BPM- und Taktart-Einstellung: Eltern können ein Grid vorgeben oder korrigieren. Default bleibt „Kind stiftet den Takt“; Eltern-BPM ist ein bewusster Override (Regel 8 in 2.2).
- Metronom: visuell am aktuellen Grid. 4/4 ist die *Default-Taktart*, nicht eine vom tatsächlichen Grid entkoppelte Audio-Wahrheit. Kindseite nur visuelle Anzeige; Elternseite optionaler Metronom-Ton, leise, abschaltbar, kein scharfer Klick in voller Lautstärke.

### 3.3 Risiko

Mini-DAW-Gefahr: Die Kindseite muss strikt dünn bleiben. Alles andere gehört hinter den erweiterten Bereich, und der sollte sich nicht wie ein zweites Produkt anfühlen. Neue Ideen werden zuerst mit Kindern gegengeprüft, bevor sie Standard werden.

---

## 4. Export einzelner Loops (nur Elternseite)

- soundfile schreibt WAV; ffmpeg im Hintergrund liefert MP3, **falls** ffmpeg vorhanden ist. Fehlt es, bleibt WAV der Weg, und die UI erklärt das — ffmpeg wird nicht still vorausgesetzt und muss in Packaging/Docs aufgenommen werden, bevor MP3 als Feature gilt.
- WAV als Default (unverfälschte Samples), MP3 als Option.
- Marker können als Cue-Points mitgeschrieben werden, falls das Zielformat das zuverlässig kann. WAV-Cue-Chunks sind nicht einheitlich; Alternative: Sidecar oder BWF. Der Export darf an dieser Frage nicht scheitern.
- Kein Export auf der Kindseite, kein Upload, kein Teilen standardmäßig. Kinderstimmen sind personenbezogene Daten; der Export bleibt lokal und elterngesteuert (DSGVO; in Deutschland typisch Einwilligung der Eltern unter 16, wenn ein Dienst auf Einwilligung setzt; COPPA unter 13 bei US-Bezug).

---

## 5. Export der Summe (N Takte, keine Zeitachse)

Neue Anforderung: Ein Projekt als **Summe** in einer vordefinierten Taktlänge exportieren. Es wird **keine Zeitachse** und kein Arrangement eingeführt. Der Export wiederholt die vorhandenen Loops, so wie sie in der Session laufen, für N Takte beim Grid-Tempo.

### 5.1 Mathematik

Session-Grid `G` = Länge eines Takts in Frames (siehe Begriffsklärung in 2.2). Taktart `B` = Schläge pro Takt (Default 4). Daraus

- `BPM = B × 60 × Samplerate / G`
- Exportlänge in Samples: `S = N × G`

Das ist identisch mit

- `S = round(N × B × 60 / BPM × Samplerate)`

sofern BPM und `G` aus derselben Definition stammen. Gerundet wird nur in der BPM-Anzeige bzw. beim Umweg über BPM; der Render selbst sollte in **ganzen Frames** `N × G` bleiben, damit die Loops exakt schließen. Eltern wählen `N` (z. B. 4, 8, 16 Takte) und ggf. die Taktart, nicht eine Zeit in Sekunden.

Fehlt ein Grid (freie Sitzung ohne Takt): kein stilles Raten. Entweder Eltern setzen BPM/Taktart für diesen Export, oder die UI erklärt, dass eine Summe „über N Takte“ erst mit Grid möglich ist. Optionaler Notbehelf: N-mal die Länge des längsten loopenden Samples — nur nach ausdrücklicher Wahl, und in der Datei/Metadaten als solcher Notbehelf gekennzeichnet.

### 5.2 Loops unterschiedlicher Länge

- **Vielfache des Grids** (2, 3, … Takte): laufen wie live vom Start weg; in N Takten passen sie, wenn N ein Vielfaches ihrer Länge in Takten ist, sonst endet der Export mitten in ihrer Wiederholung (das ist akzeptiert, kein Arrangement).
- **Teiler des Grids** (z. B. halber Takt nach `fit_to_grid`): wiederholen sich entsprechend oft pro Takt, ebenfalls wie live.
- **Freier-Modus-Pads:** behalten ihre eigene Länge, werden **nicht** ins Grid gestreckt. Sie starten bei Export-Beginn (oder, wenn der Elternschalter „am Grid-Punkt starten“ an ist, analog zum Live-Verhalten) und wiederholen sich unverändert. Am Exportende wird hart abgeschnitten, plus optionaler kurzer Ausklang (siehe 5.3). Nicht loopende, nur einmalig abgespielte Pads: Default ist, sie wegzulassen; optionales Häkchen „einmal am Anfang einrechnen“.
- Nur Pads mit Sample; stumm geschaltete oder gerade nicht loopende Pads defaultmäßig nicht in der Summe, mit der Option „alle belegten Pads als Loop“.

### 5.3 Pegel, Limiter, Ausklang

- Dieselbe Gain-Kette wie live: Kind- bzw. Session-Lautstärke, danach der Eltern-Master-Limiter (Ceiling in dB(FS)) auf die **Summe**, nicht spurweise vorher „schöner“ machen.
- Optionaler kurzer Fade-Out am Ende (Eltern, Default z. B. 10–20 ms oder ein Bruchteil des letzten Takts, mit Obergrenze), damit der File-Schnitt nicht knackt. Kein automatisches Arrangement-Ende, kein Count-out-Ritual, das eine Zeitachse vortäuscht.
- Format: WAV als Default, MP3 analog zu Abschnitt 4, wenn ffmpeg da ist. Mono, Session-Samplerate. Kein Upload.

Das bleibt im Kind-Modell: Pads sind Clips, der Export ist „alles, was gerade zusammen klingt, N Takte lang“, nicht eine Session-View-Aufnahme auf eine Timeline.

---

## 6. Undo und Redo (für die Zielgruppe zentral)

### 6.1 Was schon da ist

- Globaler Button „Zurück“, Strg+Z, Event `undo` mit `data.target = seq`, Stack im Zustand, auch nach Archivierung über Snapshots.
- Während einer Aufnahme: zuerst Aufnahme beenden; war sie zu kurz, gibt es nichts zu undoen.
- „Verlauf“ holt ältere Takes desselben Pads zurück (`restore_pad`).

Das darf der Plan nicht ein zweites Mal erfinden. Ein neuer Event-Typ `pad_undo` ist **nicht** die Lösung.

### 6.2 Was fehlt und warum es Kinder brauchen

Ein Sechsjähriges Kind trifft Pads aus Versehen ständig. Der globale Zurück-Button liegt unten und macht die *letzte inhaltliche Änderung irgendwo* rückgängig — möglicherweise auf einem anderen Pad, als das Kind gerade ansieht. Ohne **Undo am Pad** und ohne **Redo** fühlt sich eine falsche Aufnahme wie ein toter Zweig an. Das ist für die Zielgruppe wichtiger als Time-Stretching.

### 6.3 Modell: bestehenden `undo`-Event erweitern

Das Event-Modell hat bereits `type` und `pad`. `EVENT_TYPES` ist ein geschlossenes Set; der Parser lehnt unbekannte Typen ab. Ein zweiter Typ verdoppelt Semantik und erschwert das Lesen alter Logs ohne Gewinn.

- `undo` ohne `pad` (wie heute): obersten Stack-Eintrag zurücknehmen (global, Button „Zurück“).
- `undo` mit `pad = N` und `data.target`: letzte *dieses Pad betreffende* Inhaltsänderung zurücknehmen (auch wenn danach ein anderes Pad geändert wurde). Der Reducer muss den passenden Eintrag finden, nur dieses Pad (und ggf. ein von genau diesem Event gesetztes Master-Grid) restaurieren und den Stack konsistent halten, damit ein späteres globales Undo nichts doppelt oder verwirft.
- Grenze: derselbe `UNDO_LIMIT` (1000) bzw. ein in der TOML begrenztes Fenster, falls Snapshots groß werden.
- **Redo:** neuer Event-Typ `redo` und ein Redo-Stack, der bei jeder neuen Inhaltsänderung geleert wird. Ohne Redo ist „Zurück“ für Kinder angstbesetzt. Redo-Button neben Zurück, nur sichtbar/aktiv wenn möglich; auf dem Launchpad nur, wenn das Modell das hergibt, sonst weglassen statt einer versteckten Geste.

Kind-Affordance: Global „Zurück“ / „Wiederholen“ bleiben unten, groß. Pro Pad eine eindeutige, verwechselungssichere Geste (keine unsichtbare Wischgeste; Farbe **und** Icon/Form). Verwechslung mit Löschen oder Loop-Stopp in Tests prüfen. Eine laufende Aufnahme abbrechen bleibt: Zurück oder nochmal dasselbe Pad (wie heute).

---

## 7. Pegelmanagement, Clipping und Auto-Gain

Kinder schreien ins Mikro. Ohne Pegelkonzept entstehen verzerrte Loops, die kein Stretch und kein Grid retten.

**Wichtige Grenze:** Auto-Gain in der Software sitzt **hinter** dem ADC. Ist der Wandler bereits bei ±Vollaussteuerung, ist die Wellenform zerstört. Auto-Gain ist Komfort, kein Schutz.

Maßnahmen in GUI und Backend:

1. **Peak-Anzeige** während der Aufnahme (Eltern: Meter-Skala; Kind: grobe Stufe + deutliches Clip-Zeichen, Farbe+Form).
2. **Input-Trim / Headroom** (Eltern): Aufnahmepegel unter 0 dBFS halten, z. B. Zielbereich −12 bis −6 dBFS. Default mit Reserve, nicht „so laut wie möglich“.
3. **Soft-Clip oder leichter Limiter auf dem Input** nach dem Trim, damit kurze Spitzen weich begrenzt werden, statt hart zu knicken — ersetzt nicht den Headroom.
4. **Auto-Gain an/aus** (Eltern, Default **aus**): langsames Nachziehen der durchschnittlichen Lautheit in einem engen Rahmen, kein pumpendes AGC. Bei Reizempfindlichkeit ist ein festes Trim vorhersehbarer. Clippt das Eingangssignal, darf Auto-Gain nicht „einfach lauter“ machen.
5. Clip-Ereignisse kurz merken, damit Eltern „zu laut“ sehen, ohne dass Kinddaten in eine Cloud wandern.

Persistenz in `settings.toml` (z. B. `auto_gain`, `input_gain_db`, `peak_meter`).

---

## 8. Gerätezuweisung: Input und Output getrennt

Die Engine hat schon zwei Streams, bindet sie aber beide an den Systemdefault.

- In der Eltern-GUI zwei Listen: **Aufnahmegerät** und **Wiedergabegerät**, inkl. „Systemstandard“, plus Wahl der Host-API (Abschnitt 12).
- Speichern nach **stabilem Namen** (und Host-API), nicht nur nach PortAudio-Index; Indizes verrutschen beim Umstecken.
- Wechsel live, soweit PortAudio das hergibt: Streams sauber neu öffnen. Wenn ein Neustart des Streams nötig ist, das kurz ansagen, nicht einfrieren.
- `latency_ms = "auto"` nach jedem Geräte- oder Backend-Wechsel neu aus den gemeldeten Latenzen ableiten; manueller Korrekturwert bleibt.
- Hinweis: Zwei verschiedene Geräte können gegeneinander driften; wo möglich, gleiches Interface für ein und aus. Bluetooth für Live-Aufnahme/Monitoring **abraten** (häufig hohe, schwankende Latenz). Lautsprecher + Mikro erzeugen Rückkopplung; ein Kommunikations- oder AEC-Modus wäre für Musik die falsche „Lösung“.
- Fehlendes Mikro oder fehlender Ausgang: wie heute startfähig mit Statuszeile; in der Geräte-GUI klar markiert.

Die Auto-Latenz ist im README als nicht feldgeprüft beschrieben. Vor dem Versprechen „neue Loops liegen genau auf den gehörten“ einmal mit echtem Mikro und Kopfhörer gegenmessen.

---

## 9. Lautstärkeregler und Eltern-Limiter

### 9.1 Lautstärke auf beiden Oberflächen, rechts oben

- Ein großer Regler **rechts oben** auf der Kindseite und ebenso rechts oben im Elternbereich (gleiche Position = Vorhersehbarkeit). Kein verstecktes Einstellungs-Item.
- Eine Quelle der Wahrheit: beide Regler zeigen und steuern denselben Session-Pegel. Der Kindregler bewegt sich **innerhalb der von Eltern gesetzten Obergrenze**. Drehen Eltern den Limiter/Ceiling herunter, rutscht der Kindwert sichtbar mit, nie darüber.
- Keine plötzlichen Sprünge, feinmotorisch verzeihend (große Fläche). Optional kurzer weicher Fade beim Öffnen der App. Loops starten nach einem Absturz ohnehin nicht von selbst.

### 9.2 Limiter nur im Elternbereich

- Eine maximale **digitale** Lautstärke, die die App nie überschreitet: ein Ceiling auf den **Master nach der Summe aller Pads, Effekte und des Kind-Reglers**, im Output-Callback vor (oder als Ersatz für) das heutige harte `np.clip`.
- Zwei zusammengehörige Hebel: (a) Maximalgewinn / Ceiling in dB(FS), z. B. Default −6 dBFS; (b) ein echter Peak-Limiter, damit die Summe vieler Loops nicht an die Decke knallt. Für Kinderohren ist (a) der „wird nie lauter als“-Hebel; (b) verhindert Übersteuerungs-Kratzer.
- Start-/Stopp-Pieps und Metronom laufen durch denselben Master.

### 9.3 Ehrlich: dB(FS) ist nicht dB(SPL)

Die App begrenzt die Amplitude im Rechner. Den Schalldruck am Ohr bestimmen zusätzlich Systemlautstärke, Kopfhörer-Empfindlichkeit und Sitz des Hörers. Ein Kind kann den App-Deckel aushebeln, indem es die OS-Lautstärke aufreißt oder sehr empfindliche In-Ears nutzt.

Die Eltern-GUI sagt das in einem kurzen, klaren Satz und empfiehlt kabelgebundene Kinderkopfhörer mit eigener Begrenzung. Referenz, nicht als in der App messbar verkaufen: WHO/ITU Mode 2 zielt auf **75 dBA über 40 Stunden/Woche** für Kinder, nicht auf eine pauschale 85-dB-Marke (85 dB taucht u. a. in der Spielzeugnorm EN 71-1 für Kopfhörer auf und ist ein anderes Messregime). Siehe Abschnitt 17.

---

## 10. Sets speichern und öffnen (Elternseite)

Eltern sollen komplette Loopstation-Sets speichern und wieder öffnen können, um zu sichern, was das Kind macht. Das Kind arbeitet an einer Session; die Eltern **frieren** sie ein. Kein Set-Dialog, kein Dateisystem auf der Kindseite.

### 10.1 Was ein Set ist

Ein Set ist die komplette Sitzung: Event-Log (inkl. Snapshots und, soweit vorhanden, Archivteile, die für das Wiederherstellen nötig sind), alle referenzierten Audio-Puffer und ein Snapshot der `settings.toml`. Ablage als **Ordner** oder **ZIP** (ein ZIP ist ein gepackter Ordner derselben Struktur). Dateiendung z. B. `.loopset` für das ZIP, damit es in der Eltern-GUI erkennbar ist.

Vorschlag für die Struktur:

```
manifest.toml          # format_version, app_version, created_at (UTC),
                       # sample_rate, pad_count, grid (frames/rate oder leer)
settings.toml          # Snapshot der Sitzungs-Einstellungen
data/events.jsonl      # aktives Protokoll (beginnt mit Snapshot, wie im Ist)
data/archive/          # nur soweit nötig, damit der Zustand vollständig ist
samples/*.wav          # jeder referenzierte Puffer, unverändert
```

Im Manifest steht eine **Format-Version**. Unbekannte zukünftige Versionen werden nicht still „irgendwie“ geöffnet. Audio bleibt WAV (dieselbe Samplerate wie die Sitzung). Keine Cloud, kein automatisches Teilen.

### 10.2 Speichern (atomisch)

- Zuerst in ein temporäres Verzeichnis bzw. eine temporäre ZIP-Datei schreiben, Daten flushen/`fsync`, erst dann an den Zielort **umbenennen** (atomic replace). Ein abgebrochener Speichervorgang darf ein vorhandenes Set nicht halb überschreiben.
- Nur Samples übernehmen, die das Log noch referenziert (aktueller Stand, Verlauf, Undo-Ziele). verwaiste Dateien im Arbeitsordner nicht ungefragt mitpacken, aber auch nichts löschen, das Undo noch brauchen könnte.
- Läuft gerade eine Aufnahme, zuerst beenden oder den Speichern-Dialog verweigern — kein halber Puffer im Set.
- Nach dem Speichern arbeitet das Kind unverändert weiter; das Set ist eine Kopie, keine neue „geöffnete Datei“, die die Session sperrt (einfaches Modell: Save a Snapshot, nicht ein Dokument mit Save/Save-as-Semantik wie in einer DAW). Optional „Speichern und weiter“ als einziger Weg.

### 10.3 Öffnen

- Versionsprüfung: zu neu → ablehnen mit klarer Meldung („neuere Loopstation nötig“). Zu alt → wenn möglich laden, sonst ablehnen; Migrationen dokumentieren.
- Event-Log nachspielen wie beim normalen Start (`replay` ab letztem Snapshot). Der **Undo-Stack bleibt erhalten**, weil er Teil des Zustands und der Snapshots ist: Eltern können nach dem Öffnen weiterhin zurücknehmen, was in dieser eingefrorenen Sitzung noch auf dem Stack lag. Der Redo-Stack startet leer (er wird im Ist nicht persistiert). Das ist gewollt: das Set ist die Sitzung, nicht eine „flachgebügelte“ Abmischung.
- Gerätenamen und Host-API aus dem Settings-Snapshot: existiert das Gerät nicht (anderes Haus, anderer Rechner), **Fallback auf das Systemstandard-Gerät** der aktuellen Plattform, mit einem kurzen Hinweis im Elternbereich, keine stille Fehlkonfiguration und kein Absturz. `latency_ms = "auto"` nach dem Öffnen neu ableiten.
- Pfade in `data_dir` werden auf den geöffneten Set- bzw. einen Arbeitsordner umgesetzt, nicht 1:1 aus einem anderen Rechner übernommen.
- Öffnen ersetzt die laufende Session erst nach Rückfrage, wenn ungespeicherte Änderungen da sind („jetzt zuerst als Set sichern?“). Danach gilt das geladene Set als aktuelle Session (Kopie in den normalen Datenordner oder Arbeiten aus einem entpackten Arbeitsverzeichnis — Umsetzung entscheidet sich am einfacheren, absturzfesten Weg).

---

## 11. Plattformen und Packaging

Fokus bleibt **Linux und Windows**. macOS ist machbar, aber kein drittes Produktkonzept: dieselbe App, dasselbe Event- und Pad-Modell; unterschiedlich sind Backend-Auswahl und Packaging.

### 11.1 Backend-Matrix

| Plattform | Host-APIs (PortAudio / sounddevice) | Default dieser App | Bemerkung |
|---|---|---|---|
| Windows | WASAPI, DirectSound, MME, optional ASIO | **WASAPI Shared** | Siehe Abschnitt 12. DirectSound und MME sind auf modernem Windows Kompatibilitätsschichten über WASAPI. |
| Linux | ALSA; PulseAudio bzw. PipeWire typischerweise über die ALSA- (oder JACK-)Kompatibilitätsschicht; JACK, falls vorhanden | **ALSA** (auf typischen Desktops oft schon PipeWire/Pulse als Plugin) | Entspannter als Windows; kein ASIO. PipeWire ist heute der übliche Desktop-Pfad, ohne dass die App PipeWire speziell ansprechen muss. |
| macOS | CoreAudio | **CoreAudio** | sounddevice/PySide6 laufen out of the box. |

Die App wählt das Default-Backend pro Plattform; Eltern können auf Windows (und ggf. Linux, wenn mehrere APIs sichtbar sind) bewusst umstellen. Geräte-Listen sind nach Host-API zu gruppieren.

### 11.2 Packaging-Notizen

- **Windows:** Weiterhin PyInstaller als Ordner plus Inno-Setup-Installer (wie im README). sounddevice-Wheels mitbringen (pip, nicht conda), damit die ASIO-Zusatz-DLL optional ladbar bleibt (Abschnitt 12). Mikrofon-Berechtigung über die Windows-Privatsphäre-Einstellungen; der bestehende Hinweis im README bleibt. Ungesignierter Installer löst SmartScreen aus — für ein Produkt perspektivisch Code Signing einplanen.
- **Linux:** Bestehendes `scripts/install-linux.sh` (venv, PortAudio, Qt-Libs, Menüeintrag). Distributionen wie bisher. Optional später Flatpak/AppImage, kein Muss für diese Fassung. Audio-Server (PipeWire/Pulse) gehört zum Desktop und wird nicht mitinstalliert.
- **macOS (machbar, nachrangig):** `.app`-Bundle mit `Info.plist`, zwingend `NSMicrophoneUsageDescription` (sonst bleibt das Mikro stumm bzw. das System blockt). Codesigning und **Notarisierung** für Gatekeeper, sonst „kann nicht geöffnet werden“. PySide6 und sounddevice nutzen CoreAudio ohne Extra-Backend-Code. Universelles oder Apple-Silicon-Bundle festlegen; sounddevice liefert bereits universelle dylibs in den Wheels. Entlastung der Sandbox-Fragen erst, wenn ein Store-Vertrieb überhaupt Thema wird (lokaler Betrieb bleibt Default).

Kein separates Mac-Feature-Set, keine andere Kind-UX.

---

## 12. Windows-Audio-Backends

### 12.1 Entscheidung zum Default

Die Vorgabe aus dem Gespräch war: **DirectSound als Default**, ASIO als Option für Eltern mit gutem Equipment.

Diese Fassung setzt den Default trotzdem auf **WASAPI im Shared-Modus** und begründet das in Abschnitt 15. Kurz:

- Seit Windows Vista wird DirectSound intern über WASAPI Shared emuliert. DirectSound kann daher nicht besser sein als WASAPI Shared, sondern nur dieselbe Pipeline plus eine zusätzliche, oft spürbare Schicht (in der PortAudio-Praxis u. a. eine inhärente Verzögerung in der Größenordnung von ca. 20 ms und auf der Aufnahmeseite historisch Probleme mit Puffern unter 31,25 ms, bis hin zu Hänger-Risiken). DirectSound gilt in der PortAudio-Pflege als Legacy-API mit Regressionen in neueren Windows-Versionen.
- WASAPI Shared ist der native, von Microsoft für Apps vorgesehene Weg, mischt sich mit anderen Programmen (Systemtöne, die Eltern-Session im Browser), liefert verlässlichere Latenzangaben und erlaubt auf Windows 10+ kleinere Perioden als der alte 10-ms-Default.
- WASAPI Exclusive und ASIO bleiben Optionen für Eltern mit Interface, sind aber als Default ungeeignet (exklusiver Gerätezugriff: das Kind-Tablet darf den Rest des Rechners nicht verstummen lassen).
- MME nur als letzter Fallback (hohe Latenz). DirectSound bleibt in der Liste als Kompatibilität, nicht als Empfehlung.

Implementierung über PortAudio-Host-APIs, die sounddevice bereits durchreicht (`sd.default.device`, Host-API-Index, ggf. `WasapiSettings`). Kein eigenes C++-Backend.

### 12.2 ASIO als Eltern-Option

- ASIO ist in den Einstellungen ein bewusster Schalter für Eltern mit Audio-Interface, nicht der Alltagspfad.
- **Die mit `pip` installierte sounddevice-Version (ab 0.5.1, aktuell im Projekt `>= 0.4.6`, also bei frischem Pin auf ≥ 0.5.1 anheben) enthält zwei PortAudio-DLLs:** eine ohne ASIO (Default) und eine mit ASIO. Die ASIO-DLL wird geladen, wenn **vor** dem `import sounddevice` die Umgebungsvariable `SD_ENABLE_ASIO` gesetzt ist. Quelle: [sounddevice Installation / ASIO Support](https://python-sounddevice.readthedocs.io/en/latest/installation.html), [Version History 0.5.1](https://python-sounddevice.readthedocs.io/en/latest/version-history.html), [PR #556](https://github.com/spatialaudio/python-sounddevice/pull/556). Der Default ohne ASIO ist bewusst so, wegen Problemen, die in [Issue #496](https://github.com/spatialaudio/python-sounddevice/issues/496) diskutiert wurden.
- **Steinberg-SDK:** Für den normalen Windows-Installer über offizielle pip-Wheels muss das Projekt **nicht selbst** PortAudio gegen das Steinberg-ASIO-SDK bauen. Ein eigener PortAudio-Build (z. B. wenn jemand die DLL ersetzen will) bräuchte das proprietäre ASIO-SDK und unterliegt dessen Lizenz; das SDK selbst darf nicht einfach mitgeliefert werden. conda-forge-Pakete haben **kein** ASIO — deshalb im Installer die pip-Wheels verwenden, nicht conda.
- Risiken, die die UI benennen soll: Nicht jeder ASIO-Treiber ist sauber; viele Interfaces öffnen **exklusiv** (kein paralleles YouTube, kein Systemding). **ASIO4ALL** ist ein Wrapper, kein nativer Gerätetreiber, und verhält sich oft anders als ein Interface-ASIO. Wechsel des Backends nur in den Elterneinstellungen, mit kurzem Hinweis und Stream-Neustart.

Linux bleibt bei ALSA/PipeWire „entspannter“: keine ASIO-Frage, typischerweise Shared-Zugriff über den Session-Audio-Server.

---

## 13. Ableton Session View als konzeptioneller Rahmen

Nicht Ableton reverse-engineeren und keine Session-View-Kopie bauen. Die **Pad-Grid-Metapher ist bereits eine Session View**: jedes Pad ist ein Clip-Slot, das Raster ist die Szene ohne Szenen-Zeile. Was wir tun, prüfen wir an einer kurzen Checkliste — und lassen wegl, was die Kindseite zur Mini-DAW machen würde.

**Behalten (bzw. bewusst ausrichten):**

- **Clip-Launch:** Ein Tipp startet oder stoppt den Clip auf dem Pad. Quantisiert, wenn ein Grid und bereits Loops laufen (das tut die App schon: Start/Stopp an der nächsten Grenze, Warten mit Puls und Balken).
- **Launch-Quantisierung:** Das Grid ist die Quantisierung. Ohne laufendes Grid startet der Clip sofort (wie heute, wie ein erster Clip in einer leeren Session).
- **Overdub auf dem Clip, nicht auf einer Zeitachse:** Falls Overdub später kommt, passiert es **auf dem Pad** (neuer Take oder — nur als späteres, nicht kind-default — Addieren auf denselben Puffer), nie als Spur auf einem Arrangement. Der Default für Kinder bleibt: neue Aufnahme **ersetzt** den aktiven Take, der alte bleibt im Verlauf. Das ist näher an „Clip neu aufnehmen“ als an einem Pedal-Looper mit zwölf Schichten.

**Weglassen:**

- Automation, Clip-Envelopes, Follow Actions als Pflichtprogramm.
- MIDI-Routing, virtuelle Instrumente, Plug-in-Kette.
- Arrangement-View, Szenen-Launch-Zeile, Crossfader zwischen Szenen, Recording in eine lineare Timeline.
- Session-Record-Arm für viele Spuren gleichzeitig als Kind-Alltag (technisch können mehrere Dinge laufen; die UX bleibt ein Pad nach dem anderen).

Die erweiterte Elternansicht darf Wellenform und Marker zeigen, ohne die Session zu einem Ableton zu machen. Export der Summe (Abschnitt 5) ist „die Session N Takte lang rendern“, nicht „ins Arrangement aufnehmen“.

---

## 14. Umsetzungsreihenfolge

1. **Master-Lautstärke, Eltern-Ceiling/Limiter, Peak/Clip-Anzeige, Input-Trim** — Gehör und verzerrungsfreie Aufnahmen zuerst; beide Oberflächen bekommen den Regler rechts oben.
2. **Settings-GUI** mit Parental Gate, Live-Übernahme der sicheren Werte, getrennte Geräte, **Host-API** (Windows: WASAPI Shared als Default, ASIO optional), Auto-Gain-Schalter (Default aus), bestehende TOML-Werte.
3. **Crossfade proportional** an der Loop-Naht.
4. **Undo pro Pad + Redo**, auf dem bestehenden Event-Modell; Kind-Affordance sichtbar machen. (Globalen Zurück-Button nicht entfernen.)
5. **Onset-Verschiebung beim Stopp** (zirkulär) plus **Onset-Grid mit den Fallback-Regeln** aus 2.2; Auto-Grid in den Einstellungen abschaltbar.
6. Rubber Band (oder vorübergehender Stretch-Fallback) hinter `fit_to_grid`, nur für knappe Abweichungen.
7. Erweiterte Ansicht: Wellenform, Marker, BPM-Override, visuelles Metronom; optional leiser Metronom-Ton.
8. Freier Pad-Modus; `master_set.source` statt eines zweiten Grid-Event-Typs.
9. Export einzelner Loops (WAV, MP3 nur mit erklärtem ffmpeg-Weg); lokal, nur Eltern.
10. **Export der Summe** (N Takte, keine Zeitachse).
11. **Sets speichern/öffnen** (atomisch, Versionsprüfung, Geräte-Fallback, Undo-Stack bleibt).
12. Packaging vertiefen (sounddevice ≥ 0.5.1 und `SD_ENABLE_ASIO` im Windows-Installer; macOS-Bundle inklusive Mikrofon-Plist, Signing/Notarisierung, sobald Mac an der Reihe ist).

Die Session-View-Checkliste ist kein eigener Implementierungsschritt, sondern die Messlatte für 4, 5, 7, 8 und 10. Jeder Schritt soll für sich auslieferbar sein und Tests ohne Hardware behalten (die Suite mockt Audio, MIDI und Uhr bereits).

---

## 15. Abweichungen von den Vorgaben (Begründung)

1. **Kein neuer Event-Typ `pad_undo`.** Undo existiert bereits als `undo`. Das Event hat schon ein Feld `pad`. Ein zweiter Typ zwingt Parser, Reducer, Snapshots und Docs in eine unnötige Doppelstruktur. Stattdessen: `undo` mit `pad` für pad-lokales Zurück, `undo` ohne `pad` weiter global, plus neuem `redo`. Eine zwischenzeitliche Planfassung auf `main` hatte `pad_undo` und „kein Undo im bisherigen Plan“ formuliert — das widerspricht dem Code und wird hier nicht übernommen.
2. **Auto-Gain ist nicht der Clipping-Schutz und nicht der Default.** Der Schalter kommt in die GUI, Default ist **aus** (nicht an). Ergänzt um Input-Trim, Peak/Clip-Anzeige und Soft-Begrenzung. Begründung: Auto-Gain verhindert kein ADC-Clipping und kann die Lautheit unvorhersehbar machen — ungünstig bei Reizempfindlichkeit.
3. **Rubber Band ist nicht Schritt 1.** Hoher Packaging-Aufwand, falsche Wirkung auf zu kurze Takes, geringerer Alltagsnutzen für Sechsjährige als Undo, Naht und Pegel. Die Funktion bleibt, nur später und mit Anwendungsgrenze.
4. **Kein stilles Onset-Grid bei 3-s-Abstand.** Fenster **40–200 BPM** (nicht 60–240). Außerhalb: Fallback auf Aufnahmelänge oder freien Modus plus Elternkorrektur.
5. **Onset-Trim ist eine Verschiebung, kein Abschneiden**, und steht in der Reihenfolge **vor** Stretch und `fit_to_grid`.
6. **`grid_seed` wird nicht als eigener Typ eingeführt.** Herkunft des Takts wandert in `master_set.data`.
7. **Metronom nicht bedingungslos „immer Vierteltakt“ als Audio-Wahrheit.** 4/4 ist Default-Taktart; die Periode folgt dem tatsächlichen Grid.
8. **Limiter als dB(FS)-Ceiling auf den Master**, Kindregler innerhalb dieser Grenze. Die Vorgabe „maximale Lautstärke, die nie überschritten wird“ gilt *in der App*. Systemlautstärke und Kopfhörer bleiben ehrlich benannt. Orientierung WHO/ITU **75 dBA / 40 h** für Kinder, nicht 85 dB.
9. **Crossfade typisch 2 % mit 10-%- und 25-ms-Kappe**, nicht 5–10 % ohne Obergrenze, weil kurze Loops sonst aufgefressen werden.
10. **Redo wird fest eingeplant**, nicht nur „ggf.“
11. **Keine DAW als Unterbau.** Cakewalk by BandLab ist seit dem **1. August 2025** abgeschaltet (Aktivierung tot, Help Center 2. Januar 2026); Nachfolger sind Cakewalk Sonar und Cakewalk Next (Free-Tier + Membership). Eine zwischenzeitliche Planfassung, die CbB noch als „kostenlos“ führt, ist veraltet.
12. **Windows-Default ist WASAPI Shared, nicht DirectSound.** Die Gesprächsvorgabe (DirectSound default, ASIO optional) wird hier bewusst nicht wörtlich umgesetzt. Begründung siehe Abschnitt 12.1: DirectSound ist auf modernem Windows eine Legacy-Schicht über WASAPI, typischerweise mit extra Latenz und bekannten Aufnahme-Pufferproblemen; für eine Loopstation mit Overdub/Sync ist das der falsche Default. ASIO bleibt die optionale Eltern-Wahl für Interfaces. DirectSound und MME bleiben als Fallback in der Liste. Das ist die einzige Stelle, an der eine konkrete technische Vorgabe aus dem Chat *ersetzt* (nicht nur ergänzt) wird.
13. **ASIO-SDK muss das Projekt nicht selbst einbinden**, wenn der Windows-Installer die offiziellen pip-Wheels von sounddevice (≥ 0.5.1) mitbringt und ASIO über `SD_ENABLE_ASIO` aktiviert. Ein eigener PortAudio-Build wäre der Fall, in dem das Steinberg-SDK und dessen Lizenz relevant werden.
14. **Overdub auf dem Clip** wird als Session-View-Prinzip festgehalten, aber nicht als Kind-Default: Kinder ersetzen den Take (alter Take im Verlauf). Schicht-Overdub wäre ein späteres, bewusstes Feature auf demselben Pad, keine Zeitachse.

---

## 16. Offene Punkte

- Rubber-Band-Python-Bindings: welche Distribution? Windows-Packaging (PyInstaller-Hook). Alternative Stretch-Engine nur als Zwischenlösung.
- Onset-Detection an echtem Kind-Material testen (Klatschen, Rufen, Summen); spektraler Flux nur bei Bedarf.
- Feldmessung der Round-Trip-Latenz mit typischem USB-Mikro und Kopfhörer, je Backend (WASAPI Shared, ggf. ASIO).
- Cue-Point-Format für den Einzel-Export (WAV-Cue vs. Sidecar vs. BWF).
- Marker-Daten: Event `marker_set` oder Datei neben dem WAV? Muss mit Undo/Redo, Verlauf und Sets zusammenpassen.
- Feingestaltung der Pad-Undo-Geste: mit Zielgruppe testen.
- ffmpeg-Bundling im Windows-Installer (Lizenz, Größe) oder MP3 nicht versprechen.
- Set-Format-Version und Migrationsregeln, sobald die erste Version geschrieben ist; maximale Set-Größe (viele Verlauf-WAVs).
- macOS: Signing-Zertifikat, Notarisierungsablauf, Mikrofon-Text in der plist, erst wenn Mac wirklich gebaut wird.
- Rechtliches, falls die App jemals in Stores mit Kinder-Kategorie, Analytics oder Teilen landet: Parental Gate ≠ Einwilligung; COPPA/DSGVO Art. 8; in Deutschland typisch 16 Jahre für eigene Einwilligung in Informationsgesellschafts-Dienste. Der lokale Betrieb ohne Netz bleibt der gewünschte Default.

---

## 17. Recherche: freie Editoren, DAWs, Best Practices

Ausführlichere Ausarbeitung entstand als Begleitdokument `recherche.md` **außerhalb dieses Repositories**. Hier der für den Plan gezogene Kern mit Quellen.

### 17.1 Editoren und DAWs — nicht als Unterbau, nur als Lehre

| Werkzeug | Lizenz / Status | Für Looping / Overdub / Echtzeit | Lehre für loopstation-kids |
|---|---|---|---|
| **Audacity** | GPL, kostenlos; 4.0.0 am 3.9.2026 | Overdub auf neuer Spur, Loop-*Wiedergabe*, keine Live-Loopstation; Latenzkompensation nach Messung; Software-Monitoring ist verzögert | Round-Trip kalibrieren; Kopfhörer; Kompensation ≠ Monitoring-Latenz; Rubber Band als Stretch-Referenz, nicht als Live-Callback |
| **ocenaudio** | Freeware, **nicht** Open Source | Im Wesentlichen Ein-Datei-Editor, kein Looper | Keine Abhängigkeit; Wellenform-Ideen höchstens für die Elternansicht |
| **Ardour** | GPL; offizielle Binaries kostenpflichtig/Demo | Starke nicht-destruktive DAW, Loop-Record und Punch schließen sich aus; automatische Latenzkompensation | Nicht-destruktiv bleiben; USB-Mikro-Resampling beachten; keine schwere Dependency |
| **LMMS** | GPL-2 | Kein brauchbarer Live-Looper | Nicht verwenden |
| **REAPER** | Proprietär, 60 Tage testen, 60/225 USD | Sehr gutes Loop-Record, Takes, manuelle Latency-Offsets | Referenz für Loopback-Kalibrierung, nicht für die UI |
| **Cakewalk by BandLab** | **Eingestellt nach 1.8.2025, Aktivierung tot (Help Center 2.1.2026)** | — | Nicht empfehlen; Nachfolger **Cakewalk Sonar** und **Cakewalk Next** (Free-Tier + Membership) |
| **Tracktion Waveform Free** | Kostenlos, aktuell; T7 ist der alte Vorgänger | Loop-Record/Takes ja; **Launcher-Grid ist ein bezahltes Expansion Pack** | Kein kostenloses Ableton-Ersatz-Grid unterstellen |
| **Qtractor** | GPL-2+, nur Linux | Takes, Overdub über Clips, JACK | Nur Linux-Referenz |

Open-Source-Looper als *Konzept*-Quelle, nicht als Kind-UI: **SooperLooper** (Overdub, Feedback/Decay, fast unbegrenztes Undo/Redo, Quantize, Crossfade), **Giada**, **Luppp** (Pflege unklar). **Loopino** ist ein Sampler/Editor, kein Live-Looper. Schwere Frameworks (JUCE mit AGPL oder kommerzieller Lizenz, Superpowered nur bezahlt) sind für dieses Python-Projekt nicht nötig.

### 17.2 Professionelle Looper — Patterns, die dieser Plan übernimmt

- **Boss RC-1 / RC-5 / RC-505mkII:** Erste Phrase setzt die Länge (`LOOP LENGTH AUTO`). Zustandsautomat Rec / Play / Overdub. **Quantize nur beim ersten Record, nicht beim Overdub.** `AUTO REC` startet bei Überschreiten einer Eingangsschwelle (Onset-/Pegel-Start — Vorbild für Abschnitt 2, bei uns mit Fallback). Undo typischerweise **nur die letzte Schicht**, plus Redo; am 505mkII **pro Spur**. Fade gegen harte Kanten. Zustände in **Farbe und Bewegung/Form**.
- **Loopy Pro** (A Tasty Pixel, nicht „Sam Aaron“ — Sam Aaron ist Sonic Pi): Overdub mit Feedback/Decay; Peel/Replace als Schicht-Undo; Count-In/Out und Längen-Quantisierung. Für Kinder ist Decay/Replace zu viel — ein Pad, ein Take, Verlauf und Undo reichen; das Prinzip „Schicht sichtbar zurücknehmen“ stützt Pad-Undo + Redo.
- **BandLab Looper:** spielt vorgefertigte Packs, ist **kein** Mikrofon-Overdub-Looper (Hilfe, Stand 11.10.2026). Nicht als Vorbild für Aufnahme verwechseln.
- **n-Track:** Takes/Lanes, Latenzkalibrierung — Take-Idee entspricht eher unserem Verlauf.
- **GarageBand Live Loops / Ableton Session:** Raster, Count-In, Clip-Länge, Merge/Overdub als Option. Das stützt Abschnitt 13, nicht eine zweite Oberfläche.

Layer-Management in loopstation-kids: **ein aktiver Sample pro Pad**, Historie der Takes. Overdub-Schichten nur als mögliches späteres Eltern- oder Fortgeschrittenen-Feature auf demselben Clip (Abschnitt 13), kein Schritt, der die Kindseite aufbläht.

### 17.3 UX- und Schutzleitlinien

- Große Ziele, wenige Modi, Vorhersehbarkeit, keine überraschenden Pegel- oder Klangwechsel.
- Zustände immer **Farbe + Form/Icon/Text**, nicht Farbe allein ([WCAG 2.2 SC 1.4.1](https://www.w3.org/WAI/WCAG22/Understanding/use-of-color.html)).
- Plötzliche Pieps und Metronom abschaltbar und leise; sie laufen durch den Master-Limiter.
- In-App-Limiter = dB(FS). WHO/ITU-Kinderdosis 75 dBA / 40 h als Orientierung für Eltern, nicht als in der App gemessener Wert.
- Parental Gate für den Elternbereich; kein Netz, kein Teilen ohne späteren, bewussten Rechtsrahmen. Ein Gate ist nicht die gesetzliche Einwilligung ([Apple Guideline 5.1.4](https://developer.apple.com/app-store/review/guidelines/)).

### 17.4 Quellen-URLs

- Audacity 4.0.0: https://www.audacityteam.org/changelog/4.0.0/
- Audacity Playing and Recording: https://manual.audacityteam.org/man/playing_and_recording.html
- ocenaudio: https://www.ocenaudio.com/whatis
- Ardour FAQ: https://ardour.org/faq.html
- Ardour Latency: https://manual.ardour.org/synchronization/latency-and-latency-compensation/
- LMMS Song Editor: https://docs.lmms.io/user-manual/navigation/song-editor
- REAPER Purchase: https://www.reaper.fm/purchase.php
- Cakewalk by BandLab sunset: https://help.cakewalk.com/hc/en-us/articles/53866492346009-What-happened-to-Cakewalk-by-BandLab-I-can-t-seem-to-re-activate-it-anymore
- Cakewalk Sonar FAQ: https://help.cakewalk.com/hc/en-us/articles/41129734682393-Cakewalk-Sonar-FAQ
- Cakewalk Next: https://www.cakewalk.com/next
- Waveform Free: https://www.tracktion.com/products/waveform-free
- Qtractor: https://qtractor.org/
- SooperLooper: https://sonosaurus.com/sooperlooper/features.html
- Boss RC-1: https://static.roland.com/assets/media/pdf/RC-1_eng03_W.pdf
- Boss RC-5 Reference: https://static.roland.com/assets/media/pdf/RC-5_reference_eng01_W.pdf
- Boss RC-505mkII Parameter: https://static.roland.com/assets/media/pdf/RC-505mk2_Parameter_eng04_W.pdf
- Loopy Pro Overdub: https://wiki.loopypro.com/Overdub
- Loopy Pro Quantization: https://wiki.loopypro.com/Working_with_Record_Count-In/Out_and_Quantization
- BandLab Looper: https://help.bandlab.com/hc/en-us/articles/115004496573-Using-the-Looper
- Ableton Recording New Clips: https://www.ableton.com/en/live-manual/11/recording-new-clips/
- sounddevice ASIO / Installation: https://python-sounddevice.readthedocs.io/en/latest/installation.html
- sounddevice Version History: https://python-sounddevice.readthedocs.io/en/latest/version-history.html
- sounddevice PR ASIO-Flag: https://github.com/spatialaudio/python-sounddevice/pull/556
- PortAudio zu DirectSound-Latenz: https://github.com/PortAudio/portaudio/issues/911
- FlexASIO Backends (DirectSound über WASAPI): https://github.com/dechamps/FlexASIO/blob/master/BACKENDS.md
- Microsoft Low Latency Audio / WASAPI: https://learn.microsoft.com/en-us/windows-hardware/drivers/audio/low-latency-audio
- WHO/ITU H.870: https://www.itu.int/rec/T-REC-H.870
- WHO-ITU Summary: https://cdn.who.int/media/docs/default-source/documents/health-topics/deafness-and-hearing-loss/standard-summary-make-listening-safe.pdf?sfvrsn=fc114686_14
- Apple Kids / Guidelines: https://developer.apple.com/kids/ · https://developer.apple.com/app-store/review/guidelines/
- Google Play Families: https://support.google.com/googleplay/android-developer/answer/9893335?hl=en
- WCAG 1.4.1: https://www.w3.org/WAI/WCAG22/Understanding/use-of-color.html
- DSGVO-Kinder (EU-Kommission): https://commission.europa.eu/law/law-topic/data-protection/information-business-and-organisations/legal-grounds-processing-data/are-there-any-specific-safeguards-data-about-children_en
