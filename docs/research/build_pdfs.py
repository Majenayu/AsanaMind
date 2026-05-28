"""
Build the AsanMinds research paper and patent specification PDFs
directly from the markdown source, using ReportLab. No pandoc / no
LaTeX needed.

Usage:
    python docs/research/build_pdfs.py

Outputs (next to the .md sources):
    docs/research/research-paper.pdf
    docs/research/patent-application.pdf
    docs/research/research-paper.rtf      (open in Word for editing)
    docs/research/patent-application.rtf  (open in Word for editing)
"""

from __future__ import annotations

import re
from pathlib import Path
from html import escape as html_escape

from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT, TA_CENTER
from reportlab.lib.units import inch, mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle,
    KeepTogether, ListFlowable, ListItem, HRFlowable
)
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

ROOT = Path(__file__).resolve().parent


# ─────────────────────────────────────────────────────────────────
# Markdown → ReportLab Flowables
# ─────────────────────────────────────────────────────────────────
#
# This is intentionally a very small markdown subset — exactly what
# we use in the research-paper.md and patent-application.md files:
#
#   * # / ## / ### / #### headings
#   * paragraphs separated by blank lines
#   * **bold** and *italic*  (also _italic_)
#   * `inline code`
#   * fenced ```code blocks```
#   * - bulleted lists and 1. numbered lists (single-level)
#   * | a | b | c | tables (with --- separator)
#   * --- horizontal rules
#   * YAML front-matter (--- ... ---) at the very top, parsed for
#     title / author / abstract / keywords
#
# Pandoc-fancy syntax (footnotes, math blocks, citations) is rendered
# verbatim — fine for our purposes since we want the source readable.
# ─────────────────────────────────────────────────────────────────

INLINE_BOLD   = re.compile(r"\*\*(.+?)\*\*")
INLINE_ITALIC = re.compile(r"(?<!\*)\*(?!\*)([^*]+?)\*(?!\*)|_(.+?)_")
INLINE_CODE   = re.compile(r"`([^`]+)`")
INLINE_LINK   = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _inline(text: str) -> str:
    """Convert inline markdown to ReportLab mini-HTML."""
    s = html_escape(text, quote=False)
    s = INLINE_LINK.sub(
        lambda m: f'<link href="{m.group(2)}" color="#1B4F8C">{m.group(1)}</link>', s
    )
    s = INLINE_BOLD.sub(r"<b>\1</b>", s)
    # italic — handle *...* and _..._ separately
    s = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<i>\1</i>", s)
    s = re.sub(r"(?<!\w)_([^_\n]+?)_(?!\w)", r"<i>\1</i>", s)
    s = INLINE_CODE.sub(
        r'<font face="Courier" size="9" backColor="#F0EFEA">\1</font>', s
    )
    return s


def parse_front_matter(md: str) -> tuple[dict, str]:
    """Pull a YAML-ish front-matter block off the top, return (meta, body)."""
    meta: dict = {}
    if md.lstrip().startswith("---"):
        # find the closing ---
        rest = md.lstrip()
        end = rest.find("\n---", 4)
        if end > 0:
            block = rest[3:end]
            body = rest[end + 4:].lstrip("\n")
            cur_key = None
            cur_buf: list[str] = []
            for ln in block.splitlines():
                if not ln.strip():
                    continue
                if ln.startswith("  ") or ln.startswith("\t"):
                    cur_buf.append(ln.strip())
                    continue
                if cur_key and cur_buf:
                    meta[cur_key] = "\n".join(cur_buf)
                    cur_buf = []
                if ":" in ln:
                    k, _, v = ln.partition(":")
                    cur_key = k.strip()
                    v = v.strip().strip("\"'")
                    if v == "" or v == "|":
                        cur_buf = []
                    else:
                        meta[cur_key] = v
                        cur_key = None
            if cur_key and cur_buf:
                meta[cur_key] = "\n".join(cur_buf)
            return meta, body
    return meta, md


