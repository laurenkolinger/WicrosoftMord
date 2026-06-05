# Welcome to Redline

This is a sample document so you can try the review loop immediately.

**Try this:** select any sentence below, click the 💬 **Comment** bubble, and leave a
note like *"tighten this"* or *"needs a citation"*. Then, in your VS Code Claude Code
panel, run `/loop 45s /redline`. Within a tick or two you'll see the text change, a
green/red diff appear in the comment, and Claude's reply — all without a page refresh.

## Things you can test

- **Citations** render as links. Coral cover has declined sharply across the Caribbean
  over recent decades [@jackson2014], with disease and thermal stress as major drivers
  [@hughes2017]. Click a citation to jump to the reference list at the bottom.
- **Images** show inline. Drop a PNG into your `docs/` folder and reference it:
  `![A reef survey transect](my-figure.png)`
- **Dark mode**: the ◐ button (top right) flips white-on-black ⇄ black-on-white.
- **Font size**: ⌘+ / ⌘− (or the A+ / A− buttons) resize the document.
- **Export**: the **Export .docx** button renders this Markdown to a Word file with the
  citations linked — the format your field expects.

## How the collaboration works

You comment here → comments become files on disk → Claude (in your editor) reads them,
edits this document, and writes replies back → this view updates live. Markdown stays the
source of truth so Claude can edit and diff it cleanly; `.docx` is one click away whenever
you need to hand it off.
