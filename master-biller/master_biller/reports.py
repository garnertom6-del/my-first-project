"""
AGENT 5 - Reporter. Writes:
  output/<date>/Providers/<Provider>_Billing_Report.pdf   one per provider (send to the provider)
  output/<date>/Master_Biller_Overview.pdf                 all providers on one page (for you)
  output/<date>/Rebill_Worklist.xlsx                       every line to rebill, with tracking columns
"""
import os, re
from collections import defaultdict
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
                                KeepTogether, ListFlowable, ListItem)

NAVY = colors.HexColor("#1f3a5f"); BLUE = colors.HexColor("#2e6da4"); LT = colors.HexColor("#eaf1f8")
RED = colors.HexColor("#b3261e"); GREEN = colors.HexColor("#1e7d34"); AMBER = colors.HexColor("#9a6700")
GREY = colors.HexColor("#666666"); LINEG = colors.HexColor("#cdd6e0")
ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=ss["Title"], textColor=NAVY, fontSize=19, alignment=TA_LEFT, fontName="Helvetica-Bold", spaceAfter=2)
SUB = ParagraphStyle("SUB", parent=ss["Normal"], textColor=GREY, fontSize=10.5)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], textColor=NAVY, fontSize=12.5, fontName="Helvetica-Bold", spaceBefore=12, spaceAfter=5)
BODY = ParagraphStyle("BODY", parent=ss["Normal"], fontSize=9.4, leading=12.5)
SMALL = ParagraphStyle("SMALL", parent=ss["Normal"], fontSize=8.2, textColor=GREY, leading=10.5)
CELL = ParagraphStyle("CELL", parent=ss["Normal"], fontSize=8.2, leading=10)
STEP = ParagraphStyle("STEP", parent=ss["Normal"], fontSize=8.5, leading=11)


def m(x): return "${:,.2f}".format(x or 0)
def d(x): return x.strftime("%m/%d/%Y") if x else ""
def safe(s): return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")
def W(c, st=None): return Paragraph(str(c), st or CELL)


def grid(data, widths, head=BLUE, money_cols=()):
    t = Table(data, colWidths=widths, repeatRows=1)
    style = [("BACKGROUND", (0, 0), (-1, 0), head), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
             ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8.3),
             ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LT]),
             ("GRID", (0, 0), (-1, -1), 0.4, LINEG), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    for c in money_cols:
        style.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    t.setStyle(TableStyle(style))
    return t


