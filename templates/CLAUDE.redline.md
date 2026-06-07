# WicrosoftMord (Redline) is active in this project

A human is reviewing documents in the **WicrosoftMord** web app and leaving comments for you.

- **Standing directions**: ALWAYS read **`.redline/instructions.md`** first (the user's house-style
  rules set in Setup — e.g. "no em dashes", spelling, voice, which resources to cite) and obey it in
  every edit, reply, and draft. It overrides your defaults and applies even when no comment mentions it.
- **Documents** under review live in the `docsDir` set in `.redline/config.json` (default `docs/`),
  as Markdown. Markdown is the source of truth; the final artifact is **.docx** (exported via pandoc).
- **Comments** are JSON files in `.redline/comments/`. Each has `file`, `quote`, `body`, and `status`.

## When the user asks you to address comments — or runs `/loop 45s /redline`

Use the **`redline` skill** (`/redline`). One pass =
1. read `.redline/comments/*.json`, take the ones with `status: "open"` you have not already addressed;
2. find each `quote` in its document and make the edit `body` asks for;
3. write back into that comment file: a `revision` `{before, after}` (both are the exact text spans as
   they appear, plain text) and a `thread` reply, and **leave `status` as `"open"`; only the user resolves
   comments.** NEVER set `status` to `"resolved"` or `"wontfix"`, and never set `acknowledged`. If you
   decline a change, still leave it `open` and explain why in the reply;
4. summarize in one line.

Only ever modify comment files whose status was `open`. Comments stay `open` until the *user* resolves
them; a user reply adds to the thread so you re-engage on the next pass.

## When you draft or revise documents

Write **pandoc-clean Markdown** so it exports to .docx with linked citations and visible images:
- citations: `[@bibtexkey]` (a `references.bib` powers the links);
- images: `![caption](relative/path.png)` with files under the docs folder;
- standard headings/lists/tables; avoid raw HTML.

See `.claude/skills/redline/SKILL.md` for the full contract.

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
