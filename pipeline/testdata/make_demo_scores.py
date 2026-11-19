#!/usr/bin/env python3
"""Erzeugt die gemeinfreien Demo-Partituren für Play-along.

Beide Stücke sind eigens für dieses Projekt komponiert (CC0 / gemeinfrei).

    python make_demo_scores.py <zielordner>

Ausgabe:
  uebungsstueck.musicxml – Klarinette in B (transponiert notiert) + Klavier,
                           mit Wiederholung, Tempowechseln, Fermaten,
                           Mehrtaktpause, Altissimo, 32teln und Kadenz (a piacere).
  etuede.musicxml        – Klarinette solo, KLINGEND notiert (ohne <transpose>),
                           zum Testen der automatischen Transposition und des
                           Metronom-Modus.
"""
from __future__ import annotations

import sys
from pathlib import Path
from xml.sax.saxutils import escape

DIV = 24  # divisions pro Viertel (erlaubt 32tel = 3 und Triolen)
DUR = {"w": 96, "h.": 72, "h": 48, "q.": 36, "q": 24, "e.": 18, "e": 12, "s": 6, "t": 3}
TYPE = {"w": "whole", "h": "half", "q": "quarter", "e": "eighth", "s": "16th", "t": "32nd"}
STEPS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def pitch_xml(p: str) -> str:
    """'C5', 'Bb3', 'F#4' -> <pitch>"""
    step, rest = p[0], p[1:]
    alter = 0
    while rest and rest[0] in "b#":
        alter += -1 if rest[0] == "b" else 1
        rest = rest[1:]
    a = f"<alter>{alter}</alter>" if alter else ""
    return f"<pitch><step>{step}</step>{a}<octave>{rest}</octave></pitch>"


def note(p: str | None, d: str, *, chord=False, staff=None, voice=1, fermata=False,
         tie: str | None = None, accidental: str | None = None) -> str:
    """p=None -> Pause. d z.B. 'q', 'h.'"""
    base = d.rstrip(".")
    dots = len(d) - len(base)
    out = ["<note>"]
    if chord:
        out.append("<chord/>")
    out.append("<rest/>" if p is None else pitch_xml(p))
    out.append(f"<duration>{DUR[d]}</duration>")
    if tie in ("start", "stop"):
        out.append(f'<tie type="{tie}"/>')
    out.append(f"<voice>{voice}</voice><type>{TYPE[base]}</type>")
    out.extend(["<dot/>"] * dots)
    if accidental:
        out.append(f"<accidental>{accidental}</accidental>")
    if staff:
        out.append(f"<staff>{staff}</staff>")
    nots = []
    if fermata:
        nots.append('<fermata type="upright"/>')
    if tie in ("start", "stop"):
        nots.append(f'<tied type="{tie}"/>')
    if nots:
        out.append("<notations>" + "".join(nots) + "</notations>")
    out.append("</note>")
    return "".join(out)


def whole_rest(measure_len: int, staff=None, voice=1) -> str:
    s = f"<staff>{staff}</staff>" if staff else ""
    return (f'<note><rest measure="yes"/><duration>{measure_len}</duration>'
            f"<voice>{voice}</voice>{s}</note>")


def seq(spec: str, **kw) -> str:
    """'C5:q E5:q G5:h' -> Noten. Pause: 'r:q'. Fermate: Suffix '!'. Akkord: 'C4+E4+G4:q'."""
    out = []
    for tok in spec.split():
        fermata = tok.endswith("!")
        tok = tok.rstrip("!")
        p, d = tok.split(":")
        if p == "r":
            out.append(note(None, d, fermata=fermata, **kw))
            continue
        for i, single in enumerate(p.split("+")):
            out.append(note(single, d, chord=i > 0, fermata=fermata and i == 0, **kw))
    return "".join(out)


def backup(n: int) -> str:
    return f"<backup><duration>{n}</duration></backup>"


