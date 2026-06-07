#!/usr/bin/env python3
"""
WicrosoftMord — a portable, file-backed document review surface.

The server never talks to Claude. It only reads/writes plain files inside the
*active project's* `.redline/` directory. Claude reads those same files, edits
the documents, and writes replies back. The browser polls and live-updates.

The active project folder is chosen IN THE UI (folder picker) and persisted, so
you point WicrosoftMord at any folder without touching a terminal. Its absolute
path is shown in the window so you can copy it and tell Claude where to loop.

Stdlib only. Optional: `pandoc` on PATH enables Markdown -> .docx export.
"""

import json
import os
import re
import shutil
import subprocess
import threading
import time
import random
import datetime
import sys
import mimetypes
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HOME = os.path.expanduser("~")
if HERE not in sys.path:
    sys.path.insert(0, HERE)   # so we can import sibling modules (docx_import)

WEB_DIR = os.environ.get("REDLINE_WEB", os.path.join(ROOT, "web"))
STYLES_DIR = os.path.join(ROOT, "styles")        # bundled CSL reference styles
TEMPLATES_DIR = os.path.join(ROOT, "templates")  # bundled .docx reference templates
PORT = int(os.environ.get("REDLINE_PORT", "8787"))
HOST = os.environ.get("REDLINE_HOST", "127.0.0.1")   # local-only by default; Docker opts into 0.0.0.0
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


def within_home(p):
    """True only if p is HOME or strictly inside it (trailing-separator safe)."""
    return p == HOME or p.startswith(HOME + os.sep)

ACTIVE_FILE = os.path.join(ROOT, ".wmord-active.json")   # remembers the chosen folder
DEFAULT_WORKSPACE = os.path.join(ROOT, "workspace")       # stable scratch default

DOCX_FONTS = {"tnr": "reference-tnr.docx", "arial": "reference-arial.docx"}

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".tif", ".tiff", ".pdf"}
_lock = threading.Lock()

# The single mutable piece of server state: which project folder is active.
_active = {"project": None}


# --------------------------------------------------------------------------- #
# Active project (chosen in the UI, persisted)
# --------------------------------------------------------------------------- #
def init_active():
    saved = None
    try:
        with open(ACTIVE_FILE, "r", encoding="utf-8") as fh:
            saved = json.load(fh).get("project")
    except Exception:
        saved = None
    env_data = os.environ.get("REDLINE_DATA")
    if saved and os.path.isdir(saved):
        _active["project"] = os.path.abspath(saved)
    elif env_data:
        _active["project"] = os.path.dirname(os.path.abspath(env_data))
    else:
        os.makedirs(DEFAULT_WORKSPACE, exist_ok=True)
        _active["project"] = DEFAULT_WORKSPACE
    ensure_dirs()


def set_project(path):
    full = os.path.realpath(os.path.expanduser(path or ""))
    if not within_home(full):
        raise ValueError("choose a folder inside your home directory")
    os.makedirs(full, exist_ok=True)
    _active["project"] = full
    try:
        atomic_write(ACTIVE_FILE, json.dumps({"project": full}, indent=2))
    except Exception:
        pass
    ensure_dirs()
    return full


def project_dir():
    return _active["project"]


def data_dir():
    return os.path.join(project_dir(), ".redline")


def comments_dir():
    return os.path.join(data_dir(), "comments")


def exports_dir():
    return os.path.join(project_dir(), "exports")   # visible in the project folder, not hidden in .redline


def uistate_path():
    return os.path.join(data_dir(), "ui-state.json")   # the whole UI state, so a reopen looks identical


def load_uistate():
    try:
        with open(uistate_path(), "r", encoding="utf-8") as fh:
            d = json.load(fh)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_uistate(data):
    if not isinstance(data, dict):
        return {"ok": False}
    ensure_dirs()
    atomic_write(uistate_path(), json.dumps(data, indent=0))
    return {"ok": True}


def config_path():
    return os.path.join(data_dir(), "config.json")


