#!/bin/bash
# Stáhne nejnovější verzi appky a stanice z GitHubu a restartuje server.
#   bash ~/Seedcounter/stanice/aktualizovat.sh
set -e
cd "$(dirname "$0")/.."
git pull
sudo systemctl restart htz-stanice
echo "Aktualizováno. Obnov stránku v prohlížeči (F5)."
