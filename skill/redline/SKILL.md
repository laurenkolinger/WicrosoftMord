---
name: redline
description: Address reviewer comments left in the Redline review UI. Reads open comments from .redline/comments/, edits the referenced Markdown documents to satisfy each comment, records a before/after revision and a reply, and leaves the comment open for the user to resolve. Run on a loop (`/loop 45s /redline`) for rolling collaboration. Use whenever the user mentions Redline comments, document review feedback, or asks you to "address the comments".
---

# Redline — addressing review comments

You are collaborating with a human who reviews your writing in the **Redline / WicrosoftMord** web app.
They highlight text and leave comments. Those comments are plain JSON files on disk.
Your job: work the open comments, edit the documents, and write back — so the loop turns.

## FIRST, every pass: read the standing directions

Before doing anything else, read **`.redline/instructions.md`** if it exists. It holds the user's
standing house-style rules set in Setup (for example: "no em dashes", spelling, voice, tone, which
resources to cite). **Obey it in every edit, reply, and draft** — it overrides your defaults. If a rule
says no em dashes, use commas, colons, or parentheses instead, and remove any em dashes you would add.
These directions apply even when no comment mentions them.

## The contract (files in the project)

- Documents under review: Markdown files in the `docsDir` from `.redline/config.json` (default `docs/`).
- Comments: one JSON file per comment in `.redline/comments/*.json`:

```json
{
  "id": "cmt_...",
  "file": "draft.md",            // path relative to docsDir
  "quote": "the exact text the human highlighted",
  "prefix": "…text just before…", // helps you locate the right occurrence
  "suffix": "…text just after…",
  "body": "what the human wants",  // the actual instruction
  "status": "open",                // open | resolved | wontfix
  "acknowledged": false,
  "thread": [ {"author": "user", "text": "...", "at": "..."} ],
  "revision": null
}
```

## Your single pass (this is what `/redline` does)

1. **Read** every file in `.redline/comments/`. Select those with `status == "open"` that you have not
   already addressed — i.e. skip a comment whose latest `thread` entry is already from `claude` and that
   carries no newer `user` reply after it (you handled it; the user hasn't pushed back yet). If there is
   nothing new to address, say "No open comments" and stop. (Idempotent — never re-do work you already did;
   comments stay `open` until the *user* resolves them, so use the thread, not the status, to tell what is
   done.)
2. For each open comment, **locate the text**: find `quote` in the named document (use `prefix`/`suffix`
   to disambiguate if the quote appears more than once). The quote is the *rendered* text, so inline
   markdown like `**bold**` or `[@cite]` may surround it in the source — match on the visible words.
3. **Make the edit** the comment asks for, directly in the Markdown file. Keep it tight and in the
   author's voice. If the comment is a question, answer it in your reply rather than editing.
4. **Record the result** by overwriting the comment's JSON file with:
   - `revision`: `{ "before": "<exact old text span>", "after": "<exact new text span>", "at": "<ISO time>" }`
     — BOTH `before` and `after` must be the exact text spans as they appear in the document (plain text,
     so the UI can locate `after` in the rendered document). Keep them to the changed span (a sentence or
     two), not the whole document. This drives the red/green diff the human sees.
   - append to `thread`: `{ "author": "claude", "text": "<one line: what you did / why>", "at": "<ISO time>" }`
   - **leave `status` as `"open"`; only the user resolves comments.** NEVER set `status` to `"resolved"`
     or `"wontfix"`, and never set `acknowledged`. You edit the document and reply; the USER decides when a
     comment is resolved. If you decline to make a change (e.g. it would be factually wrong), still leave
     `status` as `"open"` and explain why in your `thread` reply so the user can decide.
   - leave `acknowledged` as-is (the human clears it with "Looks good").
   Write valid JSON. Preserve all other fields. Edit ONLY comment files whose status was `open`.
5. After the pass, give a 1-line summary: `Addressed N comments in <files>.`

Comments stay `open` throughout; a user reply adds a new `user` entry to `thread`, so on the next pass
you'll see their pushback — read the latest user message and respond to it (edit + reply again, still
leaving `status` as `open`). The user is the only one who marks a comment resolved.

