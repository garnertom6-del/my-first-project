"""
The five billing agents. Each one has ONE job and hands its result to the next.

  1. Collector      - finds every file in inbox/<Provider>/<Payer>/ and works out what it is
  2. Remit Reader   - reads 835 remittance advice files
  3. Status Reader  - reads claim-status and billed (Notenetic / ShareNote) exports
  4. Rebill Analyst - decides Paid / Denied / Pending, why, and whether it can be rebilled
  5. Reporter       - (reports.py) writes the PDFs and the Excel rebill worklist
"""
import json, os, re
from collections import defaultdict
from datetime import datetime, timedelta

from . import era835, csv_import, denials

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def log(agent, msg):
    print("[%s] %s" % (agent, msg))


def load_payers():
    with open(os.path.join(HERE, "config", "payers.json")) as fh:
        cfg = json.load(fh)
    return cfg["payers"], [n.lower() for n in cfg["billing_systems"]["names"]]


def match_payer(text, payers):
    t = (text or "").lower()
    for p in payers:
        if p["name"].lower() in t or any(a in t for a in p["aliases"]):
            return p
    return None


# ----------------------------------------------------------------- AGENT 1
def collector(inbox):
    payers, billing_systems = load_payers()
    found = []
    if not os.path.isdir(inbox):
        return found, payers
    for provider in sorted(os.listdir(inbox)):
        pdir = os.path.join(inbox, provider)
        if not os.path.isdir(pdir) or provider.startswith("."):
            continue
        for sub in sorted(os.listdir(pdir)):
            sdir = os.path.join(pdir, sub)
            if not os.path.isdir(sdir):
                continue
            is_billed = sub.lower() in billing_systems
            payer = None if is_billed else match_payer(sub, payers)
            for fn in sorted(os.listdir(sdir)):
                path = os.path.join(sdir, fn)
                if fn.startswith((".", "~")) or not os.path.isfile(path):
                    continue
                low = fn.lower()
                if low.endswith((".csv", ".xlsx", ".xlsm")):
                    kind = "billed" if is_billed else "status"
                elif low.endswith((".835", ".txt", ".edi", ".era", ".x12", ".dat")):
                    with open(path, encoding="utf-8", errors="replace") as fh:
                        head = fh.read(200).lstrip("﻿").lstrip()
                    if not head.startswith("ISA") or "835" not in open(path, errors="replace").read(3000):
                        log("Collector", "skipped (not an 835): %s" % path)
                        continue
                    kind = "835"
                else:
                    log("Collector", "skipped (unknown file type): %s" % path)
                    continue
                found.append(dict(path=path, provider=provider, payer=(payer["name"] if payer else sub), kind=kind))
    log("Collector", "found %d file(s) for %d provider(s)" % (len(found), len({f['provider'] for f in found})))
    return found, payers


# ----------------------------------------------------------------- AGENT 2
def remit_reader(files, payers):
    lines, payments, plb = [], [], []
    for f in files:
        if f["kind"] != "835":
            continue
        try:
            l, p, a = era835.parse_835(f["path"], provider_hint=f["provider"], payer_hint=f["payer"])
        except Exception as e:
            log("Remit Reader", "could not read %s: %s" % (f["path"], e))
            continue
        for x in l + p + a:
            pm = match_payer(x.get("payer", ""), payers)
            x["payer"] = pm["name"] if pm else (f["payer"] or x.get("payer", ""))
            x["provider"] = f["provider"]
        for x in p:
            x["payee"] = f["provider"]
        lines += l; payments += p; plb += a
    log("Remit Reader", "%d service line(s), %d payment(s), %d provider-level adjustment(s)"
        % (len(lines), len(payments), len(plb)))
    return lines, payments, plb


# ----------------------------------------------------------------- AGENT 3
def status_reader(files):
    status, billed = [], []
    for f in files:
        if f["kind"] not in ("status", "billed"):
            continue
        try:
            rows = csv_import.normalise(f["path"], f["provider"], f["payer"], f["kind"])
        except Exception as e:
            log("Status Reader", "could not read %s: %s" % (f["path"], e))
            continue
        (status if f["kind"] == "status" else billed).extend(rows)
    log("Status Reader", "%d claim-status line(s), %d billed line(s)" % (len(status), len(billed)))
    return status, billed


# ----------------------------------------------------------------- AGENT 4
def _pkey(r):
    """Same client: use Medicaid/member ID when there is one, otherwise the name."""
    mid = re.sub(r"\W", "", r.get("member_id") or "").upper()
    name = re.sub(r"[^a-z]", "", ((r.get("patient_first") or "") + (r.get("patient_last") or "")).lower())
    return mid or name


