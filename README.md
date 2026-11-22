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

Für Windows gibt es einen Installer (`Loopstation-Setup-<Version>.exe`), der alles mitbringt (außer dem optionalen Rubber Band, siehe [Stretch-Engine](#stretch-engine-rubber-band)); Python muss nicht installiert sein. Er entsteht in GitHub Actions (Workflow `windows-installer`, bei einem Tag `v<Version>` oder per Hand gestartet) und liegt dort als Artefakt; bei einem Tag zusätzlich als Entwurf eines Releases. Pull Requests, die `packaging/`, `pyproject.toml`, `requirements*.txt`, `settings.toml` oder `loopstation/installed.py` ändern, bauen und starten den Installer ebenfalls, damit er vor dem Zusammenführen geprüft ist.

- Installation ohne Adminrechte für den aktuellen Benutzer (auf Wunsch für alle Benutzer), mit Startmenü-Eintrag und optionaler Desktop-Verknüpfung. Deinstallieren über „Apps & Features“.
- Einstellungen, Aufnahmen und Ereignis-Protokoll liegen in `%LOCALAPPDATA%\Loopstation` (`settings.toml`, `samples/`, `data/`). Beim ersten Start wird dort eine kommentierte `settings.toml` angelegt. Updates und Deinstallation lassen diesen Ordner unangetastet, die Aufnahmen bleiben also erhalten. Wer alles entfernen will, löscht den Ordner von Hand.
- Meldungen der App (etwa „kein Mikrofon“) stehen in `%LOCALAPPDATA%\Loopstation\loopstation.log`.
- Der Installer ist nicht signiert. Windows SmartScreen zeigt deshalb beim ersten Start „Der Computer wurde durch Windows geschützt“; über „Weitere Informationen“ und „Trotzdem ausführen“ geht es weiter.
- Audio-System ist standardmäßig WASAPI im geteilten Modus (Shared): die Loopstation spielt neben anderen Programmen, nichts wird stumm geschaltet. DirectSound und MME stehen als Notbehelf in der Liste (höhere Verzögerung). Siehe [Plattformen und Audio](#plattformen-und-audio).
- Der Installer bringt beide PortAudio-DLLs von sounddevice (ab 0.5.1) mit, die Standard-DLL und die mit ASIO-Unterstützung. Die App nutzt die Standard-DLL; die ASIO-DLL wird nur geladen, wenn Eltern in den Einstellungen „ASIO zulassen“ einschalten (`asio = true`, wirkt nach einem Neustart).
- Windows fragt beim ersten Aufnehmen eventuell nach dem Mikrofon-Zugriff. Falls die Aufnahme stumm bleibt: Einstellungen → Datenschutz → Mikrofon → „Desktop-Apps den Zugriff auf das Mikrofon erlauben“ einschalten.

Selbst bauen (unter Windows, mit Python 3.12 und [Inno Setup 6](https://jrsoftware.org/isinfo.php)):

```powershell
pip install -c packaging/windows/constraints.txt -r requirements.txt -r packaging/windows/requirements-build.txt
python packaging/windows/make_icon.py build/loopstation.ico
pyinstaller --noconfirm packaging/windows/loopstation.spec
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" /DAppVersion=1.2.0 packaging\windows\loopstation.iss
```

Das Ergebnis liegt in `dist\Loopstation-Setup-1.2.0.exe`. Gebündelt wird mit PyInstaller als Ordner (nicht als Einzeldatei), damit die App schnell startet und nichts nach `%TEMP%` entpacken muss.

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
- **Rubber Band ist optional und wird nicht mitgeliefert** (`stretch_engine = "auto"`): ohne Rubber Band läuft wie bisher der einfache Stretch, die App läuft normal. Wer die bessere Qualität will, lädt Rubber Band nur auf eigenen Wunsch nach: unter Windows den neuen Installer erneut laufen lassen und „Rubber Band (GPL) herunterladen“ ankreuzen (standardmäßig aus; der Installer zeigt vorher Name, Lizenz, Herkunft, Größe und Prüfsumme und lädt erst nach Ihrer Zustimmung), unter Linux `scripts/install-linux.sh` erneut aufrufen und der Frage zustimmen (oder `--rubberband`), aus dem Quellcode `pip install pylibrb`. Auch später geht das jederzeit; der Elternbereich zeigt, ob Rubber Band installiert ist. Rubber Band steht unter der GPL, siehe [Drittanbieter-Lizenzen](#drittanbieter-lizenzen).
- **Neuer Elternbereich** hinter der Kachel „Eltern“ unten rechts (zwei Sekunden halten, Rechenaufgabe), mit sieben Bereichen: Lautstärke & Pegel, Geräte & Audio, Takt & Loop (mit Eltern-Takt und Metronom), Verlauf & Undo, Erweitert (Wellenform, Marker), Sets sichern und öffnen, Export als WAV.
- **„Alle löschen“ ist von der Kinderseite in den Elternbereich gewandert** (Verlauf & Undo, „Alle Pads löschen …“, mit Rückfrage; „Zurück“ holt alles wieder). Kinder können so nicht mehr versehentlich alles leeren.
- **Loops kürzen (neu in 1.1.1):** Erweitert schneidet einen Loop an Anfang und Ende zu (Griffe in der Wellenform, Vorhören, Übernehmen oder Verwerfen); das Original bleibt im Verlauf, Zurück bringt es wieder, und ein Stand ohne diese Version kennt das Kürzen nicht.
- **Marker bleiben, wo Sie sie setzen (1.1.2):** „Zwischen Markern strecken“ meckert nicht mehr, wenn ein Marker auf einem Schlag sitzt, der neben der geschätzten Taktlinie liegt; die 10-%-Grenze gilt nur noch bei einem von Erwachsenen eingestellten Takt. Die Schlag-Erkennung erfindet bei Rascheln, Rauschen und Nachhall keine Schläge mehr, und neue Marker rasten auf Wunsch auf die nächste echte Transiente ein (`snap_markers`, Schalter in Erweitert, standardmäßig aus).
- **Kein Piepen mehr auf der Aufnahme (1.1.3):** Der Start-Ton klingt vollständig aus, bevor die Aufnahme beginnt (sie startet dadurch einen Moment nach dem Druck), und der leise Metronom-Ton schweigt, solange aufgenommen wird; der Start-Ton lässt sich im Elternbereich (Lautstärke & Pegel, „Aufnahmestart-Ton“, `record_start_tone`) abschalten.
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

Aufnahme- und Wiedergabegerät sowie das Audio-System wählen Erwachsene in der Elternansicht im Werkzeug „Geräte“ (`input_device`, `output_device`, `audio_hostapi`; leer heißt Systemstandard). Ein Wechsel greift sofort: die Audio-Streams starten kurz neu, `latency_ms = "auto"` wird für das neue Gerät neu bestimmt. Geräte werden per Name gemerkt; fehlt ein Gerät beim Start, nimmt die App den Systemstandard und sagt es.

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
- **Alle löschen** gibt es nicht auf der Kinderseite, sondern nur in der Elternansicht im Werkzeug „Verlauf“ („Alle Pads löschen …“): leert alle Pads nach einer Ja/Nein-Frage; „Zurück“ holt alles wieder.

Ein zweiter Klick auf den aktiven Modus oder ESC führt zurück zu „Spielen“. Aufnahmen stoppen nach der eingestellten Höchstlänge von selbst.

Tastatur: Strg+Z (Zurück), Strg+Y oder Strg+Umschalt+Z (Wiederholen), ESC (zurück zu „Spielen“). Im Elternbereich lassen sich die Pegel-Regler mit den Pfeiltasten und Bild auf/ab verstellen.

### Im Takt bleiben

Die erste Aufnahme bestimmt die Loop-Länge. Jede weitere Aufnahme wird auf genau diese Länge geschnitten: Ist sie kürzer, wird sie mit Stille aufgefüllt, ist sie länger, wird sie auf zwei, drei, … Loop-Längen aufgefüllt (ein Stopp kurz nach einem Loop-Ende zählt noch zu diesem Loop). So laufen alle Loops gemeinsam und nie auseinander.

- Laufen schon Loops, beginnt eine neue Aufnahme erst am nächsten Loop-Anfang. Bis dahin behält das Pad seine Farbe und sein Symbol, leuchtet langsam und weich himmelblau auf (0,5 Hz, ohne Blinken) und zeigt einen Balken, der sich bis zum Loop-Anfang füllt. Erst dann erscheint der Sekunden-Countdown.
- Ein Loop startet und stoppt per Pad ebenfalls am Loop-Anfang (gleiche Anzeige). Läuft noch kein Loop, startet er sofort. „Alles still“, Löschen und „Zurück“ wirken sofort.
- Die Loop-Länge gilt, solange irgendein Pad belegt ist, auch wenn das erste Pad gelöscht oder neu aufgenommen wird. Werden alle Pads leer, beginnt eine neue Runde: Eine himmelblaue Welle läuft über die Pads, und die nächste Aufnahme bestimmt die neue Loop-Länge. „Zurück“ holt die alte Loop-Länge mit den Aufnahmen wieder; eine frühere Version, die in eine leere Runde zurückgeholt wird, bestimmt die Loop-Länge neu.
- Liegt eine Aufnahme knapp neben ganzen Takten (weniger als 10 % daneben), wird sie weich auf die volle Länge gezogen statt aufgefüllt oder abgeschnitten (`stretch_to_grid`, standardmäßig an). Die Tonhöhe bleibt dabei erhalten; deutlich daneben wird wie oben aufgefüllt oder geschnitten. Aufnahmen über laufenden Loops liegen schon im Takt und werden nie gestreckt: liegen sie höchstens 10 % neben ganzen Takten, werden sie auf die nächstliegende ganze Zahl von Loops geschnitten oder mit Stille aufgefüllt (auch ein etwas zu langes Ende fällt dann weg); deutlich daneben wie oben. So bleibt jeder Schlag samplegenau dort, wo er eingespielt wurde.
- Abschalten mit `loop_sync = false` in `settings.toml`; dann behält jede Aufnahme ihre eigene Länge wie früher.
- Optional (`auto_grid = true`, standardmäßig aus): Die erste Aufnahme einer Sitzung beginnt bei ihrem ersten Schlag (Klatschen, Stampfen); sie wird nur verschoben, nicht gekürzt. Liegen zwei oder mehr Schläge im erlaubten Tempo (`grid_bpm_min`, `grid_bpm_max`), entscheidet der Median ihrer Abstände über den Takt gemäß `time_signature` (`2/4`, `3/4`, `4/4`, `6/8`); danach verfeinern die Schläge, die im Loop landen (der erste Takt ab dem ersten Schlag), Tempo und Einsatz, damit der Loop in sich gleichmäßig ist und ohne Hinken über die Naht läuft. Wird das Kind beim Klatschen etwas langsamer, passt der Takt so zu den Schlägen im Loop statt zum Durchschnitt; die Verfeinerung darf das Tempo aber höchstens um 3 % vom Median wegziehen (ein einzelner verrutschter Klatscher zieht es nicht), sonst bleibt der Median-Takt. Der Loop beginnt am Schlag oder knapp davor, bei scharfen Angriffen probengenau. Liegen keine zwei Schläge im erlaubten Tempo, gilt die Aufnahmelänge, aber nur, wenn sie als Takt taugt (dieselben Tempo-Grenzen); sonst bekommt die Sitzung lieber keinen Takt als einen falschen. Weitere Aufnahmen werden nie verschoben. Im Elternbereich stehen Tempo, Taktart und woher der Takt kommt (Aufnahmelänge, Schläge oder Eltern-Vorgabe).

Wie genau neue Loops auf den gehörten liegen, hängt von der Verzögerung zwischen Lautsprecher und Mikrofon ab (`latency_ms`). Der Standard `"auto"` nimmt den Wert, den der Audiotreiber meldet; klingen neue Loops etwas zu spät oder zu früh, lässt sich der Wert in Millisekunden einstellen. Mit echtem Mikrofon und Lautsprecher ist das bisher nicht nachgemessen, die Tests prüfen den Schnitt mit nachgebauter Soundkarte samplegenau.

## Launchpad

Ein angeschlossenes Novation Launchpad wird automatisch erkannt (auch nachträglich eingesteckt). Die Pads oben links auf dem Launchpad entsprechen den Pads auf dem Bildschirm und leuchten in denselben Farben.

- Launchpad Mini MK3, X, Pro MK3 und MK2: volle Farben.
- Ältere Modelle (Launchpad, S, Mini MK1/MK2): nur rote und grüne LEDs, leere Pads bleiben dunkel.
- Das erste Launchpad Pro wird nicht unterstützt.

- Kurz tippen wirkt beim Loslassen, lange halten schaltet den freien Modus des Pads um (wie auf dem Bildschirm).

Die Launchpad-Anbindung ist bisher nur mit nachgebauten MIDI-Ports getestet, noch nicht an echten Geräten.

## Einstellungen

In `settings.toml` im Startordner (jede Zeile ist dort kommentiert): Rastergröße (`rows`, `cols`), maximale Aufnahmelänge, Abtastrate, Pieptöne (`sound_effects`, `record_start_tone`), Vollbild, Launchpad an/aus, taktgenauer Schnitt an/aus (`loop_sync`), Lautstärke (`volume`) mit Obergrenze (`max_level_db`), Mikrofonpegel (`input_gain_db`), automatischer Aufnahmepegel (`auto_gain`), Pegelanzeige der Aufnahme für Eltern (`peak_meter`), Takt aus der ersten Aufnahme (`auto_grid`, `time_signature`, `grid_bpm_min`, `grid_bpm_max`), Verzögerung zwischen Lautsprecher und Mikrofon (`latency_ms`), weiche Loop-Naht an/aus (`soft_seam`), freie Pads am Takt-Punkt starten (`free_pad_on_grid`), Marker als Cue-Punkte im Export (`export_cue_points`), Marker auf Transienten einrasten (`snap_markers`), Strecken knapp neben dem Takt (`stretch_to_grid`), Aufnahme- und Wiedergabegerät (`input_device`, `output_device`) und Audio-System (`audio_hostapi`, Standard WASAPI unter Windows, ALSA unter Linux) sowie ASIO (`asio`), leiser Metronom-Ton (`metronome_tone`, `metronome_level_db`), Stretch-Engine (`stretch_engine`, siehe [Stretch-Engine](#stretch-engine-rubber-band)), Sperrzeit und Rückkehr der Elternansicht (`parent_unlock_minutes`, `parent_idle_minutes`), Datenordner. Fehlt die Datei, gelten die Standardwerte.

## Elternbereich

Erwachsene erreichen den Elternbereich über die Kachel „Eltern“ unten rechts: zwei Sekunden gedrückt halten, dann eine Rechenaufgabe lösen. Die Aufgabe liegt abgedunkelt über dem Fenster, die Musik läuft weiter, Tipper, Tasten und das Launchpad lösen dabei nichts aus; Esc oder „Abbrechen“ führt zurück. Die Kinderseite bleibt bewusst schlicht: Pads, Modi, Zurück und Wiederholen, Alles still, Lautstärke, ein rotes Zeichen bei zu lauter Aufnahme und der Puls (ein Punkt je Schlag des Takts, der aktuelle leuchtet weich auf). Alles mit Zahlen und Fachbegriffen liegt im Elternbereich.

Nach der richtigen Antwort zeigt dasselbe Fenster die **Elternansicht**: oben der Umschalter Kinder|Eltern, der Takt (Tempo, Taktart, woher er kommt), Zurück, Wieder, Still und die Lautstärke; links die Werkzeuge; in der Mitte dieselben Pads als breite Kacheln mit Länge, kleiner Welle und Zustandssymbol; unten das Detailfeld des gewählten Pads. Die Pads bleiben spielbar, das Launchpad auch: ein Tipp auf das Symbol unten links wirkt wie ein Tipp auf der Kinderseite („Spielen“), ein Tipp auf die übrige Kachel wählt sie nur aus. Tasten: Pfeile wählen, Leertaste spielt, L startet oder stoppt den Loop, R nimmt auf, Entf löscht (Zurück holt es wieder), Enter klappt das Detailfeld auf und zu, M setzt dort einen Marker, F1 führt zur Kinderseite. Zurück zu den Kindern geht es mit einem Tipp auf „Kinder“ oder F1; nach `parent_idle_minutes` Minuten ohne Eingabe am Bildschirm oder an der Tastatur (Standard 10, 0 = nie) kehrt die Ansicht von selbst zurück, schließt dabei eine offene Seitenleiste und verlangt danach wieder die Rechenaufgabe. Wer innerhalb von `parent_unlock_minutes` Minuten (0 bis 15, Standard 0 = immer fragen) nach der Rechenaufgabe wieder das Schloss hält, kommt ohne neue Aufgabe hinein, aber nur, wenn die Eltern in der Aufgabe den Schalter „Sperre … offen lassen“ eingeschaltet haben (er ist standardmäßig aus und nur sichtbar, wenn `parent_unlock_minutes` über 0 liegt).

Die Werkzeuge der Elternansicht öffnen eine **Seitenleiste** rechts neben den Pads, im selben Fenster. Die Pads rücken zusammen und bleiben spielbar, das Launchpad auch; so lässt sich etwa der Pegel prüfen, während das Kind spielt. Ein erneuter Tipp auf das Werkzeug, „Pads“, das Kreuz oben in der Leiste oder Esc schließt sie wieder. Ein Tipp auf den Takt oben öffnet „Takt“:

- **Verlauf:** die Änderungen der Sitzung (neueste oben, Uhrzeit aus dem Protokoll), Zurück und Wiederholen, „nur dieses Pad“ an der jeweils letzten Änderung eines Pads und „Alle Pads löschen …“ mit Rückfrage.
- **Sets** und **Export:** eigene Abschnitte weiter unten.
- **Pegel:** Obergrenze, Limiter, Mikrofon mit Pegelanzeige und Trim, automatischer Aufnahmepegel, weiche Naht und die zuletzt zu lauten Aufnahmen.
- **Geräte:** Mikrofon und Ausgabe getrennt (mit Testton), Audio-System, Verzögerung (automatisch oder von Hand). Siehe [Plattformen und Audio](#plattformen-und-audio).
- **System:** Launchpad, Vollbild, längste Aufnahme, Pieptöne, Stretch-Verfahren, Marker, Sperrzeit und Rückkehr der Elternansicht, Rastergröße, Abtastrate, Datenordner.
- **Takt:** aktueller Takt (Tempo, Taktart, Länge, Quelle), Takt korrigieren (Eltern-BPM), Loop-Verhalten, Metronom, Taktart und Tempo-Fenster.

Unter den Pads liegt das **Detailfeld** des gewählten Pads. Zugeklappt ist es eine Zeile (Nummer, Länge, Zustand); ein Tipp auf die Zeile, den Pfeil rechts, einen Reiter, Enter oder ein Doppeltipp auf eine Kachel klappt es auf, Esc oder der Pfeil klappt es wieder zu. Aufgeklappt nimmt es knapp die halbe Fensterhöhe, die Kacheln werden flacher und bleiben spielbar. Eine Seitenleiste und das aufgeklappte Detailfeld wechseln sich ab. Wählen ändert, was das Detailfeld zeigt; Starten eines Pads (Symbol, Tasten, Launchpad) ändert es nicht. Die Reiter:

- **Loop:** Wellenform mit Kürz-Griffen, Markern und Abspielkopf; darunter die Kürz-Bilanz und eine Zeile Anhören, Marker, Strecken, Export, Takt rasten, rechts Verwerfen und Übernehmen (siehe [Wellenform, Marker und Kürzen](#wellenform-marker-und-kürzen)). Ein gesperrter Knopf sagt, warum.
- **Pad:** freier Modus, Start am Takt (die Einstellung `free_pad_on_grid`, gilt für alle freien Pads), die Takes dieses Pads zum Anhören und Zurückholen (ein Schritt auf dem Zurück-Stapel) und der Pegel der Aufnahme mit Zielzone und „zu laut“. Name und Lautstärke je Pad sind ausgegraut: sie kommen mit dem neuen Kern.
- **Aufnahme:** Mikrofonpegel (live während einer Aufnahme), längste Aufnahme und Aufnahmestart-Ton; das sind dieselben Einstellungen wie unter „System“, gesichert auf demselben Weg.
- **Effekte (später):** ausgegraut.

Der Verlauf eines Pads (alle früheren Aufnahmen zum Anhören und Zurückholen) ist auch für Kinder da: Modus „Verlauf“, dann Pad antippen.

Der Elternbereich schreibt die `settings.toml` mit allen Kommentaren (siehe [Einstellungen](#einstellungen)). Es gibt keinen Knopf „Speichern“: jede Änderung wirkt sofort und wird sofort gesichert, Schalter und Auswahllisten bei jedem Tipp, Zahlen beim Verlassen des Feldes oder kurz nach der letzten Änderung, Text beim Verlassen oder mit Enter. Ein ungültiger Wert wird nicht gesichert; die Leiste sagt oben in Rot, warum, bis er korrigiert ist. Eine beschädigte `settings.toml` wird nie überschrieben. Nur Rastergröße, Abtastrate, ASIO und Datenordner wirken erst nach einem Neustart; das steht direkt am Feld. Die Pegelanzeige (`peak_meter`) ist standardmäßig an.

## Wellenform, Marker und Kürzen

In der Elternansicht im Detailfeld (Reiter „Loop“) und in der Seitenleiste „Takt“. Die Kinderseite bekommt davon nichts außer dem Puls.

- **Wellenform und Marker:** ein Pad wählen (das Detailfeld folgt der Wahl) und den Loop mit den Schlag-Linien des Takts ansehen (1.1, 1.2 … für Takt und Schlag). Es gibt keine Zeitachse und keine Spuren. In die Wellenform tippen und „Marker“ (oder M) legt einen Marker (bis zu 16, mit Buchstaben A bis P); ein Tipp auf einen Marker und „Marker löschen“ nimmt ihn wieder weg, „Anhören“ spielt den Loop einmal mit weißem Abspielkopf (ein zweiter Tipp hält an), „Export“ sichert ihn als WAV (wie der Einzel-Export). Mit „Marker auf Schläge einrasten“ (Schalter unter „System“, standardmäßig aus) springt ein neuer Marker auf den nächsten echten Schlag in der Nähe (etwa 60 ms), ohne Schlag bleibt er, wo er ist. „Strecken“ schiebt jeden Marker auf seinen Schlag (ab einem Marker); die Marker sind maßgeblich, der Takt wird deswegen nicht angemeckert, nur bei einem von Erwachsenen eingestellten Takt (Eltern-BPM) gilt die Grenze von 10 %; der Loop davor liegt im Verlauf, Zurück bringt ihn wieder. Wird ein schon gestreckter Loop mit weiteren Markern noch einmal gestreckt, streckt die Loopstation die ursprüngliche Aufnahme in einem Durchgang auf dieselben Schläge, damit der Klang nicht mit jedem Durchgang weiter verschmiert (geht das nicht, etwa nach dem Kürzen, bei anderem Takt, bei einem Eltern-Takt mehr als 10 % Abweichung zum Original oder wenn der Eintrag der Streckung im Protokoll schon archiviert ist, wird wie bisher der Loop selbst gestreckt). Es zählen dabei die Marker, die auf dem gestreckten Loop stehen: einer, der dort gelöscht wurde, gilt beim nächsten Strecken nicht mehr. Marker gehören zur Aufnahme (Sample-Datei), nicht zum Pad, und stehen im Ereignis-Protokoll als `marker_set`; sie liegen nicht auf dem Zurück-Stapel des Kindes.
- **Loop kürzen:** die Griffe „Anfang“ und „Ende“ in der Wellenform ziehen, die Zeile unter der Welle zeigt die neue Länge in Sekunden und Takten. „Anhören“ spielt dann die neue Fassung einmal, „Übernehmen“ legt sie als neue Aufnahme auf das Pad, „Verwerfen“ setzt die Griffe zurück. Standardmäßig rastet die Länge auf ganze Takte („Takt rasten“, Schalter an), so bleiben alle Loops im Raster; ohne Schalter gilt genau die gezogene Länge, abgespielt wird sie mit Stille aufgefüllt auf ganze Takte, die Loop-Periode der anderen Pads ändert sich nie. Gibt der Loop den Takt vor (er hat ihn gesetzt) und würde er danach nicht mehr in den Takt passen, fragt das Detailfeld: „Raster neu setzen“ (die gekürzte Länge ist der neue Takt, die anderen Loops passen sich an, sofern das Tempo erlaubt ist) oder „Auf Takt rasten“. Die Mindestlänge ist das Größere aus 0,30 s und zwei Nahtfades plus 50 ms. Es entsteht eine neue Sample-Datei, die Aufnahme davor bleibt unverändert im Verlauf; im Protokoll steht es als `loop_trim` (mit Start, Ende und neuer Länge), Zurück und Wiederholen (auch nur für dieses Pad) nehmen es zurück und bringen es wieder, auch einen neu gesetzten Takt. Marker wandern mit dem Schnitt. Export und Sets nutzen die gekürzte Fassung.
- **Takt korrigieren (Eltern-BPM, in der Leiste „Takt“):** Tempo (innerhalb von `grid_bpm_min` bis `grid_bpm_max`) und Taktart vorgeben. Das hat Vorrang vor dem gemessenen Takt: Aufnahmen stiften danach kein neues Raster mehr (ein Onset richtet die erste Aufnahme höchstens aus). Im Ereignis-Protokoll steht es als `master_set` mit `source = parent_bpm`. Läuft schon Ton, werden die Loops ohne Änderung der Dateien neu an das Raster angepasst und laufende Loops beginnen auf den neuen Takten von vorn. „Gemessenen Takt“ gibt das Raster wieder an die Aufnahmen zurück. Ohne Ton in der Sitzung gilt der Wert ab der nächsten ersten Aufnahme. Die erste Aufnahme auf dem Eltern-Takt wird an das Raster angepasst (aufgefüllt oder gekürzt), aber nicht gestreckt; `stretch_to_grid` gilt erst für die folgenden Aufnahmen.
- **Metronom (in der Leiste „Takt“):** eine Reihe von Schlägen am echten Takt (erster Schlag eckig, aktueller gefüllt). Ohne laufende Loops zählt sie nach der Uhr weiter. Optional ein leiser Ton auf jedem Schlag (`metronome_tone`, standardmäßig aus; `metronome_level_db`, standardmäßig -20 dB): er läuft durch Lautstärke und Obergrenze und wird vorgezogen mit Stille davor an die Audio-Ausgabe gegeben, damit er unabhängig vom Bildschirmtakt auf dem Schlag liegt. Mit Lautsprecher hört das Mikrofon ihn bei einer Aufnahme mit.

## Export

Nur in der Elternansicht im Werkzeug „Export“, lokal, ohne Upload. Das Format ist WAV, 24 Bit, mono, in der Abtastrate der Sitzung; die Dateien landen in `Dokumente/Loopstation/Export`.

- **Summe:** alles, was gerade loopt (oder alle belegten Pads als Loop), über N Takte (4, 8, 16, 32 oder eine eigene Zahl). Die Länge ist genau N × Taktlänge in ganzen Frames, jeder Loop startet vorn und wiederholt sich wie live. Es gilt dieselbe Pegelkette wie live: Lautstärke, dann der Limiter mit der Eltern-Obergrenze auf die Summe. Optional ein kurzer Ausklang (15 ms) und Einmal-Pads am Anfang. Ohne Takt in der Sitzung (`loop_sync` aus) wird nicht geraten: die Seite erklärt das, und nur auf ausdrückliche Wahl gilt „N × längstes Sample“ als Notbehelf, vermerkt im Kommentar der Datei.
- **Einzelner Loop:** das aufgenommene Sample unverändert, ohne Lautstärke und Limiter. Die Marker des Loops werden als Cue-Punkte in die WAV-Datei geschrieben (`export_cue_points`, standardmäßig an, auch im Export-Dialog schaltbar); klappt das nicht, liegt eine Begleitdatei `.markers.json` daneben. Das Sichern scheitert daran nie.

## Sets sichern und öffnen

Erwachsene frieren die laufende Sitzung als Set ein und öffnen gespeicherte Sets wieder: Elternansicht, Werkzeug „Sets“ („Als Set sichern“). Ein Set ist eine Kopie der Sitzung (Ereignis-Protokoll samt Zurück-Schritten, alle Aufnahmen als WAV, Kopie der `settings.toml`) als `.loopset`-Datei (ZIP) oder als Ordner, standardmäßig unter `Dokumente/Loopstation/Sets`. Das Kind spielt nach dem Sichern einfach weiter.

- Gesichert wird erst in eine temporäre Datei, dann umbenannt: ein Abbruch überschreibt kein altes Set halb. Läuft eine Aufnahme, wird das Sichern verweigert.
- Beim Öffnen wird das Set vollständig geprüft, bevor etwas ersetzt wird: zu neue Formatversion, falsche Padzahl oder Abtastrate, beschädigte Dateien. Ist die aktuelle Sitzung nicht gesichert, fragt die Seite zuerst („Erst sichern, dann öffnen“, „Ohne sichern“). Die Zurück-Schritte des Sets bleiben, „Wiederholen“ startet leer.
- Die eigenen Einstellungen des Rechners bleiben maßgeblich. Fehlt ein Gerät aus dem Set, wird der Systemstandard benutzt und die Sets-Seite sagt es.
- Das Öffnen ersetzt `data/` und `samples/` zwischen zwei Sitzungen im selben Prozess (die Loopstation baut Fenster, Protokoll und Audio neu auf). Wird das mittendrin abgebrochen, schließt der nächste Start den Tausch ab (`loopstation/session.py`).

## Stretch-Engine (Rubber Band)

Eine Aufnahme knapp neben einem ganzen Takt (unter 10 %) wird beim Stopp auf genau diese Länge gezogen, die Tonhöhe bleibt (`stretch_to_grid`). Aufnahmen über laufenden Loops liegen schon im Takt und werden nur geschnitten oder aufgefüllt, nie gestreckt. Dafür gibt es zwei Engines hinter derselben Schnittstelle (`loopstation/audio/stretch.py`):

- **Rubber Band** über das Python-Paket `pylibrb` (Wheel mit eingebauter Bibliothek): sauberer, vor allem bei Stimmen. Es ist **nicht Teil der Loopstation und nicht im Windows-Installer enthalten**; es wird nur auf Wunsch nachgeladen (siehe unten). Die Loopstation prüft beim Start, ob es sich laden und rechnen lässt, und schreibt das Ergebnis ins Protokoll (`stretch engine: ...`). Die App selbst greift dafür nie ins Netz.
- **Einfacher Stretch** (WSOLA, nur numpy): immer eingebaut. Klatscher und Schläge setzt er an ihre gestreckte Stelle, damit der Takt im Loop stimmt. Er läuft, wenn Rubber Band fehlt, nicht lädt oder bei einem einzelnen Stretch einen Fehler meldet. Eine Aufnahme geht deshalb nie verloren.

Die Einstellung `stretch_engine` (in der Elternansicht unter „System“, „Stretch-Verfahren“) wählt: `auto` (Standard) nimmt Rubber Band, wenn es gefunden wird, sonst still den einfachen Stretch (ohne Hinweis); `rubberband` will Rubber Band: fehlt es, meldet der Elternbereich deutlich „Rubber Band nicht installiert, einfache Engine aktiv“ mit dem Weg zum Nachinstallieren, und die App läuft mit dem einfachen Stretch weiter; `simple` nimmt immer den einfachen Stretch. Der Elternbereich zeigt den Status: installiert (mit Version) oder nicht installiert.

So kommt Rubber Band auf den Rechner (immer nur mit Zustimmung):

- **Windows:** im Installer die Aufgabe „Rubber Band (GPL) herunterladen“ ankreuzen (standardmäßig aus). Der Installer lädt `pylibrb` von PyPI (siehe `packaging/windows/rubberband.inc`: URL, Version, SHA-256), prüft die Prüfsumme und entpackt es nach `<Programmordner>\rubberband`. Schlägt Download oder Prüfsumme fehl, wird die Loopstation trotzdem installiert und die App meldet „Rubber Band nicht installiert, einfache Engine aktiv“. Bestandsnutzer lassen den Installer erneut laufen und setzen den Haken; Deinstallieren entfernt den Ordner wieder.
- **Linux:** `scripts/install-linux.sh` fragt danach (Standard: nein). `--rubberband` stimmt zu, `--no-rubberband` fragt nicht; ohne Terminal und ohne `--rubberband` wird nichts geladen, auch nicht mit `--yes`. Es wird nur ein fertiges Wheel installiert (x86_64); sonst bleibt es beim einfachen Stretch.
- **Aus dem Quellcode:** `pip install pylibrb` in der Umgebung der Loopstation.

## Drittanbieter-Lizenzen

Dieses Projekt selbst steht unter Apache-2.0 (siehe [LICENSE](LICENSE)). Die Programme und Bibliotheken, die es benutzt, haben ihre eigenen Lizenzen:

| Bestandteil | Lizenz | Hinweis |
|---|---|---|
| Rubber Band (über `pylibrb`) | GPL (Rubber Band: GPL-2.0 oder neuer, `pylibrb`: GPL-2.0), kommerzielle Lizenz beim Hersteller möglich | wird nicht mitgeliefert, nur auf Wunsch des Nutzers geladen, siehe unten |
| PortAudio (über `sounddevice`) | MIT-ähnlich | wird mit dem Windows-Installer ausgeliefert |
| Qt / PySide6 | LGPL-3.0 (Qt for Python), Qt zusätzlich auch GPL und kommerziell | wird mit dem Windows-Installer ausgeliefert; die LGPL verlangt u. a. den Lizenztext und die Möglichkeit, die Bibliothek auszutauschen |

Ehrlicher Hinweis zu Rubber Band: Rubber Band steht unter der GPL. Die Loopstation liefert es nicht aus: weder der Windows-Installer noch das Quellcode-Archiv enthalten es, und die App lädt nichts nach. Es kommt nur auf ausdrücklichen Wunsch des Nutzers auf dessen Rechner (Installer-Haken, Zustimmung in `install-linux.sh` oder eigenes `pip install pylibrb`). Die GPL des geladenen Pakets und ihre Pflichten bleiben bei dem, der es lädt und weitergibt. Wer einen Rechner oder ein Abbild mit installiertem Rubber Band weitergibt, löst die GPL-Pflichten aus (vor allem das Angebot des Quellcodes), solange keine kommerzielle Lizenz vorliegt. Rechtlich bewertet das hier niemand; vor einer Weitergabe also Lizenzen prüfen oder die kommerzielle Lizenz klären.

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

## License

Copyright 2026 thelad-dev. Licensed under the Apache License 2.0, see [LICENSE](LICENSE).
