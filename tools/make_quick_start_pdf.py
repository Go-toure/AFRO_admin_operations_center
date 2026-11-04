"""Writes www/WHO_AFRO_Admin_Operations_Center_Quick_Start.pdf from opscenter/guide.py (the same text as the Quick start page).
Needs reportlab (and segno for the QR code); they are not needed to run the app.

    pip install reportlab segno
    python tools/make_quick_start_pdf.py --url https://<address of the app>
Without --url the PDF has no QR code. Run it again whenever opscenter/guide.py changes, and commit the PDF."""
import argparse
import io
import sys
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from opscenter import __version__, guide  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="", help="address of the app, printed as a QR code")
    ap.add_argument("--out", default=str(HERE / "www" / guide.PDF_NAME))
    a = ap.parse_args()
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, KeepTogether, ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    blue, ink, grey = colors.HexColor("#0b3a5a"), colors.HexColor("#1d2b36"), colors.HexColor("#5f6f7c")
    ss = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=ss["BodyText"], fontName="Helvetica", fontSize=9.5, leading=13, textColor=ink)
    h1 = ParagraphStyle("h1", parent=body, fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=blue)
    sub = ParagraphStyle("sub", parent=body, textColor=grey, fontSize=10)
    h2 = ParagraphStyle("h2", parent=body, fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=blue, spaceBefore=10, spaceAfter=4)
    small = ParagraphStyle("s", parent=body, fontSize=8, textColor=grey)

    def items(rows):
        if all(isinstance(r, str) for r in rows):
            rows = [("", r) for r in rows]
        out, li = [], []
        for it in rows:
            if isinstance(it, tuple):
                li.append(ListItem(Paragraph(("<b>%s:</b> %s" % (escape(it[0]), escape(it[1]))) if it[0] else escape(it[1]), body), leftIndent=12))
            else:
                if li:
                    out.append(ListFlowable(li, bulletType="bullet", start="•", leftIndent=12))
                    li = []
                out.append(Paragraph(escape(it), body))
                out.append(Spacer(1, 3))
        if li:
            out.append(ListFlowable(li, bulletType="bullet", start="•", leftIndent=12))
        return out

    logo = HERE / "www" / "who_afro_logo.png"
    head = [[Image(str(logo), width=34 * mm, height=19.1 * mm) if logo.is_file() else "",
             [Paragraph(escape(guide.TITLE), h1), Spacer(1, 3), Paragraph(escape(guide.SUBTITLE), sub)]]]
    t = Table(head, colWidths=[40 * mm, 130 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eef5fa")),
                           ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#dde5ea")), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                           ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    story = [t, Spacer(1, 8), Paragraph("About the Operations Center", h2)]
    story += [Paragraph(escape(x), body) for x in guide.ABOUT]
    story += [Spacer(1, 4), Paragraph("<b>Key objectives</b>", body)]
    story += [ListFlowable([ListItem(Paragraph(escape(o), body), leftIndent=12) for o in guide.OBJECTIVES], bulletType="bullet",
                           start="•", leftIndent=12)]
    if a.url:
        import segno
        buf = io.BytesIO()
        segno.make(a.url, error="m").save(buf, kind="png", scale=6, border=2)
        buf.seek(0)
        qr = Image(buf, width=34 * mm, height=34 * mm)
        story += [Paragraph("Open the Operations Center on a mobile device", h2),
                  Table([[qr, Paragraph(escape(guide.MOBILE) + "<br/><br/>" + escape(a.url), body)]], colWidths=[40 * mm, 130 * mm],
                        style=[("VALIGN", (0, 0), (-1, -1), "MIDDLE")])]
    for heading, rows in guide.SECTIONS:
        story.append(KeepTogether([Paragraph(escape(heading), h2)] + items(rows)[:2]))
        story += items(rows)[2:]
    story += [Paragraph("Technical support", h2), Paragraph(escape(guide.SUPPORT_TEXT) + "<br/>" + escape(guide.SUPPORT_EMAIL), body)]

    def footer(c, d):
        c.saveState()
        c.setFont("Helvetica", 8)
        c.setFillColor(grey)
        c.drawString(18 * mm, 10 * mm, "WHO AFRO GIS Centre  |  Operations Center version %s" % __version__)
        c.drawRightString(A4[0] - 18 * mm, 10 * mm, "Page %d" % d.page)
        c.restoreState()

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(a.out, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
                      title=guide.TITLE + " - Quick Start Guide", author="WHO AFRO GIS Centre").build(story, onFirstPage=footer, onLaterPages=footer)
    print("written:", a.out)


if __name__ == "__main__":
    main()
