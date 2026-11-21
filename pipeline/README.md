# Play-along: Verarbeitung auf dem Server

Das Programm `playalong` baut aus einer Partitur (MusicXML) und optional einer Aufnahme (MP3) ein **Liedpaket** (`.playalong`) und legt es auf dem NAS ab. Ist eine Aufnahme dabei, wird sie automatisch **mit den Noten abgeglichen**: Für jeden Takt wird die Startzeit in der Aufnahme ermittelt (`sync.json`). Läuft unter Windows und Linux, nur auf dem Prozessor (keine Grafikkarte nötig), ohne Internet und ohne KI.

Im Player lässt sich bei Liedern mit Aufnahme oben zwischen **„Noten“** (Begleitung aus der Partitur) und **„Original“** (die Aufnahme, mit mitlaufendem Cursor) umschalten.

## 1. Einmalig: Installation auf dem Windows-Laptop

1. **Python installieren:** <https://www.python.org/downloads/> → „Download Python 3.12“ (oder neuer). Im Installer unten das Häkchen **„Add python.exe to PATH“** setzen, dann „Install Now“.
2. **Code holen:** Auf <https://github.com/tihohub/playalong> → grüner Knopf **„Code“** → **„Download ZIP“**. Die ZIP-Datei z. B. nach `C:\playalong` entpacken.
3. **Eingabeaufforderung öffnen:** Windows-Taste, `cmd` eintippen, Enter.
4. In den Ordner wechseln und das Programm installieren (dauert ein paar Minuten, lädt einmalig ca. 300 MB):

   ```
   cd C:\playalong\playalong-main\pipeline
   python -m venv .venv
   .venv\Scripts\activate
   pip install -e .
   ```

5. **Desktop-Verknüpfung anlegen** (im selben Fenster):

   ```
   playalong verknuepfung
   ```

   Auf dem Desktop erscheint **„Play-along Werkstatt“**. Das Eingabefenster wird danach nicht mehr gebraucht.

Unter Linux (Mini-PC) entsprechend: `python3 -m venv .venv`, `source .venv/bin/activate`, `pip install -e .`, `playalong verknuepfung` (legt einen Eintrag im Anwendungsmenü an).

### Auf eine neue Version aktualisieren

**In der Werkstatt:** Gibt es auf GitHub eine neue Version, erscheint oben die Karte **„Neue Version verfügbar“**. Ein Klick auf **„Jetzt aktualisieren“** lädt sie herunter, spielt sie ein (bei Bedarf samt neuer Bibliotheken) und startet die Werkstatt neu. Zielordner, Einstellungen und Liedpakete bleiben erhalten. Beim allerersten Mal heißt die Karte „Aktualisierung einrichten“: einmal klicken, danach werden neue Versionen automatisch angezeigt.

Die Werkstatt fragt dafür nur bei GitHub nach, und nur solange sie geöffnet ist. Ohne Internet funktioniert alles andere wie gewohnt.

**Von Hand** (falls die Werkstatt einmal nicht startet):

1. Auf GitHub wieder **„Code“ → „Download ZIP“** und nach `C:\playalong` entpacken. Vorhandene Dateien ersetzen lassen, die Installation in `.venv` bleibt erhalten.
2. Im `cmd`-Fenster:

   ```
   cd C:\playalong\playalong-main\pipeline
   .venv\Scripts\activate
   pip install -e .
   ```

## 2. Ein Lied verarbeiten mit der Werkstatt (empfohlen)

1. Doppelklick auf **„Play-along Werkstatt“** auf dem Desktop. Der Browser öffnet sich mit der Werkstatt.
2. **Zielordner** festlegen (nur beim ersten Mal): „Ordner wählen …“ und z. B. `G:\Meine Ablage\Apps\Playalong` oder die NAS-Freigabe auswählen. Der Ordnerdialog öffnet sich manchmal **hinter** dem Browserfenster.
3. **Partitur** (`.mxl`/`.musicxml`) ins Feld 1 ziehen oder anklicken und auswählen. Titel, Komponist und die erkannte Klarinettenstimme werden angezeigt und lassen sich ändern.
4. Optional die **Aufnahme** (MP3) ins Feld 2 ziehen.
5. **„Liedpaket bauen“** klicken. Nach wenigen Sekunden erscheint „Fertig“ und der Knopf **„Prüfbericht öffnen“**.
6. Für das nächste Lied **„Nächstes Lied“** klicken.

Unten listet die Werkstatt alle Liedpakete im Zielordner, jeweils mit Link zum Prüfbericht. **Beenden:** oben rechts auf „Beenden“ klicken. Die Werkstatt läuft nur auf diesem Rechner und ist aus dem Netz nicht erreichbar.

### Nur eine Aufnahme, keine Noten? Rohentwurf

In der Werkstatt oben „**Nur Aufnahme → Rohentwurf**“ wählen, die MP3 hineinziehen und Titel, Taktart sowie die beiden Hilfen prüfen:

- **Melodie-Instrument:** *gezupft/angeschlagen* (Banjo, Mandoline, Gitarre, Klavier: Töne beginnen an den hörbaren Anschlägen) oder *gehalten* (Bläser, Streicher, Gesang). „Automatisch“ erkennt das am Abklingen der Töne.
- **Melodie liegt:** automatisch (meist über der Begleitung), eher hoch oder eher tief.

Dann „**Rohentwurf erstellen**“ klicken. Ergebnis:

- `<Titel> (Rohentwurf).playalong`: sofort im Player nutzbar (Original-Modus mit der Aufnahme)
- `Rohentwürfe\<Titel> (Rohentwurf).musicxml`: zum **Nachbearbeiten in MuseScore**; danach als normale Partitur wieder durch die Werkstatt schicken

**Verfahren:**

- **schnell (ohne KI):** in Sekunden fertig. Gut, wenn die Melodie klar vorne liegt (Soloinstrument mit Klavier o. Ä.).
- **genauer mit lokaler KI:** trennt die Aufnahme zuerst mit **Demucs** in Spuren (Gesang, Gitarre, Klavier, Bass, Schlagzeug, Rest) und erkennt dann mit **Basic Pitch** die Noten der Melodiespur. Hilft vor allem bei lautem Bass, Bands und Synthesizer-Musik. Die Melodiespur wird automatisch gewählt oder unter „Melodie in Spur“ festgelegt. Dauert einige Minuten pro Lied.
  - **Einmalige Einrichtung:** Beim ersten Mal erscheint der Knopf **„KI-Erweiterung einrichten“**. Die Werkstatt lädt dann ein eigenes Python, PyTorch (CPU), Demucs, Basic Pitch und die Modelle herunter (ca. 1,6 GB, Ordner `C:\Users\<Name>\.playalong\ki`). Danach läuft alles ohne Internet, ohne Konto und ohne Kosten. Löschen: diesen Ordner entfernen.

**Tempo:** Die Werkstatt zeigt nach dem Entwurf das erkannte Tempo an. Bei schnellen Stücken erkennt sie manchmal nur das halbe Tempo (bei sehr vielen schnellen Noten auch das doppelte). Dann sind die Takte zu lang bzw. zu kurz, was man im Prüfbericht am Taktklick hört. Mit **„Doppelt so schnell neu erstellen“** bzw. **„Halb so schnell neu erstellen“** rechnet die Werkstatt neu. Beim KI-Verfahren dauert das nur Sekunden, weil Spurtrennung und Notenerkennung je Aufnahme zwischengespeichert werden (die letzten 5 Aufnahmen, unter `.playalong\ki\zwischenspeicher`).

Die Werkstatt zeigt an, wie **sicher** die Erkennung war (gut / mittel / unsicher). Bei „unsicher“ lohnt es sich, die beiden Hilfen anders einzustellen.

Das ist ausdrücklich nur eine **Starthilfe**. Laute Bässe und Liegetöne werden herausgerechnet, und die Melodielinie wird geglättet: Oktavfehler und einzelne Ausreißer, die zu keinem Nachbarton passen, werden korrigiert, echte große Sprünge bleiben erhalten. Trotzdem müssen Rhythmus, Tonart und einzelne Töne fast immer korrigiert werden. Gemessen an synthetischen Aufnahmen (Anteil richtiger Töne pro 16tel): Solo-Etüde 82 %, Klarinette mit Klavier 85 %, gezupfte Melodie über lautem Bass 61 % (82 % wenn man Oktavfehler mitzählt). Echte Aufnahmen, vor allem Orchester und Synthesizer, sind deutlich schwieriger. Kommandozeile: `playalong entwurf aufnahme.mp3 --titel "…" --taktart 4 --instrument gezupft --lage auto`, mit KI: `playalong ki-einrichten` (einmalig), dann `playalong entwurf aufnahme.mp3 --verfahren ki --spur auto`; Tempo korrigieren mit `--tempo-faktor 2` bzw. `0.5`.

## 3. Ein Lied verarbeiten mit der Kommandozeile (Alternative)

Eingabeaufforderung öffnen, dann:

```
cd C:\playalong\playalong-main\pipeline
.venv\Scripts\activate
```

Zielordner einmalig festlegen (der Ordner muss schon existieren):

```
playalong ziel "G:\Meine Ablage\Apps\Playalong"
```

Am einfachsten liegen Partitur und Aufnahme in einem Arbeitsordner, z. B. `C:\Noten`.

**Nur Noten** (Begleitung kommt aus der Partitur):

```
playalong build "C:\Noten\Zelda.mxl"
```

**Noten + Aufnahme** (mit automatischem Abgleich):

```
playalong build "C:\Noten\Zelda.mxl" "C:\Noten\Zelda.mp3"
```

Das dauert pro Lied meist nur Sekunden. Danach liegen auf dem NAS:

- `Zelda.playalong`: das Liedpaket, das Noel auf dem iPad über „Lied importieren“ öffnet
- `Prüfberichte\Zelda.html`: der Prüfbericht (siehe unten)