# ─────────────────────────────────────────────────────────────────
# Block parser
# ─────────────────────────────────────────────────────────────────

def md_to_blocks(md: str) -> list[dict]:
    """Convert markdown to a list of block dicts:
        {kind: 'h1'|'h2'|'h3'|'h4'|'p'|'code'|'ul'|'ol'|'hr'|'table', ...}
    """
    blocks: list[dict] = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i]
        stripped = ln.strip()

        # blank line
        if not stripped:
            i += 1
            continue

        # horizontal rule
        if stripped in ("---", "***", "___"):
            blocks.append({"kind": "hr"})
            i += 1
            continue

        # fenced code
        if stripped.startswith("```"):
            i += 1
            buf: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1  # close fence
            blocks.append({"kind": "code", "text": "\n".join(buf)})
            continue

        # heading
        m = re.match(r"^(#{1,6})\s+(.+?)\s*$", ln)
        if m:
            blocks.append({
                "kind": f"h{len(m.group(1))}",
                "text": m.group(2).rstrip("#").strip(),
            })
            i += 1
            continue

        # blockquote
        if stripped.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                buf.append(lines[i].lstrip().lstrip(">").lstrip())
                i += 1
            blocks.append({"kind": "blockquote", "text": "\n".join(buf)})
            continue

        # tables: a row starting with | followed by a separator row
        if stripped.startswith("|") and i + 1 < len(lines) \
                and re.match(r"^\s*\|?[\s:|-]+\|?\s*$", lines[i + 1]):
            header = [c.strip() for c in stripped.strip("|").split("|")]
            i += 2  # skip separator
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            blocks.append({"kind": "table", "header": header, "rows": rows})
            continue

        # bulleted list
        if re.match(r"^\s*[-*]\s+", ln):
            items: list[str] = []
            while i < len(lines) and re.match(r"^\s*[-*]\s+", lines[i]):
                items.append(re.sub(r"^\s*[-*]\s+", "", lines[i]))
                i += 1
                # continuation lines (indented under a bullet)
                while i < len(lines) and lines[i].startswith("  ") and lines[i].strip():
                    items[-1] += " " + lines[i].strip()
                    i += 1
            blocks.append({"kind": "ul", "items": items})
            continue

        # numbered list
        if re.match(r"^\s*\d+\.\s+", ln):
            items = []
            while i < len(lines) and re.match(r"^\s*\d+\.\s+", lines[i]):
                items.append(re.sub(r"^\s*\d+\.\s+", "", lines[i]))
                i += 1
                while i < len(lines) and lines[i].startswith("   ") and lines[i].strip():
                    items[-1] += " " + lines[i].strip()
                    i += 1
            blocks.append({"kind": "ol", "items": items})
            continue

        # paragraph: gather until blank or heading
        buf = [ln]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(
            r"^(#{1,6}\s|\s*[-*]\s|\s*\d+\.\s|```|>|\|)", lines[i]
        ):
            buf.append(lines[i])
            i += 1
        blocks.append({"kind": "p", "text": " ".join(s.strip() for s in buf)})

    return blocks


# ─────────────────────────────────────────────────────────────────
# Style sheets
# ─────────────────────────────────────────────────────────────────

