"""Play-along Werkstatt: Bedienoberfläche im Browser für die Pipeline.

Startet einen kleinen Webserver nur auf diesem Rechner (127.0.0.1) und öffnet den Browser.
Keine zusätzlichen Abhängigkeiten: nur die Python-Standardbibliothek.

    playalong gui            (oder Doppelklick auf die Verknüpfung „Play-along Werkstatt“)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import urlopen

from . import __version__

PORT = 8765
HOME = Path.home() / ".playalong"
UPLOADS = HOME / "werkstatt-uploads"
LOG = HOME / "werkstatt.log"
MAX_UPLOAD = 300 * 1024 * 1024  # 300 MB
CLARINET_RE = re.compile(r"klarinette|clarinet|clarinetto|clarinete|clarinette|^\s*(b-)?kl(ar)?\.|^\s*cl\.", re.I)
WEB = Path(__file__).with_name("web")


def _log(msg: str) -> None:
    try:
        HOME.mkdir(exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except OSError:
        pass


# --------------------------------------------------------------------------- Aufträge

class Job:
    def __init__(self) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.status = "running"
        self.log: list[str] = []
        self.result: dict = {}
        self.error = ""


JOBS: dict[str, Job] = {}
UPLOADED: dict[str, Path] = {}
BOOT_ID = uuid.uuid4().hex[:8]  # ändert sich bei jedem Start (Seite erkennt den Neustart)


def score_info(path: Path) -> dict:
    from .package import parts
    from .score import build_timeline, load_musicxml

    root = load_musicxml(path)
    tl = build_timeline(root)
    ps = parts(root)
    # gleiche Erkennung wie im Player: Name oder MIDI-Programm 72 (Klarinette)
    solo = ""
    for sp in root.iter("score-part"):
        name = (sp.findtext("part-name") or "") + " " + " ".join((e.text or "") for e in sp.iter("instrument-name"))
        prog = (sp.findtext("midi-instrument/midi-program") or "").strip()
        if CLARINET_RE.search(name.strip()) or prog == "72":
            solo = sp.get("id") or ""
            break
    has_transpose = False
    if solo:
        for p in root.findall("part"):
            if p.get("id") == solo:
                has_transpose = p.find("measure/attributes/transpose") is not None
    return {
        "title": tl.title,
        "composer": tl.composer,
        "measures": len({m.src for m in tl.measures}),
        "played": len(tl.measures),
        "duration": round(tl.duration),
        "tempos": [round(q) for _, q in tl.tempos[:8]],
        "parts": [{"id": i, "name": n} for i, n in ps],
        "solo": solo or (ps[0][0] if ps else ""),
        "soloTransposed": has_transpose,
    }


def list_packages(ziel: str) -> list[dict]:
    d = Path(ziel)
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.playalong"), key=lambda x: x.stat().st_mtime, reverse=True):
        item = {"file": p.name, "size": p.stat().st_size, "mtime": p.stat().st_mtime, "title": p.stem, "audio": False}
        try:
            with zipfile.ZipFile(p) as z:
                m = json.loads(z.read("manifest.json"))
                item["title"] = m.get("title") or p.stem
                item["composer"] = m.get("composer") or ""
                item["audio"] = bool(m.get("audio"))
        except (OSError, KeyError, ValueError, zipfile.BadZipFile):
            item["broken"] = True
        rep = d / "Prüfberichte" / f"{p.stem}.html"
        item["report"] = rep.name if rep.exists() else ""
        out.append(item)
    return out


def choose_folder(start: str) -> str:
    """Windows-/Linux-Ordnerdialog (tkinter) in eigenem Prozess öffnen."""
    code = (
        "import sys, tkinter as tk\n"
        "from tkinter import filedialog\n"
        "r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True)\n"
        "p = filedialog.askdirectory(title='Zielordner für Liedpakete wählen', initialdir=sys.argv[1] or None)\n"
        "sys.stdout.write(p or '')\n"
    )
    try:
        res = subprocess.run([sys.executable, "-c", code, start or ""], capture_output=True, text=True,
                             timeout=900, encoding="utf-8")
        return res.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def run_draft(job: Job, req: dict) -> None:
    from .package import build_draft_package

    try:
        audio = UPLOADED.get(req.get("aufnahme", ""))
        if not audio:
            raise ValueError("Bitte zuerst eine Aufnahme auswählen.")
        ziel = req.get("ziel") or ""
        if not Path(ziel).is_dir():
            raise ValueError(f"Zielordner nicht gefunden: {ziel or '(keiner)'}")
        t = time.time()
        info: dict = {}
        instrument = req.get("instrument") if req.get("instrument") in ("auto", "gezupft", "gehalten") else "auto"
        lage = req.get("lage") if req.get("lage") in ("auto", "hoch", "tief") else "auto"
        pkg, xml = build_draft_package(audio, ziel, title=(req.get("titel") or "").strip() or audio.stem,
                                       composer=(req.get("komponist") or "").strip(),
                                       beats_per_bar=3 if str(req.get("taktart")) == "3" else 4,
                                       instrument=instrument, lage=lage, progress=job.log.append, info=info)
        rep = Path(ziel) / "Prüfberichte" / f"{pkg.stem}.html"
        job.result = {"file": pkg.name, "path": str(pkg), "report": rep.name if rep.exists() else "",
                      "draft": str(xml), "seconds": round(time.time() - t), "erkennung": info}
        job.status = "done"
        _log(f"Rohentwurf: {pkg}")
    except Exception as e:  # noqa: BLE001
        job.error = str(e) or e.__class__.__name__
        job.status = "error"
        _log("Fehler beim Rohentwurf: " + traceback.format_exc())


def run_update(job: Job, srv) -> None:
    from . import update

    try:
        latest = update.apply(progress=job.log.append)
        job.result = {"sha": latest["sha"][:7], "date": latest["date"]}
        job.status = "done"
        _log(f"aktualisiert auf {latest['sha'][:7]}")
        time.sleep(1.5)  # Oberfläche holt sich noch den Status
        update.restart(srv.server_address[1])
        srv.shutdown()
    except Exception as e:  # noqa: BLE001
        job.error = str(e) or e.__class__.__name__
        job.status = "error"
        _log("Fehler beim Aktualisieren: " + traceback.format_exc())


def run_build(job: Job, req: dict) -> None:
    from .cli import NOTATION
    from .package import build_package

    try:
        score = UPLOADED.get(req.get("partitur", ""))
        if not score:
            raise ValueError("Bitte zuerst eine Partitur auswählen.")
        audio = UPLOADED.get(req.get("aufnahme", "")) if req.get("aufnahme") else None
        ziel = req.get("ziel") or ""
        if not Path(ziel).is_dir():
            raise ValueError(f"Zielordner nicht gefunden: {ziel or '(keiner)'}")
        t = time.time()
        target = build_package(
            score, audio, ziel,
            title=(req.get("titel") or "").strip() or None,
            composer=(req.get("komponist") or "").strip(),
            solo_part=req.get("stimme") or None,
            notation=NOTATION.get(req.get("notiert") or "auto", "auto"),
            sync=True, report=True, progress=job.log.append,
        )
        rep = Path(ziel) / "Prüfberichte" / f"{target.stem}.html"
        job.result = {"file": target.name, "path": str(target), "report": rep.name if rep.exists() else "",
                      "seconds": round(time.time() - t)}
        job.status = "done"
        _log(f"gebaut: {target}")
    except Exception as e:  # noqa: BLE001 – Fehler für die Oberfläche aufbereiten
        job.error = str(e) or e.__class__.__name__
        job.status = "error"
        _log("Fehler beim Bauen: " + traceback.format_exc())


# --------------------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = f"PlayalongWerkstatt/{__version__}"

    def log_message(self, fmt: str, *args) -> None:  # leise
        pass

    # Schutz: nur Aufrufe von dieser Oberfläche selbst annehmen
    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code: int = 200) -> None:
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _err(self, msg: str, code: int = 400) -> None:
        self._json({"error": msg}, code)

    def _body_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def do_GET(self) -> None:  # noqa: N802
        if not self._host_ok():
            return self._err("Nicht erlaubt", 403)
        path = urlparse(self.path).path
        cfg = self.server.cfg  # type: ignore[attr-defined]
        if path in ("/", "/index.html"):
            return self._send(200, (WEB / "werkstatt.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/icon.png":
            return self._send(200, (WEB / "icon.png").read_bytes(), "image/png")
        if path == "/api/ping":
            return self._json({"app": "playalong-werkstatt", "version": __version__, "boot": BOOT_ID})
        if path == "/api/config":
            z = cfg.get("ziel", "")
            return self._json({"ziel": z, "zielOk": bool(z) and Path(z).is_dir(), "version": __version__})
        if path == "/api/update":
            from . import update

            return self._json(update.check())
        if path == "/api/pakete":
            return self._json(list_packages(cfg.get("ziel", "")))
        if path.startswith("/api/job/"):
            job = JOBS.get(path.rsplit("/", 1)[-1])
            if not job:
                return self._err("Unbekannter Auftrag", 404)
            return self._json({"status": job.status, "log": job.log, "result": job.result, "error": job.error})
        if path.startswith("/bericht/"):
            name = Path(unquote(path[len("/bericht/"):])).name  # kein Pfad, nur Dateiname
            f = Path(cfg.get("ziel", "")) / "Prüfberichte" / name
            if not name.endswith(".html") or not f.is_file():
                return self._err("Prüfbericht nicht gefunden", 404)
            return self._send(200, f.read_bytes(), "text/html; charset=utf-8")
        return self._err("Nicht gefunden", 404)

    def do_POST(self) -> None:  # noqa: N802
        # eigener Header verhindert Aufrufe von fremden Webseiten (CSRF)
        if not self._host_ok() or self.headers.get("X-Werkstatt") != "1":
            return self._err("Nicht erlaubt", 403)
        path = urlparse(self.path).path
        srv = self.server
        cfg = srv.cfg  # type: ignore[attr-defined]
        try:
            if path == "/api/upload":
                n = int(self.headers.get("Content-Length") or 0)
                if n <= 0 or n > MAX_UPLOAD:
                    return self._err("Datei ist leer oder zu groß.")
                name = Path(unquote(self.headers.get("X-Filename") or "datei")).name or "datei"
                fid = uuid.uuid4().hex[:12]
                d = UPLOADS / fid
                d.mkdir(parents=True, exist_ok=True)
                f = d / name
                remaining = n
                with f.open("wb") as out:
                    while remaining > 0:
                        chunk = self.rfile.read(min(1 << 20, remaining))
                        if not chunk:
                            break
                        out.write(chunk)
                        remaining -= len(chunk)
                UPLOADED[fid] = f
                res = {"id": fid, "name": name, "size": n}
                if self.headers.get("X-Kind") == "partitur":
                    try:
                        res["info"] = score_info(f)
                    except Exception as e:  # noqa: BLE001
                        return self._err(f"Die Partitur kann nicht gelesen werden: {e}")
                return self._json(res)
            if path == "/api/ziel":
                z = (self._body_json().get("ziel") or "").strip().strip('"')
                if not Path(z).is_dir():
                    return self._err(f"Ordner nicht gefunden: {z}")
                cfg["ziel"] = z
                srv.save_cfg(cfg)  # type: ignore[attr-defined]
                return self._json({"ziel": z, "zielOk": True})
            if path == "/api/ziel/waehlen":
                p = choose_folder(cfg.get("ziel", ""))
                if p:
                    p = str(Path(p))
                    cfg["ziel"] = p
                    srv.save_cfg(cfg)  # type: ignore[attr-defined]
                return self._json({"ziel": cfg.get("ziel", ""), "zielOk": bool(cfg.get("ziel")) and Path(cfg["ziel"]).is_dir(), "changed": bool(p)})
            if path in ("/api/build", "/api/entwurf"):
                req = self._body_json()
                req["ziel"] = cfg.get("ziel", "")
                job = Job()
                JOBS[job.id] = job
                target = run_build if path == "/api/build" else run_draft
                threading.Thread(target=target, args=(job, req), daemon=True).start()
                return self._json({"job": job.id})
            if path == "/api/update":
                if any(j.status == "running" for j in JOBS.values()):
                    return self._err("Bitte warten, bis der laufende Auftrag fertig ist.")
                job = Job()
                JOBS[job.id] = job
                threading.Thread(target=run_update, args=(job, srv), daemon=True).start()
                return self._json({"job": job.id})
            if path == "/api/beenden":
                self._json({"ok": True})
                threading.Thread(target=srv.shutdown, daemon=True).start()
                return None
        except (ValueError, OSError) as e:
            return self._err(str(e))
        return self._err("Nicht gefunden", 404)


def _running_instance(port: int) -> bool:
    try:
        with urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=1) as r:
            return json.loads(r.read()).get("app") == "playalong-werkstatt"
    except (OSError, ValueError):
        return False


def _wait_until_free(port: int, seconds: float = 30) -> None:
    """Beim Neustart: warten, bis die alte Instanz beendet ist."""
    end = time.time() + seconds
    while time.time() < end and _running_instance(port):
        time.sleep(0.3)
    time.sleep(0.3)


def main(open_browser: bool = True, port: int = PORT, restart: bool = False) -> int:
    # Start ohne Konsolenfenster (pythonw): Ausgaben ins Leere bzw. ins Protokoll
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    from .cli import _load_config, _save_config

    url = f"http://127.0.0.1:{port}/"
    if restart:
        _wait_until_free(port)
    elif _running_instance(port):
        # läuft schon: nur den Browser öffnen
        if open_browser:
            webbrowser.open(url)
        return 0
    shutil.rmtree(UPLOADS, ignore_errors=True)  # alte Uploads aufräumen
    srv = None
    for _ in range(40):  # Port evtl. noch kurz belegt
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            time.sleep(0.5)
    if srv is None:
        _log(f"Port {port} ist belegt – Werkstatt nicht gestartet")
        return 1
    srv.cfg = _load_config()  # type: ignore[attr-defined]
    srv.save_cfg = _save_config  # type: ignore[attr-defined]
    _log(f"Werkstatt gestartet: {url}")
    print(f"Play-along Werkstatt läuft: {url}\nDieses Fenster offen lassen. Beenden: in der Werkstatt auf „Beenden“ klicken oder Strg+C.")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        shutil.rmtree(UPLOADS, ignore_errors=True)
        _log("Werkstatt beendet")
    return 0


def gui_entry() -> None:
    """Einstieg für die Verknüpfung (ohne Konsolenfenster)."""
    sys.exit(main())
