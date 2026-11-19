import './style.css';
import { Engine, EngineState, HoldMode } from './audio/engine';
import { ScoreView } from './score/view';
import { prepareScore, PreparedScore } from './musicxml/prepare';
import { buildTimeline, measureAt, Timeline } from './musicxml/timeline';
import { importFile } from './musicxml/load';
import * as db from './db';
import type { Song } from './db';

const BASE = import.meta.env.BASE_URL;
const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;

// ---------------------------------------------------------------- Zustand
const engine = new Engine(BASE);
let view: ScoreView | null = null;
let song: Song | null = null;
let prepared: PreparedScore | null = null;
let tl: Timeline | null = null;
let loopOn = false;
let pickMode: 0 | 1 | 2 = 0; // Schleifenbereich antippen: 0 aus, 1 Start, 2 Ende
let wakeLock: { release: () => Promise<void> } | null = null;

// ---------------------------------------------------------------- Globale Einstellungen
interface GlobalPrefs {
  accompaniment: boolean; accompanimentVolume: number;
  solo: boolean; soloVolume: number;
  metronome: boolean; metronomeVolume: number;
  countInBars: number; holdMode: HoldMode; fermataStretch: number;
}
const PREF_KEY = 'playalong.prefs';
function loadPrefs(): Partial<GlobalPrefs> {
  try {
    return JSON.parse(localStorage.getItem(PREF_KEY) ?? '{}');
  } catch {
    return {};
  }
}
function savePrefs(): void {
  const o = engine.opts;
  const p: GlobalPrefs = {
    accompaniment: o.accompaniment, accompanimentVolume: o.accompanimentVolume,
    solo: o.solo, soloVolume: o.soloVolume, metronome: o.metronome, metronomeVolume: o.metronomeVolume,
    countInBars: o.countInBars, holdMode: o.holdMode, fermataStretch: o.fermataStretch,
  };
  try {
    localStorage.setItem(PREF_KEY, JSON.stringify(p));
  } catch {
    /* privat-Modus o. ä. */
  }
}
engine.setOptions(loadPrefs());

// ---------------------------------------------------------------- Hilfen
function toast(msg: string, ms = 2500): void {
  const t = $('toast');
  t.textContent = msg;
  t.hidden = false;
  clearTimeout((toast as unknown as { h: number }).h);
  (toast as unknown as { h: number }).h = window.setTimeout(() => (t.hidden = true), ms);
}
function loading(on: boolean, text = 'Lädt …'): void {
  $('loading').hidden = !on;
  $('loading-text').textContent = text;
}
function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);
}
function fmtDate(ts: number): string {
  if (!ts) return 'noch nie gespielt';
  const d = new Date(ts);
  return 'zuletzt ' + d.toLocaleDateString('de-DE', { day: 'numeric', month: 'short' }) + ', '
    + d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
}

// iOS: Audio erst nach Nutzerinteraktion freischalten; Samples früh laden
let unlocked = false;
document.addEventListener('pointerdown', () => {
  if (unlocked) return;
  unlocked = true;
  engine.unlock().catch(() => {});
  engine.loadSamples().catch((e) => toast(`Klänge konnten nicht geladen werden: ${e.message}`, 5000));
}, { capture: true });

// ---------------------------------------------------------------- Bibliothek
async function showLibrary(): Promise<void> {
  engine.stop();
  engine.mic.stop();
  releaseWakeLock();
  $('player').hidden = true;
  $('library').hidden = false;
  const list = await db.listSongs();
  const ul = $('song-list');
  ul.replaceChildren();
  $('empty-hint').hidden = list.length > 0;
  for (const s of list) {
    const li = document.createElement('li');
    li.className = 'song';
    li.innerHTML = `<button class="song-open"><b>${escapeHtml(s.title)}${s.hasAudio ? '<span class="badge">MP3</span>' : ''}</b>
      <span>${escapeHtml(s.composer || '')}${s.composer ? ' · ' : ''}${fmtDate(s.lastPlayed)}</span></button>
      <button class="btn small del" aria-label="Löschen">Löschen</button>`;
    li.querySelector('.song-open')!.addEventListener('click', () => openSong(s.id));
    li.querySelector('.del')!.addEventListener('click', async () => {
      if (!confirm(`„${s.title}“ wirklich aus der Bibliothek löschen?`)) return;
      await db.deleteSong(s.id);
      showLibrary();
    });
    ul.appendChild(li);
  }
}