def direction(*, words=None, rehearsal=None, tempo=None, beat="quarter", dotted=False,
              placement="above", staff=None) -> str:
    types = []
    if rehearsal:
        types.append(f'<direction-type><rehearsal enclosure="square">{escape(rehearsal)}</rehearsal></direction-type>')
    if words:
        types.append(f'<direction-type><words font-weight="bold">{escape(words)}</words></direction-type>')
    if tempo:
        dot = "<beat-unit-dot/>" if dotted else ""
        types.append(f"<direction-type><metronome><beat-unit>{beat}</beat-unit>{dot}"
                     f"<per-minute>{tempo}</per-minute></metronome></direction-type>")
    st = f"<staff>{staff}</staff>" if staff else ""
    snd = f'<sound tempo="{tempo * (1.5 if dotted else 1) * (0.5 if beat == "eighth" else 1):g}"/>' if tempo else ""
    return f'<direction placement="{placement}">{"".join(types)}{st}{snd}</direction>'


def attributes(*, key=None, time=None, clefs=None, staves=None, transpose=None, divisions=True) -> str:
    out = ["<attributes>"]
    if divisions:
        out.append(f"<divisions>{DIV}</divisions>")
    if key is not None:
        out.append(f"<key><fifths>{key}</fifths></key>")
    if time:
        out.append(f"<time><beats>{time[0]}</beats><beat-type>{time[1]}</beat-type></time>")
    if staves:
        out.append(f"<staves>{staves}</staves>")
    for i, c in enumerate(clefs or [], start=1):
        num = f' number="{i}"' if staves else ""
        sign, line = c
        out.append(f"<clef{num}><sign>{sign}</sign><line>{line}</line></clef>")
    if transpose:
        out.append(f"<transpose><diatonic>{transpose[0]}</diatonic><chromatic>{transpose[1]}</chromatic></transpose>")
    out.append("</attributes>")
    return "".join(out)


def barline(*, repeat=None, style=None, location="right") -> str:
    s = f"<bar-style>{style}</bar-style>" if style else ""
    r = f'<repeat direction="{repeat}"/>' if repeat else ""
    return f'<barline location="{location}">{s}{r}</barline>'


def score(title: str, composer: str, parts: list[tuple[str, str, str, list[str]]]) -> str:
    """parts: (id, name, midi_program, measures_xml)"""
    plist = []
    for pid, name, prog, _ in parts:
        plist.append(
            f'<score-part id="{pid}"><part-name>{escape(name)}</part-name>'
            f'<score-instrument id="{pid}-I1"><instrument-name>{escape(name)}</instrument-name></score-instrument>'
            f'<midi-instrument id="{pid}-I1"><midi-program>{prog}</midi-program></midi-instrument></score-part>')
    body = []
    for pid, _, _, measures in parts:
        ms = "".join(f'<measure number="{i}">{m}</measure>' for i, m in enumerate(measures, start=1))
        body.append(f'<part id="{pid}">{ms}</part>')
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
            '"http://www.musicxml.org/dtds/partwise.dtd">\n'
            '<score-partwise version="4.0">'
            f"<work><work-title>{escape(title)}</work-title></work>"
            f'<identification><creator type="composer">{escape(composer)}</creator>'
            "<rights>Gemeinfrei (CC0) – für Play-along erstellt</rights></identification>"
            f'<part-list>{"".join(plist)}</part-list>{"".join(body)}</score-partwise>\n')


# --------------------------------------------------------------------------
# Übungsstück: Klarinette in B + Klavier
# Konzert: B-Dur (2 b). Klarinette notiert: C-Dur, klingt große Sekunde tiefer.
# --------------------------------------------------------------------------

