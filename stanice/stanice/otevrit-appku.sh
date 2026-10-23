#!/bin/sh
# Otevře appku stanice v prohlížeči přes celou obrazovku.
# Volitelný parametr: kolik sekund počkat (po startu, než naběhne server).
sleep "${1:-0}"
B=$(command -v chromium-browser || command -v chromium)
exec "$B" --app=http://localhost:8080 --start-fullscreen --noerrdialogs --disable-infobars