# --------------------------------------------------------------------------- #
# Storage helpers
# --------------------------------------------------------------------------- #
def ensure_dirs():
    os.makedirs(comments_dir(), exist_ok=True)
    os.makedirs(exports_dir(), exist_ok=True)
    if not os.path.exists(config_path()):
        atomic_write(config_path(), json.dumps(default_config(), indent=2))


def default_config():
    return {"title": os.path.basename(project_dir()) or "WicrosoftMord", "docsDir": "docs"}


def load_config():
    try:
        with open(config_path(), "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    except Exception:
        cfg = {}
    base = default_config()
    base.update(cfg or {})
    return base


def instructions_path():
    return os.path.join(data_dir(), "instructions.md")


def load_instructions():
    """Standing directions the user set in Setup (house style, resources, rules)."""
    try:
        with open(instructions_path(), "r", encoding="utf-8") as fh:
            return fh.read()
    except Exception:
        return ""


def save_settings(data):
    cfg = load_config()
    if isinstance(data.get("title"), str) and data["title"].strip():
        cfg["title"] = data["title"].strip()
    if isinstance(data.get("docsDir"), str) and data["docsDir"].strip():
        cfg["docsDir"] = data["docsDir"].strip()
    if isinstance(data.get("exportFont"), str):
        cfg["exportFont"] = data["exportFont"]      # "", "tnr", or "arial"
    if isinstance(data.get("cslStyle"), str):
        cfg["cslStyle"] = data["cslStyle"]          # a filename in STYLES_DIR, or ""
    if isinstance(data.get("exportTemplate"), str):
        cfg["exportTemplate"] = data["exportTemplate"].strip()   # absolute path to a custom .docx reference doc, or ""
    if isinstance(data.get("bibPath"), str):
        cfg["bibPath"] = data["bibPath"].strip()                 # absolute path to a references .bib, or "" to auto-find
    if isinstance(data.get("litDir"), str):
        cfg["litDir"] = data["litDir"].strip()                   # folder of source-literature PDFs for Claude to cite/verify against
    if isinstance(data.get("styleDir"), str):
        cfg["styleDir"] = data["styleDir"].strip()               # folder of the author's own writing samples (for VOICE only, not content)
    ensure_dirs()
    atomic_write(config_path(), json.dumps(cfg, indent=2))
    if "instructions" in data:
        atomic_write(instructions_path(), data.get("instructions") or "")
    return {"ok": True}


def activity_path():
    return os.path.join(data_dir(), "activity.json")


def load_activity():
    """Latest loop status the user sees in the window (written by Claude each pass)."""
    try:
        with open(activity_path(), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def list_styles():
    # bundled styles plus any .csl you drop in the project folder or its csl/ subfolder
    out, seen = [], set()
    dirs = [STYLES_DIR, project_dir(), os.path.join(project_dir(), "csl")]
    for d in dirs:
        if os.path.isdir(d):
            for n in sorted(os.listdir(d)):
                if n.lower().endswith(".csl") and n not in seen:
                    seen.add(n); out.append(n)
    return out


def resolve_style(name):
    """Find a .csl by filename across the bundled dir and the project folder."""
    for d in (STYLES_DIR, project_dir(), os.path.join(project_dir(), "csl")):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    return None


def add_style(path):
    expanded = os.path.expanduser(path or "")
    if os.path.islink(expanded):
        raise ValueError("symlinks are not allowed")
    src = os.path.realpath(expanded)          # resolves any symlinks in parent dirs too
    if not within_home(src):
        raise ValueError("choose a .csl file inside your home directory")
    if not src.lower().endswith(".csl") or not os.path.isfile(src):
        raise ValueError("not a .csl file")
    os.makedirs(STYLES_DIR, exist_ok=True)
    name = os.path.basename(src).replace(" ", "-")
    shutil.copy(src, os.path.join(STYLES_DIR, name))
    return {"ok": True, "style": name}


def atomic_write(path, text):
    tmp = f"{path}.tmp.{os.getpid()}.{random.randint(0, 1 << 30)}"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def docs_root():
    cfg = load_config()
    candidate = os.path.abspath(os.path.join(project_dir(), cfg.get("docsDir") or "docs"))
    if os.path.isdir(candidate):
        return candidate
    return project_dir()


def safe_join(base, rel):
    """Join rel onto base and confine via realpath, so symlinks can't escape."""
    rel = (rel or "").lstrip("/")
    base_real = os.path.realpath(base)
    target = os.path.realpath(os.path.join(base_real, rel))
    if target != base_real and not target.startswith(base_real + os.sep):
        raise ValueError("path escapes base")
    return target


def gen_id():
    return f"cmt_{int(time.time() * 1000)}_{random.randint(0x1000, 0xffff):04x}"


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


# --------------------------------------------------------------------------- #
# Folder browser (for the in-app folder picker)
# --------------------------------------------------------------------------- #
def list_dirs(path):
    base = os.path.realpath(os.path.expanduser(path or HOME))
    if not within_home(base) or not os.path.isdir(base):
        base = HOME
    dirs = []
    try:
        for name in sorted(os.listdir(base), key=str.lower):
            if name.startswith("."):
                continue
            full = os.path.join(base, name)
            if os.path.isdir(full) and not os.path.islink(full):
                dirs.append(name)
    except PermissionError:
        pass
    parent = os.path.dirname(base) if base != HOME else None
    if parent and not within_home(parent):
        parent = None
    return {"path": base, "parent": parent, "home": HOME, "dirs": dirs}


# --------------------------------------------------------------------------- #
# Documents
# --------------------------------------------------------------------------- #
def list_documents():
    root = docs_root()
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ("node_modules", "exports")]
        for name in filenames:
            if not name.lower().endswith((".md", ".markdown")):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            out.append({"path": rel, "title": doc_title(full, rel), "mtime": os.path.getmtime(full)})
    out.sort(key=lambda d: d["path"].lower())
    return out


def doc_title(full, rel):
    try:
        with open(full, "r", encoding="utf-8") as fh:
            for _ in range(40):
                line = fh.readline()
                if not line:
                    break
                m = re.match(r"^#\s+(.+)", line.strip())
                if m:
                    return m.group(1).strip()
    except Exception:
        pass
    return os.path.splitext(os.path.basename(rel))[0]


def read_doc(rel):
    full = safe_join(docs_root(), rel)
    with open(full, "r", encoding="utf-8") as fh:
        return fh.read()


def list_media():
    """All image files in the project (figures), even ones not referenced inline."""
    root = docs_root()
    out = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if not d.startswith(".") and d not in ("node_modules", "exports")]
        for n in fns:
            if os.path.splitext(n)[1].lower() in IMAGE_EXTS:
                out.append(os.path.relpath(os.path.join(dp, n), root).replace(os.sep, "/"))
        if len(out) > 500:
            break
    out.sort()
    return out[:500]