def banner(cells, width):
    """cells = [(label, value, color)]"""
    n = len(cells)
    white = lambda t, sz, b: Paragraph(t, ParagraphStyle("w", parent=ss["Normal"], textColor=colors.white, fontSize=sz,
                                                          fontName="Helvetica-Bold" if b else "Helvetica", alignment=1, leading=sz + 3))
    t = Table([[white(c[0], 8.2, True) for c in cells], [white(c[1], 15, True) for c in cells]], colWidths=[width / n] * n)
    st = [("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
          ("LINEAFTER", (0, 0), (-2, -1), 2, colors.white)]
    for i, c in enumerate(cells):
        st.append(("BACKGROUND", (i, 0), (i, -1), c[2]))
    t.setStyle(TableStyle(st))
    return t


def provider_numbers(lines, work, no_resp):
    paid = sum(r.get("paid", 0) for r in lines if r["outcome"] == "Paid")
    reb = sum(r.get("charge", 0) for r in work if r["action"] in ("FIX", "VERIFY"))
    rev = sum(r.get("charge", 0) for r in work if r["action"] == "REVIEW")
    nr = sum(b.get("charge", 0) for b in no_resp)
    return paid, reb, rev, nr


def provider_pdf(path, provider, period_label, lines, work, no_resp, payments, plb, lost):
    doc = SimpleDocTemplate(path, pagesize=letter, leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                            topMargin=0.55 * inch, bottomMargin=0.55 * inch, title="%s billing report" % provider)
    Wd = 7.3 * inch
    paid, reb, rev, nr = provider_numbers(lines, work, no_resp)
    st = [Paragraph(provider, H1), Paragraph("Billing, Remittance &amp; Rebill Report &mdash; " + period_label, SUB),
          Paragraph("Prepared %s by your billing team &bull; CONFIDENTIAL &mdash; contains PHI" % datetime.today().strftime("%B %d, %Y"), SMALL),
          Spacer(1, 4), HRFlowable(width="100%", thickness=2, color=NAVY, spaceAfter=9),
          banner([("PAID", m(paid), GREEN), ("CAN BE REBILLED", m(reb), BLUE),
                  ("NEEDS REVIEW / APPEAL", m(rev), AMBER), ("BILLED - NO ANSWER YET", m(nr), RED)], Wd)]

    # 1. by payer
    st.append(Paragraph("1. Billing summary by payer", H2))
    byp = defaultdict(lambda: dict(n=0, chg=0.0, paid=0.0, den=0, pend=0, reb=0.0))
    for r in lines:
        b = byp[r["payer"]]; b["n"] += 1; b["chg"] += r.get("charge", 0)
        if r["outcome"] == "Paid": b["paid"] += r.get("paid", 0)
        if r["outcome"] == "Denied": b["den"] += 1
        if r["outcome"] == "Pending": b["pend"] += 1
    for r in work:
        if r["action"] in ("FIX", "VERIFY"): byp[r["payer"]]["reb"] += r.get("charge", 0)
    data = [["Payer", "Lines", "Charged", "Paid", "Denied", "Pending", "Rebillable $"]]
    for p in sorted(byp):
        b = byp[p]
        data.append([W(p), b["n"], m(b["chg"]), m(b["paid"]), b["den"], b["pend"], m(b["reb"])])
    tot = lambda k: sum(b[k] for b in byp.values())
    data.append(["TOTAL", tot("n"), m(tot("chg")), m(tot("paid")), tot("den"), tot("pend"), m(tot("reb"))])
    t = grid(data, [2.2 * inch, 0.55 * inch, 1.0 * inch, 1.0 * inch, 0.65 * inch, 0.7 * inch, 1.2 * inch], NAVY, (2, 3, 6))
    t.setStyle(TableStyle([("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"), ("BACKGROUND", (0, -1), (-1, -1), LT)]))
    st.append(t)

    # 2. remittances
    st.append(Paragraph("2. Payments received (remittance advice)", H2))
    if payments:
        data = [["Payer", "Payment date", "Check / EFT #", "Method", "Amount"]]
        for p in sorted(payments, key=lambda x: (x.get("date") or datetime.min)):
            data.append([W(p["payer"]), d(p.get("date")), p.get("check", ""), {"ACH": "EFT", "CHK": "Check"}.get(p.get("method"), p.get("method", "")), m(p["amount"])])
        st.append(grid(data, [2.4 * inch, 1.1 * inch, 1.7 * inch, 0.8 * inch, 1.3 * inch], BLUE, (4,)))
    else:
        st.append(Paragraph("No 835 remittance files were in the inbox for this provider.", BODY))
    if plb:
        st.append(Spacer(1, 5))
        st.append(Paragraph("<b>Provider-level adjustments</b> (money the payer took back or added outside of a claim &mdash; "
                            "WO = overpayment recovery, L6 = interest, FB = forward balance, 72 = authorized return):", BODY))
        data = [["Payer", "Date", "Check / EFT #", "Code", "Reference", "Amount"]]
        for a in plb:
            data.append([W(a["payer"]), d(a.get("date")), a.get("check", ""), a["code"], W(a.get("ref", "")), m(-a["amount"])])
        st.append(grid(data, [2.0 * inch, 0.9 * inch, 1.4 * inch, 0.6 * inch, 1.3 * inch, 1.1 * inch], RED, (5,)))

    # 3. denial reasons
    st.append(Paragraph("3. Why claims were denied", H2))
    den = [r for r in lines if r["outcome"] == "Denied"]
    if den:
        cat = defaultdict(lambda: [0, 0.0, ""])
        for r in den:
            key = r["category"] + (" (already rebilled & paid)" if r["already_paid"] else "")
            c = cat[key]; c[0] += 1; c[1] += r.get("charge", 0); c[2] = "Done" if r["already_paid"] else r["action"]
        data = [["Denial reason", "Lines", "Amount", "What we do"]]
        word = {"FIX": "Correct & rebill", "VERIFY": "Verify eligibility, then rebill", "REVIEW": "Review / appeal",
                "EXCLUDE": "Do not rebill", "Done": "Nothing - already paid"}
        for k, v in sorted(cat.items(), key=lambda kv: -kv[1][1]):
            data.append([W(k), v[0], m(v[1]), word.get(v[2], v[2])])
        st.append(grid(data, [3.2 * inch, 0.6 * inch, 1.2 * inch, 2.3 * inch], BLUE, (2,)))
    else:
        st.append(Paragraph("No denials. ", BODY))

    # 4. rebill list by client
    st.append(Paragraph("4. Claims to rebill &mdash; by client (oldest deadline first)", H2))
    if work:
        st.append(Paragraph("Only claims that are still unpaid are listed. Anything already rebilled and paid, duplicates and "
                            "contractual adjustments are left out. <b>Rebill by</b> = timely-filing deadline from the date of service.", BODY))
        st.append(Spacer(1, 4))
        byc = defaultdict(list)
        for r in work: byc[r["patient"]].append(r)
        for name in sorted(byc, key=lambda n: (min(x.get("rebill_by") or datetime.max for x in byc[n]), n)):
            rows = sorted(byc[name], key=lambda x: x.get("dos") or datetime.min)
            ident = rows[0].get("member_id") or rows[0].get("client_id") or ""
            head = Table([[Paragraph("<b>%s</b>%s" % (name, "  (ID %s)" % ident if ident else ""), ParagraphStyle("h", parent=CELL, textColor=colors.white, fontSize=9.3)),
                           Paragraph("Total: <b>%s</b> &bull; %d line(s)" % (m(sum(x.get('charge', 0) for x in rows)), len(rows)),
                                     ParagraphStyle("h2", parent=CELL, textColor=colors.white, alignment=2, fontSize=9))]],
                         colWidths=[Wd * 0.62, Wd * 0.38])
            head.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NAVY), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
            data = [["DOS", "Payer", "Service", "Denial reason", "Fix", "Rebill by", "$"]]
            for x in rows:
                data.append([d(x.get("dos")), W(x["payer"]), x.get("svc_code", ""), W(x.get("reason", "")[:120]),
                             W("<b>%s</b><br/>%s" % (x["category"], x["action"])), W("%s<br/>%s" % (d(x.get("rebill_by")), x.get("timely", ""))), m(x.get("charge", 0))])
            st.append(KeepTogether([head, grid(data, [0.75 * inch, 1.2 * inch, 0.6 * inch, 1.95 * inch, 1.05 * inch, 1.0 * inch, 0.75 * inch], BLUE, (6,)), Spacer(1, 6)]))
        st.append(Paragraph("How to fix each type", H2))
        for c in sorted({r["category"] for r in work}):
            steps = next(r["steps"] for r in work if r["category"] == c)
            st.append(Paragraph("<b>%s</b>" % c, ParagraphStyle("c", parent=BODY, textColor=NAVY)))
            st.append(ListFlowable([ListItem(Paragraph(s, STEP), leftIndent=8) for s in steps], bulletType="1", leftIndent=14))
            st.append(Spacer(1, 3))
    else:
        st.append(Paragraph("Nothing to rebill. ", BODY))

    # 5. no response
    st.append(Paragraph("5. Billed but no answer from the payer yet (follow up)", H2))
    if no_resp:
        data = [["Client", "DOS", "Payer", "Service", "Days waiting", "$"]]
        for b in sorted(no_resp, key=lambda x: -x.get("days_waiting", 0)):
            data.append([W(b["patient"]), d(b.get("dos")), W(b.get("payer", "")), b.get("svc_code", ""), b.get("days_waiting", ""), m(b.get("charge", 0))])
        st.append(grid(data, [2.0 * inch, 0.9 * inch, 1.7 * inch, 0.8 * inch, 0.9 * inch, 1.0 * inch], RED, (5,)))
        st.append(Paragraph("Check claim status in the payer portal. If the payer has no record of the claim, resubmit it as a new claim.", SMALL))
    else:
        st.append(Paragraph("Every billed service has a response (or no Notenetic/ShareNote billed export was provided).", BODY))

    # 6. lost clients
    if lost is not None:
        st.append(Paragraph("6. Clients paid last period but not this period (possible lost billing)", H2))
        if lost:
            data = [["Client", "Paid last period", "Check"]]
            for name, amt in lost:
                data.append([W(name), m(amt), W("Was the client seen? Was the note billed? Is the auth still active?")])
            st.append(grid(data, [2.4 * inch, 1.3 * inch, 3.6 * inch], RED, (1,)))
        else:
            st.append(Paragraph("No drop-offs compared to the prior period.", BODY))

    st.append(Spacer(1, 10)); st.append(HRFlowable(width="100%", thickness=0.75, color=LINEG, spaceAfter=6))
    st.append(Paragraph("Paid = money on the remittance (or the approved amount when payment has not posted). "
                        "Rebillable = denials with a clear fix that are not yet paid. Corrected claims use frequency code 7 with the original claim number; "
                        "claims sent to a different payer go as new claims. Deadlines use the timely-filing days set for each payer.", SMALL))
    doc.build(st)
    return dict(paid=paid, reb=reb, rev=rev, nr=nr)


