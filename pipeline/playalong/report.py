"""Prüfbericht als einzelne HTML-Datei: Aufnahme anhören, Taktklick, Tempokurve, Auffälligkeiten."""
from __future__ import annotations

import base64
import html
import json
import mimetypes
from pathlib import Path

from .align import SyncResult
from .score import Timeline


def _tempo_at(tl: Timeline, pos: float) -> float:
    q = tl.tempos[0][1]
    for p, t in tl.tempos:
        if p <= pos + 1e-9:
            q = t
    return q


def write_report(tl: Timeline, res: SyncResult, audio_path: str, out: Path, title: str, note: str = "") -> Path:
    rows = []
    times = res.measure_times
    costs = res.measure_cost
    mean = sum(costs) / max(1, len(costs))
    sd = (sum((c - mean) ** 2 for c in costs) / max(1, len(costs))) ** 0.5
    for k, m in enumerate(tl.measures):
        t0 = times[k]
        t1 = times[k + 1] if k + 1 < len(times) else res.end_time
        nominal = tl.seconds(m.start + m.length) - tl.seconds(m.start)
        actual = max(1e-3, t1 - t0)
        qpm = _tempo_at(tl, m.start)
        played = qpm * nominal / actual  # tatsächliches Tempo in der Aufnahme
        flag = costs[k] > mean + 2.5 * sd or actual < 0.3 * nominal or actual > 3 * nominal
        rows.append({"k": k, "label": m.label, "t": round(t0, 3), "qpm": round(qpm, 1),
                     "played": round(played, 1), "cost": round(costs[k], 3), "flag": bool(flag)})

    mime = mimetypes.guess_type(audio_path)[0] or "audio/mpeg"
    audio_b64 = base64.b64encode(Path(audio_path).read_bytes()).decode()
    n_flag = sum(r["flag"] for r in rows)
    data = json.dumps(rows)

    page = f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Prüfbericht – {html.escape(title)}</title>
<style>
:root {{ --ink:#1d2b3a; --muted:#66707a; --line:#d8d2c4; --bg:#f4f1ea; --accent:#c0392b; --ok:#27ae60; --warn:#e67e22; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; background:var(--bg); color:var(--ink); }}
header {{ position:sticky; top:0; background:#fff; border-bottom:1px solid var(--line); padding:12px 16px; z-index:2; }}
h1 {{ font-size:1.2rem; margin:0 0 8px; }}
.bar {{ display:flex; gap:12px; align-items:center; flex-wrap:wrap; }}
audio {{ width:min(520px,100%); }}
main {{ padding:16px; max-width:1100px; margin:0 auto; }}
.summary {{ background:#fff; border:1px solid var(--line); border-radius:10px; padding:12px 16px; margin-bottom:16px; line-height:1.5; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(92px,1fr)); gap:6px; }}
.m {{ background:#fff; border:1px solid var(--line); border-radius:8px; padding:6px; cursor:pointer; text-align:left; font:inherit; }}
.m b {{ display:block; }}
.m small {{ color:var(--muted); font-size:.75rem; }}
.m.flag {{ border-color:var(--warn); background:#fff4e6; }}
.m.now {{ outline:3px solid var(--accent); }}
svg {{ width:100%; height:180px; background:#fff; border:1px solid var(--line); border-radius:10px; margin-bottom:16px; }}
.legend {{ color:var(--muted); font-size:.85rem; margin:-8px 0 16px; }}
</style></head><body>
<header>
  <h1>Prüfbericht: {html.escape(title)}</h1>
  <div class="bar">
    <audio id="a" controls preload="auto" src="data:{mime};base64,{audio_b64}"></audio>
    <label><input type="checkbox" id="click" checked> Klick an jedem Taktanfang</label>
    <span id="now"></span>
  </div>
</header>
<main>
  <div class="summary">
    <b>{len(rows)} Takte</b> abgeglichen, Aufnahme {res.audio_duration:.1f} s.
    {"<b style='color:var(--warn)'>" + str(n_flag) + (" Takt" if n_flag == 1 else " Takte") + " bitte anhören</b> (orange markiert)." if n_flag else "<b style='color:var(--ok)'>Keine Auffälligkeiten.</b>"}
    <br>So prüfen: Aufnahme abspielen. Der Klick sollte genau auf jeden Taktanfang fallen. Auf einen Takt tippen spielt ab dort.
    {('<br><b>Hinweis:</b> ' + html.escape(note)) if note else ''}
  </div>
  <svg id="curve" viewBox="0 0 1000 180" preserveAspectRatio="none"></svg>
  <div class="legend">Tempokurve: <span style="color:#2980b9">■</span> gespieltes Tempo laut Abgleich, <span style="color:#aaa">■</span> notiertes Tempo. Plötzliche Zacken deuten auf Fehler im Abgleich hin.</div>
  <div class="grid" id="grid"></div>
</main>
<script>
const rows = {data};
const a = document.getElementById('a');
const grid = document.getElementById('grid');
rows.forEach(r => {{
  const b = document.createElement('button');
  b.className = 'm' + (r.flag ? ' flag' : '');
  b.id = 'm' + r.k;
  const mm = Math.floor(r.t / 60), ss = (r.t % 60).toFixed(1).padStart(4, '0');
  b.innerHTML = `<b>Takt ${{r.label}}</b><small>${{mm}}:${{ss}} · ♩${{Math.round(r.played)}}</small>`;
  b.onclick = () => {{ a.currentTime = Math.max(0, r.t - 0.5); a.play(); }};
  grid.appendChild(b);
}});
// Tempokurve
(function () {{
  const svg = document.getElementById('curve');
  const vals = rows.flatMap(r => [r.played, r.qpm]);
  const max = Math.min(400, Math.max(...vals) * 1.1), n = rows.length;
  const x = k => (k + 0.5) / n * 1000, y = v => 175 - Math.min(v, max) / max * 165;
  const line = (key, color) => `<polyline fill="none" stroke="${{color}}" stroke-width="2" vector-effect="non-scaling-stroke" points="${{rows.map((r, k) => x(k) + ',' + y(r[key])).join(' ')}}"/>`;
  svg.innerHTML = line('qpm', '#bbb') + line('played', '#2980b9');
}})();
// Taktklick + aktuelle Position
let ctx = null, last = -1;
function beep() {{
  ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
  const o = ctx.createOscillator(), g = ctx.createGain();
  o.frequency.value = 1800; g.gain.setValueAtTime(0.5, ctx.currentTime);
  g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.05);
  o.connect(g).connect(ctx.destination); o.start(); o.stop(ctx.currentTime + 0.06);
}}
function idxAt(t) {{ let k = -1; while (k + 1 < rows.length && rows[k + 1].t <= t) k++; return k; }}
a.addEventListener('seeked', () => {{ last = idxAt(a.currentTime); }});
a.addEventListener('play', () => {{ last = idxAt(a.currentTime - 0.02); }});
setInterval(() => {{
  if (a.paused) return;
  const k = idxAt(a.currentTime);
  if (k !== last) {{
    if (k === last + 1 && document.getElementById('click').checked) beep();
    document.querySelector('.m.now')?.classList.remove('now');
    const el = document.getElementById('m' + k);
    if (el) {{ el.classList.add('now'); el.scrollIntoView({{ block: 'nearest' }}); }}
    document.getElementById('now').textContent = k >= 0 ? 'Takt ' + rows[k].label : '';
    last = k;
  }}
}}, 5);
</script>
</body></html>
"""
    out.write_text(page, encoding="utf-8")
    return out
