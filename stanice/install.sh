#!/bin/bash
# Instalace HTZ stanice na Raspberry Pi (Raspberry Pi OS Bookworm s plochou).
# Spustit jednou:   bash ~/Seedcounter/stanice/install.sh
set -e

STANICE="$(cd "$(dirname "$0")" && pwd)"
DATA="$HOME/htz-data"
PORT=8080

echo "== 1/4 Instaluji knihovny (kamera, OpenCV) =="
sudo apt-get update
sudo apt-get install -y python3-picamera2 python3-opencv python3-numpy

echo "== 2/4 Složka na měření: $DATA =="
mkdir -p "$DATA"

echo "== 3/4 Server stanice se spustí sám po každém zapnutí =="
sudo tee /etc/systemd/system/htz-stanice.service >/dev/null <<EOF
[Unit]
Description=HTZ stanice (pocitani zrn)
After=network.target

[Service]
User=$(whoami)
WorkingDirectory=$STANICE
ExecStart=/usr/bin/python3 $STANICE/server.py --port $PORT --data $DATA
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable htz-stanice
sudo systemctl restart htz-stanice

echo "== 4/4 Zástupce na ploše (appka se ovládá z počítače s Windows) =="
# The Pi only takes the photos; the screen is on the Windows computer. The app
# no longer opens here at login — Chromium on a Pi 3B+ was the slow part.
rm -f "$HOME/.config/autostart/htz-stanice.desktop"
mkdir -p "$HOME/Desktop"
cat > "$HOME/Desktop/htz-stanice.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=HTZ stanice
Comment=Počítadlo zrn
Exec=/bin/sh $STANICE/otevrit-appku.sh 0
Icon=$(dirname "$STANICE")/apple-touch-icon.png
Terminal=false
EOF
chmod +x "$HOME/Desktop/htz-stanice.desktop"

sleep 3
if systemctl is-active --quiet htz-stanice; then
  echo
  echo "Hotovo. Stanice běží."
  echo "  Na počítači s Windows otevři v Chrome nebo Edge:"
  echo "      http://$(hostname).local:$PORT   nebo   http://$(hostname -I | awk '{print $1}'):$PORT"
  echo "  Měření se ukládají i sem: $DATA/mereni.csv"
else
  echo
  echo "POZOR: server stanice neběží. Poslední zprávy:"
  sudo journalctl -u htz-stanice -n 30 --no-pager
fi
