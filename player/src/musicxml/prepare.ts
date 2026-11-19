// Vorbereitung einer MusicXML-Partitur für die Anzeige:
//  - Stimmen erkennen (Klarinette = eigene Stimme, Rest = Begleitung)
//  - klingend notierte Klarinettenstimme nach B transponieren (große Sekunde aufwärts)
//  - eigene Stimme an die erste Stelle verschieben

export interface PartInfo {
  id: string;
  name: string;
  isClarinet: boolean;
  isPiano: boolean;
}

export interface PreparedScore {
  xml: string; // vorbereitete MusicXML (für Anzeige und Zeitleiste)
  doc: Document;
  parts: PartInfo[];
  soloPartId: string;
  title: string;
  composer: string;
  transposedAutomatically: boolean;
}

export type Notation = 'auto' | 'concert' | 'transposed';

const CLARINET_RE = /klarinette|clarinet|clarinetto|clarinete|clarinette|^\s*(b-)?kl(ar)?\.|^\s*cl\.?\s|^\s*cl\.?$|^\s*bb?\s*cl/i;
const PIANO_RE = /klavier|piano|pianoforte|flügel|keyboard/i;

const STEP_NAMES = ['C', 'D', 'E', 'F', 'G', 'A', 'B'];
const STEP_SEMI = [0, 2, 4, 5, 7, 9, 11];

export function parseXml(text: string): Document {
  const doc = new DOMParser().parseFromString(text, 'application/xml');
  const err = doc.querySelector('parsererror');
  if (err) throw new Error('Die MusicXML-Datei ist fehlerhaft und kann nicht gelesen werden.');
  if (doc.documentElement.nodeName === 'score-timewise') {
    throw new Error('MusicXML im Format „timewise“ wird nicht unterstützt. Bitte als normales (partwise) MusicXML exportieren.');
  }
  if (doc.documentElement.nodeName !== 'score-partwise') {
    throw new Error('Das ist keine MusicXML-Partitur.');
  }
  return doc;
}

function text(el: Element | null | undefined): string {
  return (el?.textContent ?? '').trim();
}

export function readParts(doc: Document): PartInfo[] {
  const out: PartInfo[] = [];
  for (const sp of Array.from(doc.querySelectorAll('part-list > score-part'))) {
    const id = sp.getAttribute('id') ?? '';
    const name = text(sp.querySelector('part-name')) || text(sp.querySelector('part-abbreviation'));
    const instr = Array.from(sp.querySelectorAll('instrument-name, instrument-sound, part-abbreviation'))
      .map((e) => text(e)).join(' ');
    const prog = parseInt(text(sp.querySelector('midi-program')) || '0', 10);
    const hay = `${name} ${instr}`;
    const isClarinet = CLARINET_RE.test(name) || /clarinet|klarinette/i.test(instr) || prog === 72;
    const isPiano = !isClarinet && (PIANO_RE.test(hay) || (prog >= 1 && prog <= 8));
    out.push({ id, name: name || id, isClarinet, isPiano });
  }
  return out;
}

function partEl(doc: Document, id: string): Element | null {
  for (const p of Array.from(doc.querySelectorAll('score-partwise > part'))) {
    if (p.getAttribute('id') === id) return p;
  }
  return null;
}

/** Hat die Stimme ein <transpose>-Element (= ist transponiert notiert)? */
function hasTranspose(part: Element): boolean {
  return part.querySelector('attributes > transpose') !== null;
}

const ACC_NAMES: Record<number, string> = { [-2]: 'flat-flat', [-1]: 'flat', 0: 'natural', 1: 'sharp', 2: 'double-sharp' };

