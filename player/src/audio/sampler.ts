// Einfacher Sampler: lädt einzelne Ton-Samples und spielt beliebige Tonhöhen
// durch Umrechnen der Abspielgeschwindigkeit vom nächstgelegenen Sample.

export interface Voice {
  src: AudioBufferSourceNode;
  gain: GainNode;
  start: number;
  release: (when: number) => void;
}

const NAMES_SHARP = ['C', 'Cs', 'D', 'Ds', 'E', 'F', 'Fs', 'G', 'Gs', 'A', 'As', 'B'];
const NAMES_FLAT = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B'];

export function noteName(midi: number, flats: boolean): string {
  const n = (flats ? NAMES_FLAT : NAMES_SHARP)[midi % 12];
  return `${n}${Math.floor(midi / 12) - 1}`;
}

export interface SamplerSpec {
  baseUrl: string;
  midis: number[];
  flats: boolean;
  /** Sample in Schleife spielen (für gehaltene Blasinstrument-Töne) */
  loop: boolean;
  releaseTime: number;
  gain: number;
}

export class Sampler {
  private buffers = new Map<number, AudioBuffer>();
  private sorted: number[] = [];
  private loading: Promise<void> | null = null;
  constructor(private spec: SamplerSpec) {}

  get loaded(): boolean {
    return this.sorted.length > 0;
  }

  load(ctx: BaseAudioContext): Promise<void> {
    if (!this.loading) {
      this.loading = Promise.all(this.spec.midis.map(async (m) => {
        const url = `${this.spec.baseUrl}${noteName(m, this.spec.flats)}.mp3`;
        const res = await fetch(url);
        if (!res.ok) throw new Error(`Sample fehlt: ${url}`);
        const data = await res.arrayBuffer();
        const buf = await new Promise<AudioBuffer>((resolve, reject) => {
          // Callback-Variante für ältere Safari-Versionen
          ctx.decodeAudioData(data, resolve, reject);
        });
        this.buffers.set(m, buf);
      })).then(() => {
        this.sorted = [...this.buffers.keys()].sort((a, b) => a - b);
      }).catch((e) => {
        this.loading = null;
        throw e;
      });
    }
    return this.loading;
  }

  private nearest(midi: number): number {
    let best = this.sorted[0];
    for (const m of this.sorted) if (Math.abs(m - midi) < Math.abs(best - midi)) best = m;
    return best;
  }

  /** Spielt einen Ton. end = null -> bleibt liegen, bis release() aufgerufen wird. */
  play(ctx: BaseAudioContext, dest: AudioNode, midi: number, when: number, end: number | null, vel: number): Voice | null {
    if (!this.loaded) return null;
    const root = this.nearest(midi);
    const buf = this.buffers.get(root)!;
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.playbackRate.value = Math.pow(2, (midi - root) / 12);
    const g = ctx.createGain();
    const level = this.spec.gain * (0.25 + 0.75 * vel);
    const sp = this.spec;
    if (sp.loop && buf.duration > 1.2) {
      src.loop = true;
      src.loopStart = 0.35;
      src.loopEnd = buf.duration * 0.75;
      g.gain.setValueAtTime(0, when);
      g.gain.linearRampToValueAtTime(level, when + 0.03);
    } else {
      g.gain.setValueAtTime(level, when);
    }
    src.connect(g).connect(dest);
    src.start(when);
    let released = false;
    const release = (t: number) => {
      if (released) return;
      released = true;
      const at = Math.max(t, when + 0.01);
      g.gain.cancelScheduledValues(at);
      g.gain.setTargetAtTime(0, at, sp.releaseTime / 3);
      try {
        src.stop(at + sp.releaseTime * 2);
      } catch {
        /* schon gestoppt */
      }
    };
    if (end !== null) {
      release(end);
    } else if (!sp.loop) {
      // Klavier: Sample klingt natürlich aus
      src.stop(when + buf.duration / src.playbackRate.value + 0.05);
    }
    return { src, gain: g, start: when, release };
  }
}

function range(from: number, to: number, step: number): number[] {
  const out: number[] = [];
  for (let m = from; m <= to; m += step) out.push(m);
  return out;
}

export function createPiano(base: string): Sampler {
  // Salamander Grand Piano: A0 (21) bis C8 (108), alle kleinen Terzen
  return new Sampler({ baseUrl: `${base}samples/piano/`, midis: range(21, 108, 3), flats: false, loop: false, releaseTime: 0.35, gain: 0.9 });
}

export function createClarinet(base: string): Sampler {
  // FluidR3 GM Klarinette: C3 (48) bis C7 (96)
  return new Sampler({ baseUrl: `${base}samples/clarinet/`, midis: range(48, 96, 3), flats: true, loop: true, releaseTime: 0.12, gain: 0.8 });
}
