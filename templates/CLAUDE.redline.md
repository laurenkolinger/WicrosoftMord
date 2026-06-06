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