/** Transponiert eine klingend notierte Stimme in die B-Notation (große Sekunde aufwärts). */
export function transposeToBb(doc: Document, part: Element): void {
  // Tonart des ersten Abschnitts bestimmt die Schreibweise: zu viele Kreuze -> enharmonisch (verminderte Terz)
  let diatonic = 1;
  const firstKey = part.querySelector('attributes > key > fifths');
  if (firstKey && parseInt(text(firstKey), 10) + 2 > 7) diatonic = 2;
  const chromatic = 2;

  for (const f of Array.from(part.querySelectorAll('attributes > key > fifths'))) {
    let v = parseInt(text(f), 10) + (diatonic === 1 ? 2 : -10);
    if (v > 7) v -= 12;
    if (v < -7) v += 12;
    f.textContent = String(v);
  }

  for (const p of Array.from(part.querySelectorAll('note > pitch'))) {
    const stepEl = p.querySelector('step');
    const octEl = p.querySelector('octave');
    if (!stepEl || !octEl) continue;
    const alterEl = p.querySelector('alter');
    const step = STEP_NAMES.indexOf(text(stepEl).toUpperCase());
    const oct = parseInt(text(octEl), 10);
    const alter = alterEl ? parseFloat(text(alterEl)) : 0;
    const midi = (oct + 1) * 12 + STEP_SEMI[step] + alter + chromatic;
    let nStep = step + diatonic;
    let nOct = oct;
    if (nStep > 6) { nStep -= 7; nOct += 1; }
    const natural = (nOct + 1) * 12 + STEP_SEMI[nStep];
    const nAlter = Math.round(midi - natural);
    stepEl.textContent = STEP_NAMES[nStep];
    octEl.textContent = String(nOct);
    if (nAlter === 0) {
      alterEl?.remove();
    } else if (alterEl) {
      alterEl.textContent = String(nAlter);
    } else {
      const a = doc.createElement('alter');
      a.textContent = String(nAlter);
      p.insertBefore(a, octEl);
    }
    const note = p.parentElement!;
    const acc = note.querySelector(':scope > accidental');
    if (acc && ACC_NAMES[nAlter] !== undefined) acc.textContent = ACC_NAMES[nAlter];
  }

  // <transpose> einfügen: notiert klingt große Sekunde (bzw. verminderte Terz) tiefer
  const firstAttr = part.querySelector('measure > attributes');
  const tr = doc.createElement('transpose');
  const d = doc.createElement('diatonic');
  d.textContent = String(-diatonic);
  const c = doc.createElement('chromatic');
  c.textContent = String(-chromatic);
  tr.append(d, c);
  if (firstAttr) {
    const before = Array.from(firstAttr.children).find((ch) =>
      ['directive', 'measure-style', 'for-part'].includes(ch.nodeName));
    firstAttr.insertBefore(tr, before ?? null);
  } else {
    const m = part.querySelector('measure');
    const attr = doc.createElement('attributes');
    attr.appendChild(tr);
    m?.insertBefore(attr, m.firstChild);
  }
}

/** Verschiebt eine Stimme an die erste Stelle (part-list und Reihenfolge der <part>-Elemente). */
function moveToTop(doc: Document, id: string): void {
  const list = doc.querySelector('part-list');
  const sp = Array.from(doc.querySelectorAll('part-list > score-part')).find((e) => e.getAttribute('id') === id);
  if (list && sp && list.firstElementChild !== sp) list.insertBefore(sp, list.firstElementChild);
  const p = partEl(doc, id);
  const firstPart = doc.querySelector('score-partwise > part');
  if (p && firstPart && p !== firstPart) firstPart.parentElement!.insertBefore(p, firstPart);
}

export function readTitle(doc: Document): { title: string; composer: string } {
  const title = text(doc.querySelector('work > work-title')) || text(doc.querySelector('movement-title'))
    || text(doc.querySelector('credit-words'));
  const composer = text(doc.querySelector('identification > creator[type="composer"]'));
  return { title, composer };
}

export function prepareScore(xmlText: string, opts: { soloPartId?: string; notation?: Notation } = {}): PreparedScore {
  const doc = parseXml(xmlText);
  const parts = readParts(doc);
  if (parts.length === 0) throw new Error('Die Partitur enthält keine Stimmen.');

  const solo = parts.find((p) => p.id === opts.soloPartId) ?? parts.find((p) => p.isClarinet) ?? parts[0];
  const soloEl = partEl(doc, solo.id);
  let transposed = false;
  const notation = opts.notation ?? 'auto';
  if (soloEl && !hasTranspose(soloEl)) {
    const concert = notation === 'concert' || (notation === 'auto' && solo.isClarinet);
    if (concert) {
      transposeToBb(doc, soloEl);
      transposed = true;
    }
  }
  moveToTop(doc, solo.id);
  const { title, composer } = readTitle(doc);
  const xml = new XMLSerializer().serializeToString(doc);
  return {
    xml, doc,
    parts: readParts(doc),
    soloPartId: solo.id,
    title, composer,
    transposedAutomatically: transposed,
  };
}
