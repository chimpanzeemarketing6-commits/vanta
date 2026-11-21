#!/bin/bash
# Installs Vanta Deck for your user (no password needed, nothing outside your home folder).
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/Applications/VantaDeck"
mkdir -p "$DEST" "$HOME/.local/share/applications" "$HOME/.local/share/icons/hicolor/512x512/apps"
cp "$DIR/VantaDeck" "$DEST/VantaDeck"
chmod +x "$DEST/VantaDeck"
cp "$DIR/vanta-deck.png" "$HOME/.local/share/icons/hicolor/512x512/apps/vanta-deck.png"
cat > "$HOME/.local/share/applications/vanta-deck.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=Vanta Deck
Comment=Your game hub for Steam Deck
Exec="$DEST/VantaDeck"
Icon=vanta-deck
Categories=Game;Utility;
Terminal=false
DESK
echo "Vanta Deck is installed: find it in the app menu under Games."
if command -v steamos-add-to-steam >/dev/null 2>&1; then
  read -r -p "Add it to Steam so it opens in Game Mode too? [Y/n] " ans
  if [ "${ans,,}" != "n" ]; then
    steamos-add-to-steam "$DEST/VantaDeck" && echo "Added: in Game Mode it's under Library > Non-Steam."
  fi
fi
