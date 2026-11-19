"""Rohentwurf aus einer Aufnahme: führende Melodie als Klarinettenstimme (in B).

Nur als Starthilfe gedacht (siehe CLAUDE.md: niedrige Priorität, bei Orchestermusik
ungenau). Ergebnis muss in MuseScore nachbearbeitet werden.

Vorgehen (nur CPU, nur librosa/numpy):
1. Schläge und Tempo erkennen (Beat-Tracking), daraus Takte (4/4 oder 3/4) und ein 16tel-Raster.
2. Melodie per harmonischer Summierung über einer Drittelton-CQT: je Zeitpunkt die Tonhöhe,
   deren Grundton + Obertöne zusammen am stärksten klingen (im Klarinettenumfang).
3. Pro 16tel die häufigste Tonhöhe, gleiche Töne zusammenfassen.
4. Tonart schätzen (Krumhansl), MusicXML in B-Notation schreiben.
Die Taktzeiten sind aus Schritt 1 bekannt -> sync.json ohne weiteren Abgleich.
"""
from __future__ import annotations

from dataclasses import dataclass
from xml.sax.saxutils import escape

import numpy as np

SR = 22050
HOP = 256
BINS_PER_SEMI = 3
MIDI_LO = 50  # klingend D3 (tiefstes E der B-Klarinette)
MIDI_HI = 96  # klingend C7
HARMONICS = (1, 2, 3, 4)
VOICE_PCT = 20  # Schwelle für „es klingt etwas“ (Perzentil): niedriger = mehr Töne, aber auch mehr falsche
H_WEIGHTS = (1.0, 0.6, 0.45, 0.3)

STEP_SHARP = ["C", "C", "D", "D", "E", "F", "F", "G", "G", "A", "A", "B"]
ALT_SHARP = [0, 1, 0, 1, 0, 0, 1, 0, 1, 0, 1, 0]
STEP_FLAT = ["C", "D", "D", "E", "E", "F", "G", "G", "A", "A", "B", "B"]
ALT_FLAT = [0, -1, 0, -1, 0, 0, -1, 0, -1, 0, -1, 0]
MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
FIFTHS_OF_PC = {0: 0, 7: 1, 2: 2, 9: 3, 4: 4, 11: 5, 6: 6, 1: -5, 8: -4, 3: -3, 10: -2, 5: -1}


@dataclass
class Draft:
    musicxml: str
    measure_times: list[float]
    end_time: float
    audio_duration: float
    tempo: float
    beats_per_bar: int
    key_fifths_concert: int
    n_notes: int
    voiced_ratio: float