def write_doc(rel, content):
    """Save the document straight back to its Markdown source (the .docx source)."""
    full = safe_join(docs_root(), rel)
    if not full.lower().endswith((".md", ".markdown")):
        raise ValueError("can only edit Markdown documents")
    atomic_write(full, content)
    return os.path.getmtime(full)


# --------------------------------------------------------------------------- #
# Bibliography (lightweight .bib parse, for clickable preview citations)
# --------------------------------------------------------------------------- #
def find_bib():
    # an explicit path set in Setup wins, if it still exists
    explicit = (load_config().get("bibPath") or "").strip()
    if explicit and os.path.isfile(explicit) and explicit.lower().endswith(".bib"):
        return explicit
    for base in (docs_root(), project_dir()):
        for name in (sorted(os.listdir(base)) if os.path.isdir(base) else []):
            if name.lower().endswith(".bib"):
                return os.path.join(base, name)
    return None


def find_csl():
    for base in (docs_root(), project_dir()):
        for name in (sorted(os.listdir(base)) if os.path.isdir(base) else []):
            if name.lower().endswith(".csl"):
                return os.path.join(base, name)
    return None


def parse_bib():
    path = find_bib()
    if not path:
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except Exception:
        return []
    refs = []
    for m in re.finditer(r"@\w+\s*\{\s*([^,\s]+)\s*,(.*?)\n\}", text, re.S):
        key = m.group(1).strip()
        body = m.group(2)
        fields = {}
        for fm in re.finditer(r"(\w+)\s*=\s*[\{\"](.*?)[\}\"]\s*,?\s*\n", body + "\n", re.S):
            fields[fm.group(1).lower()] = re.sub(r"\s+", " ", fm.group(2)).strip()
        author = fields.get("author", "")
        first_author = author.split(" and ")[0].split(",")[0].strip() if author else ""
        year = fields.get("year", "")
        label = f"{first_author} {year}".strip() or key
        doi = fields.get("doi", "")
        url = fields.get("url", "")
        if not url:
            # `howpublished` sometimes carries the link (e.g. {\url{http://...}})
            howpub = fields.get("howpublished", "")
            hm = re.search(r"https?://\S+", howpub)
            if hm:
                url = hm.group(0).rstrip("}").rstrip()
        if doi:
            clean = re.sub(r"^(https?://doi\.org/|http://dx\.doi\.org/|doi:)", "", doi, flags=re.I).strip()
            link = "https://doi.org/" + clean
        elif url:
            link = url
        else:
            link = ""
        refs.append({
            "key": key, "label": label, "author": author, "year": year,
            "title": fields.get("title", ""),
            "journal": fields.get("journal", fields.get("booktitle", "")),
            "doi": doi, "url": url, "link": link,
        })
    return refs


