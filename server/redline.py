#!/usr/bin/env python3
"""
Redline — a portable, file-backed document review surface.

The server never talks to Claude. It only reads/writes plain files inside a
project's `.redline/` directory. Claude (running on the host) reads those same
files, edits the documents, and writes replies back. The browser polls and
live-updates. Filesystem = message bus, so it works across any project.

Stdlib only. Optional: `pandoc` on PATH enables Markdown -> .docx export
(with linked citations via --citeproc).
"""

import json
import os
import re
import shutil
import subprocess
import threading
import time
import random
import mimetypes
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

WEB_DIR = os.environ.get("REDLINE_WEB", os.path.join(ROOT, "web"))
DATA_DIR = os.path.abspath(
    os.environ.get("REDLINE_DATA", os.path.join(os.getcwd(), ".redline"))
)
PROJECT_DIR = os.path.dirname(DATA_DIR)
PORT = int(os.environ.get("REDLINE_PORT", "8787"))
HOST = os.environ.get("REDLINE_HOST", "0.0.0.0")

COMMENTS_DIR = os.path.join(DATA_DIR, "comments")
EXPORTS_DIR = os.path.join(DATA_DIR, "exports")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".tif", ".tiff", ".pdf"}
_lock = threading.Lock()


# --------------------------------------------------------------------------- #
# Storage helpers
# --------------------------------------------------------------------------- #
def ensure_dirs():
    os.makedirs(COMMENTS_DIR, exist_ok=True)
    os.makedirs(EXPORTS_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_PATH):
        atomic_write(CONFIG_PATH, json.dumps(default_config(), indent=2))


def default_config():
    return {"title": os.path.basename(PROJECT_DIR) or "Redline", "docsDir": "docs"}


def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    except Exception:
        cfg = {}
    base = default_config()
    base.update(cfg or {})
    return base


def atomic_write(path, text):
    tmp = f"{path}.tmp.{os.getpid()}.{random.randint(0, 1 << 30)}"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def docs_root():
    cfg = load_config()
    candidate = os.path.abspath(os.path.join(PROJECT_DIR, cfg.get("docsDir") or "docs"))
    if os.path.isdir(candidate):
        return candidate
    return PROJECT_DIR


def safe_join(base, rel):
    """Join rel onto base, refusing to escape base."""
    rel = (rel or "").lstrip("/")
    target = os.path.abspath(os.path.join(base, rel))
    if target != base and not target.startswith(base + os.sep):
        raise ValueError("path escapes base")
    return target


def gen_id():
    return f"cmt_{int(time.time() * 1000)}_{random.randint(0x1000, 0xffff):04x}"


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


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


# --------------------------------------------------------------------------- #
# Bibliography (lightweight .bib parse, for clickable preview citations)
# --------------------------------------------------------------------------- #
def find_bib():
    for base in (docs_root(), PROJECT_DIR):
        for name in sorted(os.listdir(base)) if os.path.isdir(base) else []:
            if name.lower().endswith(".bib"):
                return os.path.join(base, name)
    return None


def find_csl():
    for base in (docs_root(), PROJECT_DIR):
        for name in sorted(os.listdir(base)) if os.path.isdir(base) else []:
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
        refs.append({
            "key": key,
            "label": label,
            "author": author,
            "year": year,
            "title": fields.get("title", ""),
            "journal": fields.get("journal", fields.get("booktitle", "")),
        })
    return refs


# --------------------------------------------------------------------------- #
# Comments  (one JSON file per comment -> UI and Claude never clobber)
# --------------------------------------------------------------------------- #
def list_comments():
    out = []
    if not os.path.isdir(COMMENTS_DIR):
        return out
    for name in os.listdir(COMMENTS_DIR):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(COMMENTS_DIR, name), "r", encoding="utf-8") as fh:
                out.append(json.load(fh))
        except Exception:
            continue
    out.sort(key=lambda c: c.get("createdAt", ""))
    return out


def write_comment(comment):
    path = os.path.join(COMMENTS_DIR, f"{comment['id']}.json")
    atomic_write(path, json.dumps(comment, indent=2))
    return comment


