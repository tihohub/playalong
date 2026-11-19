"""MusicXML einlesen und eine Zeitleiste erzeugen.

Entspricht `player/src/musicxml/timeline.ts`: gleiche Regeln für Wiederholungen,
Volten, D.C./D.S./Coda/Fine und Tempi. Nur so passen die Taktindizes in
`sync.json` zu dem, was der Player abspielt. Änderungen bitte immer in beiden
Dateien nachziehen.

Positionen sind in Viertelnoten ab Stückbeginn (nach Auflösen der Wiederholungen).
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

STEP_SEMI = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
BEAT_UNIT = {"whole": 4, "half": 2, "quarter": 1, "eighth": 0.5, "16th": 0.25, "32nd": 0.125}
DYN = {"pppp": 0.25, "ppp": 0.3, "pp": 0.38, "p": 0.48, "mp": 0.58, "mf": 0.68, "f": 0.8,
       "ff": 0.9, "fff": 1, "ffff": 1, "sf": 0.85, "sfz": 0.85, "fp": 0.8}
CADENZA_RE = re.compile(r"a\s*piacere|ad\s*lib|cadenz|kadenz|senza\s*tempo|colla\s*parte|rubato\s*ad", re.I)


@dataclass
class Note:
    part: str
    start: float  # Viertel
    dur: float
    midi: int
    vel: float


@dataclass
class PlayedMeasure:
    index: int  # Index des gespielten Takts (wie im Player)
    src: int  # Index des Quelltakts
    label: str  # Taktnummer laut Partitur
    start: float
    length: float


@dataclass
class Timeline:
    title: str
    composer: str
    measures: list[PlayedMeasure]
    notes: list[Note]
    tempos: list[tuple[float, float]]  # (Position, Viertel pro Minute)
    fermatas: list[tuple[float, float]]  # (Position, Ende)
    length: float
    # Einsätze von Schlagzeug ohne Tonhöhe (Position, Stärke) – nur für den Abgleich
    unpitched: list[tuple[float, float]] = field(default_factory=list)

    # ---- Zeitumrechnung bei notiertem Tempo (100 %) ----
    def seconds(self, pos: float) -> float:
        t = 0.0
        for k, (p, q) in enumerate(self.tempos):
            nxt = self.tempos[k + 1][0] if k + 1 < len(self.tempos) else float("inf")
            if pos <= p:
                break
            t += (min(pos, nxt) - p) / (q / 60.0)
        return t

    @property
    def duration(self) -> float:
        return self.seconds(self.length)


@dataclass
class _Raw:
    label: str
    length: float = 0.0
    beats: int = 4
    beat_type: int = 4
    notes: list[dict] = field(default_factory=list)
    unpitched: list[tuple[float, float]] = field(default_factory=list)
    tempos: list[tuple[float, float]] = field(default_factory=list)
    metro_tempos: list[tuple[float, float]] = field(default_factory=list)
    fermatas: list[tuple[float, float]] = field(default_factory=list)
    cadenza: bool = False
    repeat_forward: bool = False
    repeat_backward: bool = False
    repeat_times: int = 2
    ending_start: list[int] | None = None
    ending_stop: bool = False
    segno: bool = False
    coda: bool = False
    to_coda: bool = False
    da_capo: bool = False
    dal_segno: bool = False
    fine: bool = False


def _t(el: ET.Element | None) -> str:
    return (el.text or "").strip() if el is not None else ""


def _num(el: ET.Element | None, default: float = 0.0) -> float:
    try:
        return float(_t(el))
    except ValueError:
        return default


def _add_tempo(lst: list[tuple[float, float]], rel: float, qpm: float) -> None:
    if not any(abs(r - rel) < 1e-6 for r, _ in lst):
        lst.append((rel, qpm))


def _read_sound(s: ET.Element, m: _Raw, rel: float) -> None:
    tempo = s.get("tempo")
    if tempo:
        try:
            q = float(tempo)
            if q > 0:
                _add_tempo(m.tempos, rel, q)
        except ValueError:
            pass
    if s.get("segno") is not None:
        m.segno = True
    if s.get("coda") is not None:
        m.coda = True
    if s.get("tocoda") is not None:
        m.to_coda = True
    if s.get("dacapo") == "yes":
        m.da_capo = True
    if s.get("dalsegno") is not None:
        m.dal_segno = True
    if s.get("fine") is not None:
        m.fine = True


def load_musicxml(path: str | Path) -> ET.Element:
    """Liest .musicxml/.xml oder komprimiertes .mxl und gibt das Wurzelelement zurück."""
    path = Path(path)
    data = path.read_bytes()
    if data[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(path) as z:
            name = None
            if "META-INF/container.xml" in z.namelist():
                cont = ET.fromstring(z.read("META-INF/container.xml"))
                for el in cont.iter():
                    if el.tag.endswith("rootfile") and el.get("full-path"):
                        name = el.get("full-path")
                        break
            if not name:
                name = next(n for n in z.namelist() if re.search(r"\.(musicxml|xml)$", n, re.I) and not n.startswith("META-INF"))
            data = z.read(name)
    root = ET.fromstring(data)
    if root.tag == "score-timewise":
        raise ValueError("MusicXML im Format „timewise“ wird nicht unterstützt.")
    if root.tag != "score-partwise":
        raise ValueError("Das ist keine MusicXML-Partitur.")
    return root


def _read_measures(root: ET.Element) -> list[_Raw]:
    result: list[_Raw] = []
    for part_index, part in enumerate(root.findall("part")):
        pid = part.get("id") or f"P{part_index}"
        first = part_index == 0
        divisions = 1.0
        transpose = 0.0
        beats, beat_type = 4, 4
        vel = 0.7
        for mi, m_el in enumerate(part.findall("measure")):
            if mi >= len(result):
                result.append(_Raw(label=m_el.get("number") or str(mi + 1)))
            m = result[mi]
            pos = 0.0
            max_pos = 0.0
            last_onset = 0.0
            for el in m_el:
                tag = el.tag
                if tag == "attributes":
                    d = el.find("divisions")
                    if d is not None:
                        divisions = _num(d, 1) or 1
                    time = el.find("time")
                    if time is not None and time.find("beats") is not None:
                        s = sum(int(x) for x in re.findall(r"\d+", _t(time.find("beats"))))
                        beats = s if s > 0 else 4
                        beat_type = int(_num(time.find("beat-type"), 4)) or 4
                    tr = el.find("transpose")
                    if tr is not None:
                        transpose = _num(tr.find("chromatic")) + 12 * _num(tr.find("octave-change"))
                elif tag == "note":
                    if el.find("grace") is not None or el.find("cue") is not None:
                        continue
                    dur = _num(el.find("duration"))
                    is_chord = el.find("chord") is not None
                    onset = last_onset if is_chord else pos
                    pitch = el.find("pitch")
                    notations = el.find("notations")
                    if notations is not None and notations.find("fermata") is not None:
                        m.fermatas.append((onset / divisions, dur / divisions))
                    if pitch is not None and dur > 0:
                        step = _t(pitch.find("step")).upper()
                        midi = (12 * (_num(pitch.find("octave"), 4) + 1) + STEP_SEMI.get(step, 0)
                                + _num(pitch.find("alter")) + transpose)
                        ties = [x.get("type") for x in el.findall("tie")]
                        dyn_attr = el.get("dynamics")
                        m.notes.append({
                            "part": pid, "rel": onset / divisions, "dur": dur / divisions,
                            "midi": int(round(midi)),
                            "vel": min(1.0, float(dyn_attr) / 100) if dyn_attr else vel,
                            "tie_start": "start" in ties, "tie_stop": "stop" in ties,
                        })
                    if el.find("unpitched") is not None and dur > 0 and not is_chord:
                        m.unpitched.append((onset / divisions, vel))
                    if not is_chord:
                        last_onset = pos
                        pos += dur
                elif tag == "backup":
                    pos = max(0.0, pos - _num(el.find("duration")))
                elif tag == "forward":
                    pos += _num(el.find("duration"))
                elif tag == "direction":
                    rel = (pos + _num(el.find("offset"))) / divisions
                    for dt in el.findall("direction-type"):
                        for c in dt:
                            if c.tag == "words" and _t(c):
                                w = _t(c)
                                if CADENZA_RE.search(w):
                                    m.cadenza = True
                                if re.match(r"^\s*(to\s+coda|zur\s+coda)", w, re.I):
                                    m.to_coda = True
                                if re.match(r"^\s*d\.\s*c\.", w, re.I) or re.match(r"^\s*da\s+capo", w, re.I):
                                    m.da_capo = True
                                if re.match(r"^\s*d\.\s*s\.", w, re.I) or re.match(r"^\s*dal\s+segno", w, re.I):
                                    m.dal_segno = True
                                if re.match(r"^\s*fine\s*$", w, re.I):
                                    m.fine = True
                            elif c.tag == "segno":
                                m.segno = True
                            elif c.tag == "coda":
                                m.coda = True
                            elif c.tag == "dynamics" and len(c):
                                d = c[0].tag
                                if d in DYN:
                                    vel = DYN[d]
                            elif c.tag == "metronome":
                                unit = BEAT_UNIT.get(_t(c.find("beat-unit")), 1)
                                dots = len(c.findall("beat-unit-dot"))
                                pm = _num(c.find("per-minute"))
                                if pm > 0:
                                    _add_tempo(m.metro_tempos, rel, pm * unit * (1.5 if dots else 1))
                    snd = el.find("sound")
                    if snd is not None:
                        _read_sound(snd, m, rel)
                        dyn = snd.get("dynamics")
                        if dyn:
                            try:
                                vel = min(1.0, float(dyn) / 100) or vel
                            except ValueError:
                                pass
                elif tag == "sound":
                    _read_sound(el, m, pos / divisions)
                elif tag == "barline":
                    rep = el.find("repeat")
                    if rep is not None and rep.get("direction") == "forward":
                        m.repeat_forward = True
                    if rep is not None and rep.get("direction") == "backward":
                        m.repeat_backward = True
                        try:
                            times = int(rep.get("times") or "")
                            if times > 0:
                                m.repeat_times = times
                        except ValueError:
                            pass
                    end = el.find("ending")
                    if end is not None:
                        if end.get("type") == "start":
                            m.ending_start = [int(x) for x in re.split(r"[,\s]+", end.get("number") or "1") if x.isdigit() and int(x) > 0]
                        else:
                            m.ending_stop = True
                    if el.find("segno") is not None:
                        m.segno = True
                    if el.find("coda") is not None:
                        m.coda = True
                    snd = el.find("sound")
                    if snd is not None:
                        _read_sound(snd, m, pos / divisions)
                max_pos = max(max_pos, pos)
            if first:
                m.beats, m.beat_type = beats, beat_type
            m.length = max(m.length, max_pos / divisions)

    for m in result:
        expected = m.beats * 4 / m.beat_type
        if m.length <= 0:
            m.length = expected
        elif abs(m.length - expected) < 0.02:
            m.length = expected
        if not m.tempos:
            m.tempos = m.metro_tempos
    return result


def _unroll(raw: list[_Raw]) -> list[int]:
    n = len(raw)
    order: list[int] = []
    passes: dict[int, int] = {}
    ending_end: dict[int, int] = {}
    ending_last: dict[int, bool] = {}
    for i in range(n):
        if not raw[i].ending_start:
            continue
        j = i
        while j < n - 1 and not raw[j].ending_stop and not (j > i and raw[j].ending_start):
            j += 1
        if j > i and raw[j].ending_start and not raw[j].ending_stop:
            j -= 1
        ending_end[i] = j
        ending_last[i] = not (j + 1 < n and raw[j + 1].ending_start)
    segno_idx = next((k for k, m in enumerate(raw) if m.segno), -1)

    i = 0
    repeat_start = 0
    pass_ = 1
    jumped = False
    guard = 0
    while i < n and guard < 20000:
        guard += 1
        m = raw[i]
        if m.repeat_forward and not jumped:
            repeat_start = i
        if m.ending_start:
            if jumped:
                skip = not ending_last.get(i, False)
            else:
                skip = pass_ not in m.ending_start and not (pass_ > max(m.ending_start) and ending_last.get(i, False))
            if skip:
                i = ending_end.get(i, i) + 1
                continue
        order.append(i)
        if jumped and m.fine:
            break
        if jumped and m.to_coda:
            target = next((k for k in range(i + 1, n) if raw[k].coda), -1)
            if target >= 0:
                i = target
                continue
        if m.repeat_backward and not jumped:
            done = passes.get(i, 1)
            if done < m.repeat_times:
                passes[i] = done + 1
                pass_ = done + 1
                i = repeat_start
                continue
            passes.pop(i, None)
            pass_ = 1
            repeat_start = i + 1
        if m.da_capo and not jumped:
            jumped, pass_, i = True, 1, 0
            continue
        if m.dal_segno and not jumped and segno_idx >= 0:
            jumped, pass_, i = True, 1, segno_idx
            continue
        i += 1
    return order


def build_timeline(root: ET.Element) -> Timeline:
    raw = _read_measures(root)
    order = _unroll(raw)
    measures: list[PlayedMeasure] = []
    notes: list[Note] = []
    tempos: list[tuple[float, float]] = []
    fermatas: list[tuple[float, float]] = []
    open_ties: dict[str, Note] = {}
    unpitched: list[tuple[float, float]] = []
    pos = 0.0
    for k, si in enumerate(order):
        m = raw[si]
        measures.append(PlayedMeasure(index=k, src=si, label=m.label, start=pos, length=m.length))
        tempos.extend((pos + rel, q) for rel, q in m.tempos)
        for rn in m.notes:
            start = pos + rn["rel"]
            key = f'{rn["part"]}:{rn["midi"]}'
            prev = open_ties.get(key)
            if rn["tie_stop"] and prev is not None and abs(prev.start + prev.dur - start) < 1e-6:
                prev.dur += rn["dur"]
                if not rn["tie_start"]:
                    open_ties.pop(key, None)
                continue
            ev = Note(rn["part"], start, rn["dur"], rn["midi"], rn["vel"])
            notes.append(ev)
            if rn["tie_start"]:
                open_ties[key] = ev
            else:
                open_ties.pop(key, None)
        unpitched.extend((pos + rel, v) for rel, v in m.unpitched)
        if not m.cadenza:
            fermatas.extend((pos + rel, pos + rel + d) for rel, d in m.fermatas)
        pos += m.length

    notes.sort(key=lambda x: (x.start, x.midi))
    tempos.sort(key=lambda x: x[0])
    if not tempos or tempos[0][0] > 1e-6:
        tempos.insert(0, (0.0, tempos[0][1] if tempos else 120.0))

    def text(path: str) -> str:
        el = root.find(path)
        return (el.text or "").strip() if el is not None and el.text else ""

    title = text("work/work-title") or text("movement-title")
    composer = ""
    for c in root.iter("creator"):
        if c.get("type") == "composer" and c.text:
            composer = c.text.strip()
            break
    return Timeline(title=title, composer=composer, measures=measures, notes=notes,
                    tempos=tempos, fermatas=sorted(fermatas), length=pos, unpitched=sorted(unpitched))