def _bib_citekey(bibtex):
    """Return the citekey (token after the opening brace, before the first comma)."""
    m = re.search(r"@\w+\s*\{\s*([^,\s{}]+)", bibtex or "")
    return m.group(1).strip() if m else ""


def _entry_span(text, key):
    """Locate the [start, end) span of the @type{key, ... } block in text.

    Finds "@...{KEY," at a line start, then brace-matches from the entry's
    opening "{" to its matching "}". Returns None if not found.
    """
    pat = re.compile(r"@\w+\s*\{\s*" + re.escape(key) + r"\s*,", re.S)
    for m in pat.finditer(text):
        # Confirm the citekey matches exactly (token before first comma).
        if _bib_citekey(text[m.start():m.start() + (m.end() - m.start())]) != key:
            continue
        brace = text.find("{", m.start())
        if brace < 0:
            continue
        depth = 0
        i = brace
        while i < len(text):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return (m.start(), i + 1)
            i += 1
    return None


def get_bib_entry(key):
    """Return the verbatim "@type{KEY, ... }" block from the active .bib, or ""."""
    path = find_bib()
    if not path:
        return ""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except Exception:
        return ""
    span = _entry_span(text, key)
    if not span:
        return ""
    return text[span[0]:span[1]]


def save_bib_entry(key, bibtex):
    """Validate and persist a raw BibTeX entry in the active .bib.

    Replaces the existing entry whose citekey == key; appends if absent.
    Returns the citekey parsed from the saved bibtex.
    """
    bibtex = bibtex or ""
    stripped = bibtex.lstrip()
    citekey = _bib_citekey(bibtex)
    if not stripped or not stripped.startswith("@") or not citekey:
        raise ValueError("invalid BibTeX entry")
    path = find_bib()
    if not path:
        raise ValueError("no references.bib in this project")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except Exception:
        text = ""
    span = _entry_span(text, key)
    if span:
        new_text = text[:span[0]] + bibtex + text[span[1]:]
    else:
        sep = "" if (not text or text.endswith("\n\n")) else ("\n" if text.endswith("\n") else "\n\n")
        new_text = text + sep + "\n" + bibtex if text else bibtex
    atomic_write(path, new_text)
    return citekey


