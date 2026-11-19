// Original-Modus: die Aufnahme (MP3) abspielen, Cursor über sync.json mitführen.
// Tempo ohne Tonhöhenänderung über preservesPitch des Audio-Elements (Safari/Chrome eingebaut).
import type { Timeline } from '../musicxml/timeline';
import { measureAt } from '../musicxml/timeline';
import type { Engine, EngineState, LoopSettings } from './engine';

/** Gemeinsame Schnittstelle für „Noten“ (Engine) und „Original“ */
export interface Transport {
  state: EngineState;
  tempo: number;
  loop: LoopSettings | null;
  loopPass: number;
  position(): number;
  play(from: number, countIn?: boolean): Promise<void>;
  stop(keepPos?: boolean): void;
  seek(pos: number): void;
  setTempo(f: number): void;
  countInBeat(): { beat: number; of: number } | null;
  qpmAt(pos: number): number;
  continueFromHold(): void;
  onStateChange: (s: EngineState) => void;
  onLoopPass: (pass: number, tempo: number) => void;
  onEnd: () => void;
}

export interface SyncData {
  version: number;
  end?: number;
  duration?: number;
  measures: { index: number; time: number }[];
}

/** Prüft, ob sync.json zur Partitur passt. Gibt sonst eine Fehlermeldung zurück. */
export function checkSync(tl: Timeline, sync: unknown): string | null {
  const s = sync as SyncData | undefined;
  if (!s || !Array.isArray(s.measures)) return 'Im Liedpaket fehlt der Abgleich (sync.json).';
  if (s.measures.length !== tl.measures.length) {
    return `Der Abgleich passt nicht zur Partitur (${s.measures.length} statt ${tl.measures.length} Takte). Bitte das Paket neu bauen.`;
  }
  return null;
}

export const ORIGINAL_MIN_TEMPO = 0.5;
export const ORIGINAL_MAX_TEMPO = 1.0;

export class OriginalPlayer implements Transport {
  state: EngineState = 'stopped';
  tempo = 1;
  loop: LoopSettings | null = null;
  loopPass = 1;
  onStateChange: (s: EngineState) => void = () => {};
  onLoopPass: (pass: number, tempo: number) => void = () => {};
  onEnd: () => void = () => {};

  private audio: HTMLAudioElement;
  private url: string;
  private source: MediaElementAudioSourceNode | null = null;
  private gain: GainNode;
  private times: number[];
  private endTime: number;
  private stopPos = 0;
  private timer: number | null = null;
  private startTimer: number | null = null;
  private lastCT = -1;
  private lastPerf = 0;
  private countIn: { beat: number; of: number } | null = null;
  private countInTimes: number[] = [];
  private nextBeat = 0;
  private primed = false;
  private beatsStale = true;

  constructor(private engine: Engine, private tl: Timeline, blob: Blob, sync: SyncData) {
    this.times = sync.measures.map((m) => m.time);
    const last = tl.measures[tl.measures.length - 1];
    const lastLen = this.times.length > 1 ? this.times[this.times.length - 1] - this.times[this.times.length - 2] : 2;
    this.endTime = sync.end ?? (this.times[this.times.length - 1] + lastLen * (last ? 1 : 0));
    this.url = URL.createObjectURL(blob);
    this.audio = new Audio();
    this.audio.preload = 'auto';
    this.audio.src = this.url;
    this.setPreservesPitch();
    this.gain = engine.ctx.createGain();
    this.gain.connect(engine.output);
    this.updateVolume();
  }

  private setPreservesPitch(): void {
    const a = this.audio as HTMLAudioElement & { webkitPreservesPitch?: boolean; mozPreservesPitch?: boolean };
    a.preservesPitch = true;
    a.webkitPreservesPitch = true;
    a.mozPreservesPitch = true;
  }

  /** Lautstärke = Einstellung „Begleitung“ */
  updateVolume(): void {
    const o = this.engine.opts;
    this.gain.gain.setTargetAtTime(o.accompaniment ? o.accompanimentVolume : 0, this.engine.ctx.currentTime, 0.02);
  }

