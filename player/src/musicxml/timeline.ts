// Aus der MusicXML eine abspielbare Zeitleiste erzeugen.
// Alle Positionen sind in Viertelnoten ab Stückbeginn (nach Auflösen der Wiederholungen).

export interface NoteEvent {
  part: string;
  start: number;
  dur: number;
  midi: number;
  vel: number;
}

export interface SourceMeasure {
  index: number;
  label: string; // Taktnummer laut Partitur
  length: number; // Viertel
  beats: number;
  beatType: number;
}

export interface PlayedMeasure {
  src: number; // Index in sourceMeasures
  start: number;
  length: number;
  beats: number;
  beatType: number;
}

export interface Hold {
  pos: number; // hier anhalten
  resume: number; // hier weiterspielen
  kind: 'fermata' | 'cadenza';
}

export interface Mark {
  label: string;
  kind: 'rehearsal' | 'tempo';
  src: number; // Quelltakt
  pos: number; // erste Position in der Zeitleiste
}

export interface Beat {
  pos: number;
  accent: boolean;
}

export interface Timeline {
  sourceMeasures: SourceMeasure[];
  measures: PlayedMeasure[];
  notes: NoteEvent[]; // sortiert nach start
  tempos: { pos: number; qpm: number }[]; // sortiert, erster Eintrag bei 0
  fermatas: Hold[];
  cadenzas: Hold[];
  marks: Mark[];
  beats: Beat[];
  length: number;
}

interface RawNote {
  part: string;
  rel: number;
  dur: number;
  midi: number;
  vel: number;
  tieStart: boolean;
  tieStop: boolean;
}

interface RawMeasure {
  label: string;
  length: number;
  beats: number;
  beatType: number;
  notes: RawNote[];
  tempos: { rel: number; qpm: number }[]; // aus <sound tempo>
  metroTempos: { rel: number; qpm: number }[]; // aus Metronomangaben (nur falls kein <sound tempo>)
  fermatas: { rel: number; dur: number }[];
  cadenza: boolean;
  rehearsal: string[];
  words: string[];
  repeatForward: boolean;
  repeatBackward: boolean;
  repeatTimes: number;
  endingStart: number[] | null; // Nummern
  endingStop: boolean;
  segno: boolean;
  coda: boolean;
  toCoda: boolean;
  daCapo: boolean;
  dalSegno: boolean;
  fine: boolean;
}

const STEP_SEMI: Record<string, number> = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
const DYN: Record<string, number> = { pppp: 0.25, ppp: 0.3, pp: 0.38, p: 0.48, mp: 0.58, mf: 0.68, f: 0.8, ff: 0.9, fff: 1, ffff: 1, sf: 0.85, sfz: 0.85, fp: 0.8 };
const CADENZA_RE = /a\s*piacere|ad\s*lib|cadenz|kadenz|senza\s*tempo|colla\s*parte|rubato\s*ad/i;
const BEAT_UNIT: Record<string, number> = { whole: 4, half: 2, quarter: 1, eighth: 0.5, '16th': 0.25, '32nd': 0.125 };

function t(el: Element | null | undefined): string {
  return (el?.textContent ?? '').trim();
}
function num(el: Element | null | undefined, def = 0): number {
  const v = parseFloat(t(el));
  return Number.isFinite(v) ? v : def;
}
function kids(el: Element, name?: string): Element[] {
  const out: Element[] = [];
  for (const c of Array.from(el.children)) if (!name || c.nodeName === name) out.push(c);
  return out;
}

function emptyMeasure(label: string): RawMeasure {
  return {
    label, length: 0, beats: 4, beatType: 4, notes: [], tempos: [], metroTempos: [], fermatas: [], cadenza: false,
    rehearsal: [], words: [], repeatForward: false, repeatBackward: false, repeatTimes: 2,
    endingStart: null, endingStop: false, segno: false, coda: false, toCoda: false,
    daCapo: false, dalSegno: false, fine: false,
  };
}

/** Tempo nur einmal pro Position übernehmen (steht oft in mehreren Stimmen) */
function addTempo(list: { rel: number; qpm: number }[], rel: number, qpm: number): void {
  if (!list.some((x) => Math.abs(x.rel - rel) < 1e-6)) list.push({ rel, qpm });
}

function readSound(s: Element, m: RawMeasure, rel: number): void {
  const tempo = s.getAttribute('tempo');
  if (tempo) {
    const q = parseFloat(tempo);
    if (q > 0) addTempo(m.tempos, rel, q);
  }
  if (s.hasAttribute('segno')) m.segno = true;
  if (s.hasAttribute('coda')) m.coda = true;
  if (s.hasAttribute('tocoda')) m.toCoda = true;
  if (s.getAttribute('dacapo') === 'yes') m.daCapo = true;
  if (s.hasAttribute('dalsegno')) m.dalSegno = true;
  if (s.hasAttribute('fine')) m.fine = true;
}