$<HTMLInputElement>('file-input').addEventListener('change', async (e) => {
  const input = e.target as HTMLInputElement;
  const files = Array.from(input.files ?? []);
  input.value = '';
  for (const f of files) {
    loading(true, `Importiere „${f.name}“ …`);
    try {
      const imp = await importFile(f);
      prepareScore(imp.xml); // prüft, ob die Partitur lesbar ist
      const s: Song = {
        id: db.newId(), title: imp.title, composer: imp.composer, xml: imp.xml,
        audio: imp.audio, audioName: imp.audioName, sync: imp.sync, manifest: imp.manifest,
        addedAt: Date.now(), lastPlayed: 0,
        settings: { soloPart: imp.manifest?.soloPart, notation: imp.manifest?.notation },
      };
      await db.putSong(s);
      db.requestPersistence();
      toast(`„${s.title}“ wurde importiert.`);
    } catch (err) {
      alert(`Import fehlgeschlagen (${f.name}):\n${(err as Error).message}`);
    } finally {
      loading(false);
    }
  }
  showLibrary();
});

$('add-demos').addEventListener('click', async () => {
  const demos = [
    { file: 'uebungsstueck.musicxml', title: 'Übungsstück in B' },
    { file: 'etuede.musicxml', title: 'Etüde in B (klingend notiert)' },
  ];
  const existing = new Set((await db.listSongs()).map((s) => s.title));
  let added = 0;
  for (const d of demos) {
    if (existing.has(d.title)) continue;
    const res = await fetch(`${BASE}demo/${d.file}`);
    const xml = await res.text();
    await db.putSong({
      id: db.newId(), title: d.title, composer: 'Play-along (gemeinfrei)', xml,
      addedAt: Date.now() - added, lastPlayed: 0, settings: {},
    });
    added++;
  }
  toast(added ? 'Demo-Stücke hinzugefügt.' : 'Die Demo-Stücke sind schon da.');
  showLibrary();
});

// ---------------------------------------------------------------- Player öffnen
async function openSong(id: string): Promise<void> {
  const s = await db.getSong(id);
  if (!s) return;
  song = s;
  $('library').hidden = true;
  $('player').hidden = false;
  $('song-title').textContent = s.title;
  loading(true, 'Noten werden gesetzt …');
  await new Promise((r) => requestAnimationFrame(() => setTimeout(r, 20)));
  try {
    await loadScore();
    await db.updateSong(s.id, { lastPlayed: Date.now() });
  } catch (err) {
    alert(`Das Lied konnte nicht geöffnet werden:\n${(err as Error).message}`);
    loading(false);
    showLibrary();
    return;
  }
  loading(false);
}

async function loadScore(): Promise<void> {
  if (!song) return;
  engine.stop();
  const st = song.settings ?? {};
  prepared = prepareScore(song.xml, { soloPartId: st.soloPart, notation: st.notation ?? song.manifest?.notation });
  tl = buildTimeline(prepared.doc);
  if (!view) view = new ScoreView($('score-scroller'), $('score'));
  view.zoom = st.zoom ?? defaultZoom();
  view.showAccompaniment = st.showPiano ?? true;
  await view.load(prepared.xml, prepared.soloPartId);
  view.render();
  engine.setTimeline(tl, prepared.soloPartId);
  engine.loop = null;
  loopOn = false;
  setTempoUi(st.tempo ?? 100);
  engine.setTempo((st.tempo ?? 100) / 100);
  fillJumpList();
  fillPartOptions();
  $<HTMLInputElement>('opt-show-acc').checked = view.showAccompaniment;
  $<HTMLInputElement>('opt-show-acc').disabled = prepared.parts.length < 2;
  $('zoom-label').textContent = `${Math.round(view.zoom * 100)} %`;
  $<HTMLInputElement>('loop-from').value = st.loopFrom ?? tl.sourceMeasures[0]?.label ?? '1';
  $<HTMLInputElement>('loop-to').value = st.loopTo ?? tl.sourceMeasures[Math.min(3, tl.sourceMeasures.length - 1)]?.label ?? '1';
  updateLoopUi();
  $('score-scroller').scrollTop = 0;
  syncControls();
  if (prepared.parts.length === 1 && !engine.opts.metronome) {
    toast('Stück ohne Begleitung – tipp auf „Metronom“, wenn du einen Takt brauchst.', 4000);
  }
}

