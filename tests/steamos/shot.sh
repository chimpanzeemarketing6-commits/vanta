#!/bin/bash
# shot.sh OUT.png [ENV=val ...]: run Vanta Deck on a fake SteamOS home and screenshot it
OUT=$1; shift
export DISPLAY=:97
pkill -f "Xvfb :97" 2>/dev/null; sleep 0.3
(Xvfb :97 -screen 0 1280x800x24 >/dev/null 2>&1 &); sleep 1
rm -rf /tmp/deckhome/.local/share/vanta-deck /tmp/deckhome/.cache/vanta-deck
if [ -n "$SEED" ]; then mkdir -p /tmp/deckhome/.local/share/vanta-deck; cp /tmp/deck_seed.json /tmp/deckhome/.local/share/vanta-deck/config.json; fi
env HOME=/tmp/deckhome VANTA_SYS_ROOT=/tmp/fakesys VANTA_GEOMETRY=1280x800+0+0 VANTA_JS=/nonexistent "$@" \
  timeout ${T:-9} ${BIN:-/home/claude/deckenv/bin/python /home/claude/deck/vanta_deck.py} > /tmp/deck.log 2>&1 &
sleep ${W:-7}
import -window root "$OUT"
wait
