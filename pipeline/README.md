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

5. **Zielordner auf dem NAS festlegen** (einmalig). Den Pfad zur FRITZ!Box-Freigabe findest du im Windows-Explorer unter „Netzwerk“ → FRITZ-NAS. Beispiel:

   ```
   playalong ziel "\\fritz.box\FRITZ.NAS\USB-Stick\Play-along"
   ```

   Der Ordner muss schon existieren.

**Später wieder öffnen:** Eingabeaufforderung öffnen, dann

```
cd C:\playalong\playalong-main\pipeline
.venv\Scripts\activate
```

Unter Linux (Mini-PC) entsprechend: `python3 -m venv .venv`, `source .venv/bin/activate`, `pip install -e .`

## 2. Ein Lied verarbeiten

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

## 3. Den Abgleich prüfen (Prüfbericht)

Den Prüfbericht (`Prüfberichte\<Titel>.html`) per Doppelklick im Browser öffnen:

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
