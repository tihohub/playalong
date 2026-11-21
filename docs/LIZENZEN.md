# Lizenzen

## Instrumentenklänge (in `player/public/samples/`)

- **Klavier:** *Salamander Grand Piano* von Alexander Holm, Lizenz **CC BY 3.0**
  (<https://creativecommons.org/licenses/by/3.0/>). Verwendet wird die MP3-Auswahl (jede kleine Terz), wie sie das Tone.js-Projekt bereitstellt.
- **Klarinette:** aus dem SoundFont *FluidR3_GM* von Frank Wen, Lizenz **MIT**, als MP3-Einzeltöne aus dem Projekt *midi-js-soundfonts* von Benjamin Gleitzman.

## Bibliotheken

- [OpenSheetMusicDisplay](https://github.com/opensheetmusicdisplay/opensheetmusicdisplay): BSD-3-Clause
- [VexFlow](https://github.com/0xfe/vexflow) (in OSMD enthalten): MIT
- [fflate](https://github.com/101arrowz/fflate): MIT
- [Vite](https://vitejs.dev/), [TypeScript](https://www.typescriptlang.org/): MIT / Apache-2.0 (nur zum Bauen)

## Demo-Stücke

`player/public/demo/*.musicxml` wurden für dieses Projekt geschrieben (`pipeline/testdata/make_demo_scores.py`) und sind gemeinfrei (CC0).

## Lokale KI für den Rohentwurf (optional, nicht im Repo)

Wird erst bei „KI-Erweiterung einrichten“ heruntergeladen und nur lokal genutzt:

- [Demucs](https://github.com/facebookresearch/demucs) (Spurtrennung, Modell `htdemucs_6s`): MIT
- [Basic Pitch](https://github.com/spotify/basic-pitch) (Notenerkennung): Apache-2.0
- [PyTorch](https://pytorch.org/): BSD-3-Clause; [ONNX Runtime](https://onnxruntime.ai/): MIT
- [uv](https://github.com/astral-sh/uv) (lädt Python und Pakete): MIT / Apache-2.0