def overview_pdf(path, period_label, per_provider):
    doc = SimpleDocTemplate(path, pagesize=landscape(letter), leftMargin=0.5 * inch, rightMargin=0.5 * inch,
                            topMargin=0.5 * inch, bottomMargin=0.5 * inch, title="Master Biller overview")
    Wd = 10 * inch
    T = lambda k: sum(v[k] for v in per_provider.values())
    st = [Paragraph("Master Biller &mdash; All Providers", H1), Paragraph(period_label, SUB),
          Spacer(1, 4), HRFlowable(width="100%", thickness=2, color=NAVY, spaceAfter=9),
          banner([("PAID", m(T("paid")), GREEN), ("CAN BE REBILLED", m(T("reb")), BLUE),
                  ("NEEDS REVIEW", m(T("rev")), AMBER), ("NO ANSWER YET", m(T("nr")), RED)], Wd),
          Paragraph("By provider", H2)]
    data = [["Provider", "Payers", "Lines", "Paid", "Denied lines", "Rebillable $", "Review $", "No answer $", "Top denial reason"]]
    for p, v in sorted(per_provider.items()):
        data.append([W(p), W(", ".join(v["payers"])), v["lines"], m(v["paid"]), v["denied"], m(v["reb"]), m(v["rev"]), m(v["nr"]), W(v["top"])])
    st.append(grid(data, [1.7 * inch, 2.0 * inch, 0.55 * inch, 1.0 * inch, 0.8 * inch, 1.0 * inch, 0.9 * inch, 0.9 * inch, 1.15 * inch], NAVY, (3, 5, 6, 7)))
    st.append(Spacer(1, 8))
    st.append(Paragraph("Next steps: open Rebill_Worklist.xlsx, work the FIX lines first (oldest deadline first), then VERIFY "
                        "(check NCTracks), then REVIEW. Send each provider their own PDF from the Providers folder by secure email.", BODY))
    doc.build(st)


