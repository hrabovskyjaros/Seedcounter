#!/bin/bash
# Stáhne nejnovější verzi stanice z GitHubu a znovu ji nainstaluje.
#   bash ~/Seedcounter/stanice/aktualizovat.sh
set -e
cd "$(dirname "$0")/.."
git pull
bash stanice/install.sh