function defaultZoom(): number {
  const w = Math.min(window.innerWidth, 1400);
  return Math.max(0.6, Math.min(1.4, w / 1000));
}

function fillJumpList(): void {
  const sel = $<HTMLSelectElement>('jump');
  sel.replaceChildren();
  const add = (label: string, value: string) => {
    const o = document.createElement('option');
    o.value = value;
    o.textContent = label;
    sel.appendChild(o);
  };
  add('Springen zu …', '');
  add('Anfang', 'pos:0');
  // Buchstaben und Tempoangaben desselben Takts zusammenfassen
  const bySrc = new Map<number, { pos: number; parts: string[] }>();
  for (const m of tl!.marks) {
    const e = bySrc.get(m.src) ?? { pos: m.pos, parts: [] };
    e.parts.push(m.kind === 'rehearsal' ? `[${m.label}]` : m.label);
    bySrc.set(m.src, e);
  }
  for (const [src, e] of [...bySrc.entries()].sort((a, b) => a[1].pos - b[1].pos)) {
    add(`${e.parts.join(' ')} – Takt ${tl!.sourceMeasures[src].label}`, `pos:${e.pos}`);
  }
  add('Takt eingeben …', 'ask');
}

function fillPartOptions(): void {
  const sel = $<HTMLSelectElement>('opt-solo-part');
  sel.replaceChildren();
  for (const p of prepared!.parts) {
    const o = document.createElement('option');
    o.value = p.id;
    o.textContent = p.name;
    sel.appendChild(o);
  }
  sel.value = prepared!.soloPartId;
  $<HTMLSelectElement>('opt-notation').value = song?.settings.notation ?? song?.manifest?.notation ?? 'auto';
  $('transpose-hint').textContent = prepared!.transposedAutomatically
    ? 'Die Vorlage war klingend notiert und wurde automatisch nach B transponiert (große Sekunde höher).'
    : 'Die Stimme wird so angezeigt, wie sie in der Vorlage notiert ist.';
}

function saveSettings(patch: Partial<Song['settings']>): void {
  if (!song) return;
  song.settings = { ...song.settings, ...patch };
  db.updateSong(song.id, { settings: patch }).catch(() => {});
}

// ---------------------------------------------------------------- Positionen
function firstPosOfSource(src: number, after = 0): number | null {
  const m = tl!.measures.find((x) => x.src === src && x.start >= after - 1e-9);
  return m ? m.start : null;
}
function srcFromLabel(label: string): number | null {
  const l = label.trim();
  const i = tl!.sourceMeasures.findIndex((m) => m.label === l);
  if (i >= 0) return i;
  const n = parseInt(l, 10);
  if (n >= 1 && n <= tl!.sourceMeasures.length) return n - 1;
  return null;
}
function measureStartAt(pos: number): number {
  return tl!.measures[measureAt(tl!, pos)].start;
}

