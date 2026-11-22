"""KI-Arbeitsprozess für den Rohentwurf. Läuft in der separaten KI-Umgebung (eigenes Python),
nicht in der Werkstatt selbst, und importiert deshalb nichts aus dem Paket `playalong`.

    python ki_worker.py --vorbereiten
    python ki_worker.py --audio lied.mp3 --out ordner

1. Demucs (htdemucs_6s) trennt die Aufnahme in Spuren: Gesang, Gitarre, Klavier, Bass, Schlagzeug, Rest.
2. Basic Pitch erkennt in den melodietauglichen Spuren die Noten.
Ausgabe: <out>/ergebnis.json mit Energieanteil, Spurdatei und Noten [Beginn, Ende, MIDI, Stärke] je Spur.
Fortschritt: Zeilen „FORTSCHRITT …“ auf stdout.
Alles läuft lokal; einmalig werden die Modelle heruntergeladen (bei der Einrichtung).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

MODEL = "htdemucs_6s"
MELODY_STEMS = ("vocals", "guitar", "piano", "other")
MIN_SHARE = 0.03  # Spuren mit weniger Energie werden nicht ausgewertet


def say(msg: str) -> None:
    print(f"FORTSCHRITT {msg}", flush=True)


def prepare() -> None:
    say("KI-Modelle werden geladen bzw. heruntergeladen …")
    from demucs.pretrained import get_model

    get_model(MODEL)
    logging.disable(logging.WARNING)
    from basic_pitch import ICASSP_2022_MODEL_PATH  # noqa: F401  (prüft die Installation)

    say("KI-Modelle sind bereit.")


def run(audio: str, out: Path) -> dict:
    import numpy as np
    import soundfile as sf
    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model

    out.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(max(1, (os.cpu_count() or 2)))
    say("Spurtrennung (Demucs) startet …")
    model = get_model(MODEL)
    model.eval()
    import librosa

    y, _ = librosa.load(audio, sr=model.samplerate, mono=False)
    if y.ndim == 1:
        y = np.stack([y, y])
    wav = torch.tensor(y, dtype=torch.float32)
    ref = wav.mean(0)
    mean, std = ref.mean(), ref.std() + 1e-8
    t = time.time()
    with torch.no_grad():
        sources = apply_model(model, ((wav - mean) / std)[None], device="cpu", split=True, overlap=0.25,
                              progress=False)[0]
    sources = sources * std + mean
    say(f"Spurtrennung fertig ({time.time() - t:.0f} s).")

    energy = {name: float((src ** 2).mean()) for name, src in zip(model.sources, sources)}
    total = sum(energy.values()) or 1.0
    result: dict = {"model": MODEL, "stems": {}}
    logging.disable(logging.WARNING)
    from basic_pitch import ICASSP_2022_MODEL_PATH
    from basic_pitch.inference import predict

    for name, src in zip(model.sources, sources):
        share = energy[name] / total
        entry: dict = {"energy": round(share, 4)}
        if name in MELODY_STEMS and share >= MIN_SHARE:
            f = out / f"{name}.wav"
            sf.write(f, src.numpy().T, model.samplerate)
            say(f"Noten werden erkannt: Spur „{name}“ …")
            _, _, events = predict(str(f), ICASSP_2022_MODEL_PATH, onset_threshold=0.5, frame_threshold=0.3,
                                   minimum_note_length=60)
            entry["file"] = str(f)
            entry["events"] = [[round(float(e[0]), 4), round(float(e[1]), 4), int(e[2]), round(float(e[3]), 3)]
                               for e in events]
        result["stems"][name] = entry
    (out / "ergebnis.json").write_text(json.dumps(result), encoding="utf-8")
    say("KI-Auswertung fertig.")
    return result


def main() -> int:
    # Meldungen immer in UTF-8 ausgeben: Wegen „python -I“ wird PYTHONIOENCODING ignoriert,
    # und Windows würde sonst cp1252 verwenden (Anführungszeichen und „…“ kämen als � an).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser()
    p.add_argument("--vorbereiten", action="store_true")
    p.add_argument("--audio")
    p.add_argument("--out")
    a = p.parse_args()
    try:
        if a.vorbereiten:
            prepare()
        else:
            run(a.audio, Path(a.out))
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"FEHLER {e.__class__.__name__}: {e}", flush=True)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
