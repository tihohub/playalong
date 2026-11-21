"""Rohentwurf aus einer Aufnahme: führende Melodie als Klarinettenstimme (in B).

Nur als Starthilfe gedacht (siehe CLAUDE.md: niedrige Priorität, bei Orchestermusik
ungenau). Ergebnis muss in MuseScore nachbearbeitet werden.

Vorgehen (nur CPU, nur librosa/numpy):
1. Schläge und Tempo erkennen (Beat-Tracking), daraus Takte (4/4 oder 3/4) und ein 16tel-Raster.
2. Drittelton-Spektrum (CQT): Tonhöhen, die fast das ganze Stück über auffällig laut liegen
   (Bass, Orgelpunkt, Akkordteppich), werden auf ihren eigenen typischen Pegel gedämpft.
   Normale Begleitung bleibt unverändert, damit die Melodie nicht mit ihr verwechselt wird.
3. Harmonische Summierung (Grundton + Obertöne) im Klarinettenumfang, mit leichter Vorliebe
   für die gewählte Lage (Melodien liegen meist über der Begleitung).
4a. „gehalten“ (Bläser, Streicher, Gesang): je Zeitpunkt der stärkste Kandidat, pro 16tel
    Mehrheitsentscheidung.
4b. „gezupft“ (Banjo, Mandoline, Gitarre, Klavier): Töne beginnen an hörbaren Anschlägen;
    je Anschlag zählt die Tonhöhe, deren Energie dort neu einsetzt.
    „automatisch“ rechnet beide und nimmt das eindeutigere Ergebnis.
5. Melodielinie glätten: Oktave je Ton im Zusammenhang wählen (Viterbi: kleine Sprünge, nahe der
   gleitenden Hauptlage, andere Oktave nur wenn hörbar); kurze Ausreißer entfernen.
6. Tonart schätzen (Krumhansl), MusicXML in B-Notation schreiben, Sicherheit angeben.
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
MIDI_EXT = MIDI_LO
HARMONICS = (1, 2, 3, 4)
H_WEIGHTS = (1.0, 0.6, 0.45, 0.3)
VOICE_PCT = 20  # Schwelle für „es klingt etwas“ (Perzentil): niedriger = mehr Töne, aber auch mehr falsche
DRONE = 50.0  # ab dem Wievielfachen des üblichen Pegels gilt ein Dauerton als „Liegeton“
LAGE_PRIOR = {"auto": 0.15, "hoch": 0.45, "tief": -0.3}  # Vorliebe je Oktave über/unter C5
INSTRUMENTE = ("auto", "gezupft", "gehalten")
PLUCK_DECAY = 0.75  # Melodietöne fallen nach 0,2 s unter diesen Anteil -> „gezupft“

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
    mode: str  # tatsächlich verwendet: „gezupft“ oder „gehalten“
    confidence: float  # 0..1
    confidence_label: str  # gut / mittel / unsicher


# --------------------------------------------------------------------------- Merkmale

def _harmonic_sum(L: np.ndarray, n_cand: int) -> np.ndarray:
    sal = np.zeros((n_cand, L.shape[1]))
    for h, w in zip(HARMONICS, H_WEIGHTS):
        off = int(round(12 * np.log2(h) * BINS_PER_SEMI))
        sal += w * L[off:off + n_cand]
    return sal


def _restrict(sal_ext: np.ndarray, lage: str) -> np.ndarray:
    """Nur Kandidaten im Klarinettenumfang, gewichtet nach Lage."""
    a = (MIDI_LO - MIDI_EXT) * BINS_PER_SEMI
    sal = sal_ext[a:a + (MIDI_HI - MIDI_LO + 1) * BINS_PER_SEMI]
    midi = MIDI_LO + np.arange(sal.shape[0]) / BINS_PER_SEMI
    prior = np.exp(LAGE_PRIOR.get(lage, 0.15) * (midi - 72) / 12)
    return sal * prior[:, None]


def _clarity(col: np.ndarray, best: int) -> float:
    """Wie deutlich der beste Kandidat vor dem nächstbesten (außerhalb ±1 Halbton) liegt, 0..1."""
    v = col[best]
    if v <= 0:
        return 0.0
    mask = np.ones(len(col), bool)
    mask[max(0, best - BINS_PER_SEMI):best + BINS_PER_SEMI + 1] = False
    second = col[mask].max() if mask.any() else 0.0
    return float(max(0.0, (v - second) / v))


def _spectra(y: np.ndarray, lage: str):
    """Gibt (Zeiten, aufgehellte Salienz, Anschlags-Salienz) im Klarinettenumfang zurück."""
    import librosa

    n_cand_ext = (MIDI_HI - MIDI_EXT + 1) * BINS_PER_SEMI
    top = int(np.ceil(12 * np.log2(max(HARMONICS)))) * BINS_PER_SEMI + 1
    C = np.abs(librosa.cqt(y, sr=SR, hop_length=HOP, fmin=librosa.midi_to_hz(MIDI_EXT),
                           n_bins=n_cand_ext + top, bins_per_octave=12 * BINS_PER_SEMI))
    # Liegetöne dämpfen: nur Tonhöhen, deren Dauerpegel weit über dem üblichen liegt
    med = np.median(C, axis=1, keepdims=True)
    ref = np.maximum(med, DRONE * np.median(med)) + 1e-9
    L = np.log1p(C / ref)
    sal = _restrict(_harmonic_sum(L, n_cand_ext), lage)
    # Anschläge: Zunahme der (nicht aufgehellten) Energie über ca. 3 Bilder
    Lr = np.log1p(10 * C / (C.max() + 1e-9))
    lag = 3
    D = np.maximum(0, Lr - np.concatenate([Lr[:, :lag], Lr[:, :-lag]], axis=1))
    att = _restrict(_harmonic_sum(D, n_cand_ext), lage)
    times = librosa.frames_to_time(np.arange(C.shape[1]), sr=SR, hop_length=HOP)
    return times, sal, att


# --------------------------------------------------------------------------- Modus „gehalten“

def _cells_held(times, sal, grid) -> tuple[list, list, float]:
    frame_max = sal.max(axis=0)
    thr = np.percentile(frame_max, VOICE_PCT)
    best = sal.argmax(axis=0)
    voiced = frame_max > thr
    midi = np.where(voiced, MIDI_LO + best / BINS_PER_SEMI, np.nan)
    clar = [_clarity(sal[:, t], best[t]) for t in np.nonzero(voiced)[0][::4]]
    cells: list[int | None] = []
    for a, b in zip(grid[:-1], grid[1:]):
        sel = (times >= a) & (times < b)
        vals = midi[sel]
        v = vals[~np.isnan(vals)]
        if len(vals) == 0 or len(v) < 0.5 * len(vals):
            cells.append(None)
            continue
        r = np.round(v).astype(int)
        cells.append(int(np.bincount(r - MIDI_LO).argmax() + MIDI_LO))
    for i in range(1, len(cells) - 1):  # einzelne Ausreißer zwischen gleichen Tönen glätten
        if cells[i - 1] is not None and cells[i - 1] == cells[i + 1] and cells[i] != cells[i - 1]:
            cells[i] = cells[i - 1]
    starts = [i == 0 or cells[i] != cells[i - 1] for i in range(len(cells))]
    return cells, starts, float(np.mean(clar)) if clar else 0.0


# --------------------------------------------------------------------------- Modus „gezupft“

def _cells_plucked(y, times, sal, att, grid) -> tuple[list, list, float, float]:
    import librosa

    on = librosa.onset.onset_detect(y=y, sr=SR, hop_length=HOP, units="frames", backtrack=False)
    if len(on) == 0:
        return [None] * (len(grid) - 1), [False] * (len(grid) - 1), 0.0, 1.0
    win = 4  # ca. 45 ms nach dem Anschlag
    notes = []
    for f in on:
        a = att[:, f:f + win].max(axis=1)
        s_ = sal[:, f:f + 3 * win].mean(axis=1)
        score = a / (a.max() + 1e-9) + 0.5 * s_ / (s_.max() + 1e-9)
        best = int(score.argmax())
        notes.append((f, best, float(a[best]), _clarity(score, best)))
    strength = np.array([n[2] for n in notes])
    keep = strength >= 0.3 * np.percentile(strength, 90)  # Schlagzeug-/Bass-Anschläge ohne Melodieanteil weglassen
    notes = [n for n, k in zip(notes, keep) if k]
    n_cells = len(grid) - 1
    cells: list[int | None] = [None] * n_cells
    starts = [False] * n_cells
    beat = np.median(np.diff(grid)) * 4
    for k, (f, best, _, _) in enumerate(notes):
        t0 = times[f]
        t1 = times[notes[k + 1][0]] if k + 1 < len(notes) else t0 + beat
        t1 = min(t1, t0 + 2 * beat)  # gezupfte Töne klingen ab
        s = int(np.argmin(np.abs(grid[:-1] - t0)))
        e = max(s + 1, int(np.argmin(np.abs(grid[:-1] - t1))))
        pitch = int(round(MIDI_LO + best / BINS_PER_SEMI))
        for i in range(s, min(e, n_cells)):
            cells[i] = pitch
            starts[i] = i == s
    conf = float(np.mean([n[3] for n in notes])) if notes else 0.0
    # Abklingen: Pegel des Tons ca. 0,2 s nach dem Anschlag im Verhältnis zum Anschlag.
    # Nur Töne, nach denen mindestens 0,3 s lang kein neuer Anschlag kommt (sonst misst man den nächsten Ton).
    later = int(0.2 * SR / HOP)
    gap = int(0.3 * SR / HOP)
    ratios = []
    for k, (f, best, _, _) in enumerate(notes):
        nxt = notes[k + 1][0] if k + 1 < len(notes) else sal.shape[1]
        if nxt - f >= gap and f + later < sal.shape[1]:
            v0 = sal[best, f:f + 3].max()
            if v0 > 0:
                ratios.append(sal[best, f + later] / v0)
    if len(ratios) < 5:
        ratios = []
    decay = float(np.median(ratios)) if ratios else 1.0
    return cells, starts, conf, decay


# --------------------------------------------------------------------------- Melodielinie glätten

SMOOTH_SUPPORT = 0.4  # andere Oktave nur, wenn sie mindestens so stark hörbar ist (Anteil am erkannten Ton)
SMOOTH_FREE = 7  # Sprünge bis zu dieser Größe (Halbtöne) sind normal und kosten nichts
SMOOTH_JUMP = 0.5  # Kosten je Halbton über SMOOTH_FREE
SMOOTH_OCTAVE_JUMP = 6.0  # Zusatzkosten für Sprünge ab einer Oktave
SMOOTH_REGISTER = 0.5  # Kosten je Halbton außerhalb ±7 Halbtöne um die gleitende Hauptlage
SMOOTH_EMISSION = 10.0  # Kosten, wenn statt des erkannten Tons eine schwächere Oktave gewählt wird
SMOOTH_SWITCH = 4.0  # Grundkosten für jeden Oktavwechsel


def _notes_from_cells(cells, starts):
    """[(Start-16tel, Ende-16tel, Tonhöhe)] aus Raster + Anschlagsmarken."""
    notes = []
    for i, c in enumerate(cells):
        if c is None:
            continue
        if notes and notes[-1][1] == i and notes[-1][2] == c and not starts[i]:
            notes[-1][1] = i + 1
        else:
            notes.append([i, i + 1, c])
    return notes


def _smooth_line(cells, starts, times, sal, grid):
    """Oktavfehler und einzelne Ausreißer korrigieren (siehe Modul-Beschreibung)."""
    notes = _notes_from_cells(cells, starts)
    if len(notes) < 3:
        return cells, starts
    fidx = np.searchsorted(times, grid)

    def support(note, pitch):
        if pitch < MIDI_LO or pitch > MIDI_HI:
            return 0.0
        a = fidx[note[0]]
        b = max(a + 1, min(fidx[min(note[1], len(fidx) - 1)], a + int(0.15 * SR / HOP)))
        k = (pitch - MIDI_LO) * BINS_PER_SEMI
        return float(sal[max(0, k - 1):k + 2, a:b].max()) if b > a else 0.0

    def remove_outliers(ns):
        """Kurze Töne, die weit von beiden Nachbarn liegen und auch per Oktave nicht passen,
        dem vorigen Ton zuschlagen (meist ein anderes Instrument)."""
        out = []
        for i, n in enumerate(ns):
            prev_p = out[-1][2] if out else None
            next_p = ns[i + 1][2] if i + 1 < len(ns) else None
            neigh = [q for q in (prev_p, next_p) if q is not None]
            short = n[1] - n[0] <= 2
            far = bool(neigh) and all(abs(n[2] - q) >= 9 for q in neigh)
            octave_fits = any(all(abs(n[2] + sh - q) <= 5 for q in neigh) for sh in (-12, 12))
            if short and far and not octave_fits and out and out[-1][1] == n[0]:
                out[-1][1] = n[1]
                continue
            out.append(n)
        return out

    notes = remove_outliers(notes)
    orig = np.array([n[2] for n in notes])
    # gleitende Hauptlage: Median der Nachbartöne (±8), robust gegen einzelne Ausreißer
    center = np.array([np.median(orig[max(0, i - 8):i + 9]) for i in range(len(orig))])
    shifts = (0, -12, 12)
    cands, emis = [], []
    for i, n in enumerate(notes):
        s0 = support(n, n[2]) + 1e-9
        cs, es = [], []
        for sh in shifts:
            p = n[2] + sh
            sp = support(n, p) if sh else s0
            if sh and sp < SMOOTH_SUPPORT * s0:
                continue
            reg = max(0.0, abs(p - center[i]) - 7) * SMOOTH_REGISTER
            switch = 0.0 if sh == 0 else SMOOTH_SWITCH + SMOOTH_EMISSION * (1 - min(1.0, sp / s0))
            cs.append(p)
            es.append(switch + reg)
        cands.append(cs)
        emis.append(es)

    def trans(a, b):
        d = abs(a - b)
        return SMOOTH_JUMP * max(0, d - SMOOTH_FREE) + (SMOOTH_OCTAVE_JUMP if d >= 12 else 0.0)

    # Viterbi über die Oktav-Wahl
    cost = [list(emis[0])]
    back = [[0] * len(cands[0])]
    for i in range(1, len(notes)):
        row, brow = [], []
        for j, p in enumerate(cands[i]):
            prev = [cost[i - 1][k] + trans(q, p) for k, q in enumerate(cands[i - 1])]
            k = int(np.argmin(prev))
            row.append(prev[k] + emis[i][j])
            brow.append(k)
        cost.append(row)
        back.append(brow)
    j = int(np.argmin(cost[-1]))
    chosen = [0] * len(notes)
    for i in range(len(notes) - 1, -1, -1):
        chosen[i] = cands[i][j]
        j = back[i][j]
    for n, p in zip(notes, chosen):
        n[2] = p
    out = remove_outliers(notes)

    new_cells: list = [None] * len(cells)
    new_starts = [False] * len(cells)
    for a, b, p in out:
        for i in range(a, b):
            new_cells[i] = p
        new_starts[a] = True
    return new_cells, new_starts


# --------------------------------------------------------------------------- Verfahren „lokale KI“

KI_MIN_DUR = 0.06  # kürzere erkannte Töne verwerfen (s)


def _cells_from_events(events, grid) -> tuple[list, list, float]:
    """Noten von Basic Pitch [Beginn, Ende, MIDI, Stärke] -> einstimmige Linie im 16tel-Raster.
    Je Anschlag (±40 ms) zählt der höchste deutlich hörbare Ton; Töne außerhalb des
    Klarinettenumfangs werden in die nächste passende Oktave geholt."""
    ev = sorted((e for e in events if e[1] - e[0] >= KI_MIN_DUR), key=lambda e: e[0])
    groups: list[list] = []
    for e in ev:
        if groups and e[0] - groups[-1][0][0] <= 0.04:
            groups[-1].append(e)
        else:
            groups.append([e])
    notes = []
    for g in groups:
        loud = max(x[3] for x in g)
        cand = [x for x in g if x[3] >= 0.5 * loud]
        s, e, p, a = max(cand, key=lambda x: x[2])
        while p < MIDI_LO:
            p += 12
        while p > MIDI_HI:
            p -= 12
        notes.append([s, e, p, a])
    for k in range(len(notes) - 1):  # einstimmig: Ton endet spätestens beim nächsten Anschlag
        notes[k][1] = min(notes[k][1], notes[k + 1][0])
    n_cells = len(grid) - 1
    cells: list[int | None] = [None] * n_cells
    starts = [False] * n_cells
    g0 = grid[:-1]
    for s, e, p, _ in notes:
        a = int(np.argmin(np.abs(g0 - s)))
        b = max(a + 1, int(np.argmin(np.abs(g0 - e))))
        for i in range(a, min(b, n_cells)):
            cells[i] = int(p)
            starts[i] = i == a
    amps = [n[3] for n in notes]
    conf = float(np.clip((np.mean(amps) - 0.2) / 0.5, 0, 1)) if amps else 0.0
    return cells, starts, conf


def _line_clarity(cells, starts, times, sal, grid) -> float:
    """Sicherheit wie beim schnellen Verfahren: wie deutlich der gewählte Ton am Anschlag
    vor anderen Tönen liegt (gemessen auf der Melodiespur)."""
    fidx = np.searchsorted(times, grid)
    vals = []
    for i, (c, st) in enumerate(zip(cells, starts)):
        if c is None or not st:
            continue
        f = min(fidx[i] + 2, sal.shape[1] - 1)
        k = (c - MIDI_LO) * BINS_PER_SEMI
        if 0 <= k < sal.shape[0]:
            col = sal[:, f]
            best = int(k + np.argmax(col[max(0, k - 1):k + 2]) - (1 if k > 0 else 0))
            vals.append(_clarity(col, best))
    return float(np.mean(vals)) if vals else 0.0


def _label(conf: float) -> str:
    return "gut" if conf >= 0.35 else "mittel" if conf >= 0.2 else "unsicher"


def _align_downbeat(y: np.ndarray, beats: np.ndarray, beats_per_bar: int) -> np.ndarray:
    """Taktanfang an der Betonung ausrichten: von den möglichen Lagen (Schlag 1, 2, … als
    Taktbeginn) die mit den stärksten Einsätzen auf Schlag 1 wählen. Vor dem ersten Takt
    fehlende Schläge werden im Schlagabstand ergänzt (Auftakt), soweit die Aufnahme reicht."""
    import librosa

    if len(beats) < beats_per_bar * 4:
        return beats
    oenv = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP)
    frames = np.clip(librosa.time_to_frames(beats, sr=SR, hop_length=HOP), 0, len(oenv) - 1)
    strength = oenv[frames]
    phase = int(np.argmax([strength[p::beats_per_bar].mean() for p in range(beats_per_bar)]))
    if phase == 0:
        return beats
    step = float(np.median(np.diff(beats[: beats_per_bar * 4])))
    missing = beats_per_bar - phase  # so viele Schläge vor dem ersten erkannten ergänzen
    extra = beats[0] - step * np.arange(missing, 0, -1)
    if extra[0] >= 0:
        return np.concatenate([extra, beats])
    return beats[phase:]  # Aufnahme beginnt zu früh: angefangenen ersten Takt weglassen


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
               instrument: str = "auto", lage: str = "auto", smooth: bool = True, verfahren: str = "schnell",
               spur: str = "auto", progress=print) -> Draft:
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
    beats = _align_downbeat(y, beats, beats_per_bar)
    grid = []  # 16tel-Raster aus den Schlägen
    for a, b in zip(beats[:-1], beats[1:]):
        grid.extend(a + (b - a) * k / 4 for k in range(4))
    grid.append(beats[-1])
    grid = np.array(grid)

    if verfahren == "ki":
        from . import ki

        res, work = ki.separate_and_transcribe(audio_path, progress=progress)
        with work:
            stem = ki.choose_stem(res, spur)
            progress(f"Melodie aus der Spur „{ki.STEM_NAMES.get(stem, stem)}“ (Anteil {res['stems'][stem]['energy']:.0%}).")
            y_stem, _ = librosa.load(res["stems"][stem]["file"], sr=SR, mono=True)
        times, sal, _ = _spectra(y_stem, lage)  # für die Glättung: wie stark ist welcher Ton hörbar
        cells, starts, _ = _cells_from_events(res["stems"][stem]["events"], grid)
        conf = _line_clarity(cells, starts, times, sal, grid)
        mode = f"KI, Spur {ki.STEM_NAMES.get(stem, stem)}"
    else:
        progress("Melodie wird gesucht (Bass und Liegetöne werden herausgerechnet) …")
        times, sal, att = _spectra(y, lage)
    if verfahren == "ki":
        pass
    elif instrument == "gehalten":
        mode = "gehalten"
        cells, starts, conf = _cells_held(times, sal, grid)
    else:
        pc, ps, pconf, decay = _cells_plucked(y, times, sal, att, grid)
        # automatisch: gezupft, wenn die Melodietöne nach dem Anschlag schnell leiser werden
        mode = "gezupft" if instrument == "gezupft" or decay < PLUCK_DECAY else "gehalten"
        if mode == "gezupft":
            cells, starts, conf = pc, ps, pconf
        else:
            cells, starts, conf = _cells_held(times, sal, grid)
        if instrument == "auto":
            progress(f"Melodie-Instrument erkannt als „{mode}“ (Abklingen auf {decay:.0%} nach 0,2 s).")
    if smooth:
        cells, starts = _smooth_line(cells, starts, times, sal, grid)

    progress("Tonart wird bestimmt …")
    key_pc, major = _key(y_h)
    tonic = key_pc if major else (key_pc + 3) % 12  # Paralleltonart -> Vorzeichen
    fifths = FIFTHS_OF_PC[tonic]
    if fifths > 6:
        fifths -= 12

    per_bar = beats_per_bar * 4
    n_bars = len(cells) // per_bar
    cells, starts = cells[: n_bars * per_bar], starts[: n_bars * per_bar]
    measure_times = [float(grid[k * per_bar]) for k in range(n_bars)]
    end_time = float(grid[n_bars * per_bar]) if n_bars * per_bar < len(grid) else float(grid[-1])
    sign = "♯" if fifths > 0 else "♭" if fifths < 0 else "Vorzeichen"
    progress(f"{n_bars} Takte, Tempo ca. {tempo:.0f}, Tonart {'Dur' if major else 'Moll'} mit {abs(fifths)} {sign} (klingend)")
    label = _label(conf)
    progress(f"Sicherheit der Erkennung: {label} ({conf:.0%})")

    xml, n_notes = _to_musicxml(cells, n_bars, per_bar, beats_per_bar, tempo, fifths, title, composer, starts)
    voiced_ratio = sum(c is not None for c in cells) / max(1, len(cells))
    return Draft(xml, measure_times, end_time, duration, tempo, beats_per_bar, fifths, n_notes, voiced_ratio,
                 mode, conf, label)


def _to_musicxml(cells, n_bars, per_bar, beats_per_bar, tempo, fifths_concert, title, composer,
                 starts=None) -> tuple[str, int]:
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
        st = starts[bar * per_bar:(bar + 1) * per_bar] if starts else [False] * len(seg)
        # Läufe gleicher Tonhöhe (neuer Ton bei neuem Anschlag, auch wenn gleich hoch)
        runs = []
        for c, new in zip(seg, st):
            if runs and runs[-1][0] == c and not (new and c is not None):
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
