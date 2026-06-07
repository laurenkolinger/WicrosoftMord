#!/usr/bin/env python3
"""
WicrosoftMord — .docx import.

Convert a Word document to a clean Markdown source (via pandoc, tracked changes
accepted) AND pull the *human review* out of the file so it lands in the same
file-backed comment store the rest of WicrosoftMord uses:

  * Word COMMENTS  -> one comment JSON each, keeping the commenter's name and
    the *exact text they highlighted* (the anchored range = the quote).
  * TRACKED CHANGES (insertions / deletions) -> one comment JSON each,
    best-effort, never allowed to break the import.

Stdlib only. `pandoc` must be on PATH for the Markdown conversion.
"""

import json
import os
import re
import random
import shutil
import subprocess
import time
import zipfile


# --------------------------------------------------------------------------- #
# Small helpers (kept local so this module is self-contained / importable)
# --------------------------------------------------------------------------- #
def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def _gen_id():
    return f"cmt_{int(time.time() * 1000)}_{random.randint(0x1000, 0xffff):04x}"


def _sanitize_name(docx_path):
    """basename without extension, keeping only alnum/dash/underscore; spaces -> _."""
    base = os.path.basename(docx_path)
    stem = os.path.splitext(base)[0]
    stem = stem.replace(" ", "_")
    stem = re.sub(r"[^A-Za-z0-9_-]", "", stem)
    return stem or "document"


_ENTITIES = (
    ("&lt;", "<"),
    ("&gt;", ">"),
    ("&quot;", '"'),
    ("&apos;", "'"),
    ("&amp;", "&"),  # do amp last
)


def _unescape(text):
    if not text:
        return ""
    # numeric entities first, then named (amp last so &amp;lt; -> &lt;)
    text = re.sub(r"&#x([0-9A-Fa-f]+);", lambda m: chr(int(m.group(1), 16)), text)
    text = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)
    for ent, ch in _ENTITIES:
        text = text.replace(ent, ch)
    return text


