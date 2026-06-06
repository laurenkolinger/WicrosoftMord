#!/bin/bash
# No-terminal launcher invoked by WicrosoftMord.app (double-click).
# Arg 1 = the project folder to review. Does everything: scaffold, install the
# skill, start the server, open the browser. The user never types a command.
set -e

HOME_DIR="$HOME/WicrosoftMord"
PROJECT="${1:-$PWD}"
PORT="${REDLINE_PORT:-8787}"

# 1. scaffold the project (idempotent)
mkdir -p "$PROJECT/.redline/comments" "$PROJECT/.redline/exports" "$PROJECT/docs"
[ -f "$PROJECT/.redline/config.json" ] || \
  printf '{ "title": "%s", "docsDir": "docs" }\n' "$(basename "$PROJECT")" > "$PROJECT/.redline/config.json"
if [ -z "$(ls -A "$PROJECT/docs" 2>/dev/null)" ]; then
  cp "$HOME_DIR/templates/welcome.md" "$PROJECT/docs/welcome.md"
  [ -f "$PROJECT/references.bib" ] || cp "$HOME_DIR/templates/references.bib" "$PROJECT/references.bib"
fi

# 2. install the /redline skill + contract note into the project (wires Claude)
mkdir -p "$PROJECT/.claude/skills/redline"
cp "$HOME_DIR/skill/redline/SKILL.md" "$PROJECT/.claude/skills/redline/SKILL.md"
cp "$HOME_DIR/templates/CLAUDE.redline.md" "$PROJECT/.redline/CLAUDE.redline.md"

# 3. (re)start the server for this project, detached
lsof -ti tcp:"$PORT" | xargs kill -9 2>/dev/null || true
sleep 0.2
REDLINE_DATA="$PROJECT/.redline" REDLINE_PORT="$PORT" REDLINE_HOST=127.0.0.1 \
  nohup python3 "$HOME_DIR/server/redline.py" > "$PROJECT/.redline/server.log" 2>&1 &
disown 2>/dev/null || true

# 4. wait until it answers, then open the browser
for _ in $(seq 1 40); do
  curl -s -o /dev/null "http://localhost:$PORT/api/state" && break
  sleep 0.2
done
open "http://localhost:$PORT"
echo "ok port=$PORT project=$PROJECT"
