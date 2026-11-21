"""Lokale KI für den Rohentwurf: Einrichtung und Aufruf (Demucs + Basic Pitch).

Die KI läuft in einer eigenen Python-Umgebung unter ~/.playalong/ki, weil es für neue
Python-Versionen noch nicht alle Bausteine gibt. Die Umgebung wird per Knopf in der Werkstatt
eingerichtet: Das Werkzeug „uv“ lädt ein passendes Python (3.12) und die Pakete herunter.
Danach läuft alles ohne Internet. Kein Konto, keine Cloud, keine Kosten.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

KI_DIR = Path(os.environ.get("PLAYALONG_KI_DIR", Path.home() / ".playalong" / "ki"))
VENV = KI_DIR / "venv"
STAMP = KI_DIR / "bereit.json"
WORKER = Path(__file__).with_name("ki_worker.py")
PYTHON_VERSION = "3.12"
TORCH_INDEX = "https://download.pytorch.org/whl/cpu"  # reine CPU-Variante (klein, keine Grafikkarte nötig)
PACKAGES = ["demucs", "onnxruntime", "librosa", "mir_eval", "pretty_midi", "resampy", "scipy",
            "scikit-learn", "soundfile", "numpy"]
BASIC_PITCH = "basic-pitch==0.4.0"  # ohne Abhängigkeiten installiert (fordert sonst ein altes TensorFlow)

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0  # type: ignore[attr-defined]


def python_exe() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def status() -> dict:
    ok = python_exe().exists() and STAMP.exists()
    info = {}
    if ok:
        try:
            info = json.loads(STAMP.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            ok = False
    return {"installed": ok, "dir": str(KI_DIR), **info}


def _env() -> dict:
    env = dict(os.environ)
    env["UV_PYTHON_INSTALL_DIR"] = str(KI_DIR / "python")
    env["TORCH_HOME"] = str(KI_DIR / "torch")  # Demucs-Modelle hier ablegen
    env["HF_HOME"] = str(KI_DIR / "huggingface")
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("PYTHONPATH", None)
    return env


def _main_python() -> str:
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").exists():
        return str(exe.with_name("python.exe"))
    return str(exe)


def _run(cmd: list[str], progress, what: str) -> None:
    """Befehl ausführen, Ausgabe zeilenweise als Fortschritt weitergeben."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace", env=_env(), creationflags=_NO_WINDOW)
    tail: list[str] = []
    assert proc.stdout
    for line in proc.stdout:
        line = line.rstrip()
        if not line:
            continue
        tail = (tail + [line])[-15:]
        if line.startswith("FORTSCHRITT "):
            progress(line[len("FORTSCHRITT "):])
    if proc.wait() != 0:
        raise RuntimeError(f"{what} fehlgeschlagen:\n" + "\n".join(tail))


def setup(progress=print) -> dict:
    """KI-Umgebung einrichten (einmalig, braucht Internet, ca. 1–2 GB)."""
    KI_DIR.mkdir(parents=True, exist_ok=True)
    t = time.time()
    py = _main_python()
    if subprocess.run([py, "-m", "uv", "--version"], capture_output=True, creationflags=_NO_WINDOW).returncode != 0:
        progress("Hilfsprogramm „uv“ wird installiert …")
        _run([py, "-m", "pip", "install", "--disable-pip-version-check", "uv"], progress, "Installation von uv")
    uv = [py, "-m", "uv"]
    progress(f"Eigenes Python {PYTHON_VERSION} für die KI wird eingerichtet …")
    _run(uv + ["venv", "--clear", "--python", PYTHON_VERSION, "--python-preference", "only-managed", str(VENV)],
         progress, "Einrichten der Python-Umgebung")
    target = ["--python", str(python_exe())]
    progress("PyTorch (CPU) wird heruntergeladen – das ist der größte Teil (einige Minuten) …")
    _run(uv + ["pip", "install", *target, "torch", "torchaudio", "--index-url", TORCH_INDEX], progress,
         "Installation von PyTorch")
    progress("Demucs, Basic Pitch und Hilfsbibliotheken werden installiert …")
    _run(uv + ["pip", "install", *target, *PACKAGES], progress, "Installation der KI-Bibliotheken")
    _run(uv + ["pip", "install", *target, "--no-deps", BASIC_PITCH], progress, "Installation von Basic Pitch")
    _run([str(python_exe()), "-I", str(WORKER), "--vorbereiten"], progress, "Laden der KI-Modelle")
    info = {"python": PYTHON_VERSION, "eingerichtet": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "dauer_s": round(time.time() - t)}
    STAMP.write_text(json.dumps(info, indent=2), encoding="utf-8")
    progress(f"KI-Erweiterung ist eingerichtet ({info['dauer_s']} s).")
    return status()


def separate_and_transcribe(audio: str, progress=print) -> tuple[dict, tempfile.TemporaryDirectory]:
    """Arbeitsprozess aufrufen. Gibt (Ergebnis, Arbeitsordner) zurück; der Ordner enthält die Spuren."""
    if not status()["installed"]:
        raise RuntimeError("Die KI-Erweiterung ist noch nicht eingerichtet.")
    work = tempfile.TemporaryDirectory(prefix="playalong-ki-")
    _run([str(python_exe()), "-I", str(WORKER), "--audio", str(audio), "--out", work.name], progress,
         "KI-Auswertung")
    res = json.loads((Path(work.name) / "ergebnis.json").read_text(encoding="utf-8"))
    return res, work


STEM_NAMES = {"vocals": "Gesang", "guitar": "Gitarre", "piano": "Klavier", "other": "Rest"}


def choose_stem(res: dict, wanted: str = "auto") -> str:
    """Melodiespur wählen. Automatisch: unter den Spuren mit nennenswerter Energie die,
    deren führende Stimme am höchsten liegt (Melodien liegen meist oben); Gesang hat Vorrang."""
    stems = {k: v for k, v in res["stems"].items() if v.get("events")}
    if not stems:
        raise RuntimeError("In der Aufnahme wurden keine Töne erkannt.")
    if wanted != "auto":
        if wanted not in stems:
            raise RuntimeError(f"In der Spur „{STEM_NAMES.get(wanted, wanted)}“ wurden keine Töne erkannt.")
        return wanted
    if "vocals" in stems and stems["vocals"]["energy"] >= 0.1:
        return "vocals"
    import numpy as np

    best, best_score = None, -1e9
    for name, v in stems.items():
        if v["energy"] < 0.08:
            continue
        ev = [e for e in v["events"] if e[1] - e[0] >= 0.06]
        if len(ev) < 8:
            continue
        top = np.percentile([e[2] for e in ev], 75)
        if top > best_score:
            best, best_score = name, top
    return best or max(stems, key=lambda k: stems[k]["energy"])