def _text_runs(fragment):
    """Concatenate the plain text of every <w:t>...</w:t> inside a fragment.

    Whitespace-only <w:t xml:space="preserve"> runs are honoured. Tab/break
    elements are rendered as whitespace so words don't fuse together.
    """
    if not fragment:
        return ""
    # Convert structural whitespace markers (tabs/breaks, which live *between*
    # <w:t> runs rather than inside them) into capturable space runs so adjacent
    # words don't fuse together.
    fragment = re.sub(r"<w:tab\b[^>]*?/?>", "<w:t> </w:t>", fragment)
    fragment = re.sub(r"<w:br\b[^>]*?/?>", "<w:t> </w:t>", fragment)
    fragment = re.sub(r"<w:cr\b[^>]*?/?>", "<w:t> </w:t>", fragment)
    parts = []
    for m in re.finditer(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", fragment, re.S):
        parts.append(_unescape(m.group(1)))
    # self-closing/empty <w:t/> carries no text — nothing to add
    return "".join(parts)


def _attr(tag, name):
    """Read attribute `name` from an opening tag string (already isolated)."""
    m = re.search(r'\b' + re.escape(name) + r'\s*=\s*"([^"]*)"', tag)
    if not m:
        m = re.search(r"\b" + re.escape(name) + r"\s*=\s*'([^']*)'", tag)
    return _unescape(m.group(1)) if m else ""


# --------------------------------------------------------------------------- #
# Comment-body extraction from word/comments.xml
# --------------------------------------------------------------------------- #
def _parse_comments_xml(xml):
    """Return {id: {"author": str, "body": str, "date": str}} for each comment."""
    out = {}
    if not xml:
        return out
    # Each comment is <w:comment ...> ... </w:comment>; ids are unique.
    for m in re.finditer(r"<w:comment\b([^>]*)>(.*?)</w:comment>", xml, re.S):
        open_attrs = m.group(1)
        inner = m.group(2)
        cid = _attr(open_attrs, "w:id")
        if cid == "":
            continue
        out[cid] = {
            "author": _attr(open_attrs, "w:author"),
            "date": _attr(open_attrs, "w:date"),
            "body": _text_runs(inner).strip(),
        }
    return out


# --------------------------------------------------------------------------- #
# Anchored-quote extraction from word/document.xml
# --------------------------------------------------------------------------- #
def _parse_comment_ranges(xml):
    """For each comment id, return the plain text between its
    <w:commentRangeStart w:id="X"/> and <w:commentRangeEnd w:id="X"/>.

    Ranges may span multiple runs/paragraphs and may interleave with other
    comment ranges, so we walk the markers by position rather than assuming
    well-nested spans.
    """
    quotes = {}
    if not xml:
        return quotes

    # Collect every start/end marker with its character offset in the document.
    markers = []  # (pos, kind, id)
    for m in re.finditer(r"<w:commentRangeStart\b([^>]*?)/?>", xml):
        cid = _attr(m.group(1), "w:id")
        markers.append((m.start(), m.end(), "start", cid))
    for m in re.finditer(r"<w:commentRangeEnd\b([^>]*?)/?>", xml):
        cid = _attr(m.group(1), "w:id")
        markers.append((m.start(), m.end(), "end", cid))

    starts = {}
    for start_pos, end_pos, kind, cid in sorted(markers):
        if cid == "":
            continue
        if kind == "start":
            # first start wins if duplicated; record where the content begins
            starts.setdefault(cid, end_pos)
        else:  # end
            begin = starts.get(cid)
            if begin is None:
                quotes.setdefault(cid, "")
                continue
            span = xml[begin:start_pos]
            quotes[cid] = _text_runs(span).strip()
            starts.pop(cid, None)
    # any unmatched starts -> empty quote
    for cid in starts:
        quotes.setdefault(cid, "")
    return quotes


# --------------------------------------------------------------------------- #
# Tracked-changes extraction (best-effort)
# --------------------------------------------------------------------------- #
def _parse_tracked_changes(xml):
    """Return a list of dicts: {"kind": "ins"|"del", "author": str, "text": str}.

    <w:ins w:author=..> wraps inserted runs (text in <w:t>).
    <w:del w:author=..> wraps deleted runs (text in <w:delText>).
    Robust to nesting; failures are swallowed by the caller.
    """
    changes = []
    if not xml:
        return changes

    for m in re.finditer(r"<w:ins\b([^>]*)>(.*?)</w:ins>", xml, re.S):
        author = _attr(m.group(1), "w:author")
        text = _text_runs(m.group(2)).strip()
        if text:
            changes.append({"kind": "ins", "author": author, "text": text})

    for m in re.finditer(r"<w:del\b([^>]*)>(.*?)</w:del>", xml, re.S):
        author = _attr(m.group(1), "w:author")
        inner = m.group(2)
        parts = [
            _unescape(t.group(1))
            for t in re.finditer(r"<w:delText(?:\s[^>]*)?>(.*?)</w:delText>", inner, re.S)
        ]
        text = "".join(parts).strip()
        if text:
            changes.append({"kind": "del", "author": author, "text": text})

    return changes


# --------------------------------------------------------------------------- #
# Pandoc conversion
# --------------------------------------------------------------------------- #
def _run_pandoc(docx_path, out_md, media_dir):
    pandoc = shutil.which("pandoc")
    if not pandoc:
        raise RuntimeError("pandoc is not installed (required for .docx import).")
    # Run pandoc *inside* the output directory with a RELATIVE media dir so the
    # image links it writes are project-relative (media/media/x.png) rather than
    # absolute. Absolute paths break the UI when the project path contains spaces
    # and never resolve through /api/media. The docx is passed as an absolute path
    # so pandoc still finds it regardless of cwd.
    cwd = os.path.dirname(os.path.abspath(out_md)) or "."
    out_rel = os.path.basename(out_md)
    try:
        media_rel = os.path.relpath(media_dir, cwd)
    except ValueError:
        media_rel = media_dir
    cmd = [
        pandoc, os.path.abspath(docx_path), "-o", out_rel,
        "--wrap=none",
        "--markdown-headings=atx",
        # Force GFM PIPE tables (disable grid/multiline/simple) so the review UI,
        # which renders pipe tables, keeps every table after import.
        "-t", "markdown-grid_tables-multiline_tables-simple_tables",
        "--extract-media=" + media_rel,
        "--track-changes=accept",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=cwd)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "pandoc failed to convert the .docx")


# --------------------------------------------------------------------------- #
# Highlight-color preservation
# --------------------------------------------------------------------------- #
# pandoc collapses every Word highlight to a single `[..]{.mark}` (color lost)
# and drops shading-based highlights entirely. We re-inject the source colors so
# the app can render `<mark class="hl-COLOR">`. Highlighter-tool runs map 1:1 to
# pandoc's marks (in order); shading runs are wrapped by text search.
_SHADE_MAP = {"ffc0cb": "pink", "ffa500": "orange"}


