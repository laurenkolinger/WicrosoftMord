#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# wmord-new-project.sh — scaffold a self-contained WicrosoftMord project folder
#
# Builds a NEW working folder as a SIDE folder next to wherever this repo is
# cloned (NOT inside the repo), containing everything needed to resume the
# project entirely: the document, its figures/tables media, references, CSL
# styles, an export template slot, the .redline state (global rules + comments
# + config), an exports/ folder, and a double-click open.command bound to the
# project's OWN port (one port per project).
#
# Usage:
#   bin/wmord-new-project.sh <name> [source.docx] [references.bib] [parent-dir]
#
# Examples:
#   bin/wmord-new-project.sh bleaching ~/Desktop/paper_main.docx ~/refs/references.bib
#   bin/wmord-new-project.sh grant-aim2
# ---------------------------------------------------------------------------
set -euo pipefail

WM_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="${1:-}"
SRC_DOCX="${2:-}"
SRC_BIB="${3:-}"
PARENT="${4:-$(dirname "$WM_HOME")}"      # default: sibling of the repo clone
[ -n "$NAME" ] || { echo "usage: $0 <name> [source.docx] [references.bib] [parent-dir]"; exit 1; }

PROJ="$PARENT/$NAME"
[ -e "$PROJ" ] && { echo "✗ $PROJ already exists — pick another name or remove it."; exit 1; }
mkdir -p "$PROJ/.redline/comments" "$PROJ/media" "$PROJ/csl" "$PROJ/templates" "$PROJ/exports"

# seed the project with the repo's bundled CSL styles and Word templates (you can add more later)
[ -d "$WM_HOME/styles" ] && cp -n "$WM_HOME/styles/"*.csl "$PROJ/csl/" 2>/dev/null || true
[ -d "$WM_HOME/templates" ] && cp -n "$WM_HOME/templates/"*.docx "$PROJ/templates/" 2>/dev/null || true

# deterministic per-project port in 8800–8899 from the name (stable across restarts)
PORT="$(python3 - "$NAME" <<'PY'
import sys
print(8800 + (sum(ord(c) for c in sys.argv[1]) % 100))
PY
)"

cat > "$PROJ/.redline/config.json" <<JSON
{
  "title": "$NAME",
  "docsDir": ".",
  "port": $PORT,
  "exportFont": "tnr",
  "cslStyle": "",
  "exportTemplate": "",
  "bibPath": "",
  "litDir": "",
  "styleDir": "/Users/laurenkay/OLINGER_PUBS_WORK"
}
JSON

cat > "$PROJ/.redline/instructions.md" <<'MD'
No em dashes; use commas, colons, or parentheses instead.
American spelling. Active voice. Measured, academic tone; no hype words.
Cite only from the project references.bib, and verify claims against the source PDFs in litDir.
Match the author's voice using the writing samples in styleDir for STYLE and phrasing ONLY, never to import content.
On export, keep every figure and table at its original place with its current caption so they survive into the .docx.
MD

# If a source .docx is given: copy it in, convert to Markdown, extract figures into
# media/, and carry the .bib alongside. (Tables become real Markdown tables; figures
# become inline images so they survive export.)
if [ -n "$SRC_DOCX" ] && [ -f "$SRC_DOCX" ]; then
  cp "$SRC_DOCX" "$PROJ/"
  base="$(basename "${SRC_DOCX%.*}")"
  if command -v pandoc >/dev/null 2>&1; then
    # Figures as ![full caption](media/...png) inline at the right spot (captions kept),
    # and tables as PIPE tables (disable grid/multiline/simple) so the review UI renders them.
    if ( cd "$PROJ" && pandoc "$(basename "$SRC_DOCX")" --extract-media=media \
           -t 'markdown-grid_tables-multiline_tables-simple_tables' --wrap=none -o "$base.md" ); then
      # strip pandoc's {width=...} image attributes so the Markdown stays clean
      python3 - "$PROJ/$base.md" <<'PY'
import re,sys
p=sys.argv[1]; s=open(p,encoding="utf-8").read()
s=re.sub(r'(\!\[[^\]]*\]\([^)]*\))\{[^}]*\}', r'\1', s)   # drop {width=...}
open(p,"w",encoding="utf-8").write(s)
PY
      figs=$(grep -cE '^\!\[' "$PROJ/$base.md" 2>/dev/null || echo 0)
      echo "  • converted $(basename "$SRC_DOCX") → $base.md ($figs figures with captions in media/, tables inline)"
    else
      echo "  • pandoc conversion failed; copy the .md in by hand"
    fi
  else
    echo "  • pandoc not found; install it, then: pandoc '$(basename "$SRC_DOCX")' --extract-media=media -t markdown --wrap=none -o '$base.md'"
  fi
fi
[ -n "$SRC_BIB" ] && [ -f "$SRC_BIB" ] && cp "$SRC_BIB" "$PROJ/references.bib" && echo "  • copied references.bib"

# Double-click launcher, pinned to THIS project and THIS port.
cat > "$PROJ/open.command" <<SH
#!/usr/bin/env bash
# Double-click to open this WicrosoftMord project in your browser.
set -e
WM_HOME="$WM_HOME"
PROJ="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
PORT=$PORT
if ! curl -s "http://127.0.0.1:\$PORT/" >/dev/null 2>&1; then
  ( python3 "\$WM_HOME/server/redline.py" --project "\$PROJ" --port \$PORT >"\$PROJ/.redline/server.log" 2>&1 & )
  sleep 1.5
fi
open "http://localhost:\$PORT"
SH
chmod +x "$PROJ/open.command"

cat > "$PROJ/PROJECT.md" <<MD
# $NAME — WicrosoftMord project

Everything needed to resume this review lives in this folder.

- **open.command** — double-click to launch. Starts the server on port **$PORT**
  (this project's own port) and opens the browser. One port per project.
- **<your>.md** — the document (Markdown is the source of truth; export makes .docx).
- **media/** — figures and tables extracted from the source document.
- **references.bib** — bibliography the citations resolve against.
- **csl/** — citation styles; drop more .csl files here and they appear in Setup.
- **templates/** — Word reference templates for export (point Setup at one).
- **exports/** — every .docx export, stamped with DATE_TIME, opened in Word automatically.
- **.redline/** — the review state:
  - **instructions.md** — global house-style rules Claude obeys everywhere.
  - **comments/** — one JSON per comment (the conversation with Claude).
  - **config.json** — title, port, export font/template, CSL, bib path.

## Resume later
Double-click **open.command**. To have Claude work the comments, in the VS Code
Claude panel run: \`/loop 45s /redline\`.
MD

echo "✓ Created $PROJ"
echo "  port: $PORT  ·  launch: double-click $PROJ/open.command"
echo "  wire Claude: open this folder in VS Code and run  /loop 45s /redline"