def _common_styles() -> dict[str, ParagraphStyle]:
    base = ParagraphStyle(
        "BodyBase", fontName="Times-Roman", fontSize=10.5, leading=14,
        alignment=TA_JUSTIFY, spaceBefore=0, spaceAfter=6,
        textColor=colors.HexColor("#14120E"),
    )
    return {
        "Title": ParagraphStyle(
            "Title", parent=base, fontName="Times-Bold", fontSize=18,
            leading=22, alignment=TA_CENTER, spaceAfter=8,
        ),
        "Authors": ParagraphStyle(
            "Authors", parent=base, fontSize=10.5, alignment=TA_CENTER,
            leading=14, spaceAfter=14,
        ),
        "AbstractHead": ParagraphStyle(
            "AbstractHead", parent=base, fontName="Times-Bold",
            fontSize=10.5, leading=13, alignment=TA_LEFT, spaceAfter=2,
            spaceBefore=8,
        ),
        "AbstractBody": ParagraphStyle(
            "AbstractBody", parent=base, fontName="Times-Italic",
            fontSize=9.5, leading=12.5, alignment=TA_JUSTIFY,
            leftIndent=12, rightIndent=12, spaceAfter=10,
        ),
        "H1": ParagraphStyle(
            "H1", parent=base, fontName="Times-Bold", fontSize=12,
            leading=16, alignment=TA_LEFT, spaceBefore=14, spaceAfter=4,
            textColor=colors.HexColor("#0F3D2E"),
        ),
        "H2": ParagraphStyle(
            "H2", parent=base, fontName="Times-Bold", fontSize=11,
            leading=14, alignment=TA_LEFT, spaceBefore=10, spaceAfter=3,
            textColor=colors.HexColor("#1B2D5E"),
        ),
        "H3": ParagraphStyle(
            "H3", parent=base, fontName="Times-BoldItalic", fontSize=10.5,
            leading=13, alignment=TA_LEFT, spaceBefore=8, spaceAfter=2,
        ),
        "H4": ParagraphStyle(
            "H4", parent=base, fontName="Times-Italic", fontSize=10.5,
            leading=13, alignment=TA_LEFT, spaceBefore=6, spaceAfter=2,
        ),
        "Body": base,
        "Code": ParagraphStyle(
            "Code", parent=base, fontName="Courier", fontSize=8.6,
            leading=11, alignment=TA_LEFT, leftIndent=14, rightIndent=14,
            spaceBefore=4, spaceAfter=8, backColor=colors.HexColor("#F4F1E8"),
            borderColor=colors.HexColor("#D4CCB8"), borderWidth=0.5,
            borderPadding=6, textColor=colors.HexColor("#1B2D5E"),
        ),
        "Bullet": ParagraphStyle(
            "Bullet", parent=base, leftIndent=18, bulletIndent=6,
            spaceBefore=0, spaceAfter=4,
        ),
        "Blockquote": ParagraphStyle(
            "BQ", parent=base, fontName="Times-Italic", leftIndent=20,
            rightIndent=20, textColor=colors.HexColor("#4A453B"),
            borderColor=colors.HexColor("#C2552F"), borderWidth=0,
            spaceBefore=8, spaceAfter=10,
        ),
    }


# ─────────────────────────────────────────────────────────────────
# Render helpers
# ─────────────────────────────────────────────────────────────────

def render_blocks(blocks: list[dict], styles: dict) -> list:
    flow: list = []
    for b in blocks:
        k = b["kind"]
        if k == "hr":
            flow.append(Spacer(1, 4))
            flow.append(HRFlowable(
                width="100%", thickness=0.4,
                color=colors.HexColor("#D4CCB8"),
                spaceBefore=4, spaceAfter=8,
            ))
        elif k.startswith("h"):
            level = int(k[1])
            sty = styles.get(f"H{min(level,4)}", styles["H4"])
            flow.append(Paragraph(_inline(b["text"]), sty))
        elif k == "p":
            flow.append(Paragraph(_inline(b["text"]), styles["Body"]))
        elif k == "code":
            # ReportLab Paragraph cannot render multi-line preformatted
            # nicely with <br/>; use Preformatted-style by inserting
            # &nbsp; for spaces and <br/> for newlines.
            txt = (
                html_escape(b["text"], quote=False)
                .replace(" ", "&nbsp;")
                .replace("\n", "<br/>")
            )
            flow.append(Paragraph(txt, styles["Code"]))
        elif k == "blockquote":
            flow.append(Paragraph(_inline(b["text"]), styles["Blockquote"]))
        elif k in ("ul", "ol"):
            items = []
            for it in b["items"]:
                items.append(ListItem(
                    Paragraph(_inline(it), styles["Bullet"]),
                    leftIndent=14,
                ))
            flow.append(ListFlowable(
                items,
                bulletType="bullet" if k == "ul" else "1",
                leftIndent=14, bulletFontName="Times-Roman",
                bulletFontSize=10,
                start="bulletchar" if k == "ul" else "1",
            ))
            flow.append(Spacer(1, 4))
        elif k == "table":
            data = [b["header"]] + b["rows"]
            # Strip inline markdown from cells; keep plain text.
            data = [
                [Paragraph(_inline(c), styles["Body"]) for c in row]
                for row in data
            ]
            tbl = Table(data, repeatRows=1, hAlign="LEFT")
            tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F3D2E")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9.5),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#D4CCB8")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                    [colors.white, colors.HexColor("#F8F6EE")]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D4CCB8")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E0D9C8")),
            ]))
            flow.append(Spacer(1, 4))
            flow.append(tbl)
            flow.append(Spacer(1, 8))
    return flow


