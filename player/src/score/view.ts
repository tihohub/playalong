// Notenanzeige mit OpenSheetMusicDisplay + eigener Cursor (folgt der Wiedergabeposition).
import { OpenSheetMusicDisplay } from 'opensheetmusicdisplay';
import type { GraphicalMeasure } from 'opensheetmusicdisplay';

interface Entry {
  t: number; // Viertel ab Taktbeginn
  x: number; // px
}

interface MeasureBox {
  x: number;
  y: number;
  w: number;
  h: number;
  entries: Entry[];
  /** Mehrtaktpause: dieser Takt wird in einer gemeinsamen Box dargestellt */
  multi?: { first: number; count: number };
}

export class ScoreView {
  readonly osmd: OpenSheetMusicDisplay;
  private boxes: MeasureBox[] = [];
  private cursor: HTMLDivElement;
  private loopLayer: HTMLDivElement;
  private markLayer: HTMLDivElement;
  private lastSystemTop = -1;
  private userScrolledAt = 0;
  zoom = 1;
  /** sichtbare Begleitstimmen (Part-IDs); die eigene Stimme ist immer sichtbar */
  visibleParts = new Set<string>();
  /** Part-IDs in Partitur-Reihenfolge (eigene Stimme zuerst) */
  partIds: string[] = [];
  private soloPartId = '';

  constructor(private scroller: HTMLElement, private host: HTMLElement) {
    this.osmd = new OpenSheetMusicDisplay(host, {
      autoResize: false,
      backend: 'svg',
      drawTitle: true,
      drawSubtitle: true,
      drawComposer: true,
      drawLyricist: false,
      drawCredits: false,
      drawPartNames: true,
      drawPartAbbreviations: true,
      drawMeasureNumbers: true,
      drawFingerings: true,
      followCursor: false,
      pageFormat: 'Endless',
      newSystemFromXML: false,
      newPageFromXML: false,
    });
    const rules = this.osmd.EngravingRules;
    rules.RenderMultipleRestMeasures = true;
    rules.AutoGenerateMultipleRestMeasuresFromRestMeasures = true;
    rules.PageTopMargin = 2;
    rules.PageBottomMargin = 4;
    rules.PageLeftMargin = 2;
    rules.PageRightMargin = 2;

    this.loopLayer = document.createElement('div');
    this.loopLayer.className = 'loop-layer';
    this.markLayer = document.createElement('div');
    this.markLayer.className = 'mark-layer';
    this.cursor = document.createElement('div');
    this.cursor.className = 'score-cursor';
    this.cursor.hidden = true;
    host.parentElement!.append(this.loopLayer, this.markLayer, this.cursor);

    const markUser = () => (this.userScrolledAt = performance.now());
    scroller.addEventListener('touchmove', markUser, { passive: true });
    scroller.addEventListener('wheel', markUser, { passive: true });
  }

  async load(xml: string, soloPartId: string): Promise<void> {
    this.soloPartId = soloPartId;
    await this.osmd.load(xml);
  }

  /** Erneut zeichnen (Größe, Ausrichtung, Begleitung ein/aus) */
  render(): void {
    const sheet = this.osmd.Sheet;
    if (!sheet) return;
    sheet.Instruments.forEach((ins, i) => {
      // Erste Stimme ist immer die eigene (siehe prepareScore)
      const id = this.partIds[i] ?? ins.IdString;
      ins.Visible = i === 0 || this.visibleParts.has(id);
    });
    this.osmd.Zoom = this.zoom;
    this.osmd.render();
    this.buildBoxes();
    this.lastSystemTop = -1;
  }

  private unitPx(): number {
    return 10 * this.zoom;
  }

  private buildBoxes(): void {
    const gs = this.osmd.GraphicSheet;
    const svg = this.host.querySelector('svg');
    if (!gs || !svg) return;
    const hostRect = this.host.parentElement!.getBoundingClientRect();
    const svgRect = svg.getBoundingClientRect();
    const ox = svgRect.left - hostRect.left;
    const oy = svgRect.top - hostRect.top;
    const u = this.unitPx();
    const list = gs.MeasureList;
    const boxes: MeasureBox[] = [];

    for (let mi = 0; mi < list.length; mi++) {
      const staves = (list[mi] ?? []).filter((m): m is GraphicalMeasure => !!m && !!m.PositionAndShape
        && m.ParentStaff?.ParentInstrument?.Visible !== false && !!m.ParentStaffLine);
      if (staves.length === 0) {
        boxes.push(undefined as unknown as MeasureBox);
        continue;
      }
      const top = staves[0];
      const bottom = staves[staves.length - 1];
      const ps = top.PositionAndShape;
      const x = ox + ps.AbsolutePosition.x * u;
      const w = ps.Size.width * u;
      const y = oy + (top.PositionAndShape.AbsolutePosition.y - 1.5) * u;
      const yb = oy + (bottom.PositionAndShape.AbsolutePosition.y + 5.5) * u;
      const ents = new Map<number, number>();
      for (const m of staves) {
        for (const se of m.staffEntries ?? []) {
          const tq = se.relInMeasureTimestamp.RealValue * 4;
          const ex = ox + se.PositionAndShape.AbsolutePosition.x * u;
          const prev = ents.get(tq);
          if (prev === undefined || ex < prev) ents.set(tq, ex);
        }
      }
      const entries = [...ents.entries()].map(([t, ex]) => ({ t, x: ex })).sort((a, b) => a.t - b.t);
      const box: MeasureBox = { x, y, w, h: yb - y, entries };
      if (top.isMultiRestMeasure && top.isMultiRestMeasure()) {
        const count = (top.parentSourceMeasure as unknown as { multipleRestMeasures?: number })?.multipleRestMeasures ?? 1;
        box.multi = { first: mi, count: Math.max(1, count) };
      }
      boxes.push(box);
    }
    // Lücken (Takte innerhalb einer Mehrtaktpause) auffüllen
    for (let mi = 0; mi < boxes.length; mi++) {
      if (boxes[mi]) continue;
      let k = mi - 1;
      while (k >= 0 && !boxes[k]) k--;
      if (k >= 0) {
        const b = boxes[k];
        if (!b.multi) b.multi = { first: k, count: 1 };
        b.multi.count = Math.max(b.multi.count, mi - k + 1);
        boxes[mi] = { ...b, entries: [], multi: b.multi };
      } else {
        boxes[mi] = { x: 0, y: 0, w: 1, h: 1, entries: [] };
      }
    }
    this.boxes = boxes;
  }

