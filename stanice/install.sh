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

echo "== 4/4 Po přihlášení se otevře appka přes celou obrazovku =="
mkdir -p "$HOME/.config/autostart" "$HOME/Desktop"
# po přihlášení: počkat, než naběhne server, a otevřít appku
# na ploše: zástupce, kdyby se okno zavřelo
for pair in "$HOME/.config/autostart/htz-stanice.desktop:8" "$HOME/Desktop/htz-stanice.desktop:0"; do
  f="${pair%:*}"; wait="${pair##*:}"
  cat > "$f" <<EOF
[Desktop Entry]
Type=Application
Name=HTZ stanice
Comment=Počítadlo zrn
Exec=/bin/sh $STANICE/otevrit-appku.sh $wait
Icon=$(dirname "$STANICE")/apple-touch-icon.png
Terminal=false
EOF
  chmod +x "$f"
done

sleep 3
if systemctl is-active --quiet htz-stanice; then
  echo
  echo "Hotovo. Stanice běží."
  echo "  Na této obrazovce:   http://localhost:$PORT"
  echo "  Z jiného počítače:   http://$(hostname).local:$PORT   nebo   http://$(hostname -I | awk '{print $1}'):$PORT"
  echo "  Měření se ukládají do: $DATA/mereni.csv"
  echo "Restartuj Raspberry (sudo reboot) a appka se otevře sama."
else
  echo
  echo "POZOR: server stanice neběží. Poslední zprávy:"
  sudo journalctl -u htz-stanice -n 30 --no-pager
fi
