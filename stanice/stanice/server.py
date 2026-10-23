#!/usr/bin/env python3
"""
HTZ station — the counting box's own small server.

Serves the same web app as GitHub Pages and adds what only the box can do:
take a photo with its camera, count it right here, and keep every saved
measurement in a CSV on the box. No outside server is involved, so nothing
stops working when someone else's server does.

    python3 server.py [--port 8080] [--data ~/htz-data] [--demo FOLDER]

--demo counts the JPEGs in FOLDER in turn instead of using a camera, for
trying the station out on a computer without one.
"""
import argparse
import base64
import csv
import io
import json
import os
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))   # htz_count sits beside this file, whatever the start-up folder
import htz_count  # noqa: E402
APP_DIR = HERE.parent          # index.html and the icons live one level up, as in the repo
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/apple-touch-icon.png": ("apple-touch-icon.png", "image/png"),
    "/icon-192.png": ("icon-192.png", "image/png"),
}
CSV_FIELDS = ["Pokus", "Vzorek", "Plodina", "Zrn", "Fotky (zrn)", "Hmotnost (g)", "HTZ (g)", "Čas"]


class Camera:
    """The box camera through Picamera2, kept running between photos so a
    shot costs a capture, not a camera start-up."""

    def __init__(self):
        from picamera2 import Picamera2  # only on the Raspberry
        self.cam = Picamera2()
        cfg = self.cam.create_still_configuration(main={"format": "RGB888", "size": self.cam.sensor_resolution})
        self.cam.configure(cfg)
        self.cam.start()
        time.sleep(1.5)  # let exposure and white balance settle once

    def capture_rgb(self):
        # Picamera2's "RGB888" is laid out B, G, R in memory
        return np.ascontiguousarray(self.cam.capture_array("main")[..., ::-1])


class DemoCamera:
    """Stands in for the camera: hands out the JPEGs of a folder one by one."""

    def __init__(self, folder):
        self.files = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
        if not self.files:
            sys.exit(f"--demo: ve složce {folder} nejsou žádné fotky")
        self.i = 0

    def capture_rgb(self):
        f = self.files[self.i % len(self.files)]
        self.i += 1
        bgr = cv2.imread(str(f))
        return np.ascontiguousarray(bgr[..., ::-1])


def to_working_size(rgb, side):
    h, w = rgb.shape[:2]
    s = min(1.0, side / max(w, h))
    if s >= 1:
        return rgb
    return cv2.resize(rgb, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)


def data_url(kind, buf):
    return f"data:{kind};base64," + base64.b64encode(buf).decode("ascii")


class Station:
    def __init__(self, camera, data_dir):
        self.camera = camera
        self.lock = threading.Lock()   # one photo at a time, however many screens are open
        self.data_dir = Path(data_dir).expanduser()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.csv_path = self.data_dir / "mereni.csv"

    def shoot(self, side):
        with self.lock:
            t0 = time.time()
            rgb = to_working_size(self.camera.capture_rgb(), side)
            t1 = time.time()
            res = htz_count.count(rgb)
            t2 = time.time()
        h, w = rgb.shape[:2]
        ok, jpg = cv2.imencode(".jpg", rgb[..., ::-1], [cv2.IMWRITE_JPEG_QUALITY, 88])
        out = {"w": w, "h": h, "photo": data_url("image/jpeg", jpg.tobytes()),
               "timing": {"capture": round(t1 - t0, 2), "count": round(t2 - t1, 2)}}
        if "fail" in res:
            out["fail"] = res["fail"]
            return out
        ok, png = cv2.imencode(".png", (res.pop("mask") * 255).astype(np.uint8))
        out.update(res)
        out["mask"] = data_url("image/png", png.tobytes())
        return out

    def save(self, rec):
        """Append one measurement to the CSV. Semicolons and a BOM, so Czech
        Excel opens it straight into columns with the diacritics intact."""
        new = not self.csv_path.exists()
        with open(self.csv_path, "a", newline="", encoding="utf-8-sig" if new else "utf-8") as fh:
            wr = csv.writer(fh, delimiter=";")
            if new:
                wr.writerow(CSV_FIELDS)
            dec = lambda v, n: f"{float(v):.{n}f}".replace(".", ",")
            wr.writerow([
                rec.get("trial", ""), rec.get("name", ""), rec.get("crop", ""), rec.get("count", ""),
                " / ".join(str(s) for s in rec.get("shots", [])),
                dec(rec.get("weight", 0), 2), dec(rec.get("htz", 0), 1),
                rec.get("when") or datetime.now().strftime("%d. %m. %Y %H:%M"),
            ])


def make_handler(station):
    class Handler(BaseHTTPRequestHandler):
        # Keep-alive with a Content-Length on every reply. Under the default
        # HTTP/1.0 the server closed the socket the moment a reply was out, and
        # a browser still finishing its request got the 700 kB photo cut off by
        # a connection reset.
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            sys.stderr.write("%s %s\n" % (datetime.now().strftime("%H:%M:%S"), fmt % args))

        def send(self, code, body, ctype, extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            self.wfile.flush()

        def do_HEAD(self):
            self.do_GET()

        def send_json(self, obj, code=200):
            self.send(code, json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/api/ping":
                return self.send_json({"station": True, "demo": isinstance(station.camera, DemoCamera)})
            if path == "/api/export.csv":
                body = station.csv_path.read_bytes() if station.csv_path.exists() else "﻿".encode() + ";".join(CSV_FIELDS).encode()
                return self.send(200, body, "text/csv; charset=utf-8",
                                 {"Content-Disposition": 'attachment; filename="mereni-htz.csv"'})
            if path in STATIC:
                name, ctype = STATIC[path]
                f = APP_DIR / name
                if f.exists():
                    return self.send(200, f.read_bytes(), ctype)
            self.send(404, b"Nenalezeno", "text/plain; charset=utf-8")

        def do_POST(self):
            path = self.path.split("?")[0]
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return self.send_json({"error": "bad json"}, 400)
            try:
                if path == "/api/shoot":
                    side = int(body.get("side") or 2400)
                    return self.send_json(station.shoot(max(800, min(4000, side))))
                if path == "/api/save":
                    station.save(body)
                    return self.send_json({"ok": True})
            except Exception as e:  # keep the station up; the page shows the message
                self.log_message("chyba: %r", e)
                return self.send_json({"error": str(e)}, 500)
            self.send(404, b"Nenalezeno", "text/plain; charset=utf-8")

    return Handler


def main():
    ap = argparse.ArgumentParser(description="HTZ stanice")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--data", default="~/htz-data")
    ap.add_argument("--demo", help="složka s fotkami místo kamery")
    a = ap.parse_args()
    camera = DemoCamera(a.demo) if a.demo else Camera()
    station = Station(camera, a.data)
    srv = ThreadingHTTPServer(("0.0.0.0", a.port), make_handler(station))
    print(f"HTZ stanice běží na http://localhost:{a.port}  (data: {station.csv_path})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
