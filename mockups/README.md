# Mockups – Loopstation Kids

Stand: 20. November 2026. Grundlage: `loopstation-kids-verbesserungsplan.md` (finale Fassung, Commit 612de85).
Farben, Schrift-Gewichte und Grundaufbau sind aus der bestehenden GUI übernommen (`loopstation/gui/widgets.py`, `main_window.py`, `pad_button.py`): dunkler Hintergrund `#0E0E10`, Flächen `#26262B`, Padfarben weiß/gelb/grün/rot, Modus-Akzente grün/rot/blau/orange/lila, farbiger Rahmen im Modus-Akzent.

Jede Datei ist **1280 × 800 px Oberfläche plus ein heller Beschriftungsstreifen unten** (Titel, Plan-Abschnitt, Hinweise). Der Streifen gehört **nicht** zur App.

## Dateien

| Datei | Ansicht | Plan-Abschnitte |
|---|---|---|
| `01_kinderseite_spielen.svg` | Kinderseite, Grundansicht: Modusleiste, 12 große Pads, Zurück / Wiederholen / Alles still, ruhiger Puls, Lautstärke rechts oben, kleines Eltern-Schloss | §3, §6.3, §9.1, §2.2 Regel 7 |
| `02_kinderseite_aufnahme_zu_laut.svg` | Aufnahme läuft: Restsekunden, Fortschrittsbalken, grobe 3-Stufen-Pegelanzeige, „zu laut“-Schild (Form + Farbe + Wort) | §7 (1), §3.1, §2.2 Regel 5 |
| `03_kinderseite_warten_puls.svg` | Loop wartet auf den nächsten Takt-Anfang: weicher Puls-Ring + Füllbalken, Puls-Punkte unten | §2.2 Regel 7, §13, §3.2 |
| `04_kinderseite_freier_modus.svg` | Freier Modus: Pad wird Kreis + Wellen-Symbol; Einstieg per langem Halten mit sichtbarem Ring | §2.3 |
| `05_kinderseite_zurueck_wiederholen.svg` | Zurück am Pad (Abzeichen am geänderten Pad) und aktiver „Wiederholen“-Knopf | §6.2, §6.3, §15 Nr. 1 + 10 |
| `06_kinderseite_alles_still.svg` | Nach „Alles still“: alle Loops gestoppt, Puls ruht | §3, §0 |
| `07_kinderseite_verlauf.svg` | Verlauf-Modus: frühere Takes eines Pads anhören / nehmen | §0, §6.1, §15 Nr. 14 |
| `08_eltern_zugang_gate.svg` | Parental Gate (Rechenaufgabe mit großen Tasten) | §3, §16 |
| `09_eltern_lautstaerke_pegel.svg` | Eltern: maximale Lautstärke (dBFS-Grenze + Peak-Limiter), Hinweis dBFS ≠ dB am Ohr (WHO 75 dBA), Peak-Meter mit Zielzone, Eingangs-Trim, Soft-Clip, Auto-Gain (Standard aus), Crossfade-Schalter, Pieps, „zu laut“-Protokoll | §9.1–9.3, §7, §3.1, §1.2 |
| `10_eltern_geraete_audio.svg` | Eltern: Mikrofon (Eingang) und Lautsprecher/Kopfhörer (Ausgang) getrennt, Audio-System Windows (WASAPI geteilt = Standard, ASIO optional, WASAPI exklusiv, DirectSound, MME), Latenz auto/manuell, Hinweise | §8, §11.1, §12, §3.1 |
| `11_eltern_takt_loop.svg` | Eltern: BPM, Taktart, Takt-Länge, Quelle; Eltern-BPM-Korrektur; Schalter Auto-Grid, loop_sync, Onset-Verschiebung, Vorpause entfernen, freie Pads am Takt-Punkt, Metronom-Ton | §2.2, §2.3, §1.3, §3.1–3.2, §13 |
| `12_eltern_verlauf_undo_redo.svg` | Eltern: Zurück/Wiederholen mit Änderungsliste, pro Zeile „nur dieses Pad“; „Alle Pads löschen …“ | §6.1–6.3, §10.3 |
| `13_eltern_erweitert_wellenform_export.svg` | Eltern „Erweitert“: Wellenform mit Schlaglinien, Marker, Strecken zwischen Markern, Export eines einzelnen Loops (WAV; MP3 nur mit ffmpeg) | §3.2, §4, §1.1, §13 |
| `14_eltern_set_speichern.svg` | Set speichern (.loopset-Datei oder Ordner), Inhaltsübersicht, Hinweis atomisches Speichern | §10.1–10.2 |
| `15_eltern_set_oeffnen.svg` | Set öffnen: Liste, Details, Geräte-Fallback, zu neue Format-Version, Rückfrage bei ungesicherter Sitzung | §10.3, §10.1 |
| `16_eltern_export_summe.svg` | Export der Summe: N Takte (4/8/16/32), berechnete Länge, Pad-Auswahl, Einmal-Pads, Ausklang, WAV/MP3, Vorschau der Wiederholungen | §5.1–5.3, §4 |
| `gen_mockups.py` | Generator aller SVGs (und PNGs) – Quelle der Wahrheit für Maße und Farben | – |