def uebungsstueck() -> str:
    M44, M34 = 96, 72
    cl: list[str] = []   # Klarinette (notiert)
    pr: list[str] = []   # Klavier (klingend), 2 Systeme

    def piano(rh: str, lh: str, pre: str = "", post: str = "", length: int = M44) -> str:
        return pre + seq(rh, staff=1, voice=1) + backup(length) + seq(lh, staff=2, voice=5) + post

    # --- A: Allegro moderato, 4/4, Takte 1–4 mit Wiederholung, 5–8 -----------
    cl.append(attributes(key=0, time=(4, 4), clefs=[("G", 2)], transpose=(-1, -2))
              + direction(rehearsal="A", words="Allegro moderato", tempo=104)
              + barline(repeat="forward", style="heavy-light", location="left")
              + seq("C5:q E5:q G5:q C6:q"))
    cl.append(seq("B5:e A5:e G5:e F5:e E5:h"))
    cl.append(seq("F5:q A5:q D6:q. C6:e"))
    cl.append(seq("B5:h G5:h") + barline(repeat="backward", style="light-heavy"))
    cl.append(seq("C6:s D6:s E6:s F6:s G6:s F6:s E6:s D6:s C6:q G5:q"))
    cl.append(seq("A5:e B5:e C6:e D6:e E6:h"))
    cl.append(seq("D6:q. C6:e B5:q D6:q"))
    cl.append(seq("C6:w!") + barline(style="light-light"))

    pr.append(attributes(key=-2, time=(4, 4), staves=2, clefs=[("G", 2), ("F", 4)])
              + direction(rehearsal="A", words="Allegro moderato", tempo=104)
              + barline(repeat="forward", style="heavy-light", location="left")
              + piano("D4+F4+Bb4:q D4+F4+Bb4:q D4+F4+Bb4:q D4+F4+Bb4:q", "Bb2:h F3:h"))
    pr.append(piano("C4+Eb4+A4:q C4+Eb4+A4:q D4+F4+Bb4:h", "F2:h Bb2:h"))
    pr.append(piano("Eb4+G4+C5:q Eb4+G4+C5:q Eb4+G4+Bb4:q Eb4+G4+Bb4:q", "C3:h Eb3:h"))
    pr.append(piano("C4+F4+A4:h C4+Eb4+F4+A4:h", "F2:h F3:h") + barline(repeat="backward", style="light-heavy"))
    pr.append(piano("D4+F4+Bb4:e r:e D4+F4+Bb4:e r:e D4+F4+Bb4:q F4+Bb4+D5:q", "Bb2:q D3:q F3:q D3:q"))
    pr.append(piano("Eb4+G4+C5:q Eb4+G4+C5:q Eb4+G4+Bb4:h", "Eb2:q G2:q Bb2:h"))
    pr.append(piano("C4+F4+A4:q C4+F4+A4:q C4+Eb4+A4:q C4+Eb4+A4:q", "F2:h F3:h"))
    pr.append(piano("D4+F4+Bb4:w!", "Bb1+Bb2:w!") + barline(style="light-light"))

    # --- B: Andante, 3/4, Takte 9–18 (Klarinette pausiert 9–12) --------------
    cl.append(attributes(time=(3, 4), divisions=False)
              + direction(rehearsal="B", words="Andante", tempo=66)
              + whole_rest(M34))
    for _ in range(3):
        cl.append(whole_rest(M34))
    cl.append(seq("G5:q C6:q E6:q"))
    cl.append(seq("G6:h. "))
    cl.append(seq("F6:e E6:e D6:q C6:q"))
    cl.append(seq("A6:h G6:q"))
    cl.append(seq("E6:t F6:t G6:t A6:t B6:t C7:t B6:t A6:t G6:q E6:q"))
    cl.append(seq("C6:h.!") + barline(style="light-light"))

    def waltz(bass: str, chord: str) -> str:
        return piano(f"r:q {chord}:q {chord}:q", f"{bass}:h.", length=M34)

    pr.append(attributes(time=(3, 4), divisions=False)
              + direction(rehearsal="B", words="Andante", tempo=66)
              + waltz("Bb2", "D4+F4+Bb4"))
    pr.append(waltz("G2", "D4+G4+Bb4"))
    pr.append(waltz("Eb2", "Eb4+G4+Bb4"))
    pr.append(waltz("F2", "C4+F4+A4"))
    pr.append(waltz("Bb2", "D4+F4+Bb4"))
    pr.append(waltz("Bb2", "F4+Bb4+D5"))
    pr.append(waltz("F2", "C4+Eb4+A4"))
    pr.append(waltz("Eb2", "Eb4+G4+C5"))
    pr.append(waltz("F2", "C4+Eb4+F4+A4"))
    pr.append(piano("D4+F4+Bb4:h.!", "Bb1+Bb2:h.!", length=M34) + barline(style="light-light"))

    # --- Kadenz (a piacere), Takt 19, 4/4 ------------------------------------
    cl.append(attributes(time=(4, 4), divisions=False)
              + direction(words="Cadenza – a piacere")
              + seq("G5:s A5:s B5:s C6:s D6:s E6:s F6:s G6:s A6:s B6:s C7:s B6:s C7:q!"))
    pr.append(attributes(time=(4, 4), divisions=False)
              + direction(words="Cadenza – a piacere")
              + piano("C4+F4+A4:w!", "F2+F3:w!") + barline(style="light-light"))

    # --- C: Tempo I, Takte 20–23 ---------------------------------------------
    cl.append(direction(rehearsal="C", words="Tempo I", tempo=104)
              + seq("C5:e E5:e G5:e C6:e E6:q C6:q"))
    cl.append(seq("D6:q B5:q G5:q B5:q"))
    cl.append(seq("C6:q G5:q E5:q G5:q"))
    cl.append(seq("C6:w!") + barline(style="light-heavy"))

    pr.append(direction(rehearsal="C", words="Tempo I", tempo=104)
              + piano("D4+F4+Bb4:q D4+F4+Bb4:q D4+F4+Bb4:q D4+F4+Bb4:q", "Bb2:h D3:h"))
    pr.append(piano("C4+Eb4+A4:q C4+Eb4+A4:q C4+Eb4+F4+A4:h", "F2:h F3:h"))
    pr.append(piano("D4+F4+Bb4:q D4+F4+Bb4:q D4+G4+Bb4:q D4+F4+Bb4:q", "Bb2:h G2:h"))
    pr.append(piano("D4+F4+Bb4:w!", "Bb1+Bb2:w!") + barline(style="light-heavy"))

    return score("Übungsstück in B", "Play-along (gemeinfrei)", [
        ("P1", "Klarinette in B", "72", cl),
        ("P2", "Klavier", "1", pr),
    ])


