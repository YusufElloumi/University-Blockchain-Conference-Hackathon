"""Render DEVELOPMENT_PLAN.md to docs/development_plan.pdf.

Usage (from the repo root):  python scripts/build_plan_pdf.py
Requires: pip install reportlab

Supports the small Markdown subset the plan uses: headings, paragraphs,
bullets, checkboxes, tables, horizontal rules, **bold**, `code`, [links](url).
"""
import re
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "DEVELOPMENT_PLAN.md"
OUT = ROOT / "docs" / "development_plan.pdf"

INK = colors.HexColor("#1f2933")
MUTED = colors.HexColor("#52606d")
ACCENT = colors.HexColor("#0b6e4f")
RULE = colors.HexColor("#cbd2d9")
HEAD_BG = colors.HexColor("#e6f2ee")
ALT_BG = colors.HexColor("#f7f9fa")

BODY = ParagraphStyle("body", fontName="Helvetica", fontSize=9.5, leading=13.5,
                      textColor=INK, alignment=TA_LEFT, spaceAfter=5)
H1 = ParagraphStyle("h1", parent=BODY, fontName="Helvetica-Bold", fontSize=20,
                    leading=24, textColor=ACCENT, spaceAfter=10)
H2 = ParagraphStyle("h2", parent=BODY, fontName="Helvetica-Bold", fontSize=13.5,
                    leading=17, textColor=ACCENT, spaceBefore=12, spaceAfter=6,
                    keepWithNext=True)
H3 = ParagraphStyle("h3", parent=BODY, fontName="Helvetica-Bold", fontSize=11,
                    leading=14, spaceBefore=8, spaceAfter=4, keepWithNext=True)
BULLET = ParagraphStyle("bullet", parent=BODY, leftIndent=16, firstLineIndent=-16,
                        spaceAfter=3)
SUB = ParagraphStyle("sub", parent=BULLET, leftIndent=32)
CELL = ParagraphStyle("cell", parent=BODY, fontSize=8.5, leading=11, spaceAfter=0)
CELL_HEAD = ParagraphStyle("cellhead", parent=CELL, fontName="Helvetica-Bold")

PAGE_W = letter[0] - 1.5 * inch
BOX = '<font face="Courier" size="9">[ ]</font>&nbsp;'
BOX_DONE = '<font face="Courier" size="9">[x]</font>&nbsp;'


def inline(text: str) -> str:
    """Convert inline Markdown to ReportLab paragraph markup."""
    text = escape(text)
    text = re.sub(r"`([^`]+)`", r'<font face="Courier" size="8.5">\1</font>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)",
                  r'<link href="\2" color="#0b6e4f">\1</link>', text)
    text = re.sub(r"(?<![\"=>])(https?://[^\s<)]+)",
                  r'<link href="\1" color="#0b6e4f">\1</link>', text)
    return text


def split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def build_table(rows: list[list[str]]) -> Table:
    ncols = len(rows[0])
    longest = [max(len(r[i]) if i < len(r) else 0 for r in rows) for i in range(ncols)]
    weights = [min(max(n, 10), 60) for n in longest]
    widths = [PAGE_W * w / sum(weights) for w in weights]
    data = [[Paragraph(inline(c), CELL_HEAD) for c in rows[0]]]
    for r in rows[1:]:
        r = r + [""] * (ncols - len(r))
        data.append([Paragraph(inline(c), CELL) for c in r[:ncols]])
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ALT_BG]),
        ("GRID", (0, 0), (-1, -1), 0.4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def parse(md: str) -> list:
    story, para, lines, i = [], [], md.splitlines(), 0

    def flush():
        if para:
            story.append(Paragraph(inline(" ".join(para)), BODY))
            para.clear()

    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()
        if not stripped:
            flush()
        elif stripped.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = split_row(lines[i])
                if not all(re.fullmatch(r":?-+:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            story += [build_table(rows), Spacer(1, 8)]
            continue
        elif stripped == "---":
            flush()
            story.append(HRFlowable(width="100%", thickness=0.6, color=RULE,
                                    spaceBefore=8, spaceAfter=8))
        elif stripped.startswith("### "):
            flush(); story.append(Paragraph(inline(stripped[4:]), H3))
        elif stripped.startswith("## "):
            flush(); story.append(Paragraph(inline(stripped[3:]), H2))
        elif stripped.startswith("# "):
            flush(); story.append(Paragraph(inline(stripped[2:]), H1))
        elif stripped.startswith("- "):
            flush()
            style = SUB if line.startswith("  ") else BULLET
            body = stripped[2:]
            if body.startswith("[ ] "):
                story.append(Paragraph(BOX + inline(body[4:]), style))
            elif body.lower().startswith("[x] "):
                story.append(Paragraph(BOX_DONE + inline(body[4:]), style))
            else:
                story.append(Paragraph("&bull;&nbsp;&nbsp;" + inline(body), style))
        else:
            para.append(stripped)
        i += 1
    flush()
    return story


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(0.75 * inch, 0.5 * inch,
                      "Loser Buys development plan - UBC 2026 Hackathon - devnet only")
    canvas.drawRightString(letter[0] - 0.75 * inch, 0.5 * inch, f"Page {doc.page}")
    canvas.restoreState()


def main():
    doc = SimpleDocTemplate(
        str(OUT), pagesize=letter, title="Loser Buys Development Plan",
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=0.75 * inch, bottomMargin=0.8 * inch,
    )
    doc.build(parse(SRC.read_text(encoding="utf-8")),
              onFirstPage=footer, onLaterPages=footer)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
