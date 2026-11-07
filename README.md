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

Für Windows gibt es einen Installer (`Loopstation-Setup-<Version>.exe`), der alles mitbringt; Python muss nicht installiert sein. Er entsteht in GitHub Actions (Workflow `windows-installer`, bei einem Tag `v<Version>` oder per Hand gestartet) und liegt dort als Artefakt; bei einem Tag zusätzlich als Entwurf eines Releases.

- Installation ohne Adminrechte für den aktuellen Benutzer (auf Wunsch für alle Benutzer), mit Startmenü-Eintrag und optionaler Desktop-Verknüpfung. Deinstallieren über „Apps & Features“.
- Einstellungen, Aufnahmen und Ereignis-Protokoll liegen in `%LOCALAPPDATA%\Loopstation` (`settings.toml`, `samples/`, `data/`). Beim ersten Start wird dort eine kommentierte `settings.toml` angelegt. Updates und Deinstallation lassen diesen Ordner unangetastet, die Aufnahmen bleiben also erhalten. Wer alles entfernen will, löscht den Ordner von Hand.
- Meldungen der App (etwa „kein Mikrofon“) stehen in `%LOCALAPPDATA%\Loopstation\loopstation.log`.
- Der Installer ist nicht signiert. Windows SmartScreen zeigt deshalb beim ersten Start „Der Computer wurde durch Windows geschützt“; über „Weitere Informationen“ und „Trotzdem ausführen“ geht es weiter.
- Windows fragt beim ersten Aufnehmen eventuell nach dem Mikrofon-Zugriff. Falls die Aufnahme stumm bleibt: Einstellungen → Datenschutz → Mikrofon → „Desktop-Apps den Zugriff auf das Mikrofon erlauben“ einschalten.