def _run_color(run_xml):
    """(mechanism, color) for a run: ('hl', val) highlighter, ('shd', name) shading, else (None, None)."""
    rpr = re.search(r"<w:rPr\b[^>]*>(.*?)</w:rPr>", run_xml, re.S)
    if not rpr:
        return None, None
    rp = rpr.group(1)
    hm = re.search(r'<w:highlight w:val="([^"]+)"', rp)
    if hm and hm.group(1) not in ("none", "white"):
        return "hl", hm.group(1)
    sm = re.search(r'<w:shd\b[^>]*w:fill="([^"]+)"', rp)
    if sm and sm.group(1).lower() in _SHADE_MAP:
        return "shd", _SHADE_MAP[sm.group(1).lower()]
    return None, None


def _strip_image_attrs(md):
    """Drop pandoc's {width=..} image attributes so the Markdown stays clean."""
    return re.sub(r'(\!\[[^\]]*\]\([^)]*\))\{[^}]*\}', r'\1', md)


def _inject_highlight_colors(md, document_xml):
    """Add `.hl-<color>` classes to the Markdown so highlight colors survive import."""
    if not document_xml:
        return md
    mark_rx = r'\[((?:[^\[\]]|\[[^\]]*\])*?)\]\{\.mark([^}]*)\}'

    # 1) Highlighter-tool "regions": consecutive highlighted runs within one
    #    paragraph (pandoc merges these into a single [..]{.mark}, dropping color).
    regions = []
    for pm in re.finditer(r"<w:p\b[^>]*>(.*?)</w:p>", document_xml, re.S):
        cur = None
        for rm in re.finditer(r"<w:r\b[^>]*>(.*?)</w:r>", pm.group(1), re.S):
            mech, color = _run_color(rm.group(1))
            txt = _text_runs(rm.group(1))
            if mech == "hl":
                if cur is None:
                    cur = {}
                cur[color] = cur.get(color, 0) + max(1, len(txt))
            elif txt.strip() != "":
                if cur is not None:
                    regions.append(cur); cur = None
        if cur is not None:
            regions.append(cur)
    seq = [max(c, key=c.get) for c in regions]  # dominant color per region, in order

    it = iter(seq)

    def _repl(m):
        try:
            c = next(it)
        except StopIteration:
            c = "yellow"
        attrs = m.group(2) or ""
        if ".hl-" in attrs:
            return m.group(0)
        return "[" + m.group(1) + "]{.mark .hl-" + c + attrs + "}"

    md = re.sub(mark_rx, _repl, md, flags=re.S)

    # 2) Shading-based highlights have no pandoc mark — wrap by text. Pink tends to
    #    mark citations; orange marks phrases (skip tiny/ambiguous fragments).
    shsegs = []
    last = None
    for rm in re.finditer(r"<w:r\b[^>]*>(.*?)</w:r>", document_xml, re.S):
        mech, color = _run_color(rm.group(1))
        txt = _text_runs(rm.group(1))
        if mech == "shd":
            if last and last[0] == color:
                last[1] += txt
            else:
                last = [color, txt]; shsegs.append(last)
        elif txt.strip() != "":
            last = None

    mark_span_rx = re.compile(r'\[(?:[^\[\]]|\[[^\]]*\])*?\]\{[^}]*\.mark[^}]*\}', re.S)

    def _wrap(text, color, body):
        t = text.strip()
        if not t:
            return body
        pat = re.escape(t).replace(r'\[', r'\\?\[').replace(r'\]', r'\\?\]')
        pat = re.sub(r'\\ ', r'\\s+', pat)
        spans = [m.span() for m in mark_span_rx.finditer(body)]
        for mm in re.finditer(pat, body):
            s, e = mm.span()
            # never wrap text overlapping an existing mark — that would nest marks,
            # which no Markdown highlighter (or this UI) can render.
            if any(ms < e and s < me for ms, me in spans):
                continue
            return body[:s] + "[" + body[s:e] + "]{.mark .hl-" + color + "}" + body[e:]
        return body

    for color, t in shsegs:
        if color == "pink":
            md = _wrap(t, color, md)
    for color, t in shsegs:
        if color == "orange" and len(t.strip()) >= 6 and re.search(r"[A-Za-z]{4,}", t):
            md = _wrap(t, color, md)
    return md


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def import_docx(docx_path, docs_root, comments_dir):
    """Import a .docx into WicrosoftMord.

    1. Convert to clean Markdown (tracked changes accepted) at
       <docs_root>/<name>.md, media under <docs_root>/media.
    2. Extract Word comments -> comment JSON (source "docx"), retaining the
       commenter name and the exact highlighted text as the quote.
    3. Extract tracked changes -> comment JSON (source "docx-change"),
       best-effort.

    Returns: {"ok": True, "file": "<name>.md", "comments": <int>, "changes": <int>}
    """
    os.makedirs(docs_root, exist_ok=True)
    os.makedirs(comments_dir, exist_ok=True)

    name = _sanitize_name(docx_path)
    md_name = name + ".md"
    out_md = os.path.join(docs_root, md_name)
    media_dir = os.path.join(docs_root, "media")

    # 1) Markdown source via pandoc (must succeed — it's the document itself).
    _run_pandoc(docx_path, out_md, media_dir)

    # Read the OOXML parts we care about, defensively.
    document_xml = ""
    comments_xml = ""
    try:
        with zipfile.ZipFile(docx_path) as zf:
            names = set(zf.namelist())
            if "word/document.xml" in names:
                document_xml = zf.read("word/document.xml").decode("utf-8", "replace")
            if "word/comments.xml" in names:
                comments_xml = zf.read("word/comments.xml").decode("utf-8", "replace")
    except Exception:
        # If the archive can't be read for review data, we still have the .md.
        document_xml = document_xml or ""
        comments_xml = comments_xml or ""

    # 1b) Clean image attrs and re-inject highlight colors into the Markdown.
    #     Cosmetic — never allowed to break the import.
    try:
        with open(out_md, encoding="utf-8") as fh:
            _md = fh.read()
        _md2 = _inject_highlight_colors(_strip_image_attrs(_md), document_xml)
        if _md2 != _md:
            with open(out_md, "w", encoding="utf-8") as fh:
                fh.write(_md2)
    except Exception:
        pass

    # 2) Word comments (priority): body from comments.xml, quote from document.xml.
    comment_count = 0
    bodies = _parse_comments_xml(comments_xml)
    quotes = _parse_comment_ranges(document_xml)
    for cid in sorted(bodies, key=lambda x: (len(x), x)):
        meta = bodies[cid]
        quote = quotes.get(cid, "")
        record = _make_comment(
            md_name=md_name,
            quote=quote,
            body=meta.get("body", ""),
            author=meta.get("author", ""),
            source="docx",
        )
        _write_comment(comments_dir, record)
        comment_count += 1

    # 3) Tracked changes (nice-to-have): never let this crash the import.
    change_count = 0
    try:
        for ch in _parse_tracked_changes(document_xml):
            if ch["kind"] == "ins":
                body = 'Inserted: "%s"' % ch["text"]
            else:
                body = 'Deleted: "%s"' % ch["text"]
            record = _make_comment(
                md_name=md_name,
                quote=ch["text"],
                body=body,
                author=ch.get("author", ""),
                source="docx-change",
            )
            _write_comment(comments_dir, record)
            change_count += 1
    except Exception:
        # Tracked changes are best-effort; swallow and report what we got.
        pass

    return {"ok": True, "file": md_name, "comments": comment_count, "changes": change_count}


def _make_comment(md_name, quote, body, author, source):
    return {
        "id": _gen_id(),
        "file": md_name,
        "quote": quote or "",
        "prefix": "",
        "suffix": "",
        "body": body or "",
        "author": author or "",
        "status": "external",
        "source": source,
        "acknowledged": False,
        "createdAt": _now_iso(),
        "thread": [],
        "revision": None,
    }


def _write_comment(comments_dir, record):
    path = os.path.join(comments_dir, record["id"] + ".json")
    # Ensure unique filename even if two ids collide within the same millisecond.
    while os.path.exists(path):
        record["id"] = _gen_id()
        path = os.path.join(comments_dir, record["id"] + ".json")
    tmp = "%s.tmp.%d.%d" % (path, os.getpid(), random.randint(0, 1 << 30))
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2)
    os.replace(tmp, path)
    return path