**PNG-Fassungen:** liegen nicht im Repo (das GitHub-Werkzeug, mit dem dieser Commit gemacht wurde, kann nur Textdateien schreiben). GitHub zeigt die SVGs direkt an. PNGs erzeugen: `pip install cairosvg && python mockups/gen_mockups.py` (schreibt `*.png` neben die SVGs, 1280 × 916 px).

## Hinweise für den bauenden Agenten

**Kinderseite (strikt dünn, §3 / §3.3)**
- Erlaubt sind nur: Modusleiste (Spielen, Aufnehmen, Loop, Löschen, Verlauf – wie heute), 12 Pads, „Zurück“, „Wiederholen“, „Alles still“, visueller Puls, Lautstärkeregler rechts oben, kleines Eltern-Schloss. Keine Wellenform, kein Geräte-Menü, kein Limiter, kein Export, kein Set-Dialog.
- Große Ziele: Pads ca. 164 px bei 1280 × 800 (wie `PadGrid` heute, quadratisch zentriert), Knöpfe unten 92 px hoch, Regler-Knopf 54 px Durchmesser.
- Reizarm: keine Blink-Animationen. Puls = langsames, weiches Aufleuchten (vier Punkte = Schläge des Takts). Zustände immer mit Farbe **und** Form/Symbol (Clip-Schild, Kreis-Form beim freien Modus, Zurück-Abzeichen am Pad).
- Padfarben bleiben die heutigen Zustandsfarben (weiß leer, gelb belegt, grün läuft, rot nimmt auf) – damit stimmen GUI und Launchpad-LEDs weiter überein.
- „Wiederholen“ ist ausgegraut, wenn nichts wiederherzustellen ist (§6.3).

**Lautstärke rechts oben (§9.1)**
- Gleiche Position, gleiche Größe auf Kinder- und Elternseite, **eine** Quelle der Wahrheit. Der Bereich über der Eltern-Grenze ist schraffiert und mit Schloss markiert; der Kinderregler kann ihn nicht erreichen und rutscht mit, wenn Eltern die Grenze senken.

**Elternbereich**
- Linke Navigation mit 7 Bereichen (Lautstärke & Pegel, Geräte & Audio, Takt & Loop, Verlauf & Undo, Erweitert, Sets, Export). Oben links „Zur Kinderseite“.
- Änderungen gelten live; nur `sample_rate`, `rows`, `cols`, `data_dir` brauchen einen Neustart (§3) – das steht unten links in der Navigation.
- Der Hinweis „dBFS ist nicht dB am Ohr“ mit WHO-Orientierung 75 dBA / 40 h ist Pflichttext (§9.3).
- Auto-Gain ist **standardmäßig aus** (§7, §15 Nr. 2). WASAPI geteilt ist Windows-Standard (§12.1, §15 Nr. 12); ASIO nur als Option mit Warnung.
- MP3 erscheint ausgegraut mit Grund, wenn ffmpeg fehlt (§4).
- Auf Linux/macOS zeigt die Karte „Audio-System“ die dortigen Host-APIs (ALSA bzw. CoreAudio, §11.1); das Mockup zeigt die Windows-Variante.

**Gestaltungsentscheidungen, die der Plan offen lässt (bitte bestätigen oder ändern)**
1. **Eltern-Zugang:** kleines Schloss unten rechts, 2 Sekunden halten, dann Rechenaufgabe (§3 nennt nur „einfaches Parental Gate“).
2. **„Alle löschen“** ist von der Kinderseite in den Elternbereich gewandert (Mockup 12), weil §3 die Kinderseite auf Pads, Modi, Zurück, Alles still, Lautstärke und Puls begrenzt. Heute liegt der Knopf noch auf der Kinderseite.
3. **Pad-Undo-Geste:** als sichtbares Abzeichen am zuletzt geänderten Pad skizziert; die Feingestaltung soll laut §16 mit Kindern getestet werden.
4. **Freier Modus:** Einstieg durch langes Halten mit Fortschrittsring, Kennzeichen Kreis-Form + Wellen-Symbol (§2.3 verlangt nur „grobmotorisch, sichtbar, Form-Änderung“).
5. Alle Zahlen (BPM, Pegel, Gerätenamen, Set-Namen, Uhrzeiten) sind Beispielwerte.