// ---------------------------------------------------------------- Wiedergabe
async function togglePlay(): Promise<void> {
  if (!tl) return;
  if (engine.state === 'holding') {
    engine.continueFromHold();
    return;
  }
  if (engine.state !== 'stopped') {
    stopPlayback();
    return;
  }
  await engine.unlock();
  if (!engine.samplesLoaded) {
    loading(true, 'Klänge werden geladen …');
    try {
      await engine.loadSamples();
    } catch (e) {
      loading(false);
      alert(`Klänge konnten nicht geladen werden: ${(e as Error).message}`);
      return;
    }
    loading(false);
  }
  if (engine.opts.holdMode === 'mic' && !engine.mic.active) await startMic();
  let from = measureStartAt(engine.position());
  if (loopOn && engine.loop) {
    if (from < engine.loop.start || from >= engine.loop.end) from = engine.loop.start;
    engine.loopPass = 1;
    updateLoopInfo();
  }
  if (from >= tl.length - 1e-6) from = 0;
  await engine.play(from);
  requestWakeLock();
}

function stopPlayback(): void {
  engine.stop();
  engine.seek(measureStartAt(engine.position()));
  releaseWakeLock();
  if (song) saveSettings({ tempo: Math.round(engine.tempo * 100) });
}

engine.onStateChange = (s: EngineState) => syncControls(s);
engine.onEnd = () => {
  releaseWakeLock();
  view?.scrollToMeasure(0);
  toast('Ende des Stücks');
};
engine.onLoopPass = (pass, tempo) => {
  setTempoUi(Math.round(tempo * 100));
  updateLoopInfo();
  view?.flashMeasure(tl!.measures[measureAt(tl!, engine.loop!.start)].src);
  void pass;
};

function syncControls(s: EngineState = engine.state): void {
  const b = $('btn-play');
  const active = s !== 'stopped';
  b.textContent = active ? '■' : '▶';
  b.classList.toggle('playing', active);
  b.setAttribute('aria-label', active ? 'Stopp' : 'Abspielen');
  $('hold-overlay').hidden = s !== 'holding';
  if (s === 'holding') {
    const p = engine.position();
    const isCad = tl?.cadenzas.some((c) => Math.abs(c.pos - p) < 1e-6);
    const mic = engine.opts.holdMode === 'mic' && engine.mic.active;
    $('hold-kind').textContent = mic
      ? (isCad ? '🎤 Kadenz – spiel frei, ich warte auf die Pause' : '🎤 Fermate – setz ab, dann geht es weiter')
      : (isCad ? 'Kadenz – spiel frei, dann tippen oder Pedal' : 'Fermate – tippen oder Pedal');
  }
  $('countin').hidden = s !== 'countin';
  $<HTMLButtonElement>('btn-metronome').setAttribute('aria-pressed', String(engine.opts.metronome));
}

// Animations-Schleife: Cursor & Anzeige
function frame(): void {
  requestAnimationFrame(frame);
  if (!tl || !view || $('player').hidden) return;
  const pos = engine.position();
  const mi = measureAt(tl, pos);
  const m = tl.measures[mi];
  view.setCursor(m.src, pos - m.start, m.length, engine.state !== 'stopped');
  const last = tl.sourceMeasures[tl.sourceMeasures.length - 1]?.label ?? '';
  const label = tl.sourceMeasures[m.src].label;
  const txt = `Takt ${label} / ${last}`;
  const pd = $('pos-display');
  if (pd.textContent !== txt) pd.textContent = txt;
  const ci = engine.countInBeat();
  if (ci) {
    const el = $('countin');
    const txt2 = ci.beat === 0 ? '' : String(ci.beat);
    if (el.textContent !== txt2) el.textContent = txt2;
  }
  updateTempoLabel(pos);
  if (engine.mic.active && (!$('options').hidden || engine.state === 'holding')) {
    const w = `${Math.min(100, Math.round(Math.sqrt(engine.micLevel()) * 250))}%`;
    const bar = $('mic-bar');
    if (bar.style.width !== w) bar.style.width = w;
  }
}
requestAnimationFrame(frame);