def create_comment(data):
    cid = gen_id()
    comment = {
        "id": cid,
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
    path = os.path.join(COMMENTS_DIR, f"{cid}.json")
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
    elif action == "reopen":
        c["status"] = "open"
        c["acknowledged"] = False
    elif action == "wontfix":
        c["status"] = "wontfix"
    elif action == "ack":
        c["acknowledged"] = True
    elif action == "edit":
        c["body"] = payload.get("body", c["body"])
    elif action == "reply":
        c.setdefault("thread", []).append(
            {"author": "user", "text": payload.get("text", ""), "at": now_iso()}
        )
        # a user reply re-opens the conversation so Claude re-engages next pass
        c["status"] = "open"
        c["acknowledged"] = False
    return write_comment(c)


# --------------------------------------------------------------------------- #
# Export (Markdown -> .docx via pandoc, with linked citations)
# --------------------------------------------------------------------------- #
def export_docx(rel):
    pandoc = shutil.which("pandoc")
    if not pandoc:
        return {"ok": False, "error": "pandoc is not installed in this environment. "
                                       "The Docker image includes it; or `brew install pandoc`."}
    src = safe_join(docs_root(), rel)
    src_dir = os.path.dirname(src)
    base = os.path.splitext(os.path.basename(rel))[0]
    out = os.path.join(EXPORTS_DIR, f"{base}.docx")
    cmd = [pandoc, src, "-o", out, "--standalone",
           "--resource-path", src_dir + os.pathsep + docs_root()]
    bib = find_bib()
    if bib:
        cmd += ["--citeproc", "--bibliography", bib]
        csl = find_csl()
        if csl:
            cmd += ["--csl", csl]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    if proc.returncode != 0:
        return {"ok": False, "error": proc.stderr or "pandoc failed"}
    return {"ok": True, "download": "/api/download?path=" + urllib.parse.quote(f"{base}.docx"),
            "file": f"{base}.docx", "withCitations": bool(bib)}


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    server_version = "Redline/1.0"

    def log_message(self, *args):
        pass

    # -- helpers ----------------------------------------------------------- #
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

    # -- routing ----------------------------------------------------------- #
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == "/api/state":
                return self._send(200, {
                    "config": load_config(),
                    "documents": list_documents(),
                    "comments": list_comments(),
                    "references": parse_bib(),
                    "pandoc": bool(shutil.which("pandoc")),
                    "projectDir": PROJECT_DIR,
                })
            if path == "/api/doc":
                rel = (self._query().get("path") or [""])[0]
                full = safe_join(docs_root(), rel)
                return self._send(200, {"path": rel, "content": read_doc(rel),
                                        "mtime": os.path.getmtime(full)})
            if path == "/api/media":
                return self._serve_media((self._query().get("path") or [""])[0])
            if path == "/api/download":
                return self._serve_download((self._query().get("path") or [""])[0])
            return self._serve_static(path)
        except FileNotFoundError:
            return self._send(404, {"error": "not found"})
        except ValueError as exc:
            return self._send(400, {"error": str(exc)})
        except Exception as exc:
            return self._send(500, {"error": str(exc)})

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            with _lock:
                if path == "/api/comments":
                    return self._send(200, create_comment(self._body_json()))
                m = re.match(r"^/api/comments/([\w]+)$", path)
                if m:
                    data = self._body_json()
                    return self._send(200, update_comment(m.group(1), data.get("action", ""), data))
                if path == "/api/export":
                    return self._send(200, export_docx(self._body_json().get("path", "")))
            return self._send(404, {"error": "unknown endpoint"})
        except FileNotFoundError:
            return self._send(404, {"error": "not found"})
        except ValueError as exc:
            return self._send(400, {"error": str(exc)})
        except Exception as exc:
            return self._send(500, {"error": str(exc)})

    # -- static / media ---------------------------------------------------- #
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
        full = safe_join(EXPORTS_DIR, rel)
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
    ensure_dirs()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Redline running on http://localhost:{PORT}")
    print(f"  project : {PROJECT_DIR}")
    print(f"  docs    : {docs_root()}")
    print(f"  data    : {DATA_DIR}")
    print(f"  pandoc  : {'yes' if shutil.which('pandoc') else 'no (docx export disabled)'}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
