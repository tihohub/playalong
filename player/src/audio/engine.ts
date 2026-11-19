// Wiedergabe-Engine: plant Noten und Metronom mit Vorlauf über die Web Audio API.
import type { Timeline, Hold } from '../musicxml/timeline';
import { Sampler, Voice, createPiano, createClarinet } from './sampler';
import { MicLevel } from './mic';

export type EngineState = 'stopped' | 'countin' | 'playing' | 'holding';

/**
 * Fermaten und Kadenzen:
 *  auto – automatisch aushalten (Länge × fermataStretch)
 *  mic  – warten, bis der Spieler absetzt (Mikrofon)
 *  tap  – warten auf Tippen / Pedal / Leertaste
 */
export type HoldMode = 'auto' | 'mic' | 'tap';

export interface EngineOptions {
  accompaniment: boolean;
  accompanimentVolume: number; // 0..1
  solo: boolean; // Klarinettenstimme hörbar
  soloVolume: number;
  metronome: boolean;
  metronomeVolume: number;
  countInBars: number; // 0, 1, 2
  holdMode: HoldMode;
  fermataStretch: number; // Fermate ohne Warten: Dauer × Faktor
}

export interface LoopSettings {
  start: number;
  end: number;
  increase: number; // Prozentpunkte pro Durchgang (0 = aus)
  target: number; // Ziel-Tempo in Prozent
}

interface Anchor {
  audio: number;
  pos: number;
  factor: number;
}

/** Zeitachse bei 100 % Tempo: Position (Viertel) <-> Sekunden */
class TimeMap {
  private bp: number[] = [];
  private tc: number[] = [];
  private qps: number[] = [];

  constructor(tl: Timeline, stretch: { pos: number; end: number; factor: number }[]) {
    const points = new Set<number>([0, tl.length]);
    for (const t of tl.tempos) points.add(t.pos);
    for (const s of stretch) {
      points.add(s.pos);
      points.add(s.end);
    }
    const bps = [...points].filter((p) => p >= 0).sort((a, b) => a - b);
    let ti = 0;
    let cum = 0;
    for (let k = 0; k < bps.length; k++) {
      const p = bps[k];
      while (ti + 1 < tl.tempos.length && tl.tempos[ti + 1].pos <= p + 1e-9) ti++;
      let q = tl.tempos[ti].qpm / 60;
      for (const s of stretch) if (p >= s.pos - 1e-9 && p < s.end - 1e-9) q /= s.factor;
      this.bp.push(p);
      this.tc.push(cum);
      this.qps.push(q);
      if (k + 1 < bps.length) cum += (bps[k + 1] - p) / q;
    }
  }

  private seg(pos: number): number {
    let lo = 0;
    let hi = this.bp.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (this.bp[mid] <= pos) lo = mid;
      else hi = mid - 1;
    }
    return lo;
  }

  time(pos: number): number {
    const k = this.seg(pos);
    return this.tc[k] + (pos - this.bp[k]) / this.qps[k];
  }

  pos(time: number): number {
    let lo = 0;
    let hi = this.tc.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (this.tc[mid] <= time) lo = mid;
      else hi = mid - 1;
    }
    return this.bp[lo] + (time - this.tc[lo]) * this.qps[lo];
  }

  qpmAt(pos: number): number {
    return this.qps[this.seg(pos)] * 60;
  }
}

const LOOKAHEAD = 0.25; // Sekunden Vorlauf
const TICK_MS = 25;

export class Engine {
  readonly ctx: AudioContext;
  private master: GainNode;
  private accGain: GainNode;
  private soloGain: GainNode;
  private metGain: GainNode;
  private piano: Sampler;
  private clarinet: Sampler;

  private tl: Timeline | null = null;
  private soloPart = '';
  private map: TimeMap | null = null;
  private holds: Hold[] = [];

  opts: EngineOptions = {
    accompaniment: true, accompanimentVolume: 0.8,
    solo: false, soloVolume: 0.6,
    metronome: false, metronomeVolume: 0.6,
    countInBars: 1, holdMode: 'auto', fermataStretch: 2,
  };

  state: EngineState = 'stopped';
  tempo = 1; // Faktor
  loop: LoopSettings | null = null;
  loopPass = 1;