// ---------------------------------------------------------------- Tempo
let lastTempoLabel = '';
function setTempoUi(pct: number): void {
  $<HTMLInputElement>('tempo').value = String(pct);
  lastTempoLabel = '';
  updateTempoLabel(engine.position());
}
function updateTempoLabel(pos: number): void {
  const pct = Math.round(engine.tempo * 100);
  const bpm = Math.round(engine.qpmAt(pos) * engine.tempo);
  const txt = `${pct} % · ♩=${bpm}`;
  if (txt !== lastTempoLabel) {
    $('tempo-label').textContent = txt;
    lastTempoLabel = txt;
  }
}
function changeTempo(pct: number): void {
  pct = Math.max(25, Math.min(150, Math.round(pct)));
  $<HTMLInputElement>('tempo').value = String(pct);
  engine.setTempo(pct / 100);
  updateTempoLabel(engine.position());
}
$<HTMLInputElement>('tempo').addEventListener('input', (e) => changeTempo(+(e.target as HTMLInputElement).value));
$<HTMLInputElement>('tempo').addEventListener('change', () => saveSettings({ tempo: Math.round(engine.tempo * 100) }));
$('tempo-minus').addEventListener('click', () => {
  changeTempo(engine.tempo * 100 - 5);
  saveSettings({ tempo: Math.round(engine.tempo * 100) });
});
$('tempo-plus').addEventListener('click', () => {
  changeTempo(engine.tempo * 100 + 5);
  saveSettings({ tempo: Math.round(engine.tempo * 100) });
});

// ---------------------------------------------------------------- Bedienelemente
$('btn-play').addEventListener('click', () => togglePlay());
$('btn-continue').addEventListener('click', () => engine.continueFromHold());
$('btn-back').addEventListener('click', () => {
  if (song && view) saveSettings({ tempo: Math.round(engine.tempo * 100) });
  showLibrary();
});
$('btn-rewind').addEventListener('click', () => {
  const p = loopOn && engine.loop ? engine.loop.start : 0;
  engine.seek(p);
  view?.scrollToMeasure(tl!.measures[measureAt(tl!, p)].src);
});
$('jump').addEventListener('change', (e) => {
  const sel = e.target as HTMLSelectElement;
  const v = sel.value;
  sel.value = '';
  if (!v || !tl) return;
  let pos: number | null = null;
  if (v === 'ask') {
    const inp = prompt('Zu welchem Takt?');
    if (!inp) return;
    const src = srcFromLabel(inp);
    if (src === null) {
      toast('Diesen Takt gibt es nicht.');
      return;
    }
    pos = firstPosOfSource(src);
  } else {
    pos = parseFloat(v.slice(4));
  }
  if (pos === null) return;
  engine.seek(pos);
  view?.scrollToMeasure(tl.measures[measureAt(tl, pos)].src);
});

// Tippen auf die Noten
let downAt: { x: number; y: number; t: number } | null = null;
$('score-scroller').addEventListener('pointerdown', (e) => {
  downAt = { x: e.clientX, y: e.clientY, t: performance.now() };
});
$('score-scroller').addEventListener('pointerup', (e) => {
  if (!downAt || !tl || !view) return;
  const moved = Math.hypot(e.clientX - downAt.x, e.clientY - downAt.y);
  const dur = performance.now() - downAt.t;
  downAt = null;
  if (moved > 12 || dur > 700) return;
  if (engine.state === 'holding') {
    engine.continueFromHold();
    return;
  }
  const src = view.measureAtPoint(e.clientX, e.clientY);
  if (src === null) return;
  if (pickMode) {
    const label = tl.sourceMeasures[src].label;
    if (pickMode === 1) {
      $<HTMLInputElement>('loop-from').value = label;
      $<HTMLInputElement>('loop-to').value = label;
      pickMode = 2;
      $('loop-pick').textContent = 'Jetzt Endtakt antippen';
    } else {
      const from = srcFromLabel($<HTMLInputElement>('loop-from').value) ?? src;
      if (src < from) {
        $<HTMLInputElement>('loop-from').value = label;
        $<HTMLInputElement>('loop-to').value = tl.sourceMeasures[from].label;
      } else {
        $<HTMLInputElement>('loop-to').value = label;
      }
      pickMode = 0;
      $('loop-pick').textContent = 'Im Notenbild antippen';
      $('loop-pick').classList.remove('active');
    }
    applyLoop();
    view.flashMeasure(src);
    return;
  }
  const pos = firstPosOfSource(src);
  if (pos === null) return;
  view.flashMeasure(src);
  engine.seek(pos);
});

