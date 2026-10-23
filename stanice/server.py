#!/usr/bin/env python3
"""
HTZ station — the counting box's own small server.

The box only looks: it streams a live view of the tray from its camera and,
on request, takes a full-resolution photo. Counting happens in the browser of
whatever computer opens the station page, so a Raspberry Pi 3B+ is plenty and
the screen in front of the operator is a proper PC. Saved measurements also go
into a CSV on the box. No outside server is involved.

    python3 server.py [--port 8080] [--data ~/htz-data] [--demo FOLDER]

--demo serves the JPEGs in FOLDER in turn instead of a camera, for trying the
station out on a computer without one.
"""
import argparse
import csv
import json
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2

HERE = Path(__file__).resolve().parent
APP_DIR = HERE.parent          # the icons live one level up, as in the repo
STATIC = {
    # the station has its own page; the iPad app (index.html) is not served here
    "/": (HERE / "stanice.html", "text/html; charset=utf-8"),
    "/stanice.html": (HERE / "stanice.html", "text/html; charset=utf-8"),
    "/apple-touch-icon.png": (APP_DIR / "apple-touch-icon.png", "image/png"),
    "/icon-192.png": (APP_DIR / "icon-192.png", "image/png"),
}
PREVIEW_W = 1280      # live view width
PREVIEW_FPS = 8
CSV_FIELDS = ["Pokus", "Vzorek", "Plodina", "Zrn", "Fotky (zrn)", "Hmotnost (g)", "HTZ (g)", "Čas"]


