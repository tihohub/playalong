#!/usr/bin/env python3
"""Erzeugt aus einer Aufnahme eine zeitlich verzerrte Testfassung mit bekannter Zeitzuordnung.

Damit lässt sich prüfen, ob der Abgleich (playalong sync) auch bei Tempo-
schwankungen, Pausen und Versatz die richtigen Taktanfänge findet.

    python make_warped_audio.py original.mp3 verzerrt.mp3

Schreibt zusätzlich verzerrt.mp3.map.json: Liste von [Originalzeit, neue Zeit].
Benötigt ffmpeg.
"""
from __future__ import annotations

import json
import subprocess
import sys

# (Ende im Original in s, Tempofaktor) – Faktor < 1 = langsamer
SEGMENTS = [(40.0, 1.0), (90.0, 0.85), (130.0, 1.15), (200.0, 0.92), (None, 1.05)]
LEAD_SILENCE = 1.0
PAUSE_AT = 130.0  # Generalpause im Original einfügen (nach dem 3. Abschnitt)
PAUSE_LEN = 1.5


def main(src: str, dst: str) -> None:
    dur = float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src]).decode().strip())
    filters, labels, mapping = [], [], [[0.0, LEAD_SILENCE]]
    t_orig, t_new, k = 0.0, LEAD_SILENCE, 0
    filters.append(f"anullsrc=r=44100:cl=stereo,atrim=0:{LEAD_SILENCE}[s0]")
    labels.append("[s0]")
    for end, factor in SEGMENTS:
        end = dur if end is None else min(end, dur)
        if end <= t_orig:
            continue
        k += 1
        filters.append(f"[0:a]atrim={t_orig}:{end},asetpts=PTS-STARTPTS,atempo={factor}[a{k}]")
        labels.append(f"[a{k}]")
        t_new += (end - t_orig) / factor
        t_orig = end
        mapping.append([t_orig, t_new])
        if abs(t_orig - PAUSE_AT) < 1e-6:
            filters.append(f"anullsrc=r=44100:cl=stereo,atrim=0:{PAUSE_LEN}[p{k}]")
            labels.append(f"[p{k}]")
            t_new += PAUSE_LEN
            mapping.append([t_orig, t_new])
    filters.append(f"{''.join(labels)}concat=n={len(labels)}:v=0:a=1[out]")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-filter_complex", ";".join(filters),
                    "-map", "[out]", "-b:a", "128k", dst], check=True)
    with open(dst + ".map.json", "w") as f:
        json.dump(mapping, f)
    print(f"{dst} geschrieben ({t_new:.1f} s), Zuordnung in {dst}.map.json")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
