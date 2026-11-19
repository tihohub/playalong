"""Tests der Pipeline:  python -m unittest discover -s tests"""
from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np

from playalong.score import build_timeline, load_musicxml

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "player" / "public" / "demo" / "uebungsstueck.musicxml"


def synth(tl, path: Path, speed: float, lead: float, sr: int = 22050) -> None:
    """Einfache Klangsynthese der Partitur (Sinus + Obertöne) als WAV-Datei."""
    import soundfile as sf

    dur = lead + tl.duration / speed + 1.0
    y = np.zeros(int(dur * sr))
    for n in tl.notes:
        t0 = lead + tl.seconds(n.start) / speed
        t1 = lead + tl.seconds(n.start + n.dur) / speed
        a, b = int(t0 * sr), min(len(y), int(t1 * sr))
        t = np.arange(b - a) / sr
        f = 440 * 2 ** ((n.midi - 69) / 12)
        env = np.exp(-t * 2.5) * np.minimum(1, t * 200)
        y[a:b] += 0.08 * n.vel * env * (np.sin(2 * np.pi * f * t) + 0.4 * np.sin(4 * np.pi * f * t))
    sf.write(path, y / max(1e-9, np.abs(y).max()) * 0.8, sr)


class TimelineTest(unittest.TestCase):
    def test_demo_wie_im_player(self):
        tl = build_timeline(load_musicxml(DEMO))
        # Wiederholung Takt 1–4, dann 5–23: 27 gespielte Takte, 98 Viertel (wie player/src/musicxml/timeline.ts)
        self.assertEqual([m.label for m in tl.measures[:9]], ["1", "2", "3", "4", "1", "2", "3", "4", "5"])
        self.assertEqual(len(tl.measures), 27)
        self.assertAlmostEqual(tl.length, 98.0)
        self.assertEqual([round(q) for _, q in tl.tempos], [104, 104, 66, 104])


class PackageTest(unittest.TestCase):
    def test_paket_ohne_aufnahme(self):
        from playalong.package import build_package

        with tempfile.TemporaryDirectory() as d:
            p = build_package(DEMO, None, d, progress=lambda *_: None)
            with zipfile.ZipFile(p) as z:
                self.assertEqual(sorted(z.namelist()), ["manifest.json", "score.musicxml"])
                m = json.loads(z.read("manifest.json"))
                self.assertEqual(m["format"], "playalong")
                self.assertEqual(m["title"], "Übungsstück in B")


class AlignTest(unittest.TestCase):
    def test_abgleich_langsamer_mit_vorlauf(self):
        from playalong.align import align

        tl = build_timeline(load_musicxml(DEMO))
        speed, lead = 0.9, 0.7
        with tempfile.TemporaryDirectory() as d:
            wav = Path(d) / "demo.wav"
            synth(tl, wav, speed, lead)
            res = align(tl, str(wav), progress=lambda *_: None)
        truth = np.array([lead + tl.seconds(m.start) / speed for m in tl.measures])
        err = np.abs(np.array(res.measure_times) - truth)
        self.assertLess(np.median(err), 0.06, err)
        self.assertLess(np.percentile(err, 90), 0.15, err)


if __name__ == "__main__":
    unittest.main()
