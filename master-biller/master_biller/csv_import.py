"""
AGENT 3 helper - reads claim-status / billing exports (CSV or Excel).

Works with Trillium's claimsstatus CSV, Notenetic / ShareNote billing exports
and most portal downloads. The column names are matched using
config/column_maps.json, so a new portal usually only needs a new header name
added there.
"""
import csv, json, os, re
from datetime import datetime

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _key(s):
    return re.sub(r"[^a-z0-9#]", "", (s or "").lower())


def load_map():
    with open(os.path.join(HERE, "config", "column_maps.json")) as fh:
        return json.load(fh)["fields"]


def read_table(path):
    """Return a list of {header: value} rows for .csv / .xlsx files."""
    if path.lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook
        ws = load_workbook(path, read_only=True, data_only=True).active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        head = [str(h or "").strip() for h in rows[0]]
        return [dict(zip(head, ["" if v is None else v for v in r])) for r in rows[1:]]
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
        return list(csv.DictReader(fh))


def parse_date(v):
    if isinstance(v, datetime):
        return v
    s = str(v or "").strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%Y%m%d", "%m-%d-%Y", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def money(v):
    try:
        return round(float(str(v).replace("$", "").replace(",", "").strip() or 0), 2)
    except ValueError:
        return 0.0


def normalise(path, provider, payer, kind):
    """kind = 'status' (payer response) or 'billed' (what was sent from the EHR)."""
    fields = load_map()
    raw = read_table(path)
    if not raw:
        return []
    headers = {_key(h): h for h in raw[0].keys()}
    col = {}
    for field, names in fields.items():
        for n in names:
            if _key(n) in headers:
                col[field] = headers[_key(n)]
                break
    get = lambda r, f: (str(r.get(col[f], "")).strip() if f in col else "")
    out = []
    for r in raw:
        first, last = get(r, "client_first"), get(r, "client_last")
        if not (first or last) and get(r, "client_name"):
            nm = get(r, "client_name")
            if "," in nm:
                last, first = [x.strip() for x in nm.split(",", 1)]
            else:
                bits = nm.split()
                first, last = (bits[0], " ".join(bits[1:])) if bits else ("", "")
        if not (first or last):
            continue
        status = get(r, "status")
        paid = money(get(r, "paid"))
        approved = money(get(r, "approved"))
        out.append(dict(
            source=kind, file=path, provider=get(r, "provider") or provider, payer=get(r, "payer") or payer,
            patient_first=first.title(), patient_last=last.title(), client_id=get(r, "client_id"),
            member_id=get(r, "member_id"), dos=parse_date(get(r, "dos")),
            paid_date=parse_date(get(r, "processed_date")) or parse_date(get(r, "billed_date")),
            svc_code=get(r, "svc_code").upper(), modifiers=get(r, "modifiers"), units=money(get(r, "units")) or 1,
            charge=money(get(r, "charge")), approved=approved, paid=max(paid, approved) if kind == "status" else paid,
            status_text=status, reason=get(r, "reason"), payer_claim_no=get(r, "claim_no"),
            rendering=get(r, "rendering"), adjustments=[], remarks=[], check="",
        ))
    return out
