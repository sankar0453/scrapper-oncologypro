"""Renders one PDF from a content item's HTML body. Only ever called on
items confirmed public (see collectors.content.is_public) -- rendering
copyrighted abstract text to a file for the requesting user's own, personal,
non-commercial use (per ESMO's Terms of Use, see the skill's README);
redistribution of the output is on the caller, not this function.
"""
from __future__ import annotations

import re


def _html_to_reportlab(html: str) -> str:
    if not html:
        return ""
    html = re.sub(r"<h[1-4]>(.*?)</h[1-4]>", r"<br/><b>\1</b><br/>", html, flags=re.S)
    html = html.replace("<p>", "").replace("</p>", "<br/><br/>")
    html = re.sub(r"<(?!/?(b|i|sup|sub|br)\b)[^>]*>", "", html)
    return html


def safe_filename(name: str, maxlen: int = 120) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_")
    return name[:maxlen] or "untitled"


def render_pdf_bytes(title: str, citation: str, authors: str, affiliations: str, body_html: str) -> bytes:
    import io

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TitleX", parent=styles["Title"], fontSize=13, leading=16)
    meta_style = ParagraphStyle("Meta", parent=styles["Normal"], fontSize=9, textColor="#555555")
    body_style = ParagraphStyle("Body", parent=styles["Normal"], fontSize=10, leading=14)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm, leftMargin=20 * mm, rightMargin=20 * mm)
    story = [Paragraph(title or "", title_style), Spacer(1, 6)]
    for meta in (citation, authors, affiliations):
        if meta:
            story.append(Paragraph(meta, meta_style))
    story.append(Spacer(1, 10))
    for para in _html_to_reportlab(body_html).split("<br/><br/>"):
        para = para.strip()
        if para:
            try:
                story.append(Paragraph(para, body_style))
                story.append(Spacer(1, 4))
            except Exception:
                pass
    doc.build(story)
    return buf.getvalue()
