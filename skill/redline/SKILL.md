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

## Writing for .docx (house style — the human's field requires it)

The Markdown is the source of truth; it is exported to **.docx** via pandoc. So write pandoc-clean Markdown:
- In-text citations as `[@bibtexkey]` (e.g. `[@hughes2017]`), multiple as `[@a; @b]`. A `references.bib`
  in the project root or docs folder makes them render as linked citations in the UI and the .docx.
- Images as `![caption](relative/path.png)` with the file living under the docs folder so they render.
- Standard headings (`#`), lists, tables, blockquotes. Avoid raw HTML.
Do not generate the .docx yourself unless asked — the human exports it with the "Export .docx" button.