/** Liest alle Takte aller Stimmen und fasst sie pro Taktindex zusammen. */
function readMeasures(doc: Document): RawMeasure[] {
  const parts = Array.from(doc.querySelectorAll('score-partwise > part'));
  const result: RawMeasure[] = [];

  parts.forEach((part, partIndex) => {
    const pid = part.getAttribute('id') ?? `P${partIndex}`;
    const first = partIndex === 0; // Taktart aus der ersten Stimme
    let divisions = 1;
    let transpose = 0;
    let beats = 4;
    let beatType = 4;
    let vel = 0.7;

    kids(part, 'measure').forEach((mEl, mi) => {
      if (!result[mi]) result[mi] = emptyMeasure(mEl.getAttribute('number') ?? String(mi + 1));
      const m = result[mi];
      let pos = 0; // in divisions
      let maxPos = 0;
      let lastOnset = 0;

      for (const el of Array.from(mEl.children)) {
        switch (el.nodeName) {
          case 'attributes': {
            const d = el.querySelector('divisions');
            if (d) divisions = num(d, 1) || 1;
            const time = el.querySelector('time');
            if (time && time.querySelector('beats')) {
              const sum = t(time.querySelector('beats')).split('+').reduce((a, b) => a + (parseInt(b, 10) || 0), 0);
              beats = sum > 0 ? sum : 4;
              beatType = parseInt(t(time.querySelector('beat-type')), 10) || 4;
            }
            const tr = el.querySelector('transpose');
            if (tr) transpose = num(tr.querySelector('chromatic')) + 12 * num(tr.querySelector('octave-change'));
            break;
          }
          case 'note': {
            if (el.querySelector(':scope > grace') || el.querySelector(':scope > cue')) break;
            const dur = num(el.querySelector(':scope > duration'));
            const isChord = el.querySelector(':scope > chord') !== null;
            const onset = isChord ? lastOnset : pos;
            const pitch = el.querySelector(':scope > pitch');
            const notations = el.querySelector(':scope > notations');
            if (notations?.querySelector('fermata')) {
              m.fermatas.push({ rel: onset / divisions, dur: dur / divisions });
            }
            if (pitch && dur > 0) {
              const step = t(pitch.querySelector('step')).toUpperCase();
              const midi = 12 * (num(pitch.querySelector('octave'), 4) + 1) + (STEP_SEMI[step] ?? 0)
                + num(pitch.querySelector('alter')) + transpose;
              const ties = Array.from(el.querySelectorAll(':scope > tie')).map((x) => x.getAttribute('type'));
              const dynAttr = el.getAttribute('dynamics');
              m.notes.push({
                part: pid,
                rel: onset / divisions,
                dur: dur / divisions,
                midi: Math.round(midi),
                vel: dynAttr ? Math.min(1, parseFloat(dynAttr) / 100) : vel,
                tieStart: ties.includes('start'),
                tieStop: ties.includes('stop'),
              });
            }
            if (!isChord) {
              lastOnset = pos;
              pos += dur;
            }
            break;
          }
          case 'backup':
            pos -= num(el.querySelector('duration'));
            if (pos < 0) pos = 0;
            break;
          case 'forward':
            pos += num(el.querySelector('duration'));
            break;
          case 'direction': {
            const offset = num(el.querySelector(':scope > offset'));
            const rel = (pos + offset) / divisions;
            for (const dt of kids(el, 'direction-type')) {
              for (const c of Array.from(dt.children)) {
                if (c.nodeName === 'rehearsal' && t(c) && !m.rehearsal.includes(t(c))) m.rehearsal.push(t(c));
                if (c.nodeName === 'words' && t(c)) {
                  const w = t(c);
                  if (!m.words.includes(w)) m.words.push(w);
                  if (CADENZA_RE.test(w)) m.cadenza = true;
                  if (/^\s*(to\s+coda|zur\s+coda)/i.test(w)) m.toCoda = true;
                  if (/^\s*d\.\s*c\./i.test(w) || /^\s*da\s+capo/i.test(w)) m.daCapo = true;
                  if (/^\s*d\.\s*s\./i.test(w) || /^\s*dal\s+segno/i.test(w)) m.dalSegno = true;
                  if (/^\s*fine\s*$/i.test(w)) m.fine = true;
                }
                if (c.nodeName === 'segno') m.segno = true;
                if (c.nodeName === 'coda') m.coda = true;
                if (c.nodeName === 'dynamics') {
                  const d = c.firstElementChild?.nodeName;
                  if (d && DYN[d] !== undefined) vel = DYN[d];
                }
                if (c.nodeName === 'metronome') {
                  const unit = BEAT_UNIT[t(c.querySelector('beat-unit'))] ?? 1;
                  const dots = c.querySelectorAll('beat-unit-dot').length;
                  const pm = num(c.querySelector('per-minute'));
                  if (pm > 0) addTempo(m.metroTempos, rel, pm * unit * (dots ? 1.5 : 1));
                }
              }
            }
            const snd = el.querySelector(':scope > sound');
            if (snd) {
              readSound(snd, m, rel);
              const dyn = snd.getAttribute('dynamics');
              if (dyn) vel = Math.min(1, parseFloat(dyn) / 100) || vel;
            }
            break;
          }
          case 'sound':
            readSound(el, m, pos / divisions);
            break;
          case 'barline': {
            const rep = el.querySelector('repeat');
            if (rep?.getAttribute('direction') === 'forward') m.repeatForward = true;
            if (rep?.getAttribute('direction') === 'backward') {
              m.repeatBackward = true;
              const times = parseInt(rep.getAttribute('times') ?? '', 10);
              if (times > 0) m.repeatTimes = times;
            }
            const end = el.querySelector('ending');
            if (end) {
              const type = end.getAttribute('type');
              if (type === 'start') {
                m.endingStart = (end.getAttribute('number') ?? '1').split(/[,\s]+/).map((x) => parseInt(x, 10)).filter((x) => x > 0);
              } else {
                m.endingStop = true;
              }
            }
            if (el.querySelector('segno')) m.segno = true;
            if (el.querySelector('coda')) m.coda = true;
            const snd = el.querySelector('sound');
            if (snd) readSound(snd, m, pos / divisions);
            break;
          }
        }
        if (pos > maxPos) maxPos = pos;
      }

      if (first) {
        m.beats = beats;
        m.beatType = beatType;
      }
      const len = maxPos / divisions;
      if (len > m.length) m.length = len;
    });
  });

  // Takte ohne Inhalt: Länge aus der Taktart
  for (const m of result) {
    const expected = (m.beats * 4) / m.beatType;
    if (m.length <= 0) m.length = expected;
    // Rundungsfehler aus der Datei ausgleichen
    else if (Math.abs(m.length - expected) < 0.02) m.length = expected;
    if (m.tempos.length === 0) m.tempos = m.metroTempos;
  }
  return result;
}

