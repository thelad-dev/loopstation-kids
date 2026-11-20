# Loopstation Kids — Verbesserungsplan

Stand: 20. November 2026. Erarbeitet im Gespräch zwischen Sebastian und Aurora (Grok).
Repo: thelad-dev/loopstation-kids (Python, PySide6, sounddevice/PortAudio).

Ziel: Aus dem bestehenden Kinderspielzeug eine richtig gute Loopstation machen —
einfach für Kinder, mit genug Eltern-Einstellungen für ein ordentliches Produkt.
Die Kindseite bleibt strikt dünn (Pad-Raster, Puls, fertig); alles andere
gehört hinter den erweiterten Schalter.

---

## 1. Audio-Verbesserungen

### 1.1 Undo (neu, höchste Priorität)

- Kein Undo im bisherigen Plan — ein Sechsjähriger trifft Pads aus Versehen
  ständig. Ohne Undo fühlt sich jede falsche Aufnahme wie ein toter Zweig an.
  Für die Zielgruppe fast wichtiger als Time-Stretching.
- Umsetzung über den Event-Store: neuer Event-Typ `pad_undo`, der den letzten
  aufzeichnenden oder verändernden Event eines Pads rückgängig macht.
- Pro Pad ein eigener Undo-Stack, damit Loops unabhängig voneinander
  zurückgesetzt werden können.
- Kindseite: Undo als einfacher Button pro Pad oder global. Elternseite:
  erweiterte Undo-Historie im Event-Log einsehbar.
- Die Architektur muss nicht verbogen werden — der Event-Store ist bereits
  stark genug.

### 1.2 Rubber Band Library (Time-Stretching)

- Engine hinter Audacity, C++ mit Python-Bindings, pitch-erhaltendes
  Time-Stretching in echtzeitfähiger Qualität.
- Sauber hinter den bestehenden `fit_to_grid`-Aufruf im Controller: ein Modul,
  das `data` plus `grid` nimmt und gestretchtes `data` zurückgibt.
- Das harte Grid bleibt als Garantie erhalten, aber Aufnahmen, die knapp
  daneben liegen, werden weich in den Takt gezogen statt zerstückelt.
- Priorität: nach Undo und Pegel, da Stretching auf stabiler Grundfunktion
  aufbaut.
- Offener Punkt: welche Distribution (`rubberband-py` via pip oder eigenes
  Build)? Auf Windows-Packaging achten (PyInstaller-Hook nötig).

### 1.3 Crossfade an den Loop-Nähten

- Wenn ein Loop vom Ende zurück zum Anfang springt und die Samples dort
  nicht phasenkontinuierlich sind, gibt es einen Klick.
- Ein paar Millisekunden Überblendung an der Naht killt das komplett.
- Die Crossfade-Länge ist proportional zur Loop-Länge: grob fünf bis zehn
  Prozent, mit einer Untergrenze von wenigen Millisekunden. Ein fixer Wert
  würde kurze Loops auffressen.
- Trivial zu implementieren.

### 1.4 Onset-Detection beim Stopp

- Statt den Schnitt exakt an die Stopp-Taste zu legen: einfache
  energie-basierte Detektion, wo im Aufnahme-Puffer ein echter Einschlag
  liegt, und dorthin trimmen.
- Ändert keine Länge, aber der Loop beginnt auf einem musikalischen
  Ereignis statt auf einem zufälligen Frame.
- Offener Punkt: reine Energie-Schwelle reicht für Klatschen; für
  Summen/Melodien evtl. komplexere Methode (z. B. spektraler Flux).
  Abgleich mit dem, was Kinder real aufnehmen.

---

## 2. Takt-Philosophie: Grid aus dem Kind, nicht aus der Taste

### 2.1 Das Problem

Hartes Grid-Snapping ist fragil, wenn das Kind den Takt vorgibt:
- Ein Kind, das nur klatscht oder ruft, hat oft keinen sauberen Takt drin.
- Eine Aufnahme mit zwei Klatschern: die Pause davor und dahinter ist
  Teil des Takts (Abstand in der Mitte zwischen den Klatschern), wird
  aber abgeschnitten.
