// Mikrofon-Auswertung für das freihändige Weiterspielen nach Fermaten und Kadenzen.
// Ausgewertet werden nur Lautstärke und Tonhöhe, lokal auf dem Gerät; nichts wird aufgenommen oder gespeichert.

export class MicLevel {
  private stream: MediaStream | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private analyser: AnalyserNode | null = null;
  private buf = new Float32Array(2048);
  private sampleRate = 48000;

  get active(): boolean {
    return !!this.stream && this.stream.getAudioTracks().some((t) => t.readyState === 'live');
  }

  async start(ctx: AudioContext): Promise<void> {
    if (this.active) return;
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('Dieses Gerät erlaubt keinen Mikrofonzugriff.');
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: false, autoGainControl: false },
    });
    this.source = ctx.createMediaStreamSource(this.stream);
    this.analyser = ctx.createAnalyser();
    this.analyser.fftSize = 2048;
    this.analyser.smoothingTimeConstant = 0;
    this.buf = new Float32Array(this.analyser.fftSize);
    this.sampleRate = ctx.sampleRate;
    this.source.connect(this.analyser); // nicht mit dem Lautsprecher verbunden
  }

  stop(): void {
    this.source?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.source = null;
    this.analyser = null;
  }

  /** Aktuelle Samples holen (die neuesten stehen am Ende des Puffers) */
  private read(): boolean {
    if (!this.analyser) return false;
    this.analyser.getFloatTimeDomainData(this.buf);
    return true;
  }

  /** Effektivwert (RMS) der letzten `ms` Millisekunden, 0..1 */
  level(ms = 40): number {
    if (!this.read()) return 0;
    return this.rms(ms);
  }

  private rms(ms: number): number {
    const n = Math.min(this.buf.length, Math.max(64, Math.round((this.sampleRate * ms) / 1000)));
    let sum = 0;
    for (let i = this.buf.length - n; i < this.buf.length; i++) sum += this.buf[i] * this.buf[i];
    return Math.sqrt(sum / n);
  }

  /**
   * Misst gleichzeitig:
   *  fast  – Pegel der letzten ~10 ms (für schnelles Erkennen des Tonendes)
   *  level – Pegel der letzten ~40 ms
   *  match – wie deutlich der erwartete Ton (oder seine Oktave) gerade klingt, 0..1
   */
  analyse(targetHz: number | null): { fast: number; level: number; match: number } {
    if (!this.read()) return { fast: 0, level: 0, match: 0 };
    const fast = this.rms(10);
    const level = this.rms(40);
    let match = 0;
    if (targetHz && level > 0.003) {
      // Normalisierte Autokorrelation (NSDF) nur um die erwartete Periodendauer herum
      const sr = this.sampleRate;
      const N = 1024;
      const off = this.buf.length - N;
      const x = this.buf;
      const period = sr / targetHz;
      // ±2 Halbtöne absuchen, Maximum per Parabel verfeinern, dann ±0,5 Halbton Toleranz prüfen
      const lo = Math.max(2, Math.floor(period * Math.pow(2, -2 / 12)));
      const hi = Math.min(N / 2, Math.ceil(period * Math.pow(2, 2 / 12)));
      const vals: number[] = [];
      for (let lag = lo - 1; lag <= hi + 1; lag++) {
        let acf = 0;
        let m = 0;
        for (let i = off; i < off + N - lag; i++) {
          acf += x[i] * x[i + lag];
          m += x[i] * x[i] + x[i + lag] * x[i + lag];
        }
        vals.push(m > 0 ? (2 * acf) / m : 0);
      }
      let best = 1;
      for (let k = 1; k < vals.length - 1; k++) if (vals[k] > vals[best]) best = k;
      const a = vals[best - 1];
      const b = vals[best];
      const c = vals[best + 1];
      const denom = a - 2 * b + c;
      const shift = denom !== 0 ? Math.max(-0.5, Math.min(0.5, (0.5 * (a - c)) / denom)) : 0;
      const lagFine = lo - 1 + best + shift;
      const peak = b - 0.25 * (a - c) * shift;
      const cents = Math.abs(1200 * Math.log2(lagFine / period));
      if (cents <= 50 && vals[best] >= vals[best - 1] && vals[best] >= vals[best + 1]) match = Math.min(1, peak);
    }
    return { fast, level, match };
  }
}