## Rolling mode

The human runs `/loop 45s /redline` in their VS Code Claude Code panel. Each tick = one pass.
Keep passes fast and conservative: small, surgical edits; never rewrite untouched sections; never touch
a comment that isn't `open`. The Redline UI polls the files and updates live, so the moment you write,
they see the diff and your reply.

## Project context the human may have set (read `.redline/config.json`)

- **`styleDir`** — a folder of the author's own writing. Consult it to match their **voice and phrasing
  only**; do NOT import facts or content from it (their research has moved on). Mirror their cadence,
  sentence shape, and word choice.
- **`litDir`** — a folder of source-literature PDFs. Read from it to ground and **verify** claims, cite
  from it, and (if you can download) add newly fetched papers to it. Never assert a number or finding you
  cannot source.
- **`bibPath`** — the references `.bib` to cite from. **`exportTemplate`** — a Word reference doc the export
  copies styling from.

## Figures and tables (must survive export)

Markdown is the source of truth, so **figures and tables only reach the exported `.docx` if they are in the
Markdown.** Keep every `![caption](media/…)` image and every Markdown table at its original position, and
update the caption to match your edits. Never silently drop a figure or table when you rewrite the prose
around it. Place an image/table at the matching `Figure N` / `Table N` callout or caption.

## Writing for .docx (house style — the human's field requires it)

The Markdown is the source of truth; it is exported to **.docx** via pandoc. So write pandoc-clean Markdown:
- In-text citations as `[@bibtexkey]` (e.g. `[@hughes2017]`), multiple as `[@a; @b]`. A `references.bib`
  in the project root or docs folder makes them render as linked citations in the UI and the .docx.
- Images as `![caption](relative/path.png)` with the file living under the docs folder so they render.
- Standard headings (`#`), lists, tables, blockquotes. Avoid raw HTML.
Do not generate the .docx yourself unless asked — the human exports it with the "Export .docx" button.

## On import / first review — MANDATORY (do not skip)

### References (build the .bib and key the citations)
- A `references.bib` MUST power every citation. If the document has a numbered reference list and/or numeric in-text citations like `[1, 2, 3]` (or pandoc-escaped `\[1, 2, 3\]`), BUILD `references.bib` from that list and convert the citations:
  - One entry per reference. Keys are `lastnameYEAR` (lowercase first-author surname + year), with `a`/`b` suffixes when one author has two entries in the same year (e.g. `nemeth2023a`, `nemeth2023b`).
  - ONE FIELD PER LINE: `field = {value},`. Include author, year, title, journal/booktitle, volume, pages, and a `doi` (the DOI URL wherever one exists). Flag any reference with no DOI.
  - Replace EVERY in-text numeric citation with pandoc citations: `\[1, 2, 3\]` -> `[@key1; @key2; @key3]`. Leave NO backslash-escaped brackets in the prose.
  - Set `bibPath` and `cslStyle` in `.redline/config.json` so export runs citeproc.
- NEVER pack multiple BibTeX fields onto one line (the preview parser and humans read one field per line).

### Figures & tables (caption rides with the object)
- Every figure is an inline image `![caption](media/....png)` with a RELATIVE path (never an absolute `/Users/...` path) so it renders and survives export.
- Keep each caption WITH its figure/table. Remove any duplicate standalone caption paragraph (a `**Figure N.** ...` line that just repeats the image's caption) from the body text.
- Tables must be GFM pipe tables.
- `server/docx_import.py` already preserves figures, pipe tables, highlight colors, and Word comments on import — VERIFY they survived; fix any broken/absolute image path or duplicated caption before reviewing.