# --------------------------------------------------------------------------- #
# Comments  (one JSON file per comment -> UI and Claude never clobber)
# --------------------------------------------------------------------------- #
def list_comments():
    out = []
    cdir = comments_dir()
    if not os.path.isdir(cdir):
        return out
    for name in os.listdir(cdir):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(cdir, name), "r", encoding="utf-8") as fh:
                out.append(json.load(fh))
        except Exception:
            continue
    out.sort(key=lambda c: c.get("createdAt", ""))
    return out


def write_comment(comment):
    path = os.path.join(comments_dir(), f"{comment['id']}.json")
    atomic_write(path, json.dumps(comment, indent=2))
    return comment


def create_comment(data):
    comment = {
        "id": gen_id(),
        "file": data.get("file", ""),
        "quote": data.get("quote", ""),
        "prefix": data.get("prefix", ""),
        "suffix": data.get("suffix", ""),
        "body": data.get("body", ""),
        "status": "open",
        "author": "user",
        "acknowledged": False,
        "createdAt": now_iso(),
        "thread": [],
        "revision": None,
    }
    return write_comment(comment)


def update_comment(cid, action, payload):
    path = os.path.join(comments_dir(), f"{cid}.json")
    if action == "delete":
        if os.path.exists(path):
            os.remove(path)
        return {"ok": True}
    if not os.path.exists(path):
        raise FileNotFoundError(cid)
    with open(path, "r", encoding="utf-8") as fh:
        c = json.load(fh)
    if action == "resolve":
        c["status"] = "resolved"
    elif action == "reopen" or action == "send":
        c["status"] = "open"           # "send" passes an imported/external comment to Claude
        c["acknowledged"] = False
    elif action == "wontfix":
        c["status"] = "wontfix"
    elif action == "ack" or action == "accept":
        c["acknowledged"] = True       # user accepted/dismissed the inline suggestion
    elif action == "reject":
        c["acknowledged"] = True
        c.setdefault("thread", []).append(
            {"author": "user", "text": "Rejected this change; reverted to the original text.", "at": now_iso()}
        )
    elif action == "edit":
        c["body"] = payload.get("body", c["body"])
    elif action == "reply":
        c.setdefault("thread", []).append(
            {"author": "user", "text": payload.get("text", ""), "at": now_iso()}
        )
        c["status"] = "open"
        c["acknowledged"] = False
    return write_comment(c)