- BPM aus der ersten Aufnahme ableiten ist elegant, aber rät bei
  unklarem Input was Falsches — ein kaputtes Grid untergräbt das
  ganze Gefühl.

### 2.2 Die Lösung: Onset-basierte Grid-Messung

- Onset-Detection auf die erste Aufnahme: wo sitzen die Schläge?
- Der Abstand zwischen den Onsets ist das Grid, nicht die Stopp-Taste.
- Ein Klatscher mit zwei Klatschen bekommt als Loop genau den Abstand
  zwischen den Klatschen; die Pausen davor und danach bleiben als
  Teil des Rhythmus erhalten, weil der Loop an einem Onset beginnt
  und am nächsten endet.
- Das ist im Kern beat-aware Time-Stretching: nicht Tempo schätzen,
  sondern Periode messen.
- Ein Kind, das nur einmal klatscht: ein Onset ergibt keinen Abstand,
  dann bleibt es beim freien Modus ohne Grid. Das ist okay —
  das Kind hat eben noch keinen Takt vorgegeben.

### 2.3 Fallback-Regel für absurde Onset-Abstände (neu)

- Liegt der Onset-Abstand außerhalb eines sinnvollen BPM-Fensters
  (unter 60 BPM oder über 240 BPM), greift kein Grid.
- Der Grund: ein Abstand von drei Sekunden zwischen zwei Klatschern ist
  eher eine Pause als ein Takt. Ohne diese Regel würde die Maschine ein
  falsches, frustrierendes Grid erzwingen.
- Stattdessen: freier Modus, das Kind kann den Abstand später durch
  weitere Schläge korrigieren.

### 2.4 Freier Modus pro Pad

- Das Kind kann ein Pad explizit in den freien Modus stellen
  (z. B. eine Melodie summen, darauf aufbauen).
- Das taktfreie Sample wird nicht durch das Grid in Mitleidenschaft
  gezogen — keine Analyse, kein Schneiden, keine Streckung.
- Es darf trotzdem Tempo stiften: Beat-Detection aus einem freien Pad
  greift nur, wenn noch kein Grid existiert. Sobald die Session einen
  Takt hat, ist das Klatschen auf dem freien Pad nur noch Klang.
- Im Event-Log als eigener Event-Typ `grid_seed` speichern (nicht
  `record_stop`), damit in der Historie sichtbar ist, woher der Takt kam.

### 2.5 Pädagogischer Nebeneffekt

Das Kind lernt intuitiv, dass Rhythmus etwas ist, das man vorgibt —
nicht etwas, das die Maschine diktiert.

---

## 3. Pegel und Geräte (neu)

### 3.1 Auto-Gain

- Toggle in den Einstellungen: Auto-Gain an oder aus.
- Grund: Kinder schreien ins Mikro, Input-Clipping ist real und frustrierend.
- Bei aktivem Auto-Gain wird der Eingangspegel dynamisch angepasst,
  ohne dass die Aufnahme abgehackt oder verstümmelt wird.
- Standard: an, da die Zielgruppe das Risiko nicht selbst managen kann.

### 3.2 Device-Zuweisung

- Separate Auswahl für das Aufnahmegerät (Input) und das Wiedergabegerät
  (Output). Nicht automatisch dasselbe Gerät annehmen.
- Die Auswahl gehört in den universellen Einstellungsdialog, da Geräte
  sich ändern können (anderes Headset, USB-Mikro etc.).
- Auf der Kindseite keine Device-Auswahl — nur Anzeige des aktiven Geräts,
  falls überhaupt. Die Konfiguration ist Elternsache.

### 3.3 Lautstärkeregler (beide Oberflächen)

- Permanentes Widget rechts oben auf der Kindseite und rechts oben auf der
  Elternseite.
- Kein Einstellungs-Item, sondern immer sichtbar und griffbereit.
- Beide Regler steuern denselben globalen Pegel — eine Quelle der Wahrheit,
  zwei Bedienelemente.
- Auf der Kindseite dezent, auf der Elternseite etwas prominenter.

### 3.4 Audio-Limiter (Elternbereich only)

- In den Einstellungen (universell für beide Bereiche konfigurierbar, aber
  nur im Elternkontext sichtbar/änderbar): ein Schalter plus einstellbarer
  Maximalpegel.
