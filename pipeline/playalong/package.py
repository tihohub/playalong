"""Liedpaket (.playalong) bauen – Format siehe docs/liedpaket-format.md."""
from __future__ import annotations

import json
import os
import re
import tempfile
import zipfile
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

from . import __version__
from .score import Timeline, build_timeline, load_musicxml

AUDIO_TYPES = {".mp3", ".m4a", ".aac", ".ogg", ".wav"}


def safe_name(name: str) -> str:
    """Dateiname, der unter Windows, Linux, iOS und auf der FRITZ!Box-Freigabe funktioniert."""
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", name).strip(" .")
    return name[:120] or "Lied"


def parts(root: ET.Element) -> list[tuple[str, str]]:
    """(id, Name) aller Stimmen"""
    out = []
    for sp in root.iter("score-part"):
        name = (sp.findtext("part-name") or "").strip().replace("&amp;", "&")
        out.append((sp.get("id") or "", name))
    return out


def build_package(score_path: str | Path, audio_path: str | Path | None, out_dir: str | Path, *,
                  title: str | None = None, composer: str | None = None, solo_part: str | None = None,
                  notation: str | None = None, sync: bool = True, report: bool = True,
                  progress=print, precomputed=None) -> Path:
    score_path = Path(score_path)
    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        raise FileNotFoundError(f"Zielordner nicht gefunden: {out_dir}")
    root = load_musicxml(score_path)  # prüft auch, ob die Partitur lesbar ist
    tl = build_timeline(root)
    if solo_part and solo_part not in {p for p, _ in parts(root)}:
        raise ValueError(f"Stimme „{solo_part}“ gibt es nicht. Mit „playalong info“ lassen sich die Stimmen anzeigen.")

    title = title or tl.title or score_path.stem
    composer = composer if composer is not None else tl.composer
    score_name = "score.mxl" if score_path.read_bytes()[:2] == b"PK" else "score.musicxml"

    manifest: dict = {
        "format": "playalong",
        "version": 1,
        "title": title,
        "composer": composer,
        "score": score_name,
        "created": date.today().isoformat(),
        "generator": f"playalong-pipeline {__version__}",
    }
    if solo_part:
        manifest["soloPart"] = solo_part
    if notation and notation != "auto":
        manifest["notation"] = notation

    sync_data = None
    res = None
    audio_name = None
    if audio_path:
        audio_path = Path(audio_path)
        ext = audio_path.suffix.lower()
        if ext not in AUDIO_TYPES:
            raise ValueError(f"Unbekanntes Audioformat: {ext} (erlaubt: {', '.join(sorted(AUDIO_TYPES))})")
        audio_name = f"original{ext}"
        manifest["audio"] = audio_name
        if precomputed is not None or sync:
            from .align import align, sync_json

            res = precomputed if precomputed is not None else align(tl, str(audio_path), progress=progress)
            sync_data = sync_json(tl, res, audio_name)
            manifest["sync"] = "sync.json"

    base = safe_name(title)
    target = out_dir / f"{base}.playalong"
    progress(f"Liedpaket wird geschrieben: {target}")
    # erst in eine temporäre Datei schreiben, dann umbenennen (kein halbes Paket auf dem NAS)
    fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=out_dir)
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            z.write(score_path, score_name)
            if audio_path:
                # MP3 & Co. sind schon komprimiert
                z.write(audio_path, audio_name, compress_type=zipfile.ZIP_STORED)
            if sync_data:
                z.writestr("sync.json", json.dumps(sync_data, ensure_ascii=False, indent=1))
        os.replace(tmp, target)
        try:
            os.chmod(target, 0o644)  # normale Leserechte (temporäre Dateien sind sonst privat)
        except OSError:
            pass
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

    if report and res is not None:
        from .report import write_report

        rep_dir = out_dir / "Prüfberichte"
        rep_dir.mkdir(exist_ok=True)
        rep = write_report(tl, res, str(audio_path), rep_dir / f"{base}.html", title=title)
        progress(f"Prüfbericht: {rep}")
    return target


def build_draft_package(audio_path: str | Path, out_dir: str | Path, *, title: str, composer: str = "",
                        beats_per_bar: int = 4, instrument: str = "auto", lage: str = "auto",
                        progress=print, info: dict | None = None) -> tuple[Path, Path]:
    """Rohentwurf: Melodie aus der Aufnahme erkennen, als Klarinettenstimme speichern und
    zusammen mit der Aufnahme als Liedpaket ablegen. Gibt (Paket, MusicXML-Entwurf) zurück."""
    import numpy as np

    from .align import SyncResult
    from .transcribe import transcribe

    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        raise FileNotFoundError(f"Zielordner nicht gefunden: {out_dir}")
    title = title.strip() or Path(audio_path).stem
    full_title = f"{title} (Rohentwurf)"
    d = transcribe(str(audio_path), full_title, composer, beats_per_bar=beats_per_bar,
                   instrument=instrument, lage=lage, progress=progress)
    if info is not None:
        info.update(mode=d.mode, confidence=round(d.confidence, 2), label=d.confidence_label)
    draft_dir = out_dir / "Rohentwürfe"
    draft_dir.mkdir(exist_ok=True)
    xml_path = draft_dir / f"{safe_name(full_title)}.musicxml"
    xml_path.write_text(d.musicxml, encoding="utf-8")
    progress(f"Noten-Entwurf für MuseScore: {xml_path}")
    res = SyncResult(measure_times=d.measure_times, end_time=d.end_time, audio_duration=d.audio_duration,
                     measure_cost=[0.0] * len(d.measure_times), path=np.zeros((0, 2)))
    pkg = build_package(xml_path, audio_path, out_dir, title=full_title, composer=composer,
                        notation="transposed", progress=progress, precomputed=res)
    return pkg, xml_path


def describe(score_path: str | Path) -> str:
    root = load_musicxml(score_path)
    tl: Timeline = build_timeline(root)
    lines = [f"Titel:      {tl.title or '–'}", f"Komponist:  {tl.composer or '–'}"]
    n_src = len({m.src for m in tl.measures})
    lines.append(f"Takte:      {n_src} notiert, {len(tl.measures)} gespielt (mit Wiederholungen)")
    mins, secs = divmod(int(round(tl.duration)), 60)
    lines.append(f"Dauer:      {mins}:{secs:02d} bei notiertem Tempo")
    tempos = ", ".join(f"{round(q)}" for _, q in tl.tempos[:12]) + (" …" if len(tl.tempos) > 12 else "")
    lines.append(f"Tempi (♩/min): {tempos}")
    lines.append("Stimmen (ID: Name):")
    for pid, name in parts(root):
        lines.append(f"  {pid}: {name}")
    return "\n".join(lines)