/** Wiederholungen, Volten, D.C./D.S., Coda und Fine auflösen -> Reihenfolge der Quelltakte. */
function unroll(raw: RawMeasure[]): number[] {
  const n = raw.length;
  const order: number[] = [];
  const passes = new Map<number, number>();
  // Für jede Volte: Ende und ob es die letzte der Gruppe ist
  const endingEnd = new Map<number, number>();
  const endingLast = new Map<number, boolean>();
  for (let i = 0; i < n; i++) {
    if (!raw[i].endingStart) continue;
    let j = i;
    while (j < n - 1 && !raw[j].endingStop && !(j > i && raw[j].endingStart)) j++;
    if (j > i && raw[j].endingStart && !raw[j].endingStop) j--;
    endingEnd.set(i, j);
    endingLast.set(i, !(j + 1 < n && raw[j + 1].endingStart));
  }
  const segnoIdx = raw.findIndex((m) => m.segno);

  let i = 0;
  let repeatStart = 0;
  let pass = 1;
  let jumped = false;
  let guard = 0;
  while (i < n && guard++ < 20000) {
    const m = raw[i];
    if (m.repeatForward && !jumped) repeatStart = i;
    if (m.endingStart) {
      const skip = jumped ? !endingLast.get(i) : !m.endingStart.includes(pass) && !(pass > Math.max(...m.endingStart) && endingLast.get(i));
      if (skip) {
        i = (endingEnd.get(i) ?? i) + 1;
        continue;
      }
    }
    order.push(i);
    if (jumped && m.fine) break;
    if (jumped && m.toCoda) {
      const target = raw.findIndex((x, k) => k > i && x.coda);
      if (target >= 0) {
        i = target;
        continue;
      }
    }
    if (m.repeatBackward && !jumped) {
      const done = passes.get(i) ?? 1;
      if (done < m.repeatTimes) {
        passes.set(i, done + 1);
        pass = done + 1;
        i = repeatStart;
        continue;
      }
      passes.delete(i);
      pass = 1;
      repeatStart = i + 1;
    }
    if (m.daCapo && !jumped) {
      jumped = true;
      pass = 1;
      i = 0;
      continue;
    }
    if (m.dalSegno && !jumped && segnoIdx >= 0) {
      jumped = true;
      pass = 1;
      i = segnoIdx;
      continue;
    }
    i++;
  }
  return order;
}