# --------------------------------------------------------------------------- #
# Export (Markdown -> .docx via pandoc, with linked citations)
# --------------------------------------------------------------------------- #
def export_docx(rel):
    pandoc = shutil.which("pandoc")
    if not pandoc:
        return {"ok": False, "error": "pandoc is not installed. The Docker image includes it; "
                                       "or `brew install pandoc`."}
    cfg = load_config()
    src = safe_join(docs_root(), rel)
    src_dir = os.path.dirname(src)
    base = os.path.splitext(os.path.basename(rel))[0]
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")   # DATETIME postscript so exports are versioned, never overwritten
    out_name = f"{base}_{stamp}.docx"
    out = os.path.join(exports_dir(), out_name)
    # turn the <!-- pagebreak --> token into a real .docx page break via a raw openxml block
    pandoc_src = src
    try:
        with open(src, "r", encoding="utf-8") as fh:
            text = fh.read()
        if "<!-- pagebreak -->" in text:
            pb = "```{=openxml}\n<w:p><w:r><w:br w:type=\"page\"/></w:r></w:p>\n```"
            text = re.sub(r"<!--\s*pagebreak\s*-->", pb, text)
            ensure_dirs()
            pandoc_src = os.path.join(data_dir(), f"_export_{base}.md")
            atomic_write(pandoc_src, text)
    except Exception:
        pandoc_src = src
    cmd = [pandoc, pandoc_src, "-o", out, "--standalone",
           "--resource-path", src_dir + os.pathsep + docs_root()]
    # reference-doc precedence: a custom template you point Setup at wins; otherwise the
    # bundled academic template (Times New Roman / Arial 12pt) chosen in Setup
    font = cfg.get("exportFont")
    custom = (cfg.get("exportTemplate") or "").strip()
    used_template = None
    if custom and os.path.isfile(custom) and custom.lower().endswith((".docx", ".dotx")):
        cmd += ["--reference-doc", custom]
        used_template = os.path.basename(custom)
    elif font in DOCX_FONTS:
        ref = os.path.join(TEMPLATES_DIR, DOCX_FONTS[font])
        if os.path.isfile(ref):
            cmd += ["--reference-doc", ref]
            used_template = DOCX_FONTS[font]
    bib = find_bib()
    used_csl = None
    if bib:
        cmd += ["--citeproc", "--bibliography", bib]
        chosen = cfg.get("cslStyle")
        csl = resolve_style(chosen) if chosen else None
        if not (csl and os.path.isfile(csl)):
            csl = find_csl()
        if csl and os.path.isfile(csl):
            cmd += ["--csl", csl]
            used_csl = os.path.basename(csl)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    if proc.returncode != 0:
        return {"ok": False, "error": proc.stderr or "pandoc failed"}
    if sys.platform == "darwin":                      # preview in Word automatically
        try: subprocess.Popen(["open", out])
        except Exception: pass
    return {"ok": True, "download": "/api/download?path=" + urllib.parse.quote(out_name),
            "file": out_name, "withCitations": bool(bib), "style": used_csl,
            "font": font or "default", "template": used_template}


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    server_version = "WicrosoftMord/1.0"

    def log_message(self, *_):
        pass

    def _send(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _body_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def _query(self):
        return urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

    def _host_ok(self):
        if HOST == "0.0.0.0":
            return True   # broad bind is an explicit opt-in (Docker); skip the guard
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in LOCAL_HOSTS or host == HOST   # blocks DNS-rebinding

    def _origin_ok(self):
        origin = self.headers.get("Origin")
        if not origin:
            return True
        return (urllib.parse.urlparse(origin).hostname or "") in LOCAL_HOSTS   # blocks cross-site POST

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if not self._host_ok():
            return self._send(403, {"error": "forbidden host"})
        try:
            if path == "/api/state":
                return self._send(200, {
                    "config": load_config(),
                    "documents": list_documents(),
                    "media": list_media(),
                    "comments": list_comments(),
                    "references": parse_bib(),
                    "pandoc": bool(shutil.which("pandoc")),
                    "project": project_dir(),
                    "instructions": load_instructions(),
                    "styles": list_styles(),
                    "activity": load_activity(),
                })
            if path == "/api/project":
                return self._send(200, {"project": project_dir()})
            if path == "/api/fs/list":
                return self._send(200, list_dirs((self._query().get("path") or [HOME])[0]))
            if path == "/api/doc":
                rel = (self._query().get("path") or [""])[0]
                full = safe_join(docs_root(), rel)
                return self._send(200, {"path": rel, "content": read_doc(rel), "mtime": os.path.getmtime(full)})
            if path == "/api/ref":
                key = (self._query().get("key") or [""])[0]
                return self._send(200, {"ok": True, "key": key, "bibtex": get_bib_entry(key)})
            if path == "/api/uistate":
                return self._send(200, load_uistate())
            if path == "/api/media":
                return self._serve_media((self._query().get("path") or [""])[0])
            if path == "/api/download":
                return self._serve_download((self._query().get("path") or [""])[0])
            return self._serve_static(path)
        except FileNotFoundError:
            return self._send(404, {"error": "not found"})
        except ValueError as exc:
            return self._send(400, {"error": str(exc)})
        except Exception:
            return self._send(500, {"error": "internal error"})

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if not self._host_ok() or not self._origin_ok():
            return self._send(403, {"error": "forbidden origin"})
        try:
            with _lock:
                if path == "/api/project/set":
                    return self._send(200, {"ok": True, "project": set_project(self._body_json().get("path", ""))})
                if path == "/api/settings":
                    return self._send(200, save_settings(self._body_json()))
                if path == "/api/comments":
                    return self._send(200, create_comment(self._body_json()))
                m = re.match(r"^/api/comments/([\w]+)$", path)
                if m:
                    data = self._body_json()
                    return self._send(200, update_comment(m.group(1), data.get("action", ""), data))
                if path == "/api/export":
                    return self._send(200, export_docx(self._body_json().get("path", "")))
                if path == "/api/doc/save":
                    data = self._body_json()
                    return self._send(200, {"ok": True, "mtime": write_doc(data.get("path", ""), data.get("content", ""))})
                if path == "/api/ref":
                    data = self._body_json()
                    saved_key = save_bib_entry(data.get("key", ""), data.get("bibtex", ""))
                    return self._send(200, {"ok": True, "key": saved_key})
                if path == "/api/uistate":
                    return self._send(200, save_uistate(self._body_json()))
                if path == "/api/reveal":
                    if sys.platform == "darwin":
                        try: subprocess.Popen(["open", project_dir()])
                        except Exception: pass
                    return self._send(200, {"ok": True, "path": project_dir()})
                if path == "/api/styles/add":
                    return self._send(200, add_style(self._body_json().get("path", "")))
                if path == "/api/import":
                    return self._send(200, self._import_docx(self._body_json().get("path", "")))
            return self._send(404, {"error": "unknown endpoint"})
        except FileNotFoundError:
            return self._send(404, {"error": "not found"})
        except ValueError as exc:
            return self._send(400, {"error": str(exc)})
        except Exception:
            return self._send(500, {"error": "internal error"})

    def _import_docx(self, path):
        expanded = os.path.expanduser(path or "")
        if os.path.islink(expanded):
            raise ValueError("symlinks are not allowed")
        src = os.path.realpath(expanded)
        if not within_home(src):
            raise ValueError("choose a .docx inside your home directory")
        if not src.lower().endswith(".docx") or not os.path.isfile(src):
            raise ValueError("not a .docx file")
        try:
            from docx_import import import_docx
        except Exception as exc:
            return {"ok": False, "error": "docx import module unavailable: " + str(exc)}
        return import_docx(src, docs_root(), comments_dir())

    def _serve_static(self, path):
        if path in ("/", ""):
            path = "/index.html"
        full = safe_join(WEB_DIR, path.lstrip("/"))
        if not os.path.isfile(full):
            return self._send(404, {"error": "not found"})
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as fh:
            data = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _serve_media(self, rel):
        ext = os.path.splitext(rel)[1].lower()
        if ext not in IMAGE_EXTS:
            return self._send(403, {"error": "unsupported media type"})
        full = safe_join(docs_root(), rel)
        if not os.path.isfile(full):
            return self._send(404, {"error": "not found"})
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as fh:
            data = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _serve_download(self, rel):
        full = safe_join(exports_dir(), rel)
        if not os.path.isfile(full):
            return self._send(404, {"error": "not found"})
        with open(full, "rb") as fh:
            data = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(rel)}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)


def main():
    global PORT
    # one port per project: the project's open script pins --project and --port.
    proj, args, i = None, sys.argv[1:], 0
    while i < len(args):
        if args[i] in ("--project", "-p") and i + 1 < len(args):
            proj = args[i + 1]; i += 2; continue
        if args[i] == "--port" and i + 1 < len(args):
            try: PORT = int(args[i + 1])
            except ValueError: pass
            i += 2; continue
        i += 1
    if proj and os.path.isdir(proj):
        _active["project"] = os.path.abspath(proj)   # pin THIS process to this project (don't clobber shared state)
        ensure_dirs()
    else:
        init_active()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"WicrosoftMord running on http://localhost:{PORT}")
    print(f"  project : {project_dir()}")
    print(f"  docs    : {docs_root()}")
    print(f"  pandoc  : {'yes' if shutil.which('pandoc') else 'no (docx export disabled)'}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
