# Liedpaket-Format `.playalong`

Ein Liedpaket ist eine normale **ZIP-Datei** mit der Endung `.playalong`. Der Player akzeptiert außerdem einzelne `.musicxml`-, `.xml`- und `.mxl`-Dateien.

```
mein-lied.playalong
├── manifest.json      (Pflicht)
├── score.musicxml     (Pflicht; .mxl ist ebenfalls erlaubt)
├── original.mp3       (optional, Version 2)
└── sync.json          (optional, Version 2)
```

## manifest.json

```json
{
  "format": "playalong",
  "version": 1,
  "title": "Titel des Stücks",
  "composer": "Komponist",
  "score": "score.musicxml",
  "audio": "original.mp3",
  "sync": "sync.json",
  "soloPart": "P1",
  "notation": "auto"
}
```

| Feld | Bedeutung |
|---|---|
| `title`, `composer` | Anzeige in der Bibliothek. Fehlen sie, werden die Angaben aus der MusicXML verwendet. |
| `score` | Dateiname der Partitur im Paket |
| `audio` | (optional) Original-Aufnahme |
| `sync` | (optional) Takt→Zeit-Zuordnung zur Aufnahme |
| `soloPart` | (optional) `id` der eigenen Stimme in der MusicXML (`<score-part id="…">`). Ohne Angabe wird die Klarinette automatisch erkannt. |
| `notation` | (optional) `auto` (Standard), `transposed` (Stimme ist in B notiert) oder `concert` (Stimme ist klingend notiert und wird nach B transponiert) |

## sync.json

Wird von `playalong build` bzw. `playalong sync` erzeugt (siehe `pipeline/README.md`).

```json
{
  "version": 1,
  "audio": "original.mp3",
  "duration": 274.364,
  "end": 273.282,
  "measures": [
    { "index": 0, "label": "1", "time": 0.07 },
    { "index": 1, "label": "2", "time": 3.07 }
  ]
}
```

| Feld | Bedeutung |
|---|---|
| `measures[].index` | Index des **gespielten** Takts, beginnend bei 0, nach Auflösen der Wiederholungen, Volten und D.C./D.S. genau wie im Player (`player/src/musicxml/timeline.ts`) |
| `measures[].label` | Taktnummer laut Partitur (nur zur Lesbarkeit) |
| `measures[].time` | Startzeit des Takts in der Aufnahme, in Sekunden |
| `end` | Zeitpunkt, an dem der letzte Takt endet |
| `duration` | Gesamtlänge der Aufnahme in Sekunden |