class Camera:
    """The box camera through Picamera2. Runs in a light preview mode for the
    live view and switches to a full still for each photo."""

    def __init__(self, rotate=False):
        from picamera2 import Picamera2  # only on the Raspberry
        from libcamera import Transform
        self.cam = Picamera2()
        # a camera mounted the other way round is turned in the camera itself,
        # so the live view and the photo come out the same way up
        self.transform = Transform(hflip=1, vflip=1) if rotate else Transform()
        self.sensor = self.cam.sensor_resolution
        sw, sh = self.sensor
        size = (PREVIEW_W, round(PREVIEW_W * sh / sw) // 2 * 2)
        # "RGB888" in Picamera2 is B, G, R in memory — what OpenCV calls BGR
        self.preview = self.cam.create_preview_configuration(main={"format": "RGB888", "size": size},
                                                            transform=self.transform)
        self.cam.configure(self.preview)
        self.cam.start()
        self.stills = {}
        print(f"kamera: snímač {sw}x{sh}, náhled {size[0]}x{size[1]}", flush=True)
        time.sleep(1.5)  # let exposure and white balance settle once

    def preview_bgr(self):
        return self.cam.capture_array("main")

    def still_bgr(self, side):
        sw, sh = self.sensor
        s = min(1.0, side / max(sw, sh))
        size = (int(sw * s) // 2 * 2, int(sh * s) // 2 * 2)
        if size not in self.stills:
            self.stills[size] = self.cam.create_still_configuration(main={"format": "RGB888", "size": size},
                                                                         transform=self.transform)
        return self.cam.switch_mode_and_capture_array(self.stills[size], "main")


class DemoCamera:
    """Stands in for the camera: shows one JPEG of a folder after another."""

    def __init__(self, folder, rotate=False):
        self.rotate = rotate
        self.files = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
        if not self.files:
            sys.exit(f"--demo: ve složce {folder} nejsou žádné fotky")
        self.i = 0
        self._load()

    def _load(self):
        self.current = cv2.imread(str(self.files[self.i % len(self.files)]))
        if self.rotate:
            self.current = cv2.rotate(self.current, cv2.ROTATE_180)

    def preview_bgr(self):
        h, w = self.current.shape[:2]
        return cv2.resize(self.current, (PREVIEW_W, round(PREVIEW_W * h / w)), interpolation=cv2.INTER_AREA)

    def still_bgr(self, side):
        img = self.current
        h, w = img.shape[:2]
        s = min(1.0, side / max(w, h))
        if s < 1:
            img = cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)
        self.i += 1          # the next "sample" is the next file
        self._load()
        return img


class Station:
    def __init__(self, camera, data_dir):
        self.camera = camera
        self.cam_lock = threading.Lock()     # preview frames and stills take turns
        self.frame_cv = threading.Condition()
        self.frame = None
        self.seq = 0
        self.viewers = 0
        self.data_dir = Path(data_dir).expanduser()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.csv_path = self.data_dir / "mereni.csv"
        self.crop_path = self.data_dir / "vyrez.json"
        self.crop = self._load_crop()
        threading.Thread(target=self._preview_loop, daemon=True).start()

    # ── crop: the part of the frame that is tray floor, set once on the page.
    # Kept as fractions of the frame, so it fits the live view and the photo alike.
    def _load_crop(self):
        try:
            c = json.loads(self.crop_path.read_text())
            return [float(c[k]) for k in ("x0", "y0", "x1", "y1")]
        except Exception:
            return None

    def set_crop(self, c):
        if not c:
            self.crop = None
            self.crop_path.unlink(missing_ok=True)
            return
        x0, y0, x1, y1 = (min(1.0, max(0.0, float(c[k]))) for k in ("x0", "y0", "x1", "y1"))
        x0, x1 = sorted((x0, x1)); y0, y1 = sorted((y0, y1))
        if x1 - x0 < 0.1 or y1 - y0 < 0.1:
            raise ValueError("výřez je moc malý")
        self.crop = [x0, y0, x1, y1]
        self.crop_path.write_text(json.dumps(dict(zip(("x0", "y0", "x1", "y1"), self.crop))))

    def cropped(self, img):
        if not self.crop:
            return img
        h, w = img.shape[:2]
        x0, y0, x1, y1 = self.crop
        return img[round(y0 * h):round(y1 * h), round(x0 * w):round(x1 * w)]

    def full_frame(self):
        """One uncropped live frame, for drawing the crop on."""
        with self.cam_lock:
            bgr = self.camera.preview_bgr()
        return cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()

    def _preview_loop(self):
        """Encodes live-view frames, but only while someone is watching —
        on a Pi 3B+ the JPEG encoding is most of the work."""
        while True:
            with self.frame_cv:
                while self.viewers == 0:
                    self.frame_cv.wait()
            t = time.time()
            try:
                with self.cam_lock:
                    bgr = self.camera.preview_bgr()
                ok, jpg = cv2.imencode(".jpg", self.cropped(bgr), [cv2.IMWRITE_JPEG_QUALITY, 75])
                with self.frame_cv:
                    self.frame = jpg.tobytes()
                    self.seq += 1
                    self.frame_cv.notify_all()
            except Exception as e:
                print("náhled: chyba", repr(e), flush=True)
                time.sleep(1)
            time.sleep(max(0.0, 1 / PREVIEW_FPS - (time.time() - t)))

    def next_frame(self, last_seq):
        with self.frame_cv:
            self.frame_cv.wait_for(lambda: self.seq != last_seq and self.frame is not None, timeout=5)
            return self.seq, self.frame

    def still(self, side):
        t0 = time.time()
        # shoot bigger by the share the crop cuts away, so the cut-out still
        # has about the working size
        if self.crop:
            side = side / max(self.crop[2] - self.crop[0], self.crop[3] - self.crop[1])
        with self.cam_lock:
            bgr = self.cropped(self.camera.still_bgr(round(side)))
        ok, jpg = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 92])
        body = jpg.tobytes()
        # the last photo stays on the box, to be fetched when a count needs looking into
        (self.data_dir / "posledni.jpg").write_bytes(body)
        print(f"foto {bgr.shape[1]}x{bgr.shape[0]} za {time.time() - t0:.1f} s", flush=True)
        return body

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
        # a browser still finishing its request got a large photo cut off by a
        # connection reset.
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            if "/api/stream" not in (args[0] if args else ""):
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

        def stream(self):
            """Live view as MJPEG: one JPEG after another on an open connection."""
            self.close_connection = True
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            with station.frame_cv:
                station.viewers += 1
                station.frame_cv.notify_all()
            try:
                seq = -1
                while True:
                    seq, jpg = station.next_frame(seq)
                    if jpg is None:
                        continue
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                     + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass
            finally:
                with station.frame_cv:
                    station.viewers -= 1

        def do_GET(self):
            path, _, query = self.path.partition("?")
            if path == "/api/ping":
                return self.send_json({"station": True, "demo": isinstance(station.camera, DemoCamera)})
            if path == "/api/stream":
                return self.stream()
            if path == "/api/frame":
                return self.send(200, station.full_frame(), "image/jpeg")
            if path == "/api/crop":
                c = station.crop
                return self.send_json(dict(zip(("x0", "y0", "x1", "y1"), c)) if c else None)
            if path == "/api/still":
                try:
                    q = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
                    side = max(800, min(4000, int(q.get("side", 2400))))
                    return self.send(200, station.still(side), "image/jpeg")
                except Exception as e:  # keep the station up; the page shows the message
                    self.log_message("chyba: %r", e)
                    return self.send(500, f"Kamera nevyfotila: {e}".encode("utf-8"), "text/plain; charset=utf-8")
            if path == "/api/export.csv":
                body = station.csv_path.read_bytes() if station.csv_path.exists() else "﻿".encode() + ";".join(CSV_FIELDS).encode()
                return self.send(200, body, "text/csv; charset=utf-8",
                                 {"Content-Disposition": 'attachment; filename="mereni-htz.csv"'})
            if path == "/api/posledni.jpg":
                f = station.data_dir / "posledni.jpg"
                if f.exists():
                    return self.send(200, f.read_bytes(), "image/jpeg",
                                     {"Content-Disposition": 'attachment; filename="posledni-fotka.jpg"'})
                return self.send(404, "Zatím žádná fotka".encode("utf-8"), "text/plain; charset=utf-8")
            if path in STATIC:
                f, ctype = STATIC[path]
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
            if path == "/api/crop":
                try:
                    station.set_crop(body)
                    return self.send_json({"ok": True})
                except Exception as e:
                    return self.send_json({"error": str(e)}, 400)
            if path == "/api/save":
                try:
                    station.save(body)
                    return self.send_json({"ok": True})
                except Exception as e:
                    self.log_message("chyba: %r", e)
                    return self.send_json({"error": str(e)}, 500)
            self.send(404, b"Nenalezeno", "text/plain; charset=utf-8")

    return Handler


def main():
    ap = argparse.ArgumentParser(description="HTZ stanice")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--data", default="~/htz-data")
    ap.add_argument("--demo", help="složka s fotkami místo kamery")
    ap.add_argument("--otocit", action="store_true", help="otočit obraz o 180°")
    a = ap.parse_args()
    camera = DemoCamera(a.demo, a.otocit) if a.demo else Camera(a.otocit)
    station = Station(camera, a.data)
    srv = ThreadingHTTPServer(("0.0.0.0", a.port), make_handler(station))
    srv.daemon_threads = True
    print(f"HTZ stanice běží na http://localhost:{a.port}  (data: {station.csv_path})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