# ─────────────────────────────────────────────────────────────────
# Footer
# ─────────────────────────────────────────────────────────────────

def _make_footer(label: str):
    def _draw(c: canvas.Canvas, doc):
        c.saveState()
        c.setFont("Times-Italic", 8.5)
        c.setFillColor(colors.HexColor("#7A7364"))
        c.drawString(doc.leftMargin, 0.5 * inch, label)
        c.drawRightString(doc.pagesize[0] - doc.rightMargin,
                          0.5 * inch, f"Page {doc.page}")
        c.restoreState()
    return _draw


# ─────────────────────────────────────────────────────────────────
# Build research paper PDF
# ─────────────────────────────────────────────────────────────────

def build_research(md_path: Path, pdf_path: Path):
    md_src = md_path.read_text(encoding="utf-8")
    meta, body = parse_front_matter(md_src)

    doc = SimpleDocTemplate(
        str(pdf_path), pagesize=LETTER,
        leftMargin=0.85 * inch, rightMargin=0.85 * inch,
        topMargin=0.9 * inch, bottomMargin=0.9 * inch,
        title=meta.get("title", "AsanMinds Research Paper"),
        author=meta.get("author_flat", "P. G. Ayush Rai"),
    )
    styles = _common_styles()

    flow: list = []

    # Title
    title = (meta.get("title") or "AsanMinds Research Paper").strip("\"'")
    flow.append(Paragraph(title, styles["Title"]))

    # Authors line — flatten if YAML had structured authors
    authors_line = (
        "P. G. Ayush Rai · Vidyavardhaka College of Engineering, Mysuru, India · "
        "<font color=\"#1B4F8C\">pgayushrai@gmail.com</font>"
    )
    flow.append(Paragraph(authors_line, styles["Authors"]))

    # Keywords
    kw = meta.get("keywords", "")
    if kw:
        kw_clean = re.sub(r"\s*-\s*", "", kw).replace("\n", " · ").strip(" ·")
        flow.append(Paragraph(
            f"<b>Index Terms — </b><i>{html_escape(kw_clean)}</i>",
            styles["Body"]
        ))
        flow.append(Spacer(1, 6))

    # Abstract
    abs_text = meta.get("abstract", "")
    if abs_text:
        flow.append(Paragraph("Abstract", styles["AbstractHead"]))
        # Clean up multiline yaml-folded abstract
        abs_clean = " ".join(s.strip() for s in abs_text.splitlines() if s.strip())
        flow.append(Paragraph(_inline(abs_clean), styles["AbstractBody"]))

    flow.append(HRFlowable(
        width="100%", thickness=0.4,
        color=colors.HexColor("#D4CCB8"),
        spaceBefore=2, spaceAfter=10,
    ))

    # Body
    blocks = md_to_blocks(body)
    flow.extend(render_blocks(blocks, styles))

    doc.build(
        flow,
        onFirstPage=_make_footer("AsanMinds — Research Paper · Vidyavardhaka College of Engineering"),
        onLaterPages=_make_footer("AsanMinds — Research Paper · Vidyavardhaka College of Engineering"),
    )
    print(f"  [ok] {pdf_path.name} ({pdf_path.stat().st_size // 1024} KB)")