Selbst bauen (unter Windows, mit Python 3.11 und [Inno Setup 6](https://jrsoftware.org/isinfo.php)):

```powershell
pip install -c packaging/windows/constraints.txt -r requirements.txt -r packaging/windows/requirements-build.txt
python packaging/windows/make_icon.py build/loopstation.ico
pyinstaller --noconfirm packaging/windows/loopstation.spec
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" /DAppVersion=1.0.0 packaging\windows\loopstation.iss
```

Das Ergebnis liegt in `dist\Loopstation-Setup-1.0.0.exe`. Gebündelt wird mit PyInstaller als Ordner (nicht als Einzeldatei), damit die App schnell startet und nichts nach `%TEMP%` entpacken muss.

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

## Bedienung

| Pad-Farbe | Bedeutung |
|-----------|-----------|
| Weiß | leer |
| Gelb | Aufnahme vorhanden |
| Grün | spielt gerade oder läuft als Loop |
| Rot | nimmt gerade auf (mit Countdown) |

Oben wählt man den Modus, unten gibt es drei Knöpfe:

- **Spielen** (Standard): leeres Pad antippen startet eine Aufnahme, nochmal antippen stoppt sie. Ein gelbes Pad spielt einmal ab, ein grünes Pad wird gestoppt.
- **Aufnehmen**: jedes angetippte Pad nimmt neu auf. Die alte Aufnahme bleibt im Verlauf.
- **Loop**: gelbes Pad startet den Loop, grünes Pad stoppt ihn.
- **Löschen**: das nächste angetippte Pad wird geleert, danach geht es zurück zu „Spielen“.
- **Verlauf**: Pad antippen zeigt alle früheren Aufnahmen dieses Pads zum Anhören und Zurückholen.
- **Zurück** (Strg+Z): macht die letzte Änderung rückgängig (Aufnahme, Löschen, Zurückholen), beliebig oft.
- **Alles still**: stoppt alle Töne und Loops.
- **Alle löschen**: leert alle Pads nach einer Ja/Nein-Frage; „Zurück“ holt alles wieder.

Ein zweiter Klick auf den aktiven Modus oder ESC führt zurück zu „Spielen“. Aufnahmen stoppen nach der eingestellten Höchstlänge von selbst.

### Im Takt bleiben

Die erste Aufnahme bestimmt die Loop-Länge. Jede weitere Aufnahme wird auf genau diese Länge geschnitten: Ist sie kürzer, wird sie mit Stille aufgefüllt, ist sie länger, wird sie auf zwei, drei, … Loop-Längen aufgefüllt (ein Stopp kurz nach einem Loop-Ende zählt noch zu diesem Loop). So laufen alle Loops gemeinsam und nie auseinander.

- Laufen schon Loops, beginnt eine neue Aufnahme erst am nächsten Loop-Anfang. Bis dahin ist das Pad dunkler, hat einen pulsierenden weißen Rahmen und einen Balken, der sich bis zum Loop-Anfang füllt. Erst dann erscheint der Sekunden-Countdown.
- Ein Loop startet und stoppt per Pad ebenfalls am Loop-Anfang (gleiche Anzeige). Läuft noch kein Loop, startet er sofort. „Alles still“, Löschen und „Zurück“ wirken sofort.
- Die Loop-Länge gilt, solange irgendein Pad belegt ist, auch wenn das erste Pad gelöscht oder neu aufgenommen wird. Werden alle Pads leer, beginnt eine neue Runde: Eine himmelblaue Welle läuft über die Pads, und die nächste Aufnahme bestimmt die neue Loop-Länge. „Zurück“ holt die alte Loop-Länge mit den Aufnahmen wieder; eine frühere Version, die in eine leere Runde zurückgeholt wird, bestimmt die Loop-Länge neu.
- Abschalten mit `loop_sync = false` in `settings.toml`; dann behält jede Aufnahme ihre eigene Länge wie früher.

Wie genau neue Loops auf den gehörten liegen, hängt von der Verzögerung zwischen Lautsprecher und Mikrofon ab (`latency_ms`). Der Standard `"auto"` nimmt den Wert, den der Audiotreiber meldet; klingen neue Loops etwas zu spät oder zu früh, lässt sich der Wert in Millisekunden einstellen. Mit echtem Mikrofon und Lautsprecher ist das bisher nicht nachgemessen, die Tests prüfen den Schnitt mit nachgebauter Soundkarte samplegenau.

## Launchpad

Ein angeschlossenes Novation Launchpad wird automatisch erkannt (auch nachträglich eingesteckt). Die Pads oben links auf dem Launchpad entsprechen den Pads auf dem Bildschirm und leuchten in denselben Farben.

- Launchpad Mini MK3, X, Pro MK3 und MK2: volle Farben.
- Ältere Modelle (Launchpad, S, Mini MK1/MK2): nur rote und grüne LEDs, leere Pads bleiben dunkel.
- Das erste Launchpad Pro wird nicht unterstützt.

Die Launchpad-Anbindung ist bisher nur mit nachgebauten MIDI-Ports getestet, noch nicht an echten Geräten.

## Einstellungen

In `settings.toml` im Startordner (jede Zeile ist dort kommentiert): Rastergröße (`rows`, `cols`), maximale Aufnahmelänge, Abtastrate, Pieptöne, Vollbild, Launchpad an/aus, taktgenauer Schnitt an/aus (`loop_sync`), Verzögerung zwischen Lautsprecher und Mikrofon (`latency_ms`), Datenordner. Fehlt die Datei, gelten die Standardwerte.

## Daten

- `samples/pad_<Pad>_<Zeitstempel>.wav`: jede Aufnahme als eigene WAV-Datei. Dateien werden nie automatisch gelöscht, damit „Zurück“ und der Verlauf immer funktionieren.
- `data/events.jsonl`: das Ereignis-Protokoll, eine Zeile pro Aktion. Die Loop-Länge steht darin als `master_set` (Länge in Samples und Abtastrate), der Beginn einer neuen Runde als `session_start`. Protokolle aus älteren Versionen ohne diese Ereignisse werden weiter gelesen. Der aktuelle Zustand entsteht beim Start durch Nachspielen dieser Ereignisse. Alle 100 Ereignisse wird ein Schnappschuss des ganzen Zustands geschrieben; das aktive Protokoll hat höchstens 2000 Zeilen, ältere Abschnitte wandern nach `data/archive/`.
- Jedes Ereignis wird sofort auf die Platte geschrieben. Nach einem Absturz startet die Loopstation mit dem letzten Stand, nichts spielt von selbst los.

## Entwicklung

```bash
pip install -r requirements-dev.txt
python -m pytest -q
ruff check .
```

Die Tests brauchen weder Audiogerät noch Launchpad (Audio, MIDI und Uhr werden nachgebaut, die Oberfläche läuft mit `QT_QPA_PLATFORM=offscreen`).

Aufbau: `loopstation/store.py` (Ereignis-Protokoll), `state.py` (Zustand und Nachspielen), `controller.py` (Bedienlogik ohne Qt), `audio/` (Aufnahme und Wiedergabe, `audio/sync.py` rechnet das Loop-Raster), `midi/` (Launchpad), `gui/` (Oberfläche), `installed.py` (Start der installierten App mit Datenordner im Benutzerprofil), `packaging/windows/` (PyInstaller-Spec, Inno-Setup-Skript, App-Symbol).