- Der Limiter sorgt dafür, dass eine bestimmte Lautstärke nie
  überschritten wird — Kindersicherheit für die Ohren, besonders wenn
  mehrere Loops gleichzeitig laufen oder der Auto-Gain aggressiv ist.
- Der Limiter arbeitet auf dem Output, nach dem Lautstärkeregler.

---

## 4. Elternseite: Einstellungen, erweiterte Ansicht, Export

### 4.1 Einstellungsseite

- settings.toml existiert bereits; die GUI drumherum fehlt noch.
- Enthält u. a.: Toggle für Auto-Grid / Beat-Detection, Auto-Gain,
  Device-Auswahl (Input/Output), Limiter mit Maximalpegel.
- Die Einstellungen sind universell — sie gelten für Kind- und
  Elternbereich gleichermaßen. Die Kindseite verhält sich nur passiv
  danach.

### 4.2 Erweiterte Ansicht ("Erweitert")

- Einzelne Loops anschauen (Wellenform-Ansicht).
- Marker setzen: beat-aware Time-Stretching passiert zwischen den
  Markern statt über den ganzen Puffer (Ableton-Prinzip, ohne
  Session-View-Komplexität).
- BPM-Einstellmöglichkeit: Elternseite ist die Quelle der Wahrheit.
  Kindseite zeigt nur an, was eingestellt ist.
- Metronom: visuell, immer Vierteltakt. Auf der Kindseite nur Anzeige;
  auf der Elternseite optionaler Metronom-Ton (falls jemand ein Lied
  mitklopfen will).
- Risiko: Mini-DAW-Gefahr. Die Kindseite muss strikt dünn bleiben.
  Alles andere gehört hinter den erweiterten Schalter, und der sollte
  sich nicht wie ein zweites Produkt anfühlen.

### 4.3 Marker-Datenstruktur (offener Punkt)

- Wie passen Marker ins Event-Store-Modell? Neuer Event-Typ, z. B.
  `marker_set` mit Pad, Position, Label.

---

## 5. Export (nur Elternseite)

- soundfile schreibt WAV; ffmpeg im Hintergrund liefert MP3.
- WAV als Default (unverfälschte Samples für Weiterverwendung),
  MP3 als Option.
- Marker aus der erweiterten Ansicht können als Cue-Points mit
  reingeschrieben werden, falls das Zielformat das kann.
- Kein Export auf der Kindseite.
- Offener Punkt: WAV unterstützt Cue-Chunks nicht standardisiert.
  Alternative: Sidecar-Datei oder Broadcast Wave (BWF) mit bext-Chunk.

---

## 6. Umsetzungsreihenfolge

1. Undo (`pad_undo`-Event, pro-Pad-Stack).
2. Pegel und Geräte: Auto-Gain, Input/Output-Device-Auswahl, Limiter,
   Lautstärkeregler auf beiden Oberflächen.
3. Rubber Band Library hinter `fit_to_grid`.
4. Onset-basierte Grid-Messung mit Fallback-Regel (ersetzt/ergänzt
   Stopp-Taste-Logik).
5. Crossfade an Loop-Nähten (proportional zur Loop-Länge).
6. Onset-Detection beim Stopp (Trim auf musikalische Ereignisse).
7. settings.toml-GUI (Einstellungsseite).
8. Erweiterte Ansicht: Wellenform, Marker, BPM, Metronom.
9. Freier Pad-Modus mit `grid_seed`-Event.
10. Export (WAV/MP3, Cue-Points).

Begründung der Verschiebung: Undo und Pegel sichern die Stabilität der
Grundfunktion, bevor Stretching und Grid-Logik drauf aufbauen. Ein Kind,
das keine Rückgängig-Funktion hat und dessen Aufnahme clippt, ist
frustriert — egal wie gut das Grid ist.

---

## 7. Offene Punkte

- Rubber-Band-Python-Bindings: welche Distribution (z. B. `rubberband-py`
  via pip, oder eigenes Build)? Auf Windows-Packaging achten
  (PyInstaller-Hook nötig).
- Onset-Detection: reine Energie-Schwelle reicht für Klatschen;
  für Summen/Melodien evtl. komplexere Methode (z. B. spektrale
  Flux). Abgleich mit dem, was Kinder real aufnehmen.
