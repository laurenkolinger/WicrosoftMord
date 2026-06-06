#!/usr/bin/env python3
"""
Self-contained unit test for docx_import.import_docx.

Synthesizes a minimal-but-valid .docx in /tmp (a zip of the required OOXML
parts) containing:
  * a comment range around the words "coral bleaching" + a comment reference,
  * word/comments.xml with one comment by "Reviewer A" saying "needs a citation",
  * one tracked <w:ins w:author="Reviewer A"> run with inserted text.

Then runs import_docx into fresh /tmp dirs and asserts the Markdown was created,
the Word comment was captured (author/body/quote), and a tracked-change comment
was captured. All I/O is under /tmp; the real project is never touched.

Run:  python3 server/test_docx_import.py
"""

import json
import os
import shutil
import sys
import tempfile
import zipfile

# Import the module under test from this same directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import docx_import  # noqa: E402


CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/comments.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/>
</Types>"""

RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="comments.xml"/>
</Relationships>"""

# document.xml:
#  - one paragraph of normal text with a comment range around "coral bleaching"
#    that spans two runs (to exercise multi-run handling), plus the
#    commentReference marker.
#  - a second paragraph carrying a tracked insertion by Reviewer A.
DOCUMENT_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p>
      <w:r><w:t xml:space="preserve">Recent surveys describe widespread </w:t></w:r>
      <w:commentRangeStart w:id="0"/>
      <w:r><w:t xml:space="preserve">coral </w:t></w:r>
      <w:r><w:t>bleaching</w:t></w:r>
      <w:commentRangeEnd w:id="0"/>
      <w:r><w:commentReference w:id="0"/></w:r>
      <w:r><w:t xml:space="preserve"> across the reef.</w:t></w:r>
    </w:p>
    <w:p>
      <w:r><w:t xml:space="preserve">Thermal stress was the main driver</w:t></w:r>
      <w:ins w:id="5" w:author="Reviewer A" w:date="2026-06-05T12:00:00Z">
        <w:r><w:t xml:space="preserve"> during the 2023 marine heatwave</w:t></w:r>
      </w:ins>
      <w:r><w:t>.</w:t></w:r>
    </w:p>
  </w:body>
</w:document>"""

COMMENTS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:comment w:id="0" w:author="Reviewer A" w:date="2026-06-05T12:00:00Z" w:initials="RA">
    <w:p>
      <w:r><w:t xml:space="preserve">This claim </w:t></w:r>
      <w:r><w:t>needs a citation</w:t></w:r>
      <w:r><w:t>.</w:t></w:r>
    </w:p>
  </w:comment>
</w:comments>"""


def build_docx(path):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES)
        zf.writestr("_rels/.rels", RELS)
        zf.writestr("word/_rels/document.xml.rels", DOC_RELS)
        zf.writestr("word/document.xml", DOCUMENT_XML)
        zf.writestr("word/comments.xml", COMMENTS_XML)


def main():
    work = tempfile.mkdtemp(prefix="wmord_docx_test_")
    try:
        docx_path = os.path.join(work, "Coral Bleaching Review.docx")
        docs_root = os.path.join(work, "docs")
        comments_dir = os.path.join(work, "comments")
        build_docx(docx_path)

        result = docx_import.import_docx(docx_path, docs_root, comments_dir)
        print("import_docx ->", json.dumps(result))

        # --- assert: result shape ---
        assert result["ok"] is True, "result not ok"
        md_name = result["file"]
        assert md_name == "Coral_Bleaching_Review.md", (
            "unexpected sanitized name: %r" % md_name
        )

        # --- assert: markdown created and non-empty ---
        md_path = os.path.join(docs_root, md_name)
        assert os.path.isfile(md_path), "markdown file not created"
        md_text = open(md_path, encoding="utf-8").read()
        assert md_text.strip(), "markdown file is empty"

        # --- load all written comments ---
        records = []
        for n in sorted(os.listdir(comments_dir)):
            if n.endswith(".json"):
                records.append(json.load(open(os.path.join(comments_dir, n), encoding="utf-8")))

        docx_comments = [c for c in records if c.get("source") == "docx"]
        docx_changes = [c for c in records if c.get("source") == "docx-change"]

        # --- assert: exactly one Word comment, captured correctly ---
        assert len(docx_comments) == 1, (
            "expected exactly 1 docx comment, got %d" % len(docx_comments)
        )
        c = docx_comments[0]
        assert c["author"] == "Reviewer A", "wrong comment author: %r" % c["author"]
        assert "needs a citation" in c["body"], "comment body missing text: %r" % c["body"]
        assert "coral bleaching" in c["quote"], "quote missing highlighted text: %r" % c["quote"]
        assert c["status"] == "external", "comment status not external"
        assert c["acknowledged"] is False and c["thread"] == [] and c["revision"] is None

        # --- assert: at least one tracked-change comment with the inserted text ---
        assert len(docx_changes) >= 1, "expected >=1 docx-change comment"
        ins = [c for c in docx_changes if c["body"].startswith("Inserted:")]
        assert ins, "no inserted tracked-change comment found"
        assert "2023 marine heatwave" in ins[0]["body"], (
            "inserted text missing from change body: %r" % ins[0]["body"]
        )
        assert ins[0]["author"] == "Reviewer A", "wrong change author: %r" % ins[0]["author"]
        assert "2023 marine heatwave" in ins[0]["quote"], "change quote missing inserted text"

        # counts in the result match what we wrote
        assert result["comments"] == len(docx_comments), "comment count mismatch"
        assert result["changes"] == len(docx_changes), "change count mismatch"

        print("PASS: all assertions passed")
        print("  md_name        =", md_name)
        print("  md_bytes       =", len(md_text))
        print("  docx comments  =", len(docx_comments))
        print("  docx changes   =", len(docx_changes))
        print("  comment.quote  =", repr(c["quote"]))
        print("  comment.author =", repr(c["author"]))
        print("  change.body    =", repr(ins[0]["body"]))
        return 0
    except AssertionError as exc:
        print("FAIL:", exc)
        return 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
