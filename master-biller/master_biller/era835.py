"""
AGENT 2 helper - reads 835 remittance advice (ERA) files.

An 835 is the standard electronic "remittance advice" every payer sends
(Trillium, Alliance, Vaya, Partners, Carolina Complete Health, Healthy Blue ...).
It says, for every claim line: what was charged, what was paid, and WHY anything
was not paid (CARC/RARC codes).

This turns one 835 file into a list of simple Python dictionaries - one per
service line - that the rest of the toolkit understands.
"""
from datetime import datetime


def _d8(s):
    """Turn '20261103' into a date (or None)."""
    try:
        return datetime.strptime(s.strip()[:8], "%Y%m%d")
    except Exception:
        return None


def _f(s):
    try:
        return round(float(s), 2)
    except Exception:
        return 0.0


def split_segments(text):
    """Work out the separators from the ISA header and split into segments."""
    text = text.lstrip("﻿").strip()
    if not text.startswith("ISA"):
        raise ValueError("Not an 835/X12 file (does not start with ISA)")
    elem = text[3]
    # The ISA segment is always 106 characters; char 105 is the segment terminator.
    seg_term = text[105] if len(text) > 105 else "~"
    comp = text[104] if len(text) > 104 else ":"
    segs = []
    for raw in text.split(seg_term):
        raw = raw.strip("\r\n ")
        if raw:
            segs.append(raw.split(elem))
    return segs, comp


def _cas(seg):
    """CAS*CO*45*12.00*1*16*5.00 -> [('CO','45',12.0), ('CO','16',5.0)]"""
    out = []
    group = seg[1] if len(seg) > 1 else ""
    i = 2
    while i < len(seg):
        code = seg[i].strip() if i < len(seg) else ""
        amt = _f(seg[i + 1]) if i + 1 < len(seg) else 0.0
        if code:
            out.append((group, code, amt))
        i += 3
    return out


CLAIM_STATUS = {
    "1": "Processed as primary", "2": "Processed as secondary", "3": "Processed as tertiary",
    "4": "Denied", "19": "Primary, forwarded", "20": "Secondary, forwarded",
    "21": "Tertiary, forwarded", "22": "Reversal of previous payment", "23": "Not our claim, forwarded",
}


def parse_835(path, provider_hint="", payer_hint=""):
    """Return (lines, payments, plb) for one 835 file.

    lines    - one dict per service line (or per claim if no SVC lines)
    payments - one dict per check/EFT (BPR/TRN)
    plb      - provider-level adjustments (recoupments, withholds, interest)
    """
    with open(path, encoding="utf-8", errors="replace") as fh:
        segs, comp = split_segments(fh.read())

    lines, payments, plb = [], [], []
    pay = {}            # current check/EFT
    payer = payer_hint
    payee = provider_hint
    payee_npi = ""
    claim = None        # current CLP
    svc = None          # current SVC
    loop = None         # 'payer' | 'payee' while reading N1 loops

    def close_svc():
        nonlocal svc
        if svc is not None:
            lines.append(svc)
            svc = None

    def close_claim():
        nonlocal claim
        close_svc()
        if claim is not None and not claim["_had_svc"]:
            # claim with no service lines - keep one row for the whole claim
            row = dict(claim["_base"])
            row.update(svc_code="", modifiers="", units=0,
                       charge=claim["charge"], paid=claim["paid"],
                       adjustments=list(claim["cas"]), remarks=list(claim["remarks"]),
                       dos=claim["dos"])
            lines.append(row)
        claim = None

    for s in segs:
        tag = s[0]
        g = lambda i: s[i].strip() if len(s) > i else ""
        if tag == "BPR":
            pay = dict(amount=_f(g(2)), method=g(4), date=_d8(g(16)), check="", payer=payer, file=path)
        elif tag == "TRN":
            pay["check"] = g(2)
        elif tag == "N1":
            if g(1) == "PR":
                loop, payer = "payer", g(2) or payer_hint
                pay["payer"] = payer
            elif g(1) == "PE":
                loop, payee = "payee", (provider_hint or g(2))
                if g(3) == "XX":
                    payee_npi = g(4)
        elif tag == "LX":
            if pay and pay not in payments:
                pay["payee"] = payee
                payments.append(pay)
        elif tag == "CLP":
            close_claim()
            if pay and pay not in payments:
                pay["payee"] = payee
                payments.append(pay)
            st = g(2)
            claim = dict(
                charge=_f(g(3)), paid=_f(g(4)), cas=[], remarks=[], dos=None, _had_svc=False,
                _base=dict(
                    source="835", file=path, payer=payer or payer_hint, provider=payee or provider_hint,
                    provider_npi=payee_npi, patient_ctrl=g(1), claim_status_code=st,
                    claim_status=CLAIM_STATUS.get(st, st), claim_charge=_f(g(3)), claim_paid=_f(g(4)),
                    patient_resp=_f(g(5)), payer_claim_no=g(7), patient_last="", patient_first="",
                    member_id="", rendering="", check=pay.get("check", ""), paid_date=pay.get("date"),
                ))
        elif claim is not None and tag == "NM1":
            b = claim["_base"]
            if g(1) == "QC":
                b["patient_last"], b["patient_first"], b["member_id"] = g(3), g(4), g(9)
            elif g(1) == "82":
                b["rendering"] = (g(4) + " " + g(3)).strip() if g(2) == "1" else g(3)
            if svc is not None:
                svc.update({k: b[k] for k in ("patient_last", "patient_first", "member_id", "rendering")})
        elif claim is not None and tag == "MOA":
            claim["remarks"] += [x for x in s[3:8] if x.strip()]
        elif claim is not None and tag == "DTM":
            if g(1) in ("232", "472", "150"):
                d = _d8(g(2))
                if svc is not None and g(1) in ("472", "150"):
                    svc["dos"] = d
                elif claim["dos"] is None:
                    claim["dos"] = d
        elif claim is not None and tag == "SVC":
            close_svc()
            claim["_had_svc"] = True
            parts = g(1).split(comp)
            code = parts[1] if len(parts) > 1 else parts[0]
            svc = dict(claim["_base"])
            svc.update(svc_code=code.upper(), modifiers=":".join(p for p in parts[2:6] if p),
                       charge=_f(g(2)), paid=_f(g(3)), units=_f(g(5)) or 1,
                       adjustments=list(claim["cas"]),  # claim-level CAS applies to every line
                       remarks=list(claim["remarks"]), dos=claim["dos"])
        elif claim is not None and tag == "CAS":
            if svc is not None:
                svc["adjustments"] += _cas(s)
            else:
                claim["cas"] += _cas(s)
        elif claim is not None and tag == "LQ" and svc is not None:
            svc["remarks"].append(g(2))
        elif tag == "PLB":
            close_claim()
            i = 3
            while i + 1 < len(s):
                reason = s[i].split(comp)
                plb.append(dict(payer=payer, provider=payee, check=pay.get("check", ""),
                                date=pay.get("date"), code=reason[0],
                                ref=reason[1] if len(reason) > 1 else "", amount=_f(s[i + 1]), file=path))
                i += 2
        elif tag in ("SE", "GE", "IEA"):
            close_claim()
    close_claim()
    for p in payments:
        p.setdefault("payee", payee)
    return lines, payments, plb
