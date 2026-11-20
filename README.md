# loopstation-kids

Kindgerechte Loopstation im Novation-Launchpad-Stil: 12 große Pads (4 × 3), Geräusche mit dem Mikrofon aufnehmen, abspielen, als Loop laufen lassen, löschen und alles wieder zurücknehmen. Läuft komplett lokal, ohne Konto und ohne Internet.

## Herunterladen

Fertige Versionen stehen unter [Releases](https://github.com/thelad-dev/loopstation-kids/releases): für Windows der Installer `Loopstation-Setup-<Version>.exe` (siehe [Windows](#windows)), für Linux das Quellcode-Archiv, darin `scripts/install-linux.sh` (siehe [Linux-Installation](#linux-installation)).

## Start

Voraussetzung: Python 3.11 oder neuer. Unter Linux braucht die Tonausgabe zusätzlich PortAudio (`sudo apt install libportaudio2`).

```bash
python3 -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m loopstation
```

Mit einer anderen Einstellungsdatei: `python -m loopstation --config pfad/zu/settings.toml`.

Ohne Mikrofon, ohne Audiogerät oder ohne Launchpad startet die Loopstation trotzdem; unten im Fenster steht dann ein kurzer Hinweis.

## Windows

Für Windows gibt es einen Installer (`Loopstation-Setup-<Version>.exe`), der alles mitbringt; Python muss nicht installiert sein. Er entsteht in GitHub Actions (Workflow `windows-installer`, bei einem Tag `v<Version>` oder per Hand gestartet) und liegt dort als Artefakt; bei einem Tag zusätzlich als Entwurf eines Releases. Pull Requests, die `packaging/`, `pyproject.toml`, `requirements*.txt`, `settings.toml` oder `loopstation/installed.py` ändern, bauen und starten den Installer ebenfalls, damit er vor dem Zusammenführen geprüft ist.

- Installation ohne Adminrechte für den aktuellen Benutzer (auf Wunsch für alle Benutzer), mit Startmenü-Eintrag und optionaler Desktop-Verknüpfung. Deinstallieren über „Apps & Features“.
- Einstellungen, Aufnahmen und Ereignis-Protokoll liegen in `%LOCALAPPDATA%\Loopstation` (`settings.toml`, `samples/`, `data/`). Beim ersten Start wird dort eine kommentierte `settings.toml` angelegt. Updates und Deinstallation lassen diesen Ordner unangetastet, die Aufnahmen bleiben also erhalten. Wer alles entfernen will, löscht den Ordner von Hand.
- Meldungen der App (etwa „kein Mikrofon“) stehen in `%LOCALAPPDATA%\Loopstation\loopstation.log`.
- Der Installer ist nicht signiert. Windows SmartScreen zeigt deshalb beim ersten Start „Der Computer wurde durch Windows geschützt“; über „Weitere Informationen“ und „Trotzdem ausführen“ geht es weiter.
- Audio-System ist standardmäßig WASAPI im geteilten Modus (Shared): die Loopstation spielt neben anderen Programmen, nichts wird stumm geschaltet. DirectSound und MME stehen als Notbehelf in der Liste (höhere Verzögerung). Siehe [Plattformen und Audio](#plattformen-und-audio).
- Der Installer bringt beide PortAudio-DLLs von sounddevice (ab 0.5.1) mit, die Standard-DLL und die mit ASIO-Unterstützung. Die App nutzt die Standard-DLL; die ASIO-DLL wird nur geladen, wenn Eltern in den Einstellungen „ASIO zulassen“ einschalten (`asio = true`, wirkt nach einem Neustart).
- Windows fragt beim ersten Aufnehmen eventuell nach dem Mikrofon-Zugriff. Falls die Aufnahme stumm bleibt: Einstellungen → Datenschutz → Mikrofon → „Desktop-Apps den Zugriff auf das Mikrofon erlauben“ einschalten.

Selbst bauen (unter Windows, mit Python 3.11 und [Inno Setup 6](https://jrsoftware.org/isinfo.php)):

```powershell
pip install -c packaging/windows/constraints.txt -r requirements.txt -r packaging/windows/requirements-build.txt
python packaging/windows/make_icon.py build/loopstation.ico
pyinstaller --noconfirm packaging/windows/loopstation.spec
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" /DAppVersion=1.1.0 packaging\windows\loopstation.iss
```

Das Ergebnis liegt in `dist\Loopstation-Setup-1.1.0.exe`. Gebündelt wird mit PyInstaller als Ordner (nicht als Einzeldatei), damit die App schnell startet und nichts nach `%TEMP%` entpacken muss.

## Linux-Installation

`scripts/install-linux.sh` installiert die Loopstation aus diesem Ordner für den aktuellen Benutzer, samt Startbefehl und Menüeintrag:

```bash
scripts/install-linux.sh             # fragt vor dem Installieren der Systempakete
scripts/install-linux.sh --dry-run   # zeigt nur, was passieren würde
loopstation-kids                     # starten (oder im Menü: Loopstation)
```

Das Skript erkennt die Distribution über `/etc/os-release` und installiert die fehlenden Systempakete mit dem passenden Paketmanager: Debian, Ubuntu, Linux Mint und Verwandte (apt), Fedora, RHEL, Rocky und AlmaLinux (dnf, unter RHEL-Abkömmlingen mit EPEL), Arch, Manjaro und EndeavourOS (pacman), openSUSE (zypper) und Alpine (apk). Dazu gehören Python 3.11 oder neuer mit venv, PortAudio, libsndfile, ALSA, die Bibliotheken für die Qt-Oberfläche (libGL, libxkbcommon, xcb-util-cursor und Verwandte) sowie Compiler und Header, falls pip ein Paket aus dem Quelltext bauen muss. Root-Rechte (sudo oder doas) braucht es nur dafür, und nur nach Rückfrage oder mit `--yes`. Fehlen Pakete und gibt es keine Root-Rechte, bricht das Skript ab und nennt die Pakete samt Befehl. Unter Arch und Verwandten ist ein vollständiges Systemupdate (`pacman -Syu`) nötig, wenn die Paketdatenbanken noch fehlen; darauf weist das Skript vor der Rückfrage hin.

Was wohin kommt:

- `~/.local/share/loopstation-kids/`: das Programm in einer eigenen Python-Umgebung (`venv`), dazu `settings.toml`, die Aufnahmen (`samples/`) und das Protokoll (`data/`). Die Loopstation startet in diesem Ordner. Eine vorhandene `settings.toml` wird bei einer neuen Installation nicht überschrieben.
- `~/.local/bin/loopstation-kids`: der Startbefehl. Liegt `~/.local/bin` nicht im `PATH`, sagt das Skript Bescheid.
- `~/.local/share/applications/` und `~/.local/share/icons/`: Menüeintrag und Icon.

Weitere Optionen:

- `--yes`: Systempakete ohne Rückfrage installieren.
- `--uninstall`: Programm, Startbefehl, Menüeintrag und Icon entfernen; Aufnahmen und Einstellungen bleiben. Mit `--purge` werden auch diese gelöscht (nach Rückfrage). Systempakete bleiben installiert.
- `--no-system-packages`: Systempakete nicht anfassen, etwa auf einer Distribution, die das Skript nicht kennt.
- `--python PFAD`: einen bestimmten Python-Interpreter verwenden.

Erneut aufrufen aktualisiert die Installation auf den Stand dieses Ordners; die alte Installation bleibt bis zum erfolgreichen Abschluss bestehen. Unter Alpine kommt PySide6 aus dem Paket `py3-pyside6`, und das Skript braucht `bash` (`sudo apk add bash`). Ein Audio-Server (PipeWire oder PulseAudio) gehört zum Desktop und wird nicht mitinstalliert.

## Update

Für alle, die die Loopstation schon installiert haben (etwa Version 1.0.0). Aufnahmen, Verlauf und Ereignis-Protokoll bleiben erhalten und werden von der neuen Version weiter gelesen; das ist mit einem eingefrorenen Protokoll aus 1.0.0 getestet (`tests/test_replay_v1.py`). Wer später zurück will, sichert vorher den Datenordner (siehe [Zurück zur vorigen Version](#zurück-zur-vorigen-version)).

**Windows:** den neuen `Loopstation-Setup-<Version>.exe` einfach über die bestehende Installation laufen lassen; vorher die Loopstation beenden. Der Installer ersetzt nur das Programm. `settings.toml`, `samples/` und `data/` liegen in `%LOCALAPPDATA%\Loopstation` und bleiben unangetastet; eine vorhandene `settings.toml` wird nie überschrieben. Die installierte Version steht unter Einstellungen → Apps → Installierte Apps (bzw. „Apps & Features“) bei „Loopstation“.

**Linux (mit `install-linux.sh`):** den neuen Stand holen (neues Quellcode-Archiv aus den Releases entpacken oder im geklonten Ordner `git pull`) und von dort `scripts/install-linux.sh` erneut aufrufen. Das Skript baut die Python-Umgebung neu, installiert die Abhängigkeiten der neuen Version und ergänzt fehlende Systempakete; die alte Installation bleibt bis zum erfolgreichen Abschluss bestehen. `settings.toml`, `samples/` und `data/` in `~/.local/share/loopstation-kids/` bleiben, eine vorhandene `settings.toml` wird nicht überschrieben.

**Aus dem Quellcode:** im Ordner `git pull`, dann in der bestehenden Umgebung `pip install -r requirements.txt` (die neue Version braucht `sounddevice` ab 0.5.1; pip hebt es dabei an). Die Daten liegen wie bisher im Startordner bzw. in `data_dir`. Die Version steht in `pyproject.toml`.

Was sich für Bestandsnutzer ändert:

- **Die bestehende `settings.toml` bleibt gültig.** Neue Schlüssel, die darin fehlen, gelten mit ihren Standardwerten. In die Datei geschrieben werden sie erst, wenn Erwachsene im Elternbereich etwas ändern; dann hängt die Seite die fehlenden Schlüssel mit Kommentar an und lässt die vorhandenen Zeilen stehen.
- **Leiser als vorher:** neu sind ein Lautstärke-Regler (`volume`, Standard 0.5) und eine Obergrenze (`max_level_db`, Standard -6 dB(FS)) mit Limiter. Version 1.0.0 gab die Summe ungebremst bis zur digitalen Vollaussteuerung aus. Wer es lauter braucht, stellt beides im Elternbereich ein.
- **Takt aus Klatschen** (`auto_grid`) ist standardmäßig aus: die erste Aufnahme bestimmt den Takt wie bisher über ihre Länge.
- **Standardmäßig an** sind die weiche Loop-Naht (`soft_seam`), das Strecken knapp neben dem Takt (`stretch_to_grid`) und die Pegelanzeige (`peak_meter`).
- **Neuer Elternbereich** hinter der Kachel „Eltern“ unten rechts (zwei Sekunden halten, Rechenaufgabe), mit sieben Bereichen: Lautstärke & Pegel, Geräte & Audio, Takt & Loop (mit Eltern-Takt und Metronom), Verlauf & Undo, Erweitert (Wellenform, Marker), Sets sichern und öffnen, Export als WAV.
- **„Alle löschen“ ist von der Kinderseite in den Elternbereich gewandert** (Verlauf & Undo, „Alle Pads löschen …“, mit Rückfrage; „Zurück“ holt alles wieder). Kinder können so nicht mehr versehentlich alles leeren.
- **Auf der Kinderseite neu:** „Wiederholen“, das Zurück-Abzeichen am Pad, der freie Modus per langem Halten und das rote „zu laut“-Zeichen. Am Launchpad wirkt ein kurzer Tipp jetzt beim Loslassen.

### Zurück zur vorigen Version

Vor dem Update den Datenordner kopieren (Windows `%LOCALAPPDATA%\Loopstation`, Linux-Installation `~/.local/share/loopstation-kids/` ohne `venv/`, aus dem Quellcode `settings.toml`, `samples/` und `data/` im Startordner). Zurück geht es dann so:

- **Windows:** den alten Installer (z. B. `Loopstation-Setup-1.0.0.exe` aus den Releases) über die neue Installation laufen lassen, dann den gesicherten Datenordner zurückkopieren.
- **Linux:** das Archiv der alten Version entpacken bzw. `git checkout v1.0.0`, `scripts/install-linux.sh` erneut aufrufen, gesicherte Daten zurückkopieren.
- **Aus dem Quellcode:** `git checkout v1.0.0`, `pip install -r requirements.txt`.

Ohne Sicherung: Version 1.0.0 lehnt eine `settings.toml` mit Schlüsseln ab, die sie nicht kennt, und startet dann nicht („unbekannter Schlüssel“). Dann die neuen Schlüssel aus der Datei löschen oder die Datei selbst (es gelten die Standardwerte). Das neuere Protokoll liest 1.0.0 zwar, übergeht aber, was sie nicht kennt (Wiederholen, Zurück am Pad, freier Modus, Marker); der Stand der Pads kann daher vom zuletzt gesehenen abweichen. Mit 1.1.0 gesicherte Sets kennt 1.0.0 nicht.

## Plattformen und Audio

Unterstützt werden Linux und Windows. macOS ist geplant, aber noch nicht gebaut oder getestet.

| Plattform | Audio-System (Standard zuerst) | Hinweise |
|---|---|---|
| Windows 10/11 | WASAPI (Shared), DirectSound, MME, optional ASIO | WASAPI teilt das Gerät mit anderen Programmen und rechnet die Abtastrate bei Bedarf um. ASIO nur für Audio-Interfaces mit eigenem Treiber, siehe unten. |
| Linux | ALSA, JACK (falls vorhanden) | Unter PipeWire oder PulseAudio läuft der Ton über deren ALSA-Anbindung; die App muss dafür nichts Besonderes tun. Kein ASIO. |
| macOS | - | später |

Aufnahme- und Wiedergabegerät sowie das Audio-System wählen Erwachsene im Elternbereich unter „Geräte und Audio-System“ (`input_device`, `output_device`, `audio_hostapi`; leer heißt Systemstandard). Ein Wechsel greift sofort: die Audio-Streams starten kurz neu, `latency_ms = "auto"` wird für das neue Gerät neu bestimmt. Geräte werden per Name gemerkt; fehlt ein Gerät beim Start, nimmt die App den Systemstandard und sagt es.

**ASIO (nur Windows, optional):** „ASIO zulassen“ (`asio = true`) lädt beim nächsten Start die PortAudio-DLL mit ASIO-Unterstützung, danach erscheint ASIO als Audio-System. Viele ASIO-Treiber öffnen das Gerät exklusiv (kein anderer Ton mehr am Rechner); ASIO4ALL ist ein Wrapper und verhält sich oft anders als der Treiber eines Interfaces. Für den Alltag bleibt WASAPI der richtige Weg.

## Mikrofon und Kopfhörer

- Beim Aufnehmen Kopfhörer tragen: Lautsprecher und Mikrofon zusammen erzeugen Echo, und laufende Loops landen in der neuen Aufnahme.
- Kabelgebundene Kopfhörer benutzen. Bluetooth ist für das Mitspielen meist zu träge und schwankt; die Geräteauswahl warnt bei Bluetooth-Namen.
- Am besten dasselbe Gerät (etwa ein USB-Headset oder ein Interface) für Aufnahme und Wiedergabe: zwei getrennte Geräte können gegeneinander driften.
- Ist eine Aufnahme zu laut, zeigt das Pad ein rotes Zeichen; im Elternbereich stehen Pegelanzeige, Mikrofonpegel (`input_gain_db`), automatischer Aufnahmepegel (`auto_gain`) und die zuletzt zu lauten Aufnahmen.
- Die Obergrenze (`max_level_db`) begrenzt die Amplitude im Rechner (dB(FS)), nicht den Schalldruck am Ohr. Den bestimmen auch Systemlautstärke und Kopfhörer; für Kinder am besten Kopfhörer mit eigener Lautstärkebegrenzung.
- Windows fragt beim ersten Aufnehmen eventuell nach dem Mikrofon-Zugriff (siehe [Windows](#windows)). Unter Linux muss das Mikrofon im Audio-Server des Desktops (PipeWire/PulseAudio) eingeschaltet und nicht stumm sein.

## Bedienung

| Pad-Farbe | Bedeutung |
|-----------|-----------|
| Weiß | leer |
| Gelb | Aufnahme vorhanden |
| Grün | spielt gerade oder läuft als Loop |
| Rot | nimmt gerade auf (mit Countdown) |

Oben wählt man den Modus, unten gibt es vier Knöpfe:

- **Spielen** (Standard): leeres Pad antippen startet eine Aufnahme, nochmal antippen stoppt sie. Ein gelbes Pad spielt einmal ab, ein grünes Pad wird gestoppt.
- **Aufnehmen**: jedes angetippte Pad nimmt neu auf. Die alte Aufnahme bleibt im Verlauf.
- **Loop**: gelbes Pad startet den Loop, grünes Pad stoppt ihn.
- **Löschen**: das nächste angetippte Pad wird geleert, danach geht es zurück zu „Spielen“.
- **Verlauf**: Pad antippen zeigt alle früheren Aufnahmen dieses Pads zum Anhören und Zurückholen.
- **Zurück-Abzeichen am Pad** (graue Scheibe mit Pfeil oben rechts): nach einer Änderung an genau einem Pad erscheint es an diesem Pad. Antippen nimmt nur die letzte Änderung dieses Pads zurück.
- **Freier Modus** (ein Pad lange halten): Ein Ring füllt sich, dann wird das Pad rund und zeigt eine Welle. Der Klang auf einem freien Pad behält seine eigene Länge und wird nie in den Takt geschnitten oder gezogen (zum Summen ohne Takt). Gibt es noch keinen Takt, bestimmt die erste Aufnahme auf einem freien Pad die Taktlänge (im Protokoll `master_set` mit `source: "free_pad"`), aber nur, wenn ihre Länge als Takt taugt (gleiche Grenzen wie bei der Takt-Erkennung, `grid_bpm_min`/`grid_bpm_max`); sonst bleibt die Sitzung ohne Raster und das Pad spielt in eigener Länge. Nochmal lange halten, das Zurück-Abzeichen oder „Zurück“ stellt das Pad wieder normal. Am Launchpad gilt dasselbe: Taste halten; ein kurzer Tipp wirkt jetzt beim Loslassen.
- **Zurück** (Strg+Z): macht die letzte Änderung rückgängig (Aufnahme, Löschen, Zurückholen), beliebig oft.
- **Wiederholen** (Strg+Y oder Strg+Umschalt+Z): holt zurückgenommene Änderungen wieder; jede neue Änderung beendet diese Kette.
- **Alles still**: stoppt alle Töne und Loops.
- **Alle löschen** gibt es nicht auf der Kinderseite, sondern nur im Elternbereich unter „Verlauf & Undo“ („Alle Pads löschen …“): leert alle Pads nach einer Ja/Nein-Frage; „Zurück“ holt alles wieder.

Ein zweiter Klick auf den aktiven Modus oder ESC führt zurück zu „Spielen“. Aufnahmen stoppen nach der eingestellten Höchstlänge von selbst.

Tastatur: Strg+Z (Zurück), Strg+Y oder Strg+Umschalt+Z (Wiederholen), ESC (zurück zu „Spielen“). Im Elternbereich lassen sich die Pegel-Regler mit den Pfeiltasten und Bild auf/ab verstellen.

### Im Takt bleiben

Die erste Aufnahme bestimmt die Loop-Länge. Jede weitere Aufnahme wird auf genau diese Länge geschnitten: Ist sie kürzer, wird sie mit Stille aufgefüllt, ist sie länger, wird sie auf zwei, drei, … Loop-Längen aufgefüllt (ein Stopp kurz nach einem Loop-Ende zählt noch zu diesem Loop). So laufen alle Loops gemeinsam und nie auseinander.

- Laufen schon Loops, beginnt eine neue Aufnahme erst am nächsten Loop-Anfang. Bis dahin ist das Pad dunkler, hat einen pulsierenden weißen Rahmen und einen Balken, der sich bis zum Loop-Anfang füllt. Erst dann erscheint der Sekunden-Countdown.
- Ein Loop startet und stoppt per Pad ebenfalls am Loop-Anfang (gleiche Anzeige). Läuft noch kein Loop, startet er sofort. „Alles still“, Löschen und „Zurück“ wirken sofort.
- Die Loop-Länge gilt, solange irgendein Pad belegt ist, auch wenn das erste Pad gelöscht oder neu aufgenommen wird. Werden alle Pads leer, beginnt eine neue Runde: Eine himmelblaue Welle läuft über die Pads, und die nächste Aufnahme bestimmt die neue Loop-Länge. „Zurück“ holt die alte Loop-Länge mit den Aufnahmen wieder; eine frühere Version, die in eine leere Runde zurückgeholt wird, bestimmt die Loop-Länge neu.
- Liegt eine Aufnahme knapp neben ganzen Takten (weniger als 10 % daneben), wird sie weich auf die volle Länge gezogen statt aufgefüllt oder abgeschnitten (`stretch_to_grid`, standardmäßig an). Die Tonhöhe bleibt dabei erhalten; deutlich daneben wird wie oben aufgefüllt oder geschnitten.
- Abschalten mit `loop_sync = false` in `settings.toml`; dann behält jede Aufnahme ihre eigene Länge wie früher.
- Optional (`auto_grid = true`, standardmäßig aus): Die erste Aufnahme einer Sitzung beginnt bei ihrem ersten Schlag (Klatschen, Stampfen); sie wird nur verschoben, nicht gekürzt. Liegen zwei oder mehr Schläge im erlaubten Tempo (`grid_bpm_min`, `grid_bpm_max`), bestimmt ihr Abstand den Takt gemäß `time_signature` (`2/4`, `3/4`, `4/4`, `6/8`); sonst gilt die Aufnahmelänge, aber nur, wenn sie als Takt taugt (dieselben Tempo-Grenzen); sonst bekommt die Sitzung lieber keinen Takt als einen falschen. Weitere Aufnahmen werden nie verschoben. Im Elternbereich stehen Tempo, Taktart und woher der Takt kommt (Aufnahmelänge, Schläge oder Eltern-Vorgabe).

Wie genau neue Loops auf den gehörten liegen, hängt von der Verzögerung zwischen Lautsprecher und Mikrofon ab (`latency_ms`). Der Standard `"auto"` nimmt den Wert, den der Audiotreiber meldet; klingen neue Loops etwas zu spät oder zu früh, lässt sich der Wert in Millisekunden einstellen. Mit echtem Mikrofon und Lautsprecher ist das bisher nicht nachgemessen, die Tests prüfen den Schnitt mit nachgebauter Soundkarte samplegenau.

## Launchpad

Ein angeschlossenes Novation Launchpad wird automatisch erkannt (auch nachträglich eingesteckt). Die Pads oben links auf dem Launchpad entsprechen den Pads auf dem Bildschirm und leuchten in denselben Farben.

- Launchpad Mini MK3, X, Pro MK3 und MK2: volle Farben.
- Ältere Modelle (Launchpad, S, Mini MK1/MK2): nur rote und grüne LEDs, leere Pads bleiben dunkel.
- Das erste Launchpad Pro wird nicht unterstützt.

- Kurz tippen wirkt beim Loslassen, lange halten schaltet den freien Modus des Pads um (wie auf dem Bildschirm).

Die Launchpad-Anbindung ist bisher nur mit nachgebauten MIDI-Ports getestet, noch nicht an echten Geräten.

## Einstellungen

In `settings.toml` im Startordner (jede Zeile ist dort kommentiert): Rastergröße (`rows`, `cols`), maximale Aufnahmelänge, Abtastrate, Pieptöne, Vollbild, Launchpad an/aus, taktgenauer Schnitt an/aus (`loop_sync`), Lautstärke (`volume`) mit Obergrenze (`max_level_db`), Mikrofonpegel (`input_gain_db`), automatischer Aufnahmepegel (`auto_gain`), Pegelanzeige der Aufnahme für Eltern (`peak_meter`), Takt aus der ersten Aufnahme (`auto_grid`, `time_signature`, `grid_bpm_min`, `grid_bpm_max`), Verzögerung zwischen Lautsprecher und Mikrofon (`latency_ms`), weiche Loop-Naht an/aus (`soft_seam`), freie Pads am Takt-Punkt starten (`free_pad_on_grid`), Marker als Cue-Punkte im Export (`export_cue_points`), Strecken knapp neben dem Takt (`stretch_to_grid`), Aufnahme- und Wiedergabegerät (`input_device`, `output_device`) und Audio-System (`audio_hostapi`, Standard WASAPI unter Windows, ALSA unter Linux) sowie ASIO (`asio`), leiser Metronom-Ton (`metronome_tone`, `metronome_level_db`), Datenordner. Fehlt die Datei, gelten die Standardwerte.

## Elternbereich

Erwachsene erreichen den Elternbereich über die Kachel „Eltern“ unten rechts (zwei Sekunden gedrückt halten, dann eine Rechenaufgabe lösen). Die Kinderseite bleibt bewusst schlicht: Pads, Modi, Zurück und Wiederholen, Alles still, Lautstärke, ein rotes Zeichen bei zu lauter Aufnahme und der Puls (ein Punkt je Schlag des Takts, der aktuelle leuchtet weich auf). Alles mit Zahlen und Fachbegriffen liegt im Elternbereich. Links stehen sieben Bereiche, oben links geht es „Zur Kinderseite“, oben rechts sitzt derselbe Lautstärke-Regler wie auf der Kinderseite:

- **Lautstärke & Pegel:** Obergrenze, Peak-Limiter, Mikrofonpegel, automatischer Aufnahmepegel, weiche Naht, Pieptöne und die zuletzt zu lauten Aufnahmen.
- **Geräte & Audio:** Mikrofon und Ausgabe getrennt (mit Testton), Audio-System, Verzögerung (automatisch oder von Hand) und unter „Allgemein“ Vollbild, Launchpad, Rastergröße, Abtastrate, Datenordner. Siehe [Plattformen und Audio](#plattformen-und-audio).
- **Takt & Loop:** aktueller Takt (Tempo, Taktart, Länge, Quelle), Takt korrigieren (Eltern-BPM), Loop-Verhalten und Metronom.
- **Verlauf & Undo:** die Änderungen der Sitzung (neueste oben, Uhrzeit aus dem Protokoll), Zurück und Wiederholen, „nur dieses Pad“ an der jeweils letzten Änderung eines Pads und „Alle Pads löschen …“ mit Rückfrage.
- **Erweitert**, **Sets**, **Export:** eigene Abschnitte weiter unten.

Der Verlauf eines Pads (alle früheren Aufnahmen zum Anhören und Zurückholen) ist auch für Kinder da: Modus „Verlauf“, dann Pad antippen.

Der Elternbereich schreibt die `settings.toml` mit allen Kommentaren (siehe [Einstellungen](#einstellungen)). Lautstärke- und Pegel-Regler wirken sofort und werden sofort gespeichert; die übrigen Werte übernimmt „Speichern“ (unten in der Navigation), und zwar ohne Neustart, außer Rastergröße, Abtastrate, ASIO und Datenordner (die Seite markiert sie). Die Pegelanzeige (`peak_meter`) ist standardmäßig an.

## Erweitert

Im Elternbereich unter „Erweitert“ und „Takt & Loop“. Die Kinderseite bekommt davon nichts außer dem Puls.

- **Wellenform und Marker:** ein Pad wählen und den Loop mit den Schlag-Linien des Takts ansehen. Es gibt keine Zeitachse und keine Spuren. Auf die Wellenform klicken und „Marker setzen“ legt einen Marker (bis zu 16, mit Buchstaben A bis P); „Marker löschen“ nimmt den gewählten wieder weg, „Anhören“ spielt den Loop einmal, „Diesen Loop exportieren“ sichert ihn als WAV (wie der Einzel-Export). „Zwischen Markern strecken“ schiebt jeden Marker auf seinen Schlag, aber nur bei knapper Abweichung (unter 10 %); der Loop davor liegt im Verlauf, Zurück bringt ihn wieder. Marker gehören zur Aufnahme (Sample-Datei), nicht zum Pad, und stehen im Ereignis-Protokoll als `marker_set`; sie liegen nicht auf dem Zurück-Stapel des Kindes.
- **Takt korrigieren (Eltern-BPM, unter „Takt & Loop“):** Tempo (innerhalb von `grid_bpm_min` bis `grid_bpm_max`) und Taktart vorgeben. Das hat Vorrang vor dem gemessenen Takt: Aufnahmen stiften danach kein neues Raster mehr (ein Onset richtet die erste Aufnahme höchstens aus). Im Ereignis-Protokoll steht es als `master_set` mit `source = parent_bpm`. Läuft schon Ton, werden die Loops ohne Änderung der Dateien neu an das Raster angepasst und laufende Loops beginnen auf den neuen Takten von vorn. „Gemessenen Takt“ gibt das Raster wieder an die Aufnahmen zurück. Ohne Ton in der Sitzung gilt der Wert ab der nächsten ersten Aufnahme. Die erste Aufnahme auf dem Eltern-Takt wird an das Raster angepasst (aufgefüllt oder gekürzt), aber nicht gestreckt; `stretch_to_grid` gilt erst für die folgenden Aufnahmen.
- **Metronom (unter „Takt & Loop“):** eine Reihe von Schlägen am echten Takt (erster Schlag eckig, aktueller gefüllt). Ohne laufende Loops zählt sie nach der Uhr weiter. Optional ein leiser Ton auf jedem Schlag (`metronome_tone`, standardmäßig aus; `metronome_level_db`, standardmäßig -20 dB): er läuft durch Lautstärke und Obergrenze und wird vorgezogen mit Stille davor an die Audio-Ausgabe gegeben, damit er unabhängig vom Bildschirmtakt auf dem Schlag liegt. Mit Lautsprecher hört das Mikrofon ihn bei einer Aufnahme mit.

## Export

Nur im Elternbereich unter „Export“, lokal, ohne Upload. Das Format ist WAV, 24 Bit, mono, in der Abtastrate der Sitzung; die Dateien landen in `Dokumente/Loopstation/Export`.

- **Summe:** alles, was gerade loopt (oder alle belegten Pads als Loop), über N Takte (4, 8, 16, 32 oder eine eigene Zahl). Die Länge ist genau N × Taktlänge in ganzen Frames, jeder Loop startet vorn und wiederholt sich wie live. Es gilt dieselbe Pegelkette wie live: Lautstärke, dann der Limiter mit der Eltern-Obergrenze auf die Summe. Optional ein kurzer Ausklang (15 ms) und Einmal-Pads am Anfang. Ohne Takt in der Sitzung (`loop_sync` aus) wird nicht geraten: die Seite erklärt das, und nur auf ausdrückliche Wahl gilt „N × längstes Sample“ als Notbehelf, vermerkt im Kommentar der Datei.
- **Einzelner Loop:** das aufgenommene Sample unverändert, ohne Lautstärke und Limiter. Die Marker des Loops werden als Cue-Punkte in die WAV-Datei geschrieben (`export_cue_points`, standardmäßig an, auch im Export-Dialog schaltbar); klappt das nicht, liegt eine Begleitdatei `.markers.json` daneben. Das Sichern scheitert daran nie.

## Sets sichern und öffnen

Erwachsene frieren die laufende Sitzung als Set ein und öffnen gespeicherte Sets wieder: Elternbereich, Bereich „Sets“. Ein Set ist eine Kopie der Sitzung (Ereignis-Protokoll samt Zurück-Schritten, alle Aufnahmen als WAV, Kopie der `settings.toml`) als `.loopset`-Datei (ZIP) oder als Ordner, standardmäßig unter `Dokumente/Loopstation/Sets`. Das Kind spielt nach dem Sichern einfach weiter.

- Gesichert wird erst in eine temporäre Datei, dann umbenannt: ein Abbruch überschreibt kein altes Set halb. Läuft eine Aufnahme, wird das Sichern verweigert.
- Beim Öffnen wird das Set vollständig geprüft, bevor etwas ersetzt wird: zu neue Formatversion, falsche Padzahl oder Abtastrate, beschädigte Dateien. Ist die aktuelle Sitzung nicht gesichert, fragt die Seite zuerst („Erst sichern, dann öffnen“, „Ohne sichern“). Die Zurück-Schritte des Sets bleiben, „Wiederholen“ startet leer.
- Die eigenen Einstellungen des Rechners bleiben maßgeblich. Fehlt ein Gerät aus dem Set, wird der Systemstandard benutzt und die Sets-Seite sagt es.
- Das Öffnen ersetzt `data/` und `samples/` zwischen zwei Sitzungen im selben Prozess (die Loopstation baut Fenster, Protokoll und Audio neu auf). Wird das mittendrin abgebrochen, schließt der nächste Start den Tausch ab (`loopstation/session.py`).

## Daten

- `samples/pad_<Pad>_<Zeitstempel>.wav`: jede Aufnahme als eigene WAV-Datei. Dateien werden nie automatisch gelöscht, damit „Zurück“ und der Verlauf immer funktionieren.
- `data/clips.jsonl`: die letzten 50 zu lauten Aufnahmen (Pad, Spitzenpegel, ob das Mikrofon übersteuert hat) für den Elternbereich. Die Datei bleibt auf diesem Rechner und darf jederzeit gelöscht werden.
- `data/events.jsonl`: das Ereignis-Protokoll, eine Zeile pro Aktion. Die Loop-Länge steht darin als `master_set` (Länge in Samples und Abtastrate), der Beginn einer neuen Runde als `session_start`. Protokolle aus älteren Versionen ohne diese Ereignisse werden weiter gelesen. Der aktuelle Zustand entsteht beim Start durch Nachspielen dieser Ereignisse. Alle 100 Ereignisse wird ein Schnappschuss des ganzen Zustands geschrieben; das aktive Protokoll hat höchstens 2000 Zeilen, ältere Abschnitte wandern nach `data/archive/`.
- Jedes Ereignis wird sofort auf die Platte geschrieben. Nach einem Absturz startet die Loopstation mit dem letzten Stand, nichts spielt von selbst los.

## Entwicklung

```bash
pip install -r requirements-dev.txt
python -m pytest -q
ruff check .
```

Die Tests brauchen weder Audiogerät noch Launchpad (Audio, MIDI und Uhr werden nachgebaut, die Oberfläche läuft mit `QT_QPA_PLATFORM=offscreen`).

Aufbau: `loopstation/store.py` (Ereignis-Protokoll), `state.py` (Zustand und Nachspielen), `controller.py` (Bedienlogik ohne Qt), `audio/` (Aufnahme und Wiedergabe, `audio/sync.py` rechnet das Loop-Raster), `midi/` (Launchpad), `clips.py` (Merkzettel zu lauter Aufnahmen), `gui/` (Oberfläche), `sets.py` und `session.py` (Sets schreiben, lesen, Sitzung tauschen), `installed.py` (Start der installierten App mit Datenordner im Benutzerprofil), `packaging/windows/` (PyInstaller-Spec, Inno-Setup-Skript, App-Symbol).
