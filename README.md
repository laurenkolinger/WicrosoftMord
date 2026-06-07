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
| **WYSIWYG editing** | ✏️ Edit (the default) lets you type into the *formatted* document with a toolbar; autosaves to the `.md` source via an HTML→Markdown serialiser (what Claude reads and what becomes the `.docx`) |
| **Comment while editing** | Select text and press the comment shortcut (default ⌥C, settable in Setup) to comment without leaving the editor |
| **Split panes** | ▦ Refs docks a resizable References panel beside or below the document; click a citation to jump to its entry. Drag the divider to resize |
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

## Projects: one self-contained folder per paper, one port each

Each project lives in its **own folder, built as a side folder next to this repo clone** (not inside it).
That folder holds everything needed to resume the work entirely, and runs on **its own port** so you can
keep several projects open at once.

### Make a new project

```bash
cd ~/WicrosoftMord
bin/wmord-new-project.sh <name> [source.docx] [references.bib]
# e.g.
bin/wmord-new-project.sh bleaching ~/Desktop/paper_main.docx ~/refs/references.bib
```

This creates `../<name>/` (a sibling of the repo) and:

- assigns the project a **stable port** (8800–8899, derived from the name);
- seeds **csl/** with the bundled citation styles and **templates/** with the Word reference templates
  (add your own to either later);
- if you pass a `.docx`, **copies it in, converts it to Markdown, extracts every figure into `media/`, and
  keeps the tables** (so figures and tables survive export); copies your `.bib` in as `references.bib`;
- writes **.redline/** (global rules in `instructions.md`, `config.json` with the port, empty `comments/`);
- writes a double-click **`open.command`** that starts the server pinned to this folder and port and opens
  the browser. To resume the project any day, double-click `open.command`.

Then open the folder in VS Code and run `/loop 45s /redline` in the Claude panel to wire Claude in.

### What the folder contains (and why it fully resumes the project)

```
<name>/                         # a sibling of the cloned repo
  open.command                  # double-click: starts the server on THIS project's port, opens the browser
  <doc>.md                      # the document (Markdown is the source of truth)
  media/                        # figures & tables extracted from the source .docx
  references.bib                # bibliography the citations resolve against
  csl/                          # citation styles (drop more .csl here; they appear in Setup)
  templates/                    # Word reference templates for export (point Setup at one)
  exports/                      # every export: <doc>_<YYYY-MM-DD_HHMMSS>.docx, opened in Word automatically
  .redline/
    instructions.md             # global house-style rules Claude obeys everywhere
    comments/cmt_*.json         # one file per comment (the conversation with Claude)
    config.json                 # { title, docsDir, port, exportFont, cslStyle, exportTemplate, bibPath }
```

The **global rules and all comments live in this folder** (`.redline/`), so the whole review state travels
with it. Exports land in **`exports/`** (in the folder, not hidden), stamped with date-time so nothing is
overwritten, and open in Word automatically.

### For an agent setting this up from scratch

1. Clone this repo; read this README.
2. Run `bin/wmord-new-project.sh <name> <source.docx> <references.bib>` to build the side project folder.
   (Equivalently, do it by hand: make the folder, copy the bundled `csl/` and `templates/`, copy the
   document and `.bib` in, then `pandoc <doc>.docx --extract-media=media -t gfm -o <doc>.md` to pull the
   figures into `media/` and keep the tables.)
3. If figures still are not inline in the Markdown (e.g. they were floating objects), embed them: for each
   `Figure N`/`Table N`, place its image (`![caption](media/…png)`) or its Markdown table at the matching
   callout/caption, keeping the **current** caption text.
4. Double-click `open.command`; in VS Code run `/loop 45s /redline`.

### Figures & tables on export (read this before exporting)

Markdown is the source of truth, so **figures and tables only reach the exported `.docx` if they are in the
Markdown.** When you revise, keep every `![caption](media/…)` image and every Markdown table in place, at its
original position, with its caption updated to match your edits. Do not drop a figure/table just because you
rewrote the surrounding prose. On export the server embeds them into the `.docx` automatically.

### Pointing Setup at a custom export template

Setup → *Export: custom Word template* takes a path to any `.docx` whose styles/margins/fonts the export
should copy. Put templates in the project's `templates/` folder and point at one.

#### Have an agent build a template from an existing Word doc

Give another agent this brief:

> Produce a pandoc **reference `.docx`** (a style-only template; its body text is discarded, only its styles
> are used) from `<existing.docx>`, matching the **grants.gov** general formatting rules for the most
> space-efficient still-allowable layout: a standard serif or sans body at **11 pt**, **single line spacing**,
> **0.5 inch margins** on all sides, no extra space between paragraphs, and the document’s heading styles
> (Heading 1/2/3), Normal, Title, Caption, and Table styles defined consistently. Start from
> `pandoc --print-default-data-file reference.docx`, edit `word/styles.xml` and `word/document.xml` section
> margins to those values, set the Normal style to 11 pt single-spaced, and save as
> `templates/<name>-reference.docx`. Verify by exporting a sample and checking margins and point sizes in Word.

(See `bin/make-reference-docs.py` for how the bundled Times New Roman / Arial templates are generated.)

### Docker / many-at-once (optional)

The container image is built once. For each project: `cd project && redline init && redline up`. Each gets
its own `.redline/`; share the one image. The `open.command` approach above is the simpler path on a Mac.

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

See **Projects: one self-contained folder per paper** above for the full folder layout. In short: the
document Markdown is the source of truth, `media/` holds figures/tables, `references.bib` + `csl/` drive
citations, `templates/` holds export reference docs, `exports/` holds date-stamped `.docx` output, and
`.redline/` holds the global `instructions.md`, the per-comment JSON in `comments/`, and `config.json`.

See `.claude/skills/redline/SKILL.md` for the exact comment schema and Claude's pass algorithm.