// Tastatur & Bluetooth-Pedale
document.addEventListener('keydown', (e) => {
  if ($('player').hidden) return;
  const tag = (e.target as HTMLElement).tagName;
  if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
  if (e.key === ' ' || e.key === 'Enter') {
    e.preventDefault();
    togglePlay();
  } else if (['ArrowRight', 'ArrowDown', 'PageDown'].includes(e.key) && engine.state === 'holding') {
    e.preventDefault();
    engine.continueFromHold();
  }
});

// ---------------------------------------------------------------- Schleife
function applyLoop(): void {
  if (!tl) return;
  saveSettings({ loopFrom: $<HTMLInputElement>('loop-from').value, loopTo: $<HTMLInputElement>('loop-to').value });
  if (!loopOn) {
    engine.loop = null;
    view?.showLoop(null, null);
    return;
  }
  const a = srcFromLabel($<HTMLInputElement>('loop-from').value);
  const b = srcFromLabel($<HTMLInputElement>('loop-to').value);
  if (a === null || b === null) {
    toast('Bitte gültige Taktnummern eingeben.');
    return;
  }
  const from = Math.min(a, b);
  const to = Math.max(a, b);
  const start = firstPosOfSource(from);
  if (start === null) return;
  const endM = tl.measures.find((m) => m.src === to && m.start >= start - 1e-9);
  if (!endM) return;
  const incOn = $<HTMLInputElement>('loop-inc-on').checked;
  engine.loop = {
    start,
    end: endM.start + endM.length,
    increase: incOn ? +$<HTMLSelectElement>('loop-inc').value : 0,
    target: +$<HTMLSelectElement>('loop-target').value,
  };
  view?.showLoop(from, to);
  const p = engine.position();
  if (p < engine.loop.start - 1e-9 || p >= engine.loop.end) engine.seek(engine.loop.start);
  updateLoopInfo();
}
function updateLoopInfo(): void {
  const info = $('loop-info');
  if (!loopOn || !engine.loop) {
    info.textContent = '';
    return;
  }
  info.textContent = `Durchgang ${engine.loopPass} · ${Math.round(engine.tempo * 100)} %`;
}
function updateLoopUi(): void {
  $('btn-loop').setAttribute('aria-pressed', String(loopOn));
  $('loop-row').hidden = !loopOn;
  if (!loopOn) {
    pickMode = 0;
    $('loop-pick').classList.remove('active');
    $('loop-pick').textContent = 'Im Notenbild antippen';
  }
  applyLoop();
}
$('btn-loop').addEventListener('click', () => {
  loopOn = !loopOn;
  if (loopOn && tl && !song?.settings.loopFrom) {
    // Standard: aktueller Takt + 3
    const cur = tl.measures[measureAt(tl, engine.position())].src;
    $<HTMLInputElement>('loop-from').value = tl.sourceMeasures[cur].label;
    $<HTMLInputElement>('loop-to').value = tl.sourceMeasures[Math.min(cur + 3, tl.sourceMeasures.length - 1)].label;
  }
  updateLoopUi();
});
for (const id of ['loop-from', 'loop-to', 'loop-inc-on', 'loop-inc', 'loop-target']) {
  $(id).addEventListener('change', () => applyLoop());
}
$('loop-pick').addEventListener('click', () => {
  pickMode = pickMode ? 0 : 1;
  $('loop-pick').classList.toggle('active', pickMode !== 0);
  $('loop-pick').textContent = pickMode ? 'Starttakt antippen' : 'Im Notenbild antippen';
});

