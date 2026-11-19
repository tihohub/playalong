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

## sync.json (Version 2, Entwurf)

```json
{
  "version": 1,
  "audio": "original.mp3",
  "measures": [
    { "index": 0, "time": 0.42 },
    { "index": 1, "time": 2.71 }
  ]
}
```

`index` ist der Index des **gespielten** Takts (nach Auflösen der Wiederholungen, beginnend bei 0), `time` der Startzeitpunkt in Sekunden in der Aufnahme. Das Format wird mit Version 2 festgelegt.