def worklist_xlsx(path, work, lines, no_resp, payments, plb):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.worksheet.datavalidation import DataValidation
    wb = Workbook()
    hdr_fill = PatternFill("solid", fgColor="1F3A5F"); hdr_font = Font(bold=True, color="FFFFFF")

    def sheet(ws, headers, rows, widths):
        ws.append(headers)
        for c in ws[1]:
            c.fill, c.font, c.alignment = hdr_fill, hdr_font, Alignment(wrap_text=True, vertical="center")
        for r in rows:
            ws.append(r)
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[ws.cell(1, i).column_letter].width = w
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions

    ws = wb.active; ws.title = "Rebill Worklist"
    sheet(ws, ["Provider", "Payer", "Client", "Member/Client ID", "DOS", "Service", "Modifiers", "Units", "Charge $",
               "Original claim #", "Action", "Category", "Denial reason / codes", "Rebill by", "Deadline",
               "How to fix", "WORKED? (Y/N)", "Date resubmitted", "New claim #", "Notes"],
          [[r["provider"], r["payer"], r["patient"], r.get("member_id") or r.get("client_id", ""), r.get("dos"),
            r.get("svc_code", ""), r.get("modifiers", ""), r.get("units", ""), r.get("charge", 0), r.get("payer_claim_no", ""),
            r["action"], r["category"], r.get("reason", ""), r.get("rebill_by"), r.get("timely", ""),
            " ".join("%d) %s" % (i + 1, s) for i, s in enumerate(r["steps"])), "", "", "", ""] for r in work],
          [22, 22, 20, 16, 11, 9, 9, 6, 10, 16, 9, 18, 30, 11, 18, 60, 10, 13, 14, 25])
    dv = DataValidation(type="list", formula1='"Y,N"', allow_blank=True); ws.add_data_validation(dv); dv.add("Q2:Q5000")
    for row in ws.iter_rows(min_row=2):
        row[4].number_format = row[13].number_format = "mm/dd/yyyy"; row[8].number_format = '"$"#,##0.00'
        row[15].alignment = Alignment(wrap_text=True, vertical="top")

    sheet(wb.create_sheet("No Response"), ["Provider", "Payer", "Client", "DOS", "Service", "Charge $", "Days waiting", "Status checked?", "Notes"],
          [[b["provider"], b.get("payer", ""), b["patient"], b.get("dos"), b.get("svc_code", ""), b.get("charge", 0), b.get("days_waiting", ""), "", ""] for b in no_resp],
          [22, 22, 20, 11, 9, 10, 12, 14, 30])
    sheet(wb.create_sheet("Payments"), ["Provider", "Payer", "Date", "Check / EFT #", "Amount", "Type"],
          [[p.get("payee", ""), p["payer"], p.get("date"), p.get("check", ""), p["amount"], "Payment"] for p in payments] +
          [[a["provider"], a["payer"], a.get("date"), a.get("check", ""), -a["amount"], "PLB %s %s" % (a["code"], a.get("ref", ""))] for a in plb],
          [22, 26, 11, 18, 12, 22])
    sheet(wb.create_sheet("All Lines"), ["Provider", "Payer", "Client", "Member/Client ID", "DOS", "Service", "Charge $", "Paid $",
                                         "Outcome", "Category", "Action", "Already paid later?", "Reason / codes", "Claim #", "Paid/processed", "Source file"],
          [[r["provider"], r["payer"], r["patient"], r.get("member_id") or r.get("client_id", ""), r.get("dos"), r.get("svc_code", ""),
            r.get("charge", 0), r.get("paid", 0), r["outcome"], r["category"], r["action"], "Yes" if r["already_paid"] else "",
            r.get("reason", ""), r.get("payer_claim_no", ""), r.get("paid_date"), os.path.basename(r["file"])] for r in lines],
          [22, 22, 20, 16, 11, 9, 10, 10, 11, 18, 9, 10, 30, 16, 12, 28])
    wb.save(path)