# ─────────────────────────────────────────────────────────────────
# Build patent PDF
# ─────────────────────────────────────────────────────────────────

def build_patent(md_path: Path, pdf_path: Path):
    md_src = md_path.read_text(encoding="utf-8")
    meta, body = parse_front_matter(md_src)

    doc = SimpleDocTemplate(
        str(pdf_path), pagesize=A4,
        leftMargin=1.0 * inch, rightMargin=0.85 * inch,
        topMargin=1.0 * inch, bottomMargin=1.0 * inch,
        title=meta.get("title", "AsanMinds Patent Application"),
        author=meta.get("applicant_name", "P. G. Ayush Rai"),
    )
    styles = _common_styles()
    # Patent uses 12pt body for legal readability
    styles["Body"].fontSize = 11
    styles["Body"].leading = 15
    styles["H1"].fontSize = 13
    styles["H1"].leading = 16
    styles["H2"].fontSize = 12

    flow: list = []

    # Cover plate
    flow.append(Paragraph("INDIAN PATENT OFFICE", ParagraphStyle(
        "PatentCover", parent=styles["Title"], fontSize=11,
        textColor=colors.HexColor("#7A7364"), spaceAfter=4,
    )))
    flow.append(Paragraph("FORM 2 — COMPLETE SPECIFICATION", ParagraphStyle(
        "PatentCover2", parent=styles["Title"], fontSize=12,
        textColor=colors.HexColor("#7A7364"), spaceAfter=18,
    )))
    flow.append(HRFlowable(
        width="100%", thickness=0.6,
        color=colors.HexColor("#0F3D2E"),
        spaceBefore=2, spaceAfter=14,
    ))

    title = (meta.get("title") or "Patent Specification").strip("\"'")
    flow.append(Paragraph(title, styles["Title"]))
    flow.append(Spacer(1, 14))

    # Applicant block
    info_data = [
        ["Applicant", meta.get("applicant_name", "P. G. Ayush Rai")],
        ["Inventor",  meta.get("inventor_name", "P. G. Ayush Rai")],
        ["Nationality", meta.get("applicant_nationality", "Indian")],
        ["Address",   meta.get("applicant_address", "[Full residential address]")],
        ["Date",      meta.get("date", "2026")],
        ["Jurisdiction", meta.get("jurisdiction", "Indian Patent Office (CGPDTM)")],
    ]
    info_data = [
        [Paragraph(f"<b>{k}</b>", styles["Body"]),
         Paragraph(html_escape(str(v)), styles["Body"])]
        for k, v in info_data
    ]
    info_tbl = Table(info_data, colWidths=[1.3 * inch, 4.5 * inch], hAlign="LEFT")
    info_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#D4CCB8")),
    ]))
    flow.append(info_tbl)
    flow.append(Spacer(1, 12))

    flow.append(HRFlowable(
        width="100%", thickness=0.4,
        color=colors.HexColor("#D4CCB8"),
        spaceBefore=4, spaceAfter=14,
    ))
    flow.append(PageBreak())

    # Body
    blocks = md_to_blocks(body)
    flow.extend(render_blocks(blocks, styles))

    # Sign-off
    flow.append(Spacer(1, 30))
    flow.append(HRFlowable(width="40%", thickness=0.5,
                           color=colors.HexColor("#14120E")))
    flow.append(Paragraph(
        f"<b>Signature of applicant</b> &nbsp;&nbsp;"
        f"{meta.get('applicant_name', 'P. G. Ayush Rai')}",
        styles["Body"],
    ))
    flow.append(Paragraph(
        "Dated this _____ day of __________________, 2026, at Mysuru, India.",
        styles["Body"],
    ))

    doc.build(
        flow,
        onFirstPage=_make_footer(
            f"Patent Specification — {meta.get('applicant_name','Applicant')} · Filed under Patents Act, 1970"
        ),
        onLaterPages=_make_footer(
            f"Patent Specification — {meta.get('applicant_name','Applicant')} · Filed under Patents Act, 1970"
        ),
    )
    print(f"  [ok] {pdf_path.name} ({pdf_path.stat().st_size // 1024} KB)")


