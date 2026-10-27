#!/bin/bash
# Instalace HTZ stanice na Raspberry Pi (Raspberry Pi OS Bookworm s plochou).
# Spustit jednou:   bash ~/Seedcounter/stanice/install.sh
set -e

STANICE="$(cd "$(dirname "$0")" && pwd)"
DATA="$HOME/htz-data"
PORT=8080

echo "== 1/5 Instaluji knihovny (kamera, OpenCV, sdílení složky) =="
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python3-picamera2 python3-opencv python3-numpy v4l-utils samba

echo "== 2/5 Složka na měření: $DATA =="
mkdir -p "$DATA"

echo "== 3/5 Složka s měřeními jako síťový disk pro Windows (\\\\IP\\htz) =="
# Read-only, so Excel on the PC can never lock or overwrite the box's CSV.
# Windows 11 refuses guest access, hence a Samba login for this user.
if ! grep -q "^\[htz\]" /etc/samba/smb.conf; then
  sudo tee -a /etc/samba/smb.conf >/dev/null <<EOF

[htz]
   comment = HTZ mereni
   path = $DATA
   read only = yes
   valid users = $(whoami)
EOF
fi
if ! sudo pdbedit -L 2>/dev/null | grep -q "^$(whoami):"; then
  echo "Zadej heslo pro síťový disk (stačí stejné jako do Raspberry), dvakrát:"
  sudo smbpasswd -a "$(whoami)"
fi
sudo systemctl enable smbd
sudo systemctl restart smbd

echo "== 4/5 Server stanice se spustí sám po každém zapnutí =="
sudo tee /etc/systemd/system/htz-stanice.service >/dev/null <<EOF
[Unit]
Description=HTZ stanice (pocitani zrn)
After=network.target

[Service]
User=$(whoami)
WorkingDirectory=$STANICE
ExecStart=/usr/bin/python3 $STANICE/server.py --port $PORT --data $DATA --otocit
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable htz-stanice
sudo systemctl restart htz-stanice

echo "== 5/5 Zástupce na ploše (appka se ovládá z počítače s Windows) =="
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
  echo "  Ve Windows jako síťový disk: \\\\$(hostname -I | awk '{print $1}')\\htz   (jméno $(whoami))"
else
  echo
  echo "POZOR: server stanice neběží. Poslední zprávy:"
  sudo journalctl -u htz-stanice -n 30 --no-pager
fi