  /**
   * iOS erlaubt das Abspielen nur direkt nach einer Nutzeraktion. Deshalb das Audio-Element
   * beim ersten Tippen einmal kurz starten und anhalten; danach darf es jederzeit spielen.
   * Muss synchron im Klick-Handler aufgerufen werden.
   */
  prime(): void {
    if (this.primed) return;
    this.primed = true;
    this.connect();
    const p = this.audio.play();
    if (p) p.then(() => { if (this.state === 'stopped' || this.state === 'countin') this.audio.pause(); }).catch(() => { this.primed = false; });
  }

  private connect(): void {
    if (this.source) return;
    this.source = this.engine.ctx.createMediaElementSource(this.audio);
    this.source.connect(this.gain);
  }

  dispose(): void {
    this.stop(false);
    this.audio.removeAttribute('src');
    this.audio.load();
    this.source?.disconnect();
    this.gain.disconnect();
    URL.revokeObjectURL(this.url);
  }

  // ---------------------------------------------------------------- Zeit <-> Position
  /** Aufnahmezeit (s) eines Zeitpunkts in der Zeitleiste (Viertel) */
  timeOf(pos: number): number {
    const k = measureAt(this.tl, pos);
    const m = this.tl.measures[k];
    const t0 = this.times[k];
    const t1 = k + 1 < this.times.length ? this.times[k + 1] : this.endTime;
    return t0 + ((pos - m.start) / m.length) * (t1 - t0);
  }

