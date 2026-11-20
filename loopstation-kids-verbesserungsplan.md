# Loopstation Kids — Verbesserungsplan

Stand: 20. November 2026. Erarbeitet im Gespräch zwischen Sebastian und Aurora (Grok).
Repo: thelad-dev/loopstation-kids (Python, PySide6, sounddevice/PortAudio).

Ziel: Aus dem bestehenden Kinderspielzeug eine richtig gute Loopstation machen —
einfach für Kinder, mit genug Eltern-Einstellungen für ein ordentliches Produkt.
Die Kindseite bleibt strikt dünn (Pad-Raster, Puls, fertig); alles andere
gehört hinter den erweiterten Schalter.

---

## 1. Audio-Verbesserungen (drei Punkte, greifen ineinander)

### 1.1 Rubber Band Library (Time-Stretching)

- Engine hinter Audacity, C++ mit Python-Bindings, pitch-erhaltendes
  Time-Stretching in echtzeitfähiger Qualität.
- Sauber hinter den bestehenden `fit_to_grid`-Aufruf im Controller: ein Modul,
  das `data` plus `grid` nimmt und gestretchtes `data` zurückgibt.
- Das harte Grid bleibt als Garantie erhalten, aber Aufnahmen, die knapp
  daneben liegen, werden weich in den Takt gezogen statt zerstückelt.
- Priorität: erster Punkt, größter Effekt gegen den Frust der Kids.

### 1.2 Crossfade an den Loop-Nähten

- Wenn ein Loop vom Ende zurück zum Anfang springt und die Samples dort
  nicht phasenkontinuierlich sind, gibt es einen Klick.
- Ein paar Millisekunden Überblendung an der Naht killt das komplett.
- Trivial zu implementieren.

### 1.3 Onset-Detection beim Stopp

- Statt den Schnitt exakt an die Stopp-Taste zu legen: einfache
  energie-basierte Detektion, wo im Aufnahme-Puffer ein echter Einschlag
  liegt, und dorthin trimmen.
- Ändert keine Länge, aber der Loop beginnt auf einem musikalischen
  Ereignis statt auf einem zufälligen Frame.

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

### 2.3 Freier Modus pro Pad

- Das Kind kann ein Pad explizit in den freien Modus stellen
  (z. B. eine Melodie summen, darauf aufbauen).
- Das taktfreie Sample wird nicht durch das Grid in Mitleidenschaft
  gezogen — keine Analyse, kein Schneiden, keine Streckung.
- Es darf trotzdem Tempo stiften: Beat-Detection aus einem freien Pad
  greift nur, wenn noch kein Grid existiert. Sobald die Session einen
  Takt hat, ist das Klatschen auf dem freien Pad nur noch Klang.
- Im Event-Log als eigener Event-Typ `grid_seed` speichern (nicht
  `record_stop`), damit in der Historie sichtbar ist, woher der Takt kam.

### 2.4 Pädagogischer Nebeneffekt

Das Kind lernt intuitiv, dass Rhythmus etwas ist, das man vorgibt —
nicht etwas, das die Maschine diktiert.

---

## 3. Elternseite: Einstellungen, erweiterte Ansicht, Export

### 3.1 Einstellungsseite

- settings.toml existiert bereits; die GUI drumherum fehlt noch.
- Enthält u. a. den Toggle für Auto-Grid / Beat-Detection
  (an- und ausschaltbar).

### 3.2 Erweiterte Ansicht ("Erweitert")

- Einzelne Loops anschauen (Wellenform-Ansicht).
- Marker setzen: beat-aware Time-Stretching passiert zwischen den
  Markern statt über den ganzen Puffer (Ableton-Prinzip, ohne
  Session-View-Komplexität).
- BPM-Einstellmöglichkeit: Elternseite ist die Quelle der Wahrheit.
  Kindseite zeigt nur an, was eingestellt ist.
- Metronom: visuell, immer Vierteltakt. Auf der Kindseite nur Anzeige;
  auf der Elternseite optionaler Metronom-Ton (falls jemand ein Lied
  mitklopfen will).

### 3.3 Risiko

Mini-DAW-Gefahr: Die Kindseite muss strikt dünn bleiben.
Alles andere gehört hinter den erweiterten Schalter, und der sollte
sich nicht wie ein zweites Produkt anfühlen.

---

## 4. Export (nur Elternseite)

- soundfile schreibt WAV; ffmpeg im Hintergrund liefert MP3.
- WAV als Default (unverfälschte Samples für Weiterverwendung),
  MP3 als Option.
- Marker aus der erweiterten Ansicht können als Cue-Points mit
  reingeschrieben werden, falls das Zielformat das kann.
- Kein Export auf der Kindseite.

---

## 5. Umsetzungsreihenfolge (Vorschlag)

1. Rubber Band Library hinter `fit_to_grid`.
2. Onset-basierte Grid-Messung (ersetzt/ergänzt Stopp-Taste-Logik).
3. Crossfade an Loop-Nähten.
4. Onset-Detection beim Stopp (Trim auf musikalische Ereignisse).
5. settings.toml-GUI (Einstellungsseite).
6. Erweiterte Ansicht: Wellenform, Marker, BPM, Metronom.
7. Freier Pad-Modus mit `grid_seed`-Event.
8. Export (WAV/MP3, Cue-Points).

---

## 6. Offene Punkte

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