  get measureCount(): number {
    return this.boxes.length;
  }

  /** Cursor auf Quelltakt + Position (Viertel) innerhalb des Takts setzen */
  setCursor(src: number, rel: number, length: number, follow: boolean): void {
    const b = this.boxes[src];
    if (!b) {
      this.cursor.hidden = true;
      return;
    }
    let x: number;
    if (b.multi) {
      // gleichmäßig über die Mehrtaktpause verteilen
      const frac = (src - b.multi.first + Math.min(1, rel / Math.max(length, 1e-6))) / b.multi.count;
      x = b.x + 8 + frac * (b.w - 16);
    } else {
      const left = b.entries.length ? Math.min(b.entries[0].x, b.x + b.w) : b.x + 6;
      const pts = b.entries.length ? b.entries.slice() : [{ t: 0, x: left }];
      if (pts[0].t > 0) pts.unshift({ t: 0, x: left });
      pts.push({ t: length, x: b.x + b.w - 4 });
      x = pts[pts.length - 1].x;
      for (let i = 0; i + 1 < pts.length; i++) {
        if (rel >= pts[i].t && rel < pts[i + 1].t) {
          const f = (rel - pts[i].t) / Math.max(1e-6, pts[i + 1].t - pts[i].t);
          x = pts[i].x + f * (pts[i + 1].x - pts[i].x);
          break;
        }
      }
    }
    this.cursor.hidden = false;
    this.cursor.style.transform = `translate(${x - 2}px, ${b.y}px)`;
    this.cursor.style.height = `${b.h}px`;
    if (follow) this.follow(b);
  }

  hideCursor(): void {
    this.cursor.hidden = true;
  }

  /** Automatisch umblättern: aktuelles System nach oben scrollen */
  private follow(b: MeasureBox): void {
    if (Math.abs(b.y - this.lastSystemTop) < 2) return;
    if (performance.now() - this.userScrolledAt < 2500) return;
    this.lastSystemTop = b.y;
    const view = this.scroller.clientHeight;
    const top = this.scroller.scrollTop;
    const margin = Math.min(130, view * 0.13);
    // nur scrollen, wenn das System nicht bequem sichtbar ist oder unter der Mitte liegt
    if (b.y < top + margin * 0.5 || b.y + b.h > top + view * 0.6) {
      this.scroller.scrollTo({ top: Math.max(0, b.y - margin), behavior: 'smooth' });
    }
  }

  scrollToMeasure(src: number): void {
    const b = this.boxes[src];
    if (!b) return;
    this.lastSystemTop = b.y;
    this.userScrolledAt = 0;
    const margin = Math.min(130, this.scroller.clientHeight * 0.13);
    this.scroller.scrollTo({ top: Math.max(0, b.y - margin), behavior: 'smooth' });
  }

  /** Quelltakt an Bildschirmkoordinate */
  measureAtPoint(clientX: number, clientY: number): number | null {
    const r = this.host.parentElement!.getBoundingClientRect();
    const x = clientX - r.left;
    const y = clientY - r.top;
    for (let i = 0; i < this.boxes.length; i++) {
      const b = this.boxes[i];
      if (!b || b.w <= 1) continue;
      if (x >= b.x && x <= b.x + b.w && y >= b.y && y <= b.y + b.h) {
        if (b.multi) return b.multi.first + Math.min(b.multi.count - 1, Math.floor(((x - b.x) / b.w) * b.multi.count));
        return i;
      }
    }
    return null;
  }

  /** Schleifenbereich hervorheben */
  showLoop(from: number | null, to: number | null): void {
    this.loopLayer.replaceChildren();
    if (from === null || to === null) return;
    const seen = new Set<MeasureBox>();
    for (let i = Math.min(from, to); i <= Math.max(from, to); i++) {
      const b = this.boxes[i];
      if (!b || seen.has(b)) continue;
      seen.add(b);
      const d = document.createElement('div');
      d.className = 'loop-box';
      d.style.cssText = `left:${b.x}px;top:${b.y}px;width:${b.w}px;height:${b.h}px`;
      this.loopLayer.appendChild(d);
    }
  }

  /** Kurzzeitig einen Takt markieren (z. B. Auswahl) */
  flashMeasure(src: number): void {
    const b = this.boxes[src];
    if (!b) return;
    const d = document.createElement('div');
    d.className = 'flash-box';
    d.style.cssText = `left:${b.x}px;top:${b.y}px;width:${b.w}px;height:${b.h}px`;
    this.markLayer.appendChild(d);
    setTimeout(() => d.remove(), 700);
  }

  get soloId(): string {
    return this.soloPartId;
  }
}