  /** Position (Viertel) zu einer Aufnahmezeit */
  posOf(t: number): number {
    const ts = this.times;
    if (t <= ts[0]) return 0;
    let lo = 0;
    let hi = ts.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (ts[mid] <= t) lo = mid;
      else hi = mid - 1;
    }
    const m = this.tl.measures[lo];
    const t1 = lo + 1 < ts.length ? ts[lo + 1] : this.endTime;
    const f = Math.min(1, (t - ts[lo]) / Math.max(1e-3, t1 - ts[lo]));
    return m.start + f * m.length;
  }

  /** Viertel pro Minute in der Aufnahme an dieser Stelle (bei 100 %) */
  qpmAt(pos: number): number {
    const k = measureAt(this.tl, pos);
    const t0 = this.times[k];
    const t1 = k + 1 < this.times.length ? this.times[k + 1] : this.endTime;
    return (this.tl.measures[k].length / Math.max(1e-3, t1 - t0)) * 60;
  }

  /** geglättete Abspielzeit: currentTime wird nicht in jedem Bild aktualisiert */
  private smoothTime(): number {
    const ct = this.audio.currentTime;
    const now = performance.now();
    if (ct !== this.lastCT) {
      this.lastCT = ct;
      this.lastPerf = now;
      return ct;
    }
    if (this.state !== 'playing' || this.audio.paused) return ct;
    return ct + Math.min(0.3, ((now - this.lastPerf) / 1000) * this.audio.playbackRate);
  }

  // ---------------------------------------------------------------- Transport
  position(): number {
    if (this.state === 'stopped') return this.stopPos;
    if (this.state === 'countin') return this.stopPos;
    return this.posOf(this.smoothTime());
  }

  countInBeat(): { beat: number; of: number } | null {
    return this.state === 'countin' ? this.countIn : null;
  }

  private seekTo(t: number): Promise<void> {
    return new Promise((resolve) => {
      if (Math.abs(this.audio.currentTime - t) < 0.005) {
        resolve();
        return;
      }
      const done = () => {
        this.audio.removeEventListener('seeked', done);
        resolve();
      };
      this.audio.addEventListener('seeked', done);
      this.audio.currentTime = t;
      setTimeout(done, 1500);
    });
  }

  async play(from: number, countIn = true): Promise<void> {
    this.stop(false);
    this.connect();
    await this.engine.unlock();
    this.audio.playbackRate = this.tempo;
    this.setPreservesPitch();
    this.stopPos = from;
    const target = Math.max(0, this.timeOf(from));
    await this.seekTo(target);
    this.lastCT = -1;
    this.resetBeats(target);

    const bars = countIn ? this.engine.opts.countInBars : 0;
    if (bars > 0) {
      const k = measureAt(this.tl, from);
      const m = this.tl.measures[k];
      const compound = m.beatType === 8 && m.beats % 3 === 0 && m.beats > 3;
      const beatsPerBar = compound ? m.beats / 3 : m.beats;
      const t1 = k + 1 < this.times.length ? this.times[k + 1] : this.endTime;
      const sec = (t1 - this.times[k]) / beatsPerBar / this.tempo;
      const total = beatsPerBar * bars;
      const now = this.engine.ctx.currentTime + 0.08;
      this.countInTimes = [];
      for (let i = 0; i < total; i++) {
        const t = now + i * sec;
        this.engine.metronomeClick(t, i % beatsPerBar === 0, true);
        this.countInTimes.push(t);
      }
      this.countIn = { beat: 0, of: total };
      this.state = 'countin';
      this.onStateChange(this.state);
      // Audio-Element braucht einen Moment zum Anlaufen -> etwas früher starten
      const delay = (now - this.engine.ctx.currentTime + total * sec) * 1000 - 40;
      this.startTimer = window.setTimeout(() => this.startAudio(), Math.max(0, delay));
    } else {
      await this.startAudio();
    }
    this.timer = window.setInterval(() => this.tick(), 10);
  }

  private async startAudio(): Promise<void> {
    this.startTimer = null;
    try {
      await this.audio.play();
    } catch {
      this.stop(true);
      return;
    }
    this.countIn = null;
    this.state = 'playing';
    this.onStateChange(this.state);
  }

  stop(keepPos = true): void {
    if (keepPos && this.state !== 'stopped') this.stopPos = this.position();
    if (this.startTimer !== null) clearTimeout(this.startTimer);
    if (this.timer !== null) clearInterval(this.timer);
    this.startTimer = null;
    this.timer = null;
    this.audio.pause();
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
    this.tempo = Math.max(ORIGINAL_MIN_TEMPO, Math.min(ORIGINAL_MAX_TEMPO, f));
    this.audio.playbackRate = this.tempo;
    this.setPreservesPitch();
  }

  continueFromHold(): void {
    /* Aufnahmen warten nicht */
  }

  // ---------------------------------------------------------------- laufende Kontrolle
  private resetBeats(t: number): void {
    const beats = this.tl.beats;
    let i = 0;
    while (i < beats.length && this.timeOf(beats[i].pos) < t - 1e-3) i++;
    this.nextBeat = i;
  }

  private tick(): void {
    const ctx = this.engine.ctx;
    if (this.state === 'countin') {
      const idx = this.countInTimes.filter((x) => x <= ctx.currentTime).length;
      this.countIn = { beat: idx, of: this.countInTimes.length };
      return;
    }
    if (this.state !== 'playing') return;
    const t = this.audio.currentTime;

    // Schleife
    if (this.loop) {
      const endT = this.timeOf(this.loop.end);
      if (t >= endT - 0.01) {
        this.loopPass++;
        if (this.loop.increase > 0) {
          this.setTempo(Math.min(this.loop.target / 100, this.tempo + this.loop.increase / 100));
        }
        const start = this.timeOf(this.loop.start);
        this.audio.currentTime = start;
        this.lastCT = -1;
        this.resetBeats(start);
        this.onLoopPass(this.loopPass, this.tempo);
        return;
      }
    }
    // Ende
    if (this.audio.ended || t >= Math.min(this.endTime + 0.5, this.audio.duration || Infinity)) {
      this.stop(false);
      this.stopPos = 0;
      this.onEnd();
      return;
    }
    // Metronom zur Aufnahme (Schläge laut Abgleich)
    if (this.engine.opts.metronome) {
      if (this.beatsStale) {
        this.resetBeats(t);
        this.beatsStale = false;
      }
      const beats = this.tl.beats;
      const st = this.smoothTime();
      while (this.nextBeat < beats.length) {
        const bt = this.timeOf(beats[this.nextBeat].pos);
        const ahead = (bt - st) / this.tempo;
        if (ahead > 0.12) break;
        if (ahead > -0.02) this.engine.metronomeClick(ctx.currentTime + Math.max(0, ahead), beats[this.nextBeat].accent, false);
        this.nextBeat++;
      }
    } else {
      this.beatsStale = true;
    }
  }
}
