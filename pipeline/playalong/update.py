"""Werkstatt selbst aktualisieren: neueste Version von GitHub holen und einspielen.

Ablauf: Version auf GitHub prüfen (letzter Commit im Ordner pipeline/ auf main) ->
ZIP laden -> Dateien in den Installationsordner kopieren (.venv bleibt unberührt) ->
falls sich die Abhängigkeiten geändert haben, nur diese nachinstallieren ->
Werkstatt startet sich neu.

Kontakt nur zu GitHub (api.github.com, codeload.github.com) und nur, wenn die
Werkstatt geöffnet ist. Adressen lassen sich für Tests per Umgebungsvariable ändern.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

REPO = "tihohub/playalong"
BRANCH = "main"
API_URL = os.environ.get(
    "PLAYALONG_UPDATE_API", f"https://api.github.com/repos/{REPO}/commits?sha={BRANCH}&path=pipeline&per_page=1")
ZIP_URL = os.environ.get("PLAYALONG_UPDATE_ZIP", f"https://codeload.github.com/{REPO}/zip/refs/heads/{BRANCH}")

# Installationsordner: <root>/pipeline/playalong/update.py
PKG_DIR = Path(__file__).resolve().parent
PIPELINE_DIR = PKG_DIR.parent
ROOT = PIPELINE_DIR.parent
STAMP = PIPELINE_DIR / ".installierte-version.json"
SKIP_DIRS = {".venv", ".git", "node_modules", "__pycache__", "dist", ".idea", ".vscode"}

_cache: dict = {"t": 0.0, "data": None}


def installed() -> dict:
    try:
        return json.loads(STAMP.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _get(url: str, timeout: float = 15) -> bytes:
    req = Request(url, headers={"User-Agent": "playalong-werkstatt", "Accept": "application/vnd.github+json"})
    with urlopen(req, timeout=timeout) as r:
        return r.read()


def check(force: bool = False) -> dict:
    """Vergleicht die installierte mit der neuesten Version. Ergebnis wird 10 Minuten gemerkt."""
    if not force and _cache["data"] and time.time() - _cache["t"] < 600:
        return _cache["data"]
    inst = installed()
    try:
        commits = json.loads(_get(API_URL, timeout=8))
        latest = commits[0]
        info = {
            "sha": latest["sha"],
            "date": latest["commit"]["committer"]["date"],
            "message": latest["commit"]["message"].split("\n")[0],
        }
    except Exception as e:  # noqa: BLE001 – offline o. ä.: kein Fehler, nur Hinweis
        data = {"ok": False, "error": f"Keine Verbindung zu GitHub ({e.__class__.__name__}).",
                "installed": inst, "available": False, "writable": _writable()}
        _cache.update(t=time.time(), data=data)
        return data
    data = {"ok": True, "installed": inst, "latest": info,
            "available": inst.get("sha") != info["sha"], "writable": _writable()}
    _cache.update(t=time.time(), data=data)
    return data


def _writable() -> bool:
    """Nur aktualisieren, wenn wir in einer entpackten Kopie laufen (nicht in einem Git-Klon)."""
    return (PIPELINE_DIR / "pyproject.toml").exists() and not (ROOT / ".git").exists()


def _dependencies(pyproject: Path) -> list[str]:
    try:
        import tomllib
    except ImportError:  # Python < 3.11
        return []
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        return list(data.get("project", {}).get("dependencies", []))
    except (OSError, ValueError):
        return []


def apply(progress=print) -> dict:
    """Neueste Version herunterladen und einspielen. Gibt Infos zur neuen Version zurück."""
    if (ROOT / ".git").exists():
        raise RuntimeError("Dies ist ein Git-Arbeitsordner – bitte mit git aktualisieren.")
    if not (PIPELINE_DIR / "pyproject.toml").exists():
        raise RuntimeError(f"Installationsordner nicht erkannt: {PIPELINE_DIR}")
    status = check(force=True)
    if not status.get("ok"):
        raise RuntimeError(status.get("error") or "Keine Verbindung zu GitHub.")

    progress("Neue Version wird heruntergeladen …")
    data = _get(ZIP_URL, timeout=120)
    progress(f"{len(data) / 1e6:.1f} MB geladen, wird entpackt …")
    old_deps = _dependencies(PIPELINE_DIR / "pyproject.toml")

    with tempfile.TemporaryDirectory(prefix="playalong-update-") as tmp:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            z.extractall(tmp)
        tops = [p for p in Path(tmp).iterdir() if p.is_dir()]
        if len(tops) != 1 or not (tops[0] / "pipeline" / "pyproject.toml").exists():
            raise RuntimeError("Unerwarteter Inhalt im Download – Aktualisierung abgebrochen.")
        src = tops[0]
        new_deps = _dependencies(src / "pipeline" / "pyproject.toml")

        progress("Dateien werden ersetzt …")
        n = 0
        for f in src.rglob("*"):
            rel = f.relative_to(src)
            if any(part in SKIP_DIRS for part in rel.parts) or f.is_dir():
                continue
            dst = ROOT / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
            n += 1
        # entfernte Python-Module der Pipeline aufräumen
        for f in PKG_DIR.rglob("*.py"):
            if not (src / f.relative_to(ROOT)).exists():
                f.unlink()
        progress(f"{n} Dateien aktualisiert.")

    if new_deps and set(new_deps) != set(old_deps):
        # nur die Abhängigkeiten installieren; das Paket selbst ist „editierbar“ installiert
        # und nutzt die neuen Dateien direkt (die laufende .exe wird nicht angefasst)
        progress("Neue Bibliotheken werden installiert (kann einige Minuten dauern) …")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0  # type: ignore[attr-defined]
        res = subprocess.run([_python(), "-m", "pip", "install", "--disable-pip-version-check", *new_deps],
                             capture_output=True, text=True, creationflags=flags)
        if res.returncode != 0:
            raise RuntimeError("Bibliotheken konnten nicht installiert werden:\n" + (res.stderr or res.stdout)[-1500:])
    else:
        progress("Keine neuen Bibliotheken nötig.")

    latest = status["latest"]
    STAMP.write_text(json.dumps({"sha": latest["sha"], "date": latest["date"], "message": latest["message"],
                                 "installed": time.strftime("%Y-%m-%dT%H:%M:%S")}, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    _cache.update(t=0.0, data=None)
    progress("Fertig. Die Werkstatt startet neu …")
    return latest


def _python() -> str:
    """python.exe statt pythonw.exe für pip (Ausgabe abfangen)."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        cand = exe.with_name("python.exe")
        if cand.exists():
            return str(cand)
    return str(exe)


def restart(port: int) -> None:
    """Neue Werkstatt-Instanz starten; sie wartet, bis diese hier den Port freigegeben hat."""
    args = [sys.executable, "-m", "playalong.cli", "gui", "--ohne-browser", "--neustart", "--port", str(port)]
    kw: dict = {"cwd": str(PIPELINE_DIR), "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
    else:
        kw["start_new_session"] = True
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PIPELINE_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    subprocess.Popen(args, env=env, **kw)