// ---------------------------------------------------------------- Einstellungen
function initOptionsUi(): void {
  const o = engine.opts;
  $<HTMLInputElement>('opt-acc').checked = o.accompaniment;
  $<HTMLInputElement>('opt-acc-vol').value = String(Math.round(o.accompanimentVolume * 100));
  $<HTMLInputElement>('opt-solo').checked = o.solo;
  $<HTMLInputElement>('opt-solo-vol').value = String(Math.round(o.soloVolume * 100));
  $<HTMLInputElement>('opt-met').checked = o.metronome;
  $<HTMLInputElement>('opt-met-vol').value = String(Math.round(o.metronomeVolume * 100));
  $<HTMLSelectElement>('opt-countin').value = String(o.countInBars);
  $<HTMLSelectElement>('opt-holdmode').value = o.holdMode;
  $<HTMLSelectElement>('opt-stretch').value = String(o.fermataStretch);
  updateHoldUi();
}

function bindCheck(id: string, key: 'accompaniment' | 'solo' | 'metronome'): void {
  $(id).addEventListener('change', (e) => {
    engine.setOptions({ [key]: (e.target as HTMLInputElement).checked });
    savePrefs();
    syncControls();
  });
}
function bindVol(id: string, key: 'accompanimentVolume' | 'soloVolume' | 'metronomeVolume'): void {
  $(id).addEventListener('input', (e) => {
    engine.setOptions({ [key]: +(e.target as HTMLInputElement).value / 100 });
  });
  $(id).addEventListener('change', () => savePrefs());
}
bindCheck('opt-acc', 'accompaniment');
bindCheck('opt-solo', 'solo');
bindCheck('opt-met', 'metronome');
bindVol('opt-acc-vol', 'accompanimentVolume');
bindVol('opt-solo-vol', 'soloVolume');
bindVol('opt-met-vol', 'metronomeVolume');
// Fermaten & Kadenzen
const HOLD_HINTS: Record<HoldMode, string> = {
  auto: 'Fermaten und Kadenzen werden automatisch ausgehalten, danach spielt die Begleitung weiter.',
  mic: 'Der Player hört über das Mikrofon zu und spielt weiter, sobald du den Fermatenton absetzt. Bei Kadenzen wartet er auf etwa 1 Sekunde Pause. Der Ton wird nur auf dem iPad ausgewertet, nichts wird aufgenommen. Tippen oder Pedal geht zusätzlich immer.',
  tap: 'Weiter geht es mit Tippen auf „Weiter“ oder die Noten, mit der Leertaste oder einem Bluetooth-Pedal.',
};
function updateHoldUi(): void {
  const m = engine.opts.holdMode;
  $('row-mic').hidden = m !== 'mic';
  $('hold-hint').textContent = HOLD_HINTS[m]
    + (m !== 'auto' ? ' Fermaten, bei denen du selbst nicht spielst, laufen automatisch weiter.' : '');
  $('mic-status').textContent = engine.mic.active ? 'hört zu' : 'aus';
}
async function startMic(): Promise<boolean> {
  try {
    await engine.mic.start(engine.ctx);
    await engine.unlock(); // Audio-Sitzung auf Aufnahme + Wiedergabe umstellen
    updateHoldUi();
    return true;
  } catch (e) {
    toast(`Kein Zugriff auf das Mikrofon – es wird auf Tippen gewartet. (${(e as Error).message})`, 5000);
    engine.setOptions({ holdMode: 'tap' });
    $<HTMLSelectElement>('opt-holdmode').value = 'tap';
    savePrefs();
    updateHoldUi();
    return false;
  }
}
$('opt-holdmode').addEventListener('change', async (e) => {
  const m = (e.target as HTMLSelectElement).value as HoldMode;
  engine.setOptions({ holdMode: m });
  savePrefs();
  if (m === 'mic') await startMic();
  else engine.mic.stop();
  updateHoldUi();
});
$('opt-stretch').addEventListener('change', (e) => {
  engine.setOptions({ fermataStretch: +(e.target as HTMLSelectElement).value });
  savePrefs();
});