export function buildTimeline(doc: Document): Timeline {
  const raw = readMeasures(doc);
  const sourceMeasures: SourceMeasure[] = raw.map((m, index) => ({
    index, label: m.label, length: m.length, beats: m.beats, beatType: m.beatType,
  }));
  const order = unroll(raw);

  const measures: PlayedMeasure[] = [];
  const notes: NoteEvent[] = [];
  const tempos: { pos: number; qpm: number }[] = [];
  const fermatas: Hold[] = [];
  const cadenzas: Hold[] = [];
  const marks: Mark[] = [];
  const beats: Beat[] = [];
  const seenMarks = new Set<number>();
  const open = new Map<string, NoteEvent>(); // gebundene Noten
  let pos = 0;
  let lastMarkQpm = -1;

  for (const si of order) {
    const m = raw[si];
    measures.push({ src: si, start: pos, length: m.length, beats: m.beats, beatType: m.beatType });

    for (const tp of m.tempos) tempos.push({ pos: pos + tp.rel, qpm: tp.qpm });

    for (const rn of m.notes) {
      const start = pos + rn.rel;
      const key = `${rn.part}:${rn.midi}`;
      const prev = open.get(key);
      if (rn.tieStop && prev && Math.abs(prev.start + prev.dur - start) < 1e-6) {
        prev.dur += rn.dur;
        if (!rn.tieStart) open.delete(key);
        continue;
      }
      const ev: NoteEvent = { part: rn.part, start, dur: rn.dur, midi: rn.midi, vel: rn.vel };
      notes.push(ev);
      if (rn.tieStart) open.set(key, ev);
      else open.delete(key);
    }

    if (m.cadenza) {
      cadenzas.push({ pos, resume: pos + m.length, kind: 'cadenza' });
    } else {
      for (const f of m.fermatas) fermatas.push({ pos: pos + f.rel, resume: pos + f.rel + f.dur, kind: 'fermata' });
    }

    if (!seenMarks.has(si)) {
      seenMarks.add(si);
      for (const r of m.rehearsal) marks.push({ label: r, kind: 'rehearsal', src: si, pos });
      // Tempowechsel (auch ohne Text) und Kadenzen als Sprungziele
      const firstTempo = [...m.tempos].sort((a, b) => a.rel - b.rel)[0];
      const changed = firstTempo && Math.abs(firstTempo.qpm - lastMarkQpm) >= 1;
      const words = m.words.filter((x) => !/^\s*(to|zu[mr]?|muta in|change to)\s/i.test(x)).join(' ');
      if (m.cadenza) {
        marks.push({ label: words || 'Kadenz', kind: 'tempo', src: si, pos });
      } else if (changed) {
        const q = `♩=${Math.round(firstTempo.qpm)}`;
        marks.push({ label: words ? `${words} (${q})` : q, kind: 'tempo', src: si, pos });
      }
    }
    for (const tp of m.tempos) lastMarkQpm = tp.qpm;

    // Metronomschläge: zusammengesetzte Taktarten (6/8, 9/8, 12/8) in punktierten Vierteln
    const compound = m.beatType === 8 && m.beats % 3 === 0 && m.beats > 3;
    const step = compound ? 1.5 : 4 / m.beatType;
    for (let b = 0; b < m.length - 1e-6; b += step) beats.push({ pos: pos + b, accent: b === 0 });

    pos += m.length;
  }

  notes.sort((a, b) => a.start - b.start || a.midi - b.midi);
  tempos.sort((a, b) => a.pos - b.pos);
  if (tempos.length === 0 || tempos[0].pos > 1e-6) {
    tempos.unshift({ pos: 0, qpm: tempos.length ? tempos[0].qpm : 120 });
  }

  // Fermaten mit gleicher Position zusammenfassen
  fermatas.sort((a, b) => a.pos - b.pos);
  const mergedF: Hold[] = [];
  for (const f of fermatas) {
    const last = mergedF[mergedF.length - 1];
    if (last && Math.abs(last.pos - f.pos) < 1e-6) last.resume = Math.max(last.resume, f.resume);
    else if (last && f.pos < last.resume - 1e-6) continue; // innerhalb einer anderen Fermate
    else mergedF.push({ ...f });
  }

  return {
    sourceMeasures, measures, notes, tempos, fermatas: mergedF, cadenzas, marks, beats, length: pos,
  };
}

/** Index des gespielten Takts an Position pos. */
export function measureAt(tl: Timeline, pos: number): number {
  const ms = tl.measures;
  let lo = 0;
  let hi = ms.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (ms[mid].start <= pos + 1e-9) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}
