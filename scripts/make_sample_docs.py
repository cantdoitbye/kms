"""Render the markdown sources in scripts/sample_sources into a real PDF and DOCX.

The PDF gets a running header/footer and page numbers on purpose, so the
ingestion pipeline's boilerplate removal has something to do.

    backend/.venv/bin/python scripts/make_sample_docs.py
"""

import html
import re
from pathlib import Path

import pymupdf
from docx import Document
from docx.shared import Pt

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "sample_sources"
OUT = ROOT.parent / "sample_docs"


def md_to_html(md: str) -> str:
    out = []
    for para in re.split(r"\n\s*\n", md.strip()):
        para = para.strip()
        m = re.match(r"^(#{1,6})\s+(.*)$", para)
        if m:
            level = len(m.group(1))
            out.append(f"<h{level}>{html.escape(m.group(2))}</h{level}>")
        else:
            out.append(f"<p>{html.escape(' '.join(para.split()))}</p>")
    return "\n".join(out)


def make_pdf(md_path: Path, pdf_path: Path, header: str) -> None:
    css = """
    body { font-family: sans-serif; font-size: 10.5pt; line-height: 1.45; }
    h1 { font-size: 20pt; margin-bottom: 8pt; }
    h2 { font-size: 14pt; margin-top: 14pt; }
    h3 { font-size: 12pt; margin-top: 10pt; }
    p { margin-bottom: 6pt; text-align: justify; }
    """
    story = pymupdf.Story(html=md_to_html(md_path.read_text()), user_css=css)
    page_rect = pymupdf.paper_rect("a4")
    content_rect = page_rect + (60, 70, -60, -70)
    writer = pymupdf.DocumentWriter(tmp := OUT / ".tmp.pdf")
    more = True
    while more:
        dev = writer.begin_page(page_rect)
        more, _ = story.place(content_rect)
        story.draw(dev)
        writer.end_page()
    writer.close()

    doc = pymupdf.open(tmp)
    n = doc.page_count
    for i, page in enumerate(doc, start=1):
        page.insert_text((60, 40), header, fontsize=8, color=(0.4, 0.4, 0.4))
        page.insert_text((page_rect.width / 2 - 20, page_rect.height - 35), f"Page {i} of {n}",
                         fontsize=8, color=(0.4, 0.4, 0.4))
    doc.save(pdf_path)
    doc.close()
    tmp.unlink()


def make_docx(md_path: Path, docx_path: Path) -> None:
    d = Document()
    d.styles["Normal"].font.size = Pt(11)
    for para in re.split(r"\n\s*\n", md_path.read_text().strip()):
        para = para.strip()
        m = re.match(r"^(#{1,6})\s+(.*)$", para)
        if m:
            level = len(m.group(1))
            d.add_heading(m.group(2), level=0 if level == 1 else level - 1)
        elif " | " in para.split("\n")[0]:
            rows = [r.split(" | ") for r in para.split("\n")]
            t = d.add_table(rows=len(rows), cols=len(rows[0]))
            t.style = "Light Grid Accent 1"
            for r, row in enumerate(rows):
                for c, val in enumerate(row):
                    t.cell(r, c).text = val.strip()
        else:
            d.add_paragraph(" ".join(para.split()))
    d.save(docx_path)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    make_pdf(SRC / "employee_handbook.md", OUT / "northwind_employee_handbook.pdf",
             "Northwind Labs | Employee Handbook v4.2 | Internal")
    make_docx(SRC / "engineering_onboarding.md", OUT / "engineering_onboarding_guide.docx")
    print("Wrote:", *sorted(p.name for p in OUT.iterdir() if p.is_file()), sep="\n  ")
