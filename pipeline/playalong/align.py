"""Audio-Score-Alignment: Aufnahme (MP3) und Partitur synchronisieren.

Vorgehen (nur CPU):
1. Merkmale aus der Aufnahme: Tonklassen-Energie (Chroma) aus einer Halbton-
   Spektralanalyse (CQT), „Einsatz-Chroma“ (Zunahme der Energie je Tonklasse) und
   ein Rhythmus-Merkmal (allgemeine Einsatzstärke, prägt v. a. das Schlagzeug).
2. Dieselben Merkmale aus der Partitur (bei notiertem Tempo, inkl. Schlagzeug).
3. Dynamic Time Warping, 1. Durchgang: grob (ca. 0,19 s) über das ganze Stück,
   dann fein (ca. 23 ms) in einem Korridor um den groben Pfad.
4. 2. Durchgang: Partitur auf das gefundene Tempo strecken und nur noch die
   Feinabweichung abgleichen.
5. Zuordnung nur an Noteneinsätzen verankern, dazwischen interpolieren, und die
   Startzeit jedes gespielten Takts ablesen.

Gemessen am Testmaterial (Orchester, MuseScore-Export, auch zeitlich verzerrt
mit ±15 % Tempo und Generalpause): Median 23–40 ms, 95 % der Takte < 0,1 s.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numba import njit

from .score import Timeline

SR = 22050
HOP = 512
FPS = SR / HOP  # ca. 43 Bilder pro Sekunde
COARSE = 8  # Vergröberung für die erste Stufe
RADIUS = 24  # Korridor-Breite der feinen Stufe (in feinen Bildern, je Seite)
MIDI_MIN = 24  # C1
ONSET_W = 0.6  # Gewicht Einsatz-Chroma
BB_W = 1.5  # Gewicht Rhythmus (allgemeine Einsatzstärke, inkl. Schlagzeug)
N_BINS = 84  # 7 Oktaven


@dataclass
class SyncResult:
    measure_times: list[float]  # Startzeit jedes gespielten Takts in Sekunden
    end_time: float
    audio_duration: float
    measure_cost: list[float]  # mittlere Abweichung je Takt (0 = perfekt, ~1 = unpassend)
    path: np.ndarray  # feiner Pfad (Partiturbild, Audiobild)


# --------------------------------------------------------------------------- Merkmale

def _normalize(x: np.ndarray, floor: float) -> np.ndarray:
    """Jede Spalte auf Länge 1 bringen; leise Spalten werden zu einem gleichmäßigen Vektor."""
    n = np.linalg.norm(x, axis=0, keepdims=True)
    uniform = np.full((x.shape[0], 1), 1 / np.sqrt(x.shape[0]))
    out = np.where(n > floor, x / np.maximum(n, 1e-12), uniform)
    return out.astype(np.float32)


def _decay(x: np.ndarray, frames: int = 10) -> np.ndarray:
    """Einsätze mit exponentiellem Abklingen verschmieren (macht den Abgleich robuster)."""
    k = np.exp(-np.arange(frames) / (frames / 3))
    out = np.zeros_like(x)
    for i, w in enumerate(k):
        out[:, i:] += w * x[:, : x.shape[1] - i]
    return out


def _fold(semitones: np.ndarray, midi_min: int) -> np.ndarray:
    chroma = np.zeros((12, semitones.shape[1]), dtype=np.float64)
    for b in range(semitones.shape[0]):
        chroma[(midi_min + b) % 12] += semitones[b]
    return chroma


def _rhythm(x: np.ndarray) -> np.ndarray:
    """Einsatzstärke leicht glätten und auf 0..1 bringen."""
    k = np.array([0.25, 0.5, 1.0, 0.5, 0.25])
    y = np.convolve(x, k / k.sum(), mode="same")
    return np.clip(y / (np.percentile(y, 99) + 1e-9), 0, 1).astype(np.float32)


def audio_features(path: str):
    """Gibt (Chroma, Einsatz-Chroma, Dauer, erstes/letztes hörbares Bild, Einsatz-Hüllkurve) zurück."""
    import librosa

    y, _ = librosa.load(path, sr=SR, mono=True)
    duration = len(y) / SR
    C = np.abs(librosa.cqt(y, sr=SR, hop_length=HOP, fmin=librosa.midi_to_hz(MIDI_MIN),
                           n_bins=N_BINS, bins_per_octave=12))
    E = C ** 2  # Energie: trennt in Tests deutlich besser als logarithmische Werte
    chroma = _fold(E, MIDI_MIN)
    lag = 3
    diff = np.maximum(0, E - np.concatenate([E[:, :lag], E[:, :-lag]], axis=1))
    onset = _decay(_fold(diff, MIDI_MIN))
    # Stille am Anfang/Ende erkennen
    energy = E.sum(axis=0)
    thr = 1e-3 * np.percentile(energy, 95)
    loud = np.nonzero(energy > thr)[0]
    first, last = (int(loud[0]), int(loud[-1])) if len(loud) else (0, L.shape[1] - 1)
    bb = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP)[: E.shape[1]]
    bb = np.pad(bb, (0, E.shape[1] - len(bb)))
    return (_normalize(chroma, 1e-6 * chroma.max()), _normalize(onset, 1e-6 * max(onset.max(), 1e-12)),
            duration, first, last, _rhythm(bb))


def score_features(tl: Timeline):
    """Merkmale aus den Noten bei notiertem Tempo. Gibt außerdem erstes/letztes klingendes Bild zurück."""
    n_frames = int(np.ceil(tl.duration * FPS)) + 1
    act = np.zeros((12, n_frames))
    ons = np.zeros((12, n_frames))
    bb = np.zeros(n_frames)
    first, last = n_frames, 0
    for n in tl.notes:
        a = int(round(tl.seconds(n.start) * FPS))
        b = max(a + 1, int(round(tl.seconds(n.start + n.dur) * FPS)))
        b = min(b, n_frames)
        if a >= n_frames:
            continue
        pc = n.midi % 12
        act[pc, a:b] += n.vel
        ons[pc, a] += n.vel
        bb[a] += n.vel
        first, last = min(first, a), max(last, b - 1)
    if first > last:
        first, last = 0, n_frames - 1
    for p_, v in tl.unpitched:
        a = int(round(tl.seconds(p_) * FPS))
        if a < n_frames:
            bb[a] += 2 * v
    return _normalize(act, 1e-6), _normalize(_decay(ons), 1e-6), first, last, _rhythm(np.sqrt(bb))


# --------------------------------------------------------------------------- DTW

def _cost(sc, so, sb, ac, ao, ab) -> np.ndarray:
    # Kosinus-Abstand (Chroma, Einsatz-Chroma) + Unterschied der Einsatzstärke
    return (1 - sc.T @ ac) + ONSET_W * (1 - so.T @ ao) + BB_W * np.abs(sb[:, None] - ab[None, :])


def _pool1(x: np.ndarray, f: int) -> np.ndarray:
    n = len(x) // f * f
    p = x[:n].reshape(-1, f).max(axis=1)
    if len(x) > n:
        p = np.concatenate([p, [x[n:].max()]])
    return p


def _pool(x: np.ndarray, f: int) -> np.ndarray:
    n = x.shape[1] // f * f
    p = x[:, :n].reshape(x.shape[0], -1, f).mean(axis=2)
    if x.shape[1] > n:
        p = np.concatenate([p, x[:, n:].mean(axis=1, keepdims=True)], axis=1)
    return _normalize(p, 1e-6)


# Erlaubte Schritte (Partitur, Aufnahme): diagonal, nur Partitur, nur Aufnahme.
# Waagerechte/senkrechte Schritte kosten mehr, damit der Pfad in ähnlichen Passagen
# nicht „hängen bleibt“. 1. Durchgang moderat (folgt Tempoänderungen),
# 2. Durchgang streng (nur noch Feinabweichung nach Vorentzerrung).
STEPS = np.array([[1, 1], [1, 0], [0, 1]], dtype=np.int64)
WEIGHTS_1 = np.array([1.0, 2.0, 2.0])
WEIGHTS_2 = np.array([1.0, 3.0, 3.0])
RADIUS_2 = 30  # Korridor im 2. Durchgang (ca. 0,7 s je Seite)


@njit(cache=True)
def _banded_dtw(sc, so, sb, ac, ao, ab, lo, hi, steps, weights, onset_w, bb_w):
    """DTW nur innerhalb des Korridors [lo[i], hi[i]] je Partiturbild i (numba-beschleunigt)."""
    n = sc.shape[1]
    width = 0
    for i in range(n):
        width = max(width, hi[i] - lo[i] + 1)
    inf = 1e18
    D = np.full((n, width), inf)
    S = np.full((n, width), -1, dtype=np.int8)
    for i in range(n):
        for jj in range(hi[i] - lo[i] + 1):
            j = lo[i] + jj
            c = 1.0
            c2 = 1.0
            for k in range(sc.shape[0]):
                c -= sc[k, i] * ac[k, j]
            for k in range(so.shape[0]):
                c2 -= so[k, i] * ao[k, j]
            cost = c + onset_w * c2 + bb_w * abs(sb[i] - ab[j])
            if i == 0 and j == 0:
                D[0, jj] = cost
                continue
            best = inf
            step = -1
            for s in range(steps.shape[0]):
                pi = i - steps[s, 0]
                pj = j - steps[s, 1]
                if pi < 0 or pj < 0:
                    continue
                pjj = pj - lo[pi]
                if pjj < 0 or pj > hi[pi]:
                    continue
                v = D[pi, pjj] + weights[s] * cost
                if v < best:
                    best = v
                    step = s
            if step >= 0:
                D[i, jj] = best
                S[i, jj] = step
    # Rückverfolgung vom Ende
    path = np.zeros((n + hi[n - 1] + 2, 2), dtype=np.int64)
    i = n - 1
    j = hi[n - 1]
    k = 0
    while True:
        path[k, 0] = i
        path[k, 1] = j
        k += 1
        if i == 0 and j == 0:
            break
        s = S[i, j - lo[i]]
        if s < 0:
            break
        i -= steps[s, 0]
        j -= steps[s, 1]
    return path[:k][::-1]


def _fill_path(path: np.ndarray) -> np.ndarray:
    """Sprünge (2,1)/(3,1) usw. zu lückenlosen Schritten auffüllen."""
    out = [path[0]]
    for (i0, j0), (i1, j1) in zip(path[:-1], path[1:]):
        di, dj = i1 - i0, j1 - j0
        n = max(di, dj)
        for k in range(1, n + 1):
            out.append((i0 + round(di * k / n), j0 + round(dj * k / n)))
    return np.array(out, dtype=np.int64)


def _first_match(path: np.ndarray, n: int) -> np.ndarray:
    """Für jede Zeile i des Pfads das erste zugeordnete Spaltenbild."""
    out = np.full(n, -1.0)
    for i, j in path:
        if out[i] < 0:
            out[i] = j
    # Lücken (sollten nach _fill_path nicht vorkommen) linear schließen
    bad = out < 0
    if bad.any():
        idx = np.arange(n)
        out[bad] = np.interp(idx[bad], idx[~bad], out[~bad])
    return out


def _corridor(path: np.ndarray, n: int, m: int, scale: int, radius: int) -> tuple[np.ndarray, np.ndarray]:
    lo = np.full(n, m, dtype=np.int64)
    hi = np.zeros(n, dtype=np.int64)
    for ic, jc in path:
        i0, i1 = ic * scale, min(n, (ic + 1) * scale)
        j0, j1 = jc * scale, min(m - 1, (jc + 1) * scale - 1)
        lo[i0:i1] = np.minimum(lo[i0:i1], j0)
        hi[i0:i1] = np.maximum(hi[i0:i1], j1)
    return _finish_corridor(lo - radius, hi + radius, m)


def _finish_corridor(lo: np.ndarray, hi: np.ndarray, m: int) -> tuple[np.ndarray, np.ndarray]:
    lo = np.clip(lo, 0, m - 1)
    hi = np.clip(hi, 0, m - 1)
    lo = np.maximum.accumulate(lo)
    hi = np.minimum.accumulate(hi[::-1])[::-1]
    hi = np.maximum(hi, lo)
    lo[0] = 0
    hi[-1] = m - 1
    return lo, hi


def _dtw_path(sc, so, sb, ac, ao, ab, lo, hi, weights) -> np.ndarray:
    path = _banded_dtw(sc, so, sb, ac, ao, ab, lo, hi, STEPS, weights, ONSET_W, BB_W)
    if path[0, 0] != 0 or path[0, 1] != 0:
        raise RuntimeError("Abgleich fehlgeschlagen: kein durchgehender Pfad gefunden.")
    return _fill_path(path)


def align(tl: Timeline, audio_path: str, progress=print) -> SyncResult:
    import librosa

    progress("Aufnahme wird analysiert …")
    ac, ao, audio_dur, a_first, a_last, ab = audio_features(audio_path)
    progress("Partitur wird analysiert …")
    sc, so, s_first, s_last, sb = score_features(tl)

    # Nur den klingenden Teil abgleichen (Stille am Anfang/Ende ignorieren)
    sc_, so_, sb_ = sc[:, s_first:s_last + 1], so[:, s_first:s_last + 1], sb[s_first:s_last + 1]
    ac_, ao_, ab_ = ac[:, a_first:a_last + 1], ao[:, a_first:a_last + 1], ab[a_first:a_last + 1]
    n, m = sc_.shape[1], ac_.shape[1]

    # 1. Durchgang: grob über das ganze Stück, dann fein im Korridor
    progress("Abgleich, 1. Durchgang …")
    Cc = _cost(_pool(sc_, COARSE), _pool(so_, COARSE), _pool1(sb_, COARSE),
               _pool(ac_, COARSE), _pool(ao_, COARSE), _pool1(ab_, COARSE))
    _, wp = librosa.sequence.dtw(C=Cc, step_sizes_sigma=STEPS, weights_mul=WEIGHTS_1, backtrack=True)
    wp = _fill_path(wp[::-1])
    lo, hi = _corridor(wp, n, m, COARSE, RADIUS)
    f1 = _first_match(_dtw_path(sc_, so_, sb_, ac_, ao_, ab_, lo, hi, WEIGHTS_1), n)

    # 2. Durchgang: Partitur auf das gefundene Tempo strecken, dann nur noch Feinabgleich
    progress("Abgleich, 2. Durchgang …")
    f1s = f1 + np.arange(n) * 1e-6  # streng steigend für die Umkehrung
    i_of_j = np.clip(np.round(np.interp(np.arange(m), f1s, np.arange(n))), 0, n - 1).astype(np.int64)
    scw, sow = np.ascontiguousarray(sc_[:, i_of_j]), np.ascontiguousarray(so_[:, i_of_j])
    sbw = np.ascontiguousarray(sb_[i_of_j])
    diag = np.arange(m)
    lo2, hi2 = _finish_corridor(diag - RADIUS_2, diag + RADIUS_2, m)
    path2 = _dtw_path(scw, sow, sbw, ac_, ao_, ab_, lo2, hi2, WEIGHTS_2)
    g = _first_match(path2, m)
    first_audio = np.interp(f1, np.arange(m), g)  # Partiturbild -> Audiobild

    # Nur an Noteneinsätzen verankern: zwischen den Einsätzen (gehaltene Töne, Pausen)
    # ist die Zuordnung unbestimmt, dort wird im lokalen Tempo interpoliert.
    onset_frames = np.unique(np.clip(np.array(
        [int(round(tl.seconds(nn.start) * FPS)) - s_first for nn in tl.notes]), 0, n - 1))
    if len(onset_frames) >= 2:
        anchors = np.unique(np.concatenate([[0], onset_frames, [n - 1]]))
        vals = np.maximum.accumulate(first_audio[anchors])
        first_audio = np.interp(np.arange(n), anchors, vals)

    a_off = a_first / FPS

    def score_to_audio(t_score: float) -> float:
        x = t_score * FPS - s_first
        if x <= 0:
            return a_off + x / FPS  # vor dem ersten Ton: notiertes Tempo
        if x >= n - 1:
            return a_off + first_audio[n - 1] / FPS + (x - (n - 1)) / FPS
        i = int(np.floor(x))
        f = x - i
        return a_off + ((1 - f) * first_audio[i] + f * first_audio[i + 1]) / FPS

    starts = [tl.seconds(mm.start) for mm in tl.measures]
    times = [max(0.0, score_to_audio(t)) for t in starts]
    end_time = min(audio_dur, score_to_audio(tl.duration))

    # Güte je Takt: Abweichung zwischen Partitur und Aufnahme entlang der Zuordnung (0 = perfekt)
    jj = np.clip(np.round(first_audio).astype(np.int64), 0, m - 1)
    cost_i = ((1 - np.sum(sc_ * ac_[:, jj], axis=0)) + ONSET_W * (1 - np.sum(so_ * ao_[:, jj], axis=0))
              + BB_W * np.abs(sb_ - ab_[jj])) / (1 + ONSET_W + BB_W)
    mcost = []
    for k, t0 in enumerate(starts):
        t1 = starts[k + 1] if k + 1 < len(starts) else tl.duration
        a = int(max(0, t0 * FPS - s_first))
        b = int(min(n, max(a + 1, t1 * FPS - s_first)))
        mcost.append(float(cost_i[a:b].mean()) if b > a else 0.0)

    full_path = np.stack([np.arange(n) + s_first, first_audio + a_first], axis=1)
    return SyncResult(measure_times=times, end_time=end_time, audio_duration=audio_dur,
                      measure_cost=mcost, path=full_path)


def sync_json(tl: Timeline, res: SyncResult, audio_name: str) -> dict:
    """Format laut docs/liedpaket-format.md"""
    return {
        "version": 1,
        "audio": audio_name,
        "duration": round(res.audio_duration, 3),
        "end": round(res.end_time, 3),
        "measures": [
            {"index": mm.index, "label": mm.label, "time": round(t, 3)}
            for mm, t in zip(tl.measures, res.measure_times)
        ],
    }