# --------------------------------------------------------------------------
# Etüde: Klarinette solo, KLINGEND notiert (Konzert B-Dur)
# --------------------------------------------------------------------------

def etuede() -> str:
    m: list[str] = []
    m.append(attributes(key=-2, time=(4, 4), clefs=[("G", 2)])
             + direction(rehearsal="A", words="Allegretto", tempo=92)
             + seq("Bb4:s C5:s D5:s Eb5:s F5:s G5:s A5:s Bb5:s C6:s Bb5:s A5:s G5:s F5:q"))
    m.append(seq("D5:s F5:s Bb5:s D6:s F6:s D6:s Bb5:s F5:s D5:q Bb4:q"))
    m.append(seq("Eb5:s G5:s C6:s Eb6:s G6:s Eb6:s C6:s G5:s Eb5:e G5:e C6:q"))
    m.append(seq("F5:s A5:s C6:s Eb6:s F6:s Eb6:s C6:s A5:s F5:h"))
    m.append(direction(rehearsal="B", words="poco più mosso", tempo=104)
             + seq("Bb5:e. C6:s D6:e. Eb6:s F6:q G6:q"))
    m.append(seq("A6:s G6:s F6:s Eb6:s D6:s C6:s Bb5:s A5:s Bb5:h"))
    m.append(seq("C6:s Eb6:s A6:s C7:s A6:s Eb6:s C6:s A5:s F5:h"))
    m.append(seq("Bb5:w!") + barline(style="light-heavy"))
    return score("Etüde in B (klingend notiert)", "Play-along (gemeinfrei)", [
        ("P1", "Klarinette", "72", m),
    ])


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)
    (out / "uebungsstueck.musicxml").write_text(uebungsstueck(), encoding="utf-8")
    (out / "etuede.musicxml").write_text(etuede(), encoding="utf-8")
    print(f"Geschrieben nach {out.resolve()}")


if __name__ == "__main__":
    main()