  private anchors: Anchor[] = [];
  private scheduledPos = 0;
  private noteIdx = 0;
  private beatIdx = 0;
  private holdIdx = 0;
  private pendingHold: { hold: Hold; audio: number } | null = null;
  private pendingEnd: number | null = null;
  private voices: Voice[] = [];
  private held: Voice[] = [];
  private clicks: { osc: OscillatorNode; start: number }[] = [];
  private timer: number | null = null;
  private stopPos = 0;
  readonly mic = new MicLevel();
  /** Zustand während einer Fermate/Kadenz */
  private holdWatch: { since: number; soloPlays: boolean; nominal: number; peak: number; quietSince: number | null; autoAt: number | null } | null = null;

  onStateChange: (s: EngineState) => void = () => {};
  onLoopPass: (pass: number, tempo: number) => void = () => {};
  onEnd: () => void = () => {};

  constructor(base: string) {
    const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    this.ctx = new AC({ latencyHint: 'interactive' });
    this.master = this.ctx.createGain();
    this.master.connect(this.ctx.destination);
    this.accGain = this.ctx.createGain();
    this.soloGain = this.ctx.createGain();
    this.metGain = this.ctx.createGain();
    for (const g of [this.accGain, this.soloGain, this.metGain]) g.connect(this.master);
    this.piano = createPiano(base);
    this.clarinet = createClarinet(base);
    this.applyVolumes();
  }

  /** Muss aus einer Nutzeraktion heraus aufgerufen werden (iOS). */
  async unlock(): Promise<void> {
    // iOS: Wiedergabe auch bei Stummschalter („Klingeln aus“)
    try {
      const nav = navigator as unknown as { audioSession?: { type: string } };
      if (nav.audioSession) nav.audioSession.type = this.mic.active ? 'play-and-record' : 'playback';
    } catch {
      /* nicht unterstützt */
    }
    if (this.ctx.state !== 'running') {
      const b = this.ctx.createBuffer(1, 1, 22050);
      const s = this.ctx.createBufferSource();
      s.buffer = b;
      s.connect(this.ctx.destination);
      s.start();
      await this.ctx.resume();
    }
  }

  loadSamples(): Promise<void> {
    return Promise.all([this.piano.load(this.ctx), this.clarinet.load(this.ctx)]).then(() => {});
  }

  get samplesLoaded(): boolean {
    return this.piano.loaded && this.clarinet.loaded;
  }

  setTimeline(tl: Timeline, soloPart: string): void {
    this.stop();
    this.tl = tl;
    this.soloPart = soloPart;
    this.stopPos = 0;
    this.rebuildMap();
  }

  private rebuildMap(): void {
    if (!this.tl) return;
    const tl = this.tl;
    // Kadenzen ersetzen Fermaten innerhalb ihres Takts
    const holds = [...tl.cadenzas];
    for (const f of tl.fermatas) {
      if (!tl.cadenzas.some((c) => f.pos >= c.pos - 1e-9 && f.pos < c.resume - 1e-9)) holds.push(f);
    }
    holds.sort((a, b) => a.pos - b.pos);
    if (this.opts.holdMode !== 'auto') {
      this.holds = holds;
      this.map = new TimeMap(tl, []);
    } else {
      this.holds = [];
      this.map = new TimeMap(tl, holds.map((f) => ({ pos: f.pos, end: f.resume, factor: this.opts.fermataStretch })));
    }
  }

  setOptions(o: Partial<EngineOptions>): void {
    const holdsChanged = (o.holdMode !== undefined && (o.holdMode === 'auto') !== (this.opts.holdMode === 'auto'))
      || (o.fermataStretch !== undefined && o.fermataStretch !== this.opts.fermataStretch);
    this.opts = { ...this.opts, ...o };
    this.applyVolumes();
    if (holdsChanged) {
      const playing = this.state === 'playing';
      const p = this.position();
      if (playing) this.stop();
      this.rebuildMap();
      if (playing) this.play(p, false);
    }
  }

  private applyVolumes(): void {
    const t = this.ctx.currentTime;
    const o = this.opts;
    this.accGain.gain.setTargetAtTime(o.accompaniment ? o.accompanimentVolume : 0, t, 0.02);
    this.soloGain.gain.setTargetAtTime(o.solo ? o.soloVolume : 0, t, 0.02);
    this.metGain.gain.setTargetAtTime(o.metronome ? o.metronomeVolume : 0, t, 0.02);
  }

  qpmAt(pos: number): number {
    return this.map ? this.map.qpmAt(pos) : 120;
  }

