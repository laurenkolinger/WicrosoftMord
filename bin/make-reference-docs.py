#!/usr/bin/env python3
"""Generate pandoc "reference docx" templates for academic .docx export.

Produces "very basic, very academic" Word templates: body text 12pt
(w:sz=24, already the pandoc default in docDefaults), a single font family
throughout, headings in the same font at pandoc's default bold/sizes, and
default spacing.

Method
------
1. Start from pandoc's built-in default reference doc:
       pandoc --print-default-data-file reference.docx
2. Read word/styles.xml and replace every THEME font reference with an
   explicit font name, while leaving the code font (Consolas) alone:
       w:asciiTheme="..."    -> w:ascii="<FONT>"
       w:hAnsiTheme="..."    -> w:hAnsi="<FONT>"
       w:cstheme="..."       -> w:cs="<FONT>"
       w:eastAsiaTheme="..." -> w:eastAsia="<FONT>"
   Body size (w:sz w:val="24" in docDefaults) and heading sizes are left
   untouched.
3. Write a new docx zip preserving every original entry, replacing only
   word/styles.xml (ZIP_DEFLATED).

Usage
-----
    make-reference-docs.py                       # regenerate tnr + arial
    make-reference-docs.py "<font>" <out.docx>   # custom font/output
"""

import re
import subprocess
import sys
import zipfile
from pathlib import Path

# Repo root is the parent of bin/ — keep outputs relative to it.
ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = ROOT / "templates"

STYLES_PATH = "word/styles.xml"

# THEME attribute -> explicit attribute name. Order/whitespace tolerant.
THEME_ATTR_MAP = {
    "asciiTheme": "ascii",
    "hAnsiTheme": "hAnsi",
    "cstheme": "cs",
    "eastAsiaTheme": "eastAsia",
}

# Default templates generated when run with no args.
DEFAULT_TARGETS = [
    ("Times New Roman", TEMPLATES_DIR / "reference-tnr.docx"),
    ("Arial", TEMPLATES_DIR / "reference-arial.docx"),
]


def get_default_reference_docx() -> bytes:
    """Return pandoc's built-in default reference.docx as bytes."""
    result = subprocess.run(
        ["pandoc", "--print-default-data-file", "reference.docx"],
        check=True,
        capture_output=True,
    )
    return result.stdout


def replace_theme_fonts(styles_xml: str, font: str) -> str:
    """Replace theme font attrs with explicit font; leave Consolas alone.

    The code font (Consolas) is set via plain w:ascii/w:hAnsi attributes,
    not via *Theme attributes, so rewriting only the *Theme attributes
    leaves it untouched automatically.
    """
    out = styles_xml
    for theme_attr, plain_attr in THEME_ATTR_MAP.items():
        # Match e.g.  w:asciiTheme="majorHAnsi"  ->  w:ascii="<FONT>"
        pattern = re.compile(r'w:' + re.escape(theme_attr) + r'="[^"]*"')
        out = pattern.sub(f'w:{plain_attr}="{font}"', out)
    return out


def build_reference(default_bytes: bytes, font: str, out_path: Path) -> None:
    """Write a reference docx to out_path using `font`, preserving all entries."""
    import io

    src = zipfile.ZipFile(io.BytesIO(default_bytes), "r")

    if STYLES_PATH not in src.namelist():
        raise RuntimeError(f"{STYLES_PATH} not found in default reference.docx")

    styles_xml = src.read(STYLES_PATH).decode("utf-8")
    new_styles = replace_theme_fonts(styles_xml, font).encode("utf-8")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = new_styles if item.filename == STYLES_PATH else src.read(item.filename)
            dst.writestr(item, data)
    src.close()


def main(argv: list[str]) -> int:
    default_bytes = get_default_reference_docx()

    if len(argv) == 0:
        targets = DEFAULT_TARGETS
    elif len(argv) == 2:
        targets = [(argv[0], Path(argv[1]))]
    else:
        print(__doc__)
        print("error: expected no args, or <font name> <output path>", file=sys.stderr)
        return 2

    for font, out_path in targets:
        build_reference(default_bytes, font, out_path)
        print(f"wrote {out_path}  (font: {font})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