$('opt-countin').addEventListener('change', (e) => {
  engine.setOptions({ countInBars: +(e.target as HTMLSelectElement).value });
  savePrefs();
});
$('btn-metronome').addEventListener('click', () => {
  engine.setOptions({ metronome: !engine.opts.metronome });
  $<HTMLInputElement>('opt-met').checked = engine.opts.metronome;
  savePrefs();
  syncControls();
});
$('btn-options').addEventListener('click', () => ($('options').hidden = false));
$('opt-close').addEventListener('click', () => ($('options').hidden = true));
$('options').addEventListener('click', (e) => {
  if (e.target === $('options')) $('options').hidden = true;
});

function rerender(): void {
  if (!view || !tl) return;
  view.render();
  applyLoop();
}
$('opt-show-acc').addEventListener('change', (e) => {
  if (!view) return;
  view.showAccompaniment = (e.target as HTMLInputElement).checked;
  saveSettings({ showPiano: view.showAccompaniment });
  rerender();
});
function setZoom(z: number): void {
  if (!view) return;
  view.zoom = Math.max(0.5, Math.min(2, Math.round(z * 10) / 10));
  $('zoom-label').textContent = `${Math.round(view.zoom * 100)} %`;
  saveSettings({ zoom: view.zoom });
  rerender();
}
$('zoom-minus').addEventListener('click', () => view && setZoom(view.zoom - 0.1));
$('zoom-plus').addEventListener('click', () => view && setZoom(view.zoom + 0.1));
$('opt-solo-part').addEventListener('change', async (e) => {
  saveSettings({ soloPart: (e.target as HTMLSelectElement).value });
  loading(true, 'Noten werden neu gesetzt …');
  await loadScore().catch((err) => alert(err.message));
  loading(false);
});
$('opt-notation').addEventListener('change', async (e) => {
  saveSettings({ notation: (e.target as HTMLSelectElement).value as 'auto' | 'concert' | 'transposed' });
  loading(true, 'Noten werden neu gesetzt …');
  await loadScore().catch((err) => alert(err.message));
  loading(false);
});

// Drehen / Größe ändern -> neu setzen
let resizeTimer = 0;
let lastWidth = window.innerWidth;
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = window.setTimeout(() => {
    if (Math.abs(window.innerWidth - lastWidth) < 20) return;
    lastWidth = window.innerWidth;
    if (!$('player').hidden) rerender();
  }, 300);
});

// ---------------------------------------------------------------- Bildschirm anlassen
async function requestWakeLock(): Promise<void> {
  try {
    const wl = (navigator as unknown as { wakeLock?: { request: (t: string) => Promise<{ release: () => Promise<void> }> } }).wakeLock;
    if (wl && !wakeLock) wakeLock = await wl.request('screen');
  } catch {
    /* nicht unterstützt */
  }
}
function releaseWakeLock(): void {
  wakeLock?.release().catch(() => {});
  wakeLock = null;
}
document.addEventListener('visibilitychange', () => {
  if (document.hidden && engine.state !== 'stopped') stopPlayback();
});

// ---------------------------------------------------------------- Offline (Service Worker)
$('app-info').textContent = `Version ${__APP_VERSION__} · Daten bleiben auf diesem Gerät.`;
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  navigator.serviceWorker.register(`${BASE}sw.js`, { scope: BASE }).then((reg) => {
    reg.addEventListener('updatefound', () => {
      const nw = reg.installing;
      nw?.addEventListener('statechange', () => {
        if (nw.state === 'installed' && navigator.serviceWorker.controller) {
          toast('Neue Version installiert – beim nächsten Öffnen aktiv.', 4000);
        }
      });
    });
    if (navigator.serviceWorker.controller) {
      $('app-info').textContent += ' Offline bereit ✓';
    }
  }).catch(() => {});
}

initOptionsUi();
showLibrary();

// Für automatische Tests und Fehlersuche (Safari-Konsole)
(window as unknown as { __playalong: unknown }).__playalong = { engine, get timeline() { return tl; }, get view() { return view; } };