  /** Aktuelle Position in Vierteln */
  position(): number {
    if (this.state === 'stopped' || !this.map || this.anchors.length === 0) return this.stopPos;
    const now = this.ctx.currentTime;
    let a = this.anchors[0];
    for (const x of this.anchors) if (x.audio <= now) a = x;
    if (this.state === 'holding' && this.pendingHold) return this.pendingHold.hold.pos;
    if (now < a.audio) return a.pos;
    let p = this.map.pos(this.map.time(a.pos) + (now - a.audio) * a.factor);
    if (this.pendingHold && p > this.pendingHold.hold.pos) p = this.pendingHold.hold.pos;
    return p;
  }

  /** Fortschritt des Einzählers 0..1, oder null */
  countInBeat(): { beat: number; of: number } | null {
    if (this.state !== 'countin') return null;
    return this.countIn;
  }
  private countIn: { beat: number; of: number } | null = null;
  private countInTimes: number[] = [];

  private timeOf(a: Anchor, pos: number): number {
    return a.audio + (this.map!.time(pos) - this.map!.time(a.pos)) / a.factor;
  }

  private firstNoteFrom(pos: number, strict = false): number {
    const n = this.tl!.notes;
    let lo = 0;
    let hi = n.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (strict ? n[mid].start <= pos + 1e-9 : n[mid].start < pos - 1e-9) lo = mid + 1;
      else hi = mid;
    }
    return lo;
  }

  private firstBeatFrom(pos: number, strict = false): number {
    const b = this.tl!.beats;
    let i = 0;
    while (i < b.length && (strict ? b[i].pos <= pos + 1e-9 : b[i].pos < pos - 1e-9)) i++;
    return i;
  }

  private resetPointers(pos: number, strict = false): void {
    this.noteIdx = this.firstNoteFrom(pos, strict);
    this.beatIdx = this.firstBeatFrom(pos, strict);
    this.holdIdx = 0;
    while (this.holdIdx < this.holds.length && this.holds[this.holdIdx].pos < pos - 1e-9) this.holdIdx++;
    this.scheduledPos = pos;
  }

  async play(from: number, countIn = true): Promise<void> {
    if (!this.tl || !this.map) return;
    this.stop(false);
    await this.unlock();
    const now = this.ctx.currentTime + 0.08;
    let start = now;
    const bars = countIn ? this.opts.countInBars : 0;
    this.countInTimes = [];
    if (bars > 0) {
      const mi = this.measureIndexAt(from);
      const m = this.tl.measures[mi];
      const compound = m.beatType === 8 && m.beats % 3 === 0 && m.beats > 3;
      const beatsPerBar = compound ? m.beats / 3 : m.beats;
      const beatLen = compound ? 1.5 : 4 / m.beatType;
      const sec = beatLen / (this.map.qpmAt(from) / 60) / this.tempo;
      const total = beatsPerBar * bars;
      for (let i = 0; i < total; i++) {
        const t = now + i * sec;
        this.click(t, i % beatsPerBar === 0, true);
        this.countInTimes.push(t);
      }
      start = now + total * sec;
      this.countIn = { beat: 0, of: total };
      this.state = 'countin';
    } else {
      this.state = 'playing';
    }
    this.anchors = [{ audio: start, pos: from, factor: this.tempo }];
    this.resetPointers(from);
    this.pendingHold = null;
    this.pendingEnd = null;
    this.onStateChange(this.state);
    this.tick();
    this.timer = window.setInterval(() => this.tick(), TICK_MS);
  }

  private measureIndexAt(pos: number): number {
    const ms = this.tl!.measures;
    let i = 0;
    while (i + 1 < ms.length && ms[i + 1].start <= pos + 1e-9) i++;
    return i;
  }

  stop(keepPos = true): void {
    if (keepPos && this.state !== 'stopped') this.stopPos = this.position();
    if (this.timer !== null) clearInterval(this.timer);
    this.timer = null;
    const t = this.ctx.currentTime;
    for (const v of [...this.voices, ...this.held]) {
      if (v.start > t) {
        try {
          v.src.stop();
        } catch {
          /* */
        }
      } else v.release(t);
    }
    for (const c of this.clicks) {
      try {
        c.osc.stop();
      } catch {
        /* */
      }
    }
    this.voices = [];
    this.held = [];
    this.clicks = [];
    this.anchors = [];
    this.pendingHold = null;
    this.holdWatch = null;
    this.countIn = null;
    if (this.state !== 'stopped') {
      this.state = 'stopped';
      this.onStateChange(this.state);
    }
  }

  seek(pos: number): void {
    if (this.state === 'stopped') this.stopPos = pos;
    else this.play(pos, false);
  }

  setTempo(f: number): void {
    this.tempo = f;
    if (this.state !== 'playing') {
      if (this.anchors.length && this.state === 'countin') this.anchors[this.anchors.length - 1].factor = f;
      return;
    }
    // ab jetzt neu planen
    const now = this.ctx.currentTime;
    const pos = this.position();
    this.voices = this.voices.filter((v) => {
      if (v.start > now) {
        try {
          v.src.stop();
        } catch {
          /* */
        }
        return false;
      }
      return true;
    });
    this.clicks = this.clicks.filter((c) => {
      if (c.start > now) {
        try {
          c.osc.stop();
        } catch {
          /* */
        }
        return false;
      }
      return true;
    });
    this.anchors = [{ audio: now, pos, factor: f }];
    this.pendingHold = null;
    this.pendingEnd = null;
    this.resetPointers(pos, true);
  }

  /** Nach einer Fermate/Kadenz weiterspielen */
  continueFromHold(): void {
    if (this.state !== 'holding' || !this.pendingHold) return;
    const now = this.ctx.currentTime;
    for (const v of this.held) v.release(now);
    this.held = [];
    const resume = this.pendingHold.hold.resume;
    this.pendingHold = null;
    this.holdWatch = null;
    this.anchors = [{ audio: now + 0.03, pos: resume, factor: this.tempo }];
    this.resetPointers(resume);
    this.state = 'playing';
    this.onStateChange(this.state);
    this.tick();
  }

  /** Spielt die eigene Stimme an der Haltestelle? */
  private soloPlaysAt(pos: number, end: number): boolean {
    return this.tl!.notes.some((n) => n.part === this.soloPart && n.start < end - 1e-9 && n.start + n.dur > pos + 1e-9);
  }

  private startHoldWatch(now: number): void {
    const h = this.pendingHold!.hold;
    const a = this.anchors[this.anchors.length - 1];
    const nominal = Math.max(0.3, this.timeOf(a, h.resume) - this.timeOf(a, h.pos));
    const soloPlays = this.soloPlaysAt(h.pos, h.resume);
    // Spielt die eigene Stimme nicht mit, gibt es niemanden, auf den man warten müsste
    const autoAt = soloPlays ? null : now + nominal * this.opts.fermataStretch;
    this.holdWatch = { since: now, soloPlays, nominal, peak: 0, quietSince: null, autoAt };
  }

  private checkHold(now: number): void {
    const w = this.holdWatch;
    if (!w || !this.pendingHold) return;
    if (w.autoAt !== null && now >= w.autoAt) {
      this.continueFromHold();
      return;
    }
    if (this.opts.holdMode !== 'mic' || !this.mic.active || !w.soloPlays) return;
    const cadenza = this.pendingHold.hold.kind === 'cadenza';
    const lvl = this.mic.level();
    if (lvl > w.peak) w.peak = lvl;
    const heard = w.peak > 0.015;
    const threshold = Math.max(0.006, w.peak * 0.22);
    if (lvl < threshold) {
      if (w.quietSince === null) w.quietSince = now;
    } else {
      w.quietSince = null;
    }
    const minHold = cadenza ? 1.5 : Math.min(w.nominal, 0.8);
    const quietNeeded = cadenza ? 1.0 : 0.12;
    if (heard && now - w.since >= minHold && w.quietSince !== null && now - w.quietSince >= quietNeeded) {
      this.continueFromHold();
    }
  }

  /** Mikrofon-Pegel (für die Anzeige) */
  micLevel(): number {
    return this.mic.active ? this.mic.level() : 0;
  }

  private click(when: number, accent: boolean, countIn = false): void {
    const ctx = this.ctx;
    const osc = ctx.createOscillator();
    const g = ctx.createGain();
    osc.frequency.value = accent ? 1600 : 1000;
    const level = countIn ? Math.max(0.5, this.opts.metronomeVolume) : 1;
    g.gain.setValueAtTime(0, when);
    g.gain.linearRampToValueAtTime(level * (accent ? 0.9 : 0.6), when + 0.002);
    g.gain.exponentialRampToValueAtTime(0.001, when + 0.06);
    osc.connect(g).connect(countIn ? this.master : this.metGain);
    osc.start(when);
    osc.stop(when + 0.08);
    this.clicks.push({ osc, start: when });
  }

  private tick(): void {
    if (!this.tl || !this.map) return;
    const now = this.ctx.currentTime;
    // Aufräumen
    if (this.voices.length > 200) this.voices = this.voices.filter((v) => v.start > now - 30);
    if (this.clicks.length > 100) this.clicks = this.clicks.filter((c) => c.start > now - 1);

    if (this.state === 'countin') {
      const idx = this.countInTimes.filter((t) => t <= now).length;
      this.countIn = { beat: idx, of: this.countInTimes.length };
      if (now >= this.anchors[0].audio) {
        this.state = 'playing';
        this.countIn = null;
        this.onStateChange(this.state);
      }
    }

    if (this.pendingHold && now >= this.pendingHold.audio && this.state === 'playing') {
      this.state = 'holding';
      this.startHoldWatch(now);
      this.onStateChange(this.state);
    }
    if (this.state === 'holding') {
      this.checkHold(now);
      return;
    }
    if (this.pendingEnd !== null && now >= this.pendingEnd) {
      this.pendingEnd = null;
      this.stopPos = 0;
      this.stop(false);
      this.stopPos = 0;
      this.onEnd();
      return;
    }
    if (this.pendingHold || this.pendingEnd !== null) return;

    const horizon = now + LOOKAHEAD;
    let guard = 0;
    while (guard++ < 8) {
      const a = this.anchors[this.anchors.length - 1];
      const horizonPos = horizon <= a.audio ? a.pos : this.map.pos(this.map.time(a.pos) + (horizon - a.audio) * a.factor);
      const endPos = this.loop ? this.loop.end : this.tl.length;
      let limit = horizonPos;
      let holdHit: Hold | null = null;
      let endHit = false;
      const hold = this.holds[this.holdIdx];
      if (hold && hold.pos < endPos - 1e-9 && hold.pos <= limit) {
        limit = hold.pos;
        holdHit = hold;
      } else if (endPos <= limit) {
        limit = endPos;
        endHit = true;
      }
      this.scheduleRange(a, limit, holdHit !== null, endPos);
      if (holdHit) {
        this.pendingHold = { hold: holdHit, audio: this.timeOf(a, holdHit.pos) };
        this.holdIdx++;
        return;
      }
      if (endHit) {
        const endAudio = this.timeOf(a, endPos);
        if (this.loop) {
          this.loopPass++;
          if (this.loop.increase > 0) {
            this.tempo = Math.min(this.loop.target / 100, this.tempo + this.loop.increase / 100);
            if (this.tempo < 0.1) this.tempo = 0.1;
          }
          const pass = this.loopPass;
          const tempo = this.tempo;
          window.setTimeout(() => this.onLoopPass(pass, tempo), Math.max(0, (endAudio - now) * 1000));
          this.anchors.push({ audio: endAudio, pos: this.loop.start, factor: this.tempo });
          if (this.anchors.length > 4) this.anchors.shift();
          this.resetPointers(this.loop.start);
          continue;
        }
        this.pendingEnd = endAudio + 0.3;
        return;
      }
      return;
    }
  }

  /** Plant alle Noten/Schläge von scheduledPos bis limit. includeAtLimit: Töne genau auf limit werden gehalten. */
  private scheduleRange(a: Anchor, limit: number, includeAtLimit: boolean, endPos: number): void {
    const tl = this.tl!;
    const notes = tl.notes;
    while (this.noteIdx < notes.length) {
      const n = notes[this.noteIdx];
      const atLimit = Math.abs(n.start - limit) < 1e-9;
      if (n.start > limit + 1e-9 || (atLimit && !includeAtLimit)) break;
      this.noteIdx++;
      if (n.start < this.scheduledPos - 1e-9) continue;
      const isSolo = n.part === this.soloPart;
      const when = this.timeOf(a, n.start);
      const endQ = Math.min(n.start + n.dur, endPos);
      const end = atLimit && includeAtLimit ? null : this.timeOf(a, endQ);
      const sampler = isSolo ? this.clarinet : this.piano;
      const dest = isSolo ? this.soloGain : this.accGain;
      // Nicht-Solo-Stimmen klingen alle als Klavier (Begleitung)
      const v = sampler.play(this.ctx, dest, n.midi, when, end, n.vel);
      if (v) {
        if (end === null) this.held.push(v);
        else this.voices.push(v);
      }
    }
    const beats = tl.beats;
    while (this.beatIdx < beats.length) {
      const b = beats[this.beatIdx];
      const atLimit = Math.abs(b.pos - limit) < 1e-9;
      if (b.pos > limit + 1e-9 || (atLimit && !includeAtLimit)) break;
      this.beatIdx++;
      if (b.pos < this.scheduledPos - 1e-9) continue;
      this.click(this.timeOf(a, b.pos), b.accent);
    }
    this.scheduledPos = limit;
  }
}
