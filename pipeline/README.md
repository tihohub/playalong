# Verarbeitungs-Pipeline (Version 2)

Hier entsteht das Python-Werkzeug für den Server (Windows-Laptop bzw. Linux-Mini-PC, nur CPU):

- Audio-Score-Alignment: Original-MP3 ↔ MusicXML → `sync.json`
- Paket-Builder: erzeugt `.playalong`-Dateien im NAS-Ordner

Bis dahin: Lieder als `.musicxml`/`.mxl` direkt importieren (siehe Haupt-README).

## Bereits vorhanden

- `testdata/make_demo_scores.py`: erzeugt die gemeinfreien Demo-Stücke des Players:

  ```bash
  python3 pipeline/testdata/make_demo_scores.py player/public/demo
  ```