def _melody(y: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Gibt (Zeiten, MIDI-Tonhöhe je Bild oder nan, Stärke) zurück."""
    import librosa

    fmin = librosa.midi_to_hz(MIDI_LO)
    n_semis = MIDI_HI - MIDI_LO + 1 + int(np.ceil(12 * np.log2(max(HARMONICS)))) + 1
    C = np.abs(librosa.cqt(y, sr=SR, hop_length=HOP, fmin=fmin, n_bins=n_semis * BINS_PER_SEMI,
                           bins_per_octave=12 * BINS_PER_SEMI))
    C = np.log1p(10 * C / (C.max() + 1e-9))
    n_cand = (MIDI_HI - MIDI_LO + 1) * BINS_PER_SEMI
    sal = np.zeros((n_cand, C.shape[1]))
    for h, w in zip(HARMONICS, H_WEIGHTS):
        off = int(round(12 * np.log2(h) * BINS_PER_SEMI))
        sal += w * C[off:off + n_cand]
    # je Zeitpunkt der stärkste Kandidat; „keine Melodie“, wenn es zu leise ist.
    # Geglättet wird anschließend durch die Mehrheitsentscheidung pro 16tel.
    frame_max = sal.max(axis=0)
    thr = np.percentile(frame_max, VOICE_PCT)
    best = sal.argmax(axis=0)
    midi = np.where(frame_max > thr, MIDI_LO + best / BINS_PER_SEMI, np.nan)
    times = librosa.frames_to_time(np.arange(len(midi)), sr=SR, hop_length=HOP)
    return times, midi, frame_max


def _key(y: np.ndarray) -> tuple[int, bool]:
    """Tonart (Grundton-Tonklasse, Dur?) nach Krumhansl-Schmuckler."""
    import librosa

    chroma = librosa.feature.chroma_cqt(y=y, sr=SR, hop_length=2048).mean(axis=1)
    best = (-np.inf, 0, True)
    for pc in range(12):
        for major, prof in ((True, MAJOR), (False, MINOR)):
            r = np.corrcoef(np.roll(prof, pc), chroma)[0, 1]
            if r > best[0]:
                best = (r, pc, major)
    return best[1], best[2]


def _dur_parts(n16: int) -> list[int]:
    """Dauer in 16teln in darstellbare Notenwerte zerlegen (für Bindebögen)."""
    vals = [16, 12, 8, 6, 4, 3, 2, 1]
    out = []
    while n16 > 0:
        v = next(x for x in vals if x <= n16)
        out.append(v)
        n16 -= v
    return out


TYPE = {16: ("whole", 0), 12: ("half", 1), 8: ("half", 0), 6: ("quarter", 1), 4: ("quarter", 0),
        3: ("eighth", 1), 2: ("eighth", 0), 1: ("16th", 0)}


def transcribe(audio_path: str, title: str, composer: str = "", beats_per_bar: int = 4,
               progress=print) -> Draft:
    import librosa

    progress("Aufnahme wird geladen …")
    y, _ = librosa.load(audio_path, sr=SR, mono=True)
    duration = len(y) / SR
    progress("Schläge und Tempo werden erkannt …")
    y_h, y_p = librosa.effects.hpss(y)
    tempo, beat_frames = librosa.beat.beat_track(y=y_p + 0.5 * y_h, sr=SR, hop_length=HOP, units="frames")
    beats = librosa.frames_to_time(beat_frames, sr=SR, hop_length=HOP)
    if len(beats) < beats_per_bar * 2:
        raise RuntimeError("In der Aufnahme wurden zu wenige Schläge erkannt.")
    tempo = float(np.atleast_1d(tempo)[0])
    # Beat-Tracking verdoppelt gern das Tempo: sehr schnelle „Viertel“ -> nur jeden 2. Schlag nehmen
    while tempo > 150 and len(beats) >= beats_per_bar * 4:
        beats = beats[::2]
        tempo /= 2
    # 16tel-Raster aus den Schlägen
    grid = []
    for a, b in zip(beats[:-1], beats[1:]):
        grid.extend(a + (b - a) * k / 4 for k in range(4))
    grid.append(beats[-1])
    grid = np.array(grid)

    progress("Melodie wird verfolgt …")
    times, midi, _ = _melody(y_h)
    progress("Tonart wird bestimmt …")
    key_pc, major = _key(y_h)
    tonic = key_pc if major else (key_pc + 3) % 12  # Paralleltonart -> Vorzeichen
    fifths = FIFTHS_OF_PC[tonic]
    if fifths > 6:
        fifths -= 12

    # pro 16tel die häufigste (gerundete) Tonhöhe
    cells: list[int | None] = []
    for a, b in zip(grid[:-1], grid[1:]):
        sel = (times >= a) & (times < b)
        vals = midi[sel]
        voiced = vals[~np.isnan(vals)]
        if len(vals) == 0 or len(voiced) < 0.5 * len(vals):
            cells.append(None)
            continue
        r = np.round(voiced).astype(int)
        cells.append(int(np.bincount(r - MIDI_LO).argmax() + MIDI_LO))
    # einzelne 16tel-Ausreißer zwischen gleichen Tönen glätten
    for i in range(1, len(cells) - 1):
        if cells[i - 1] is not None and cells[i - 1] == cells[i + 1] and cells[i] != cells[i - 1]:
            cells[i] = cells[i - 1]

    per_bar = beats_per_bar * 4
    n_bars = len(cells) // per_bar
    cells = cells[: n_bars * per_bar]
    measure_times = [float(grid[k * per_bar]) for k in range(n_bars)]
    end_time = float(grid[n_bars * per_bar]) if n_bars * per_bar < len(grid) else float(grid[-1])
    progress(f"{n_bars} Takte, Tempo ca. {tempo:.0f}, Tonart {'Dur' if major else 'Moll'} mit {abs(fifths)} {'♯' if fifths > 0 else '♭' if fifths < 0 else 'Vorzeichen'} (klingend)")

    xml, n_notes = _to_musicxml(cells, n_bars, per_bar, beats_per_bar, tempo, fifths, title, composer)
    voiced_ratio = sum(c is not None for c in cells) / max(1, len(cells))
    return Draft(xml, measure_times, end_time, duration, tempo, beats_per_bar, fifths, n_notes, voiced_ratio)


def _to_musicxml(cells, n_bars, per_bar, beats_per_bar, tempo, fifths_concert, title, composer) -> tuple[str, int]:
    """Klarinette in B: notiert große Sekunde höher, Tonart +2 Quinten."""
    w_fifths = fifths_concert + 2
    if w_fifths > 6:
        w_fifths -= 12
    flats = w_fifths < 0
    div = 4  # divisions pro Viertel = 16tel
    parts = []
    n_notes = 0
    for bar in range(n_bars):
        seg = cells[bar * per_bar:(bar + 1) * per_bar]
        # Läufe gleicher Tonhöhe
        runs = []
        for c in seg:
            if runs and runs[-1][0] == c:
                runs[-1][1] += 1
            else:
                runs.append([c, 1])
        body = []
        if bar == 0:
            body.append(
                f"<attributes><divisions>{div}</divisions><key><fifths>{w_fifths}</fifths></key>"
                f"<time><beats>{beats_per_bar}</beats><beat-type>4</beat-type></time>"
                "<clef><sign>G</sign><line>2</line></clef>"
                "<transpose><diatonic>-1</diatonic><chromatic>-2</chromatic></transpose></attributes>"
                f'<direction placement="above"><direction-type><words font-style="italic">Rohentwurf – bitte prüfen</words></direction-type>'
                f'<direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>{round(tempo)}</per-minute></metronome></direction-type>'
                f'<sound tempo="{round(tempo, 1)}"/></direction>')
        if all(c is None for c in seg):
            body.append(f'<note><rest measure="yes"/><duration>{per_bar}</duration><voice>1</voice></note>')
        else:
            for pitch, length in runs:
                pieces = _dur_parts(length)
                for k, p in enumerate(pieces):
                    typ, dots = TYPE[p]
                    dot = "<dot/>" * dots
                    if pitch is None:
                        body.append(f"<note><rest/><duration>{p}</duration><voice>1</voice><type>{typ}</type>{dot}</note>")
                        continue
                    w = pitch + 2  # notiert
                    pc = w % 12
                    step = (STEP_FLAT if flats else STEP_SHARP)[pc]
                    alt = (ALT_FLAT if flats else ALT_SHARP)[pc]
                    octave = w // 12 - 1
                    a = f"<alter>{alt}</alter>" if alt else ""
                    tie, tied = "", ""
                    if len(pieces) > 1:
                        if k > 0:
                            tie += '<tie type="stop"/>'
                            tied += '<tied type="stop"/>'
                        if k < len(pieces) - 1:
                            tie += '<tie type="start"/>'
                            tied += '<tied type="start"/>'
                    nots = f"<notations>{tied}</notations>" if tied else ""
                    body.append(f"<note><pitch><step>{step}</step>{a}<octave>{octave}</octave></pitch>"
                                f"<duration>{p}</duration>{tie}<voice>1</voice><type>{typ}</type>{dot}{nots}</note>")
                    if k == 0:
                        n_notes += 1
        if bar == n_bars - 1:
            body.append('<barline location="right"><bar-style>light-heavy</bar-style></barline>')
        parts.append(f'<measure number="{bar + 1}">{"".join(body)}</measure>')
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">\n'
           '<score-partwise version="4.0">'
           f"<work><work-title>{escape(title)}</work-title></work>"
           f'<identification><creator type="composer">{escape(composer)}</creator>'
           "<encoding><software>Play-along Rohentwurf (automatisch erkannt)</software></encoding></identification>"
           '<part-list><score-part id="P1"><part-name>Klarinette in B (Rohentwurf)</part-name>'
           '<score-instrument id="P1-I1"><instrument-name>Clarinet in Bb</instrument-name></score-instrument>'
           '<midi-instrument id="P1-I1"><midi-program>72</midi-program></midi-instrument></score-part></part-list>'
           f'<part id="P1">{"".join(parts)}</part></score-partwise>\n')
    return xml, n_notes