- Cue-Point-Format: WAV unterstützt Cue-Chunks nicht standardisiert;
  Alternative: Sidecar-Datei oder Broadcast Wave (BWF) mit bext-Chunk.
- Marker-Datenstruktur: wie passen Marker ins Event-Store-Modell
  (neuer Event-Typ, z. B. `marker_set` mit Pad, Position, Label)?
- BPM-Fenster für die Onset-Fallback-Regel: 60–240 BPM als Startwert,
  feinjustierbar?

---

## 8. Recherche: Freie Editoren, DAWs, Best Practices

### 8.1 Freie Audioeditoren

- **Audacity**: Hat Rubber Band bereits eingebaut — direkteste Referenz für
  das Stretching-Modul. Einfache, kindgerechte Grundkonzepte
  (Aufnahme, Schneiden, Überblenden), aber die GUI ist zu komplex für
  die Kindseite. Als Architektur-Vorbild für 1.2 und 1.3 relevant.
- **ocenaudio**: Leichtgewichtiger, schnell, gute Wellenform-Darstellung.
  Interessant für die erweiterte Elternansicht (Wellenform + Marker),
  aber kein Looping-Konzept.
- **Ardour** (als Editor-Partial): Onset- und Transient-Detection,
  Crossfades, Beat-Grid — architektonisch die vollständigste Referenz,
  aber viel zu schwer als Dependency für ein Kinderspielzeug.

### 8.2 Freie DAWs

- **Ardour**: Wie oben — Referenz für Beat-Grid und Crossfade-Architektur,
  nicht als Dependency.
- **LMMS**: Loop-orientiert, aber die GUI ist für Kinder zu dicht.
  Das Konzept "Pad = Sound + Loop" ist aber verwandt mit eurem
  Launchpad-Ansatz.
- **Cakewalk by BandLab**: Kostenlos (nicht Open Source), solide
  Overdubbing- und Loop-Funktionen. Referenz für Session-Denken,
  aber Windows-only.
- **Qtractor**: Linux-DAW, saubere Architektur, aber wieder zu schwer.
- **Tracktion T7**: Gut dokumentiert, moderate Größe. Wenig
  Loopstation-Charakter.

Fazit für die Dependency-Frage: Keine der DAWs kommt als Library infrage.
Die Konzepte (Beat-Grid, Crossfade, Onset-Detection) werden als
eigene, schlanke Module nachgebaut — Audacity liefert den Rubber-Band-
Beweis, Ardour die Architektur-Ideen.

### 8.3 Best Practices aus Loopstation-Software

- **Loopy (Sam Aaron)**: Pro Loop ein Play-Modus, quantisiertes
  Aufnehmen, Undo pro Loop. Das ist die beste konzeptionelle Referenz
  für euer Pad-Modell — ein Pad ist im Kern ein Loopy-Loop mit
  Kind-Oberfläche.
- **BandLab**: Overdubbing mit Metronom-Sync, Layer-Management,
  Cloud-Export. Referenz für den Export-Abschnitt (WAV/MP3).
- **n-Track**: Multi-Track-Looping mit Tempo-Sync. Referenz für die
  Frage, wie mehrere Loops zusammenspielen, ohne dass die Kindseite
  es merkt.
- **Boss RC-Serie (Hardware)**: Die Aufnahme startet auf den ersten
  Sound, nicht auf eine Taste. Das ist fast ein Freibrief für eure
  Onset-Idee (1.4) — die Industrie-Praxis bestätigt, dass
  ereignisbasiertes Starten dem Tasten-Start überlegen ist.

### 8.4 Was die Recherche für den Plan bedeutet

- Undo pro Loop (Loopy) → bestätigt 1.1.
- Onset-Start (Boss RC) → bestätigt 1.4 und 2.2.
- Keine schwere DAW als Dependency → bestätigt den schlanken
  Eigenbau-Ansatz.
- Rubber Band ist der Industriestandard für Echtzeit-Stretching →
  bestätigt 1.2, keine Alternative suchen.
- Crossfade als Anteil der Loop-Länge → Ardour macht das so, bestätigt
  die proportionale Lösung in 1.3.
