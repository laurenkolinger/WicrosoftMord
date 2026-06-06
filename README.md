# WicrosoftMord

A portable, containerized **word-processor-style review surface** for writing alongside Claude Code.
*(The command-line tool and `/redline` skill keep their short names; the app is WicrosoftMord.)*

You see Claude's drafts as formatted text — with **visible images** and **linked citations** —
**highlight** passages and leave **comments**. Those comments queue to Claude on a **rolling loop**;
Claude edits the document, you see the **red/green diff** and a reply appear **live**, no refresh.
When you're done, **export to `.docx`** (the format academic fields expect) with one click.

It is project-agnostic: build it once, drop it into any repo where you write with Claude.

```
 you ──highlight + comment──▶  .redline/comments/*.json  ──▶  Claude (in VS Code) edits docs,
   ▲                                                            writes a reply, marks resolved
   └────────────  live diff + reply appears in the browser  ◀──┘
```

The web app **never talks to Claude directly**. It only reads/writes files in a `.redline/` folder
inside your project. Claude reads the same files. The filesystem is the message bus — which is exactly
why it works across any project and any Claude Code session.

---

## No-terminal start (double-click)

After a one-time build (`bash ~/WicrosoftMord/bin/build-app.sh`, done for you), there's a
**WicrosoftMord** app on your Desktop. From then on, for **any** project, with no terminal:

1. **Double-click `WicrosoftMord`** on the Desktop.
2. **Pick the project folder** in the dialog. The app scaffolds it, installs the `/redline`
   skill, starts the server, and opens your browser — automatically.
3. A dialog says the **loop command is on your clipboard**. Click into the Claude Code chat in
   VS Code, **paste (⌘V), press Enter.** Done — comments and direct edits now flow to Claude.

Inside the app, the **⌁ Wire to Claude** button re-copies that command anytime, and **✏️ Edit**
lets you type directly into the document.

---

## Setup screen (folder + your directions)

WicrosoftMord opens a **⚙ Setup** screen on first launch (reopen anytime via ⚙ or the 📁 folder chip):

- **Working folder** — browse and pick the folder WicrosoftMord reads/writes (no terminal). Its absolute
  path is shown with a **Copy** button, so you can paste it to Claude and point the loop at the same place.
  If you don't pick one, it defaults to a stable `~/WicrosoftMord/workspace` folder.
- **Project title** — what shows in the header.
- **Base directions for Claude** — your standing house-style rules (e.g. *"No em dashes; use commas or
  parentheses. Active voice. British spelling. Cite only from references.bib."*). These are saved to
  `.redline/instructions.md`, which Claude reads **first on every pass** and obeys in every edit and draft —
  even when no comment mentions them.

---

## Quick start (terminal, optional)

### 1. Get the tool

```bash
git clone https://github.com/<you>/WicrosoftMord.git ~/WicrosoftMord
export PATH="$HOME/WicrosoftMord/bin:$PATH"     # add to ~/.zshrc to make it permanent
```

(No clone needed beyond this — the tool is self-contained.)

### 2. In the project where you write with Claude

```bash
cd /path/to/your/writing-project
redline init      # scaffolds .redline/, docs/, and installs the /redline skill into this repo
redline up        # builds + starts the container (includes pandoc for .docx)
```

Open **http://localhost:8787**. You'll see a sample `docs/welcome.md`. Drafts Claude writes into
`docs/*.md` appear here automatically.

### 3. Wire it to Claude Code in VS Code

This is the key step — it connects the review surface to the editor.

1. Open the **same project folder** in VS Code with the Claude Code extension.
2. `redline init` already installed the skill at `.claude/skills/redline/` and a contract note at
   `.redline/CLAUDE.redline.md`. Add one line to your project's `CLAUDE.md` so Claude always knows:

   ```
   See .redline/CLAUDE.redline.md — address review comments with the /redline skill.
   ```

3. In the Claude Code chat panel, start the rolling loop:

   ```
   /loop 45s /redline
   ```

   Now every ~45s Claude reads your open comments, edits the docs, and replies. Leave it running while
   you review. Stop it anytime with `/loop` again or Esc. Prefer manual control? Just run `/redline`
   once whenever you want the queue worked.

That's the whole loop: **comment in the browser → Claude revises in VS Code → diff + reply show up live.**

---

## Features

| | |
|---|---|
| **Formatted review** | Markdown rendered as clean prose, two-pane with margin comments |
| **Direct editing** | ✏️ Edit lets you type into the document; autosaves straight to the `.md` source (what Claude reads and what becomes the `.docx`) |
| **Highlight + comment** | Select text → 💬 → comment is anchored to that exact passage |
| **One-click wiring** | Double-click app sets up any project; **⌁ Wire to Claude** copies the loop command |
| **Rolling queue** | `/loop 45s /redline` works the open comments automatically |
| **Live diff** | Claude's edit shows as red/green word-diff in the comment + green highlight in the text |
| **Threads** | Reply to Claude in a comment; it re-opens so Claude re-engages |
| **Citations** | `[@key]` renders as a clickable in-text link to the reference list (from `references.bib`) |
| **Images** | `![caption](fig.png)` renders inline (files under `docs/`) |
| **→ .docx** | One-click pandoc export with linked citations — the academic deliverable |
| **Dark / light** | ◐ toggles white-on-black ⇄ black-on-white |
| **Font size** | ⌘+ / ⌘− (or A+/A−) resize the document, not the browser |

---

## The `.docx` path

Markdown is the **source of truth** (so Claude can edit, diff, and comment on it cleanly), and `.docx`
is the **deliverable**. The **Export .docx** button (or `redline export draft.md`) runs pandoc:

- in-text citations `[@key]` → formatted, linked citations + a reference list (needs a `references.bib`);
- images embedded; headings, tables, lists preserved.

Drop a `.csl` file (e.g. from the Zotero style repo) into the project to control citation style.
Exports land in `.redline/exports/`.

---

## Without Docker

```bash
cd /path/to/project
redline init
redline serve        # uses your python3; install pandoc separately for .docx (brew install pandoc)
```

---

## Using it across many projects

The image is built once. For each project: `cd project && redline init && redline up`. Each project
gets its own `.redline/` data and its own copy of the skill, but they all share the one container image.
Run several at once by setting `REDLINE_PORT` (e.g. `REDLINE_PORT=8788 redline up`).

---

## Push to GitHub

```bash
cd ~/WicrosoftMord
git add -A && git commit -m "WicrosoftMord: review surface for writing with Claude"   # repo is already initialized
gh repo create WicrosoftMord --public --source=. --push   # or: git remote add origin <url> && git push -u origin main
```

`.redline/` runtime data is git-ignored, so only the tool ships.

---

## File contract (for the curious / for other agents)

```
your-project/
  docs/                       # Markdown documents under review (source of truth)
  references.bib              # optional — powers linked citations
  .redline/
    config.json               # { "title": ..., "docsDir": "docs" }
    comments/cmt_*.json        # one file per comment (UI writes new; Claude updates)
    exports/*.docx             # pandoc output
    CLAUDE.redline.md          # the contract note Claude reads
  .claude/skills/redline/SKILL.md   # the /redline skill (installed by `redline init`)
```

See `.claude/skills/redline/SKILL.md` for the exact comment schema and Claude's pass algorithm.
