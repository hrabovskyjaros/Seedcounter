# Emergency repair for a box whose system files got damaged (weak power supply):
# puts back the camera library (picamera2) and the latest station server, both
# downloaded over plain Python because git itself crashed. Run on the box:
#   python3 Seedcounter/stanice/oprava.py      (or piped from GitHub, see NAVOD)
import io
import shutil
import site
import tarfile
import urllib.request
from pathlib import Path

VER = "0.3.39"   # the Debian package on the box: python3-picamera2 0.3.39-1
RAW = "https://raw.githubusercontent.com/hrabovskyjaros/Seedcounter/main/stanice/"
home = Path.home()

print("1/2 Kamerová knihovna picamera2", VER, "...", flush=True)
data = urllib.request.urlopen(
    f"https://github.com/raspberrypi/picamera2/archive/refs/tags/v{VER}.tar.gz", timeout=120).read()
dest = Path(site.getusersitepackages())   # searched before the damaged system copy
dest.mkdir(parents=True, exist_ok=True)
shutil.rmtree(dest / "picamera2", ignore_errors=True)
with tarfile.open(fileobj=io.BytesIO(data)) as tar:
    prefix = f"picamera2-{VER}/picamera2/"
    for m in tar.getmembers():
        if m.name.startswith(prefix) and m.isfile():
            out = dest / "picamera2" / m.name[len(prefix):]
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(tar.extractfile(m).read())
print("   do", dest / "picamera2", flush=True)

print("2/2 Server stanice ...", flush=True)
for name in ("server.py", "stanice.html"):
    body = urllib.request.urlopen(RAW + name, timeout=60).read()
    (home / "Seedcounter" / "stanice" / name).write_bytes(body)
print("HOTOVO — teď: sudo systemctl restart htz-stanice", flush=True)
