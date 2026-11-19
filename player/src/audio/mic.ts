// Mikrofon-Pegel für das freihändige Weiterspielen nach Fermaten und Kadenzen.
// Es wird nur die Lautstärke ausgewertet, lokal auf dem Gerät; nichts wird aufgenommen oder gespeichert.

export class MicLevel {
  private stream: MediaStream | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private analyser: AnalyserNode | null = null;
  private buf = new Float32Array(1024);

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
    this.analyser.fftSize = 1024;
    this.buf = new Float32Array(this.analyser.fftSize);
    this.source.connect(this.analyser); // nicht mit dem Lautsprecher verbunden
  }

  stop(): void {
    this.source?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.source = null;
    this.analyser = null;
  }

  /** Effektivwert (RMS) des aktuellen Signals, 0..1 */
  level(): number {
    if (!this.analyser) return 0;
    this.analyser.getFloatTimeDomainData(this.buf);
    let sum = 0;
    for (let i = 0; i < this.buf.length; i++) sum += this.buf[i] * this.buf[i];
    return Math.sqrt(sum / this.buf.length);
  }
}
