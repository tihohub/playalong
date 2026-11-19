"""Kommandozeile: playalong build | sync | info | ziel"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import __version__

CONFIG = Path.home() / ".playalong.json"
NOTATION = {"auto": "auto", "klingend": "concert", "in-b": "transposed"}


def _load_config() -> dict:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_config(cfg: dict) -> None:
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _progress(msg: str) -> None:
    print(f"  {msg}", flush=True)


def cmd_build(a: argparse.Namespace) -> int:
    from .package import build_package

    ziel = a.ziel or _load_config().get("ziel")
    if not ziel:
        print("Kein Zielordner angegeben. Entweder --ziel ORDNER verwenden oder einmalig festlegen mit:\n"
              "  playalong ziel \"\\\\fritz.box\\FRITZ.NAS\\...\\Play-along\"")
        return 2
    t = time.time()
    print(f"Baue Liedpaket aus {a.partitur}" + (f" + {a.aufnahme}" if a.aufnahme else ""))
    target = build_package(a.partitur, a.aufnahme, ziel, title=a.titel, composer=a.komponist,
                           solo_part=a.stimme, notation=NOTATION[a.notiert], sync=not a.ohne_sync,
                           report=not a.ohne_bericht, progress=_progress)
    print(f"Fertig in {time.time() - t:.0f} s: {target}")
    return 0


def cmd_sync(a: argparse.Namespace) -> int:
    from .align import align, sync_json
    from .score import build_timeline, load_musicxml

    tl = build_timeline(load_musicxml(a.partitur))
    t = time.time()
    res = align(tl, a.aufnahme, progress=_progress)
    out = Path(a.ausgabe or Path(a.aufnahme).with_suffix(".sync.json"))
    out.write_text(json.dumps(sync_json(tl, res, Path(a.aufnahme).name), ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"sync.json geschrieben: {out} ({time.time() - t:.0f} s)")
    if a.bericht:
        from .report import write_report

        rep = write_report(tl, res, a.aufnahme, Path(a.bericht), title=tl.title or Path(a.partitur).stem)
        print(f"Prüfbericht: {rep}")
    return 0


def cmd_info(a: argparse.Namespace) -> int:
    from .package import describe

    print(describe(a.partitur))
    return 0


def cmd_ziel(a: argparse.Namespace) -> int:
    cfg = _load_config()
    if a.ordner:
        p = Path(a.ordner)
        if not p.is_dir():
            print(f"Ordner nicht gefunden: {p}")
            return 2
        cfg["ziel"] = str(p)
        _save_config(cfg)
        print(f"Zielordner gespeichert: {p}")
    else:
        print(f"Zielordner: {cfg.get('ziel', '(noch nicht festgelegt)')}")
    return 0


def cmd_gui(a: argparse.Namespace) -> int:
    from .gui import main as gui_main

    return gui_main(open_browser=not a.ohne_browser)


def cmd_verknuepfung(a: argparse.Namespace) -> int:
    """Desktop-Verknüpfung „Play-along Werkstatt“ anlegen (Windows; Linux: Startmenü-Eintrag)."""
    import os
    import subprocess

    scripts = Path(sys.executable).parent
    icon = Path(__file__).with_name("web") / "icon.ico"
    if os.name == "nt":
        target = scripts / "playalong-werkstatt.exe"
        if not target.exists():
            print(f"Nicht gefunden: {target}\nBitte zuerst im pipeline-Ordner „pip install -e .“ ausführen.")
            return 1
        ps = (
            "$d=[Environment]::GetFolderPath('Desktop');"
            "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'Play-along Werkstatt.lnk'));"
            "$s.TargetPath=$env:PA_TARGET; $s.IconLocation=$env:PA_ICON; $s.WorkingDirectory=$env:PA_DIR;"
            "$s.Description='Play-along: Liedpakete bauen'; $s.Save(); Write-Output (Join-Path $d 'Play-along Werkstatt.lnk')"
        )
        env = dict(os.environ, PA_TARGET=str(target), PA_ICON=str(icon), PA_DIR=str(scripts))
        res = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                             capture_output=True, text=True, env=env)
        if res.returncode != 0:
            print("Verknüpfung konnte nicht angelegt werden:\n" + res.stderr.strip())
            return 1
        print(f"Verknüpfung angelegt: {res.stdout.strip()}")
        return 0
    # Linux: Eintrag im Anwendungsmenü
    apps = Path.home() / ".local" / "share" / "applications"
    apps.mkdir(parents=True, exist_ok=True)
    f = apps / "playalong-werkstatt.desktop"
    f.write_text("[Desktop Entry]\nType=Application\nName=Play-along Werkstatt\n"
                 f"Exec={scripts / 'playalong-werkstatt'}\nIcon={icon.with_suffix('.png')}\nTerminal=false\n", encoding="utf-8")
    print(f"Menüeintrag angelegt: {f}")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Windows-Konsole: Umlaute und Sonderzeichen sicher ausgeben
    for s in (sys.stdout, sys.stderr):
        if s is None:
            continue
        try:
            s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(prog="playalong", description="Play-along: Liedpakete bauen und Aufnahmen mit Noten abgleichen.")
    p.add_argument("--version", action="version", version=f"playalong {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="Liedpaket (.playalong) bauen und im Zielordner ablegen")
    b.add_argument("partitur", help="MusicXML-Datei (.musicxml, .xml oder .mxl)")
    b.add_argument("aufnahme", nargs="?", help="optional: Aufnahme (MP3 o. ä.)")
    b.add_argument("--ziel", help="Zielordner (z. B. NAS-Freigabe); sonst der mit „playalong ziel“ gespeicherte")
    b.add_argument("--titel", help="Titel (Standard: aus der Partitur)")
    b.add_argument("--komponist", help="Komponist (Standard: aus der Partitur)")
    b.add_argument("--stimme", help="ID der eigenen Stimme, falls nicht automatisch erkannt (siehe „playalong info“)")
    b.add_argument("--notiert", choices=list(NOTATION), default="auto",
                   help="Klarinettenstimme: auto (Standard), klingend (wird nach B transponiert) oder in-b")
    b.add_argument("--ohne-sync", action="store_true", help="Aufnahme nicht mit den Noten abgleichen")
    b.add_argument("--ohne-bericht", action="store_true", help="keinen Prüfbericht schreiben")
    b.set_defaults(func=cmd_build)

    s = sub.add_parser("sync", help="nur abgleichen: sync.json (und optional Prüfbericht) erzeugen")
    s.add_argument("partitur")
    s.add_argument("aufnahme")
    s.add_argument("-o", "--ausgabe", help="Ausgabedatei (Standard: <aufnahme>.sync.json)")
    s.add_argument("--bericht", help="Prüfbericht als HTML-Datei schreiben")
    s.set_defaults(func=cmd_sync)

    i = sub.add_parser("info", help="Partitur anzeigen: Titel, Takte, Dauer, Stimmen")
    i.add_argument("partitur")
    i.set_defaults(func=cmd_info)

    z = sub.add_parser("ziel", help="Standard-Zielordner anzeigen oder festlegen")
    z.add_argument("ordner", nargs="?")
    z.set_defaults(func=cmd_ziel)

    g = sub.add_parser("gui", help="Werkstatt (Bedienoberfläche im Browser) starten")
    g.add_argument("--ohne-browser", action="store_true", help="Browser nicht automatisch öffnen")
    g.set_defaults(func=cmd_gui)

    v = sub.add_parser("verknuepfung", help="Desktop-Verknüpfung „Play-along Werkstatt“ anlegen")
    v.set_defaults(func=cmd_verknuepfung)

    a = p.parse_args(argv)
    try:
        return a.func(a)
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(f"Fehler: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