def _line_key(r):
    d = r["dos"].strftime("%Y-%m-%d") if r.get("dos") else ""
    return (r["provider"].lower(), _pkey(r), d, (r.get("svc_code") or "").upper())


def _outcome(r):
    if r["source"] == "835":
        if r.get("claim_status_code") == "22" or r.get("paid", 0) < 0:
            return "Reversal"
        if r.get("paid", 0) > 0:
            return "Paid"
        adj = r.get("adjustments") or []
        if adj and all(g == "PR" for g, _, _ in adj):
            return "Patient resp"
        return "Denied"
    st = (r.get("status_text") or "").lower()
    if r.get("paid", 0) > 0:
        return "Paid"
    if "pend" in st or "process" in st or "suspend" in st:
        return "Pending"
    if "den" in st or "reject" in st or r.get("reason"):
        return "Denied"
    return "Pending"


def rebill_analyst(remit_lines, status_lines, billed_lines, payers, today=None, no_response_days=30):
    today = today or datetime.today()
    pinfo = {p["name"]: p for p in payers}

    # 835 lines win over the same line from a claim-status export (no double counting)
    seen, lines = set(), []
    for r in remit_lines + status_lines:
        r["outcome"] = _outcome(r)
        k = _line_key(r) + (r["payer"], round(r.get("charge", 0), 2), r["outcome"])
        if k in seen:
            continue
        seen.add(k); lines.append(r)

    paid_keys = {_line_key(r) for r in lines if r["outcome"] == "Paid"}
    for r in lines:
        r["patient"] = ("%s %s" % (r.get("patient_first", ""), r.get("patient_last", ""))).strip().title() or r.get("patient_ctrl", "")
        r.update(category="", code="", action="", steps=[], rebill_by=None, timely="", already_paid=False)
        if r["outcome"] != "Denied":
            continue
        if r["source"] == "835":
            cat, code = denials.classify_carcs(r.get("adjustments") or [], r.get("paid", 0))
            r["reason"] = ", ".join("%s-%s" % (g, c) for g, c, _ in r.get("adjustments") or [])
            if r.get("remarks"):
                r["reason"] += " | remarks " + ", ".join(r["remarks"])
        else:
            cat, code = denials.classify_text(r.get("reason")), ""
        r["category"], r["code"] = cat, code
        r["action"] = denials.action_for(cat)
        r["steps"] = denials.steps_for(cat)
        if _line_key(r) in paid_keys:                 # already rebilled & paid
            r["already_paid"], r["action"] = True, "EXCLUDE"
        days = pinfo.get(r["payer"], {}).get("timely_filing_days", 365)
        if r.get("dos"):
            r["rebill_by"] = r["dos"] + timedelta(days=days)
            left = (r["rebill_by"] - today).days
            r["timely"] = "EXPIRED" if left < 0 else ("URGENT (%d days left)" % left if left <= 60 else "OK (%d days left)" % left)
            if left < 0 and r["action"] in ("FIX", "VERIFY"):
                r["reason"] = "Past filing deadline (was: %s) %s" % (r["category"], r.get("reason", ""))
                r["category"], r["action"] = "Timely filing", "REVIEW"
                r["steps"] = denials.steps_for("Timely filing")

    # billed in the EHR but no answer from any payer -> follow up
    answered = {_line_key(r) for r in lines}
    no_response = []
    for b in billed_lines:
        b["patient"] = ("%s %s" % (b.get("patient_first", ""), b.get("patient_last", ""))).strip().title()
        if _line_key(b) in answered:
            continue
        sent = b.get("paid_date") or b.get("dos")
        if sent and (today - sent).days >= no_response_days:
            b["days_waiting"] = (today - (b.get("dos") or sent)).days
            no_response.append(b)

    work = [r for r in lines if r["outcome"] == "Denied" and r["action"] in ("FIX", "VERIFY", "REVIEW")]
    order = {"FIX": 0, "VERIFY": 1, "REVIEW": 2}
    work.sort(key=lambda r: (r["provider"], order[r["action"]], r.get("rebill_by") or today, -r.get("charge", 0)))
    log("Rebill Analyst", "%d lines: %d paid, %d denied (%d to rebill/review, %d already paid later), "
        "%d pending, %d billed with no response"
        % (len(lines), sum(r["outcome"] == "Paid" for r in lines), sum(r["outcome"] == "Denied" for r in lines),
           len(work), sum(r["already_paid"] for r in lines), sum(r["outcome"] == "Pending" for r in lines), len(no_response)))
    return lines, work, no_response


def in_period(r, start, end):
    d = r.get("paid_date") or r.get("dos")
    return start is None or (d is not None and start <= d <= end)
