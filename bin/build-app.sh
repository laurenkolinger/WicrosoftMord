#!/bin/bash
# Builds WicrosoftMord.app (a double-clickable launcher) from the AppleScript
# source, and drops a shortcut on the Desktop. Run once after cloning.
set -e
HOME_DIR="$HOME/WicrosoftMord"
chmod +x "$HOME_DIR/bin/wmord-launch.sh" "$HOME_DIR/bin/redline" 2>/dev/null || true

rm -rf "$HOME_DIR/WicrosoftMord.app"
osacompile -o "$HOME_DIR/WicrosoftMord.app" "$HOME_DIR/bin/wmord-app.applescript"

# Desktop shortcut (alias) so it's one double-click away.
osascript -e 'tell application "Finder" to make alias file to (POSIX file "'"$HOME_DIR"'/WicrosoftMord.app") at (path to desktop folder)' >/dev/null 2>&1 || true

echo "✓ Built $HOME_DIR/WicrosoftMord.app  (+ Desktop shortcut)"
