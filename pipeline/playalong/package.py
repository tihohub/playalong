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
                  progress=print) -> Path:
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
        if sync:
            from .align import align, sync_json

            res = align(tl, str(audio_path), progress=progress)
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