**Nützliche Zusätze:**

| Zusatz | Wirkung |
|---|---|
| `--titel "Der Titel"` | Titel in der Bibliothek (sonst aus der Partitur) |
| `--komponist "Name"` | Komponist (sonst aus der Partitur) |
| `--stimme P3` | eigene Stimme festlegen, falls die Klarinette nicht automatisch erkannt wird |
| `--notiert klingend` | Klarinettenstimme ist klingend notiert → wird nach B transponiert (`in-b` = schon in B) |
| `--ziel "Ordner"` | anderer Zielordner nur für dieses Lied |
| `--ohne-sync` | Aufnahme ohne Abgleich einpacken |

**Partitur ansehen** (Titel, Takte, Dauer, Stimmen mit ihren IDs für `--stimme`):

```
playalong info "C:\Noten\Zelda.mxl"
```

## 4. Den Abgleich prüfen (Prüfbericht)

Den Prüfbericht in der Werkstatt mit „Prüfbericht öffnen“ oder per Doppelklick auf `Prüfberichte\<Titel>.html` im Browser öffnen:

- **Abspielen:** An jedem Taktanfang ertönt ein kurzer Klick. Fällt der Klick auf den Taktanfang der Musik, stimmt der Abgleich.
- **Tempokurve:** Blau ist das Tempo laut Abgleich, grau das notierte. Ritardandi und freie Stellen sieht man als Bögen. Plötzliche, einzelne Zacken deuten auf eine Fehlstelle hin.
- **Orange Takte** sind auffällig und sollten angehört werden. Ein Klick auf einen Takt spielt ab dort.

Wenn eine Stelle deutlich daneben liegt: Bescheid geben. Häufigste Ursache ist, dass Aufnahme und Partitur nicht übereinstimmen (andere Fassung, gekürzte Wiederholung, Einleitung fehlt).

## Was Aufnahme und Partitur gemeinsam haben müssen

- **Dieselbe Fassung:** gleiche Wiederholungen, gleiche Länge. Wird in der Aufnahme eine Wiederholung ausgelassen, muss sie auch in der Partitur fehlen.
- **Dieselbe Tonart** (bei Transposition der Aufnahme passt der Abgleich nicht).
- Stille am Anfang/Ende, freie Tempi, ritardandi und Fermaten sind kein Problem.

## Genauigkeit

Getestet mit einer Orchesterpartitur (27 Stimmen) und der zugehörigen MuseScore-Aufnahme, zusätzlich mit einer künstlich verzerrten Fassung (Abschnitte 15 % schneller/langsamer, Generalpause, 1 s Vorlauf):

| | Median | 95 % der Takte | schlechtester Takt |
|---|---|---|---|
| Original | 23 ms | 46 ms | 69 ms |
| verzerrt | 40 ms | 94 ms | 138 ms |

Echte Konzertaufnahmen (andere Klangfarben, Hall, rubato) sind schwieriger. Dort zuerst den Prüfbericht ansehen.

## Für Entwickler

```
python -m unittest discover -s tests -v                  # Tests
python testdata/make_demo_scores.py ../player/public/demo  # Demo-Partituren neu erzeugen
python testdata/make_warped_audio.py in.mp3 out.mp3      # verzerrte Testaufnahme (benötigt ffmpeg)
playalong sync partitur.mxl aufnahme.mp3 --bericht bericht.html   # nur abgleichen
```

- `playalong/score.py`: MusicXML → Zeitleiste. **Muss zu `player/src/musicxml/timeline.ts` passen** (gleiche Regeln für Wiederholungen, Volten, D.C./D.S., Tempi), sonst stimmen die Taktindizes in `sync.json` nicht.
- `playalong/align.py`: Abgleich (Chroma + Einsatz-Chroma + Rhythmus, zweistufiges DTW mit numba)
- `playalong/package.py`, `playalong/report.py`, `playalong/cli.py`: Paket, Prüfbericht, Kommandozeile
- `playalong/gui.py` + `playalong/web/werkstatt.html`: Werkstatt (lokaler Webserver nur auf 127.0.0.1, Standardbibliothek)
- `playalong/update.py`: Selbst-Aktualisierung aus GitHub (Commit-Stand von `pipeline/` auf `main`, Datei `.installierte-version.json`)
- `playalong/ki.py` + `playalong/ki_worker.py`: lokale KI (Einrichtung über uv mit eigenem Python 3.12 unter `~/.playalong/ki`, Aufruf von Demucs + Basic Pitch in einem eigenen Prozess)
- `playalong/transcribe.py`: Rohentwurf (Beat-Tracking, Liegetöne dämpfen, harmonische Summierung mit Lage-Vorliebe, Modus „gezupft“ über Anschläge bzw. „gehalten“ pro 16tel, Glättung der Linie per Viterbi über die Oktavwahl, Tonart nach Krumhansl, Sicherheitswert)