# ─────────────────────────────────────────────────────────────────
# RTF export (Word-compatible, lossless for editing)
# ─────────────────────────────────────────────────────────────────

def md_to_rtf(md_path: Path, rtf_path: Path):
    """Cheap-and-cheerful RTF writer — opens in Word, LibreOffice, etc."""
    md_src = md_path.read_text(encoding="utf-8")
    meta, body = parse_front_matter(md_src)
    blocks = md_to_blocks(body)

    def esc(s: str) -> str:
        return (s.replace("\\", "\\\\")
                .replace("{", r"\{")
                .replace("}", r"\}")
                .encode("ascii", "backslashreplace")
                .decode("ascii")
                .replace("\\x", "\\u")    # rough unicode handling
                + "")

    parts: list[str] = [
        r"{\rtf1\ansi\deff0",
        r"{\fonttbl{\f0 Times New Roman;}{\f1 Courier New;}}",
        r"\fs22 ",  # 11pt
    ]
    if meta.get("title"):
        parts.append(rf"\b\fs36 {esc(meta['title'].strip(chr(34)+chr(39)))}\b0\fs22\par\par")
    if meta.get("abstract"):
        parts.append(r"\b Abstract\b0\par ")
        parts.append(esc(" ".join(s.strip() for s in meta['abstract'].splitlines() if s.strip())) + r"\par\par")

    for b in blocks:
        k = b["kind"]
        if k == "hr":
            parts.append(r"\par ----------------------------\par\par")
        elif k.startswith("h") and k != "hr":
            lvl = int(k[1])
            size = {1: 32, 2: 28, 3: 24, 4: 22}.get(lvl, 22)
            parts.append(rf"\b\fs{size} {esc(b['text'])}\b0\fs22\par")
        elif k == "p":
            parts.append(esc(b["text"]) + r"\par\par")
        elif k == "code":
            parts.append(r"\f1\fs20 " + esc(b["text"]).replace("\n", r"\par ") + r"\f0\fs22\par\par")
        elif k == "ul":
            for it in b["items"]:
                parts.append(r"\bullet  " + esc(it) + r"\par")
            parts.append(r"\par")
        elif k == "ol":
            for n, it in enumerate(b["items"], 1):
                parts.append(f"{n}. " + esc(it) + r"\par")
            parts.append(r"\par")
        elif k == "table":
            parts.append(r"\b " + " | ".join(esc(c) for c in b["header"]) + r"\b0\par")
            for row in b["rows"]:
                parts.append(" | ".join(esc(c) for c in row) + r"\par")
            parts.append(r"\par")
        elif k == "blockquote":
            parts.append(r"\i  " + esc(b["text"]) + r"\i0\par\par")

    parts.append("}")
    rtf_path.write_text("\n".join(parts), encoding="ascii", errors="replace")
    print(f"  [ok] {rtf_path.name} ({rtf_path.stat().st_size // 1024} KB)")


# ─────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────

def main():
    print("Building AsanMinds research deliverables…")
    print()
    print("Research paper:")
    build_research(ROOT / "research-paper.md", ROOT / "research-paper.pdf")
    md_to_rtf(ROOT / "research-paper.md", ROOT / "research-paper.rtf")
    print()
    print("Patent specification:")
    build_patent(ROOT / "patent-application.md", ROOT / "patent-application.pdf")
    md_to_rtf(ROOT / "patent-application.md", ROOT / "patent-application.rtf")
    print()
    print("Done. Files are in docs/research/.")


if __name__ == "__main__":
    main()
