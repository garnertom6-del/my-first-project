#!/usr/bin/env python3
"""
MASTER BILLER - run all five billing agents with one command.

    python run_billing.py                      # everything in the inbox
    python run_billing.py --period weekly      # this week (Mon-Sun), by paid/processed date
    python run_billing.py --period monthly     # this month
    python run_billing.py --period weekly --date 2026-11-03     # a specific week
    python run_billing.py --period custom --start 2026-10-01 --end 2026-10-31
    python run_billing.py --provider "Sunrise"  # only providers whose folder name contains 'Sunrise'

Put files in:   inbox/<Provider name>/<Payer name>/      (835 files, claim-status CSV/Excel)
                inbox/<Provider name>/Notenetic/         (what you billed - optional)
Results go to:  output/<today>/
"""
import argparse, os, sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from master_biller import agents, reports  # noqa: E402


def bounds(period, anchor, start, end):
    if period == "all":
        return None, None, None, None, "All files in the inbox"
    if period == "weekly":
        s = (anchor - timedelta(days=anchor.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        e = s + timedelta(days=6, hours=23, minutes=59)
        return s, e, s - timedelta(days=7), e - timedelta(days=7), "Week of %s - %s (Mon-Sun)" % (s.strftime("%m/%d/%Y"), e.strftime("%m/%d/%Y"))
    if period == "monthly":
        s = anchor.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        e = (s.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(minutes=1)
        pe = s - timedelta(minutes=1)
        return s, e, pe.replace(day=1, hour=0, minute=0), pe, s.strftime("%B %Y")
    s = datetime.strptime(start, "%Y-%m-%d"); e = datetime.strptime(end, "%Y-%m-%d") + timedelta(hours=23, minutes=59)
    span = e - s
    return s, e, s - span - timedelta(minutes=1), s - timedelta(minutes=1), "%s - %s" % (s.strftime("%m/%d/%Y"), e.strftime("%m/%d/%Y"))


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="Master Biller")
    ap.add_argument("--inbox", default=os.path.join(here, "inbox"))
    ap.add_argument("--out", default=os.path.join(here, "output"))
    ap.add_argument("--period", default="all", choices=["all", "weekly", "monthly", "custom"])
    ap.add_argument("--date"); ap.add_argument("--start"); ap.add_argument("--end")
    ap.add_argument("--provider", help="only providers whose folder name contains this text")
    ap.add_argument("--no-response-days", type=int, default=30, help="flag billed claims with no answer after this many days")
    a = ap.parse_args()
    if a.period == "custom" and not (a.start and a.end):
        sys.exit("--period custom needs --start YYYY-MM-DD and --end YYYY-MM-DD")

    today = datetime.today()
    anchor = datetime.strptime(a.date, "%Y-%m-%d") if a.date else today
    s, e, ps, pe, label = bounds(a.period, anchor, a.start, a.end)

    files, payers = agents.collector(a.inbox)                                   # AGENT 1
    if a.provider:
        files = [f for f in files if a.provider.lower() in f["provider"].lower()]
    if not files:
        sys.exit("No files found. Put files in %s/<Provider>/<Payer>/ and run again (see README.md)." % a.inbox)
    remit, payments, plb = agents.remit_reader(files, payers)                   # AGENT 2
    status, billed = agents.status_reader(files)                                # AGENT 3
    lines, work, no_resp = agents.rebill_analyst(remit, status, billed, payers, today, a.no_response_days)  # AGENT 4

    # keep only the chosen period
    inp = lambda r: agents.in_period(r, s, e)
    p_lines = [r for r in lines if inp(r)]
    p_work = [r for r in work if inp(r)]
    p_pay = [p for p in payments if s is None or (p.get("date") and s <= p["date"] <= e)]
    p_plb = [x for x in plb if s is None or (x.get("date") and s <= x["date"] <= e)]
    p_nr = no_resp  # unanswered claims are always shown until they get an answer

    outdir = os.path.join(a.out, today.strftime("%Y-%m-%d")); prov_dir = os.path.join(outdir, "Providers")
    os.makedirs(prov_dir, exist_ok=True)
    per = {}
    providers = sorted({f["provider"] for f in files})
    for prov in providers:                                                      # AGENT 5
        L = [r for r in p_lines if r["provider"] == prov]
        Wk = [r for r in p_work if r["provider"] == prov]
        N = [b for b in p_nr if b["provider"] == prov]
        P = [p for p in p_pay if p.get("payee") == prov or any(r["provider"] == prov and r.get("check") == p.get("check") for r in L)]
        A = [x for x in p_plb if x["provider"] == prov]
        lost = None
        if s is not None:
            now = {r["patient"] for r in L if r["outcome"] == "Paid"}
            before = defaultdict(float)
            for r in lines:
                if r["provider"] == prov and r["outcome"] == "Paid" and agents.in_period(r, ps, pe):
                    before[r["patient"]] += r.get("paid", 0)
            lost = sorted([(n, v) for n, v in before.items() if n not in now], key=lambda x: -x[1])
        path = os.path.join(prov_dir, "%s_Billing_Report_%s.pdf" % (reports.safe(prov), today.strftime("%Y-%m-%d")))
        nums = reports.provider_pdf(path, prov, label, L, Wk, N, P, A, lost)
        top = Counter(r["category"] for r in L if r["outcome"] == "Denied" and not r["already_paid"]).most_common(1)
        nums.update(lines=len(L), denied=sum(r["outcome"] == "Denied" for r in L), payers=sorted({r["payer"] for r in L}),
                    top=top[0][0] if top else "-")
        per[prov] = nums
        agents.log("Reporter", "%s -> paid %s | rebillable %s | review %s | no answer %s"
                   % (prov, reports.m(nums["paid"]), reports.m(nums["reb"]), reports.m(nums["rev"]), reports.m(nums["nr"])))

    reports.overview_pdf(os.path.join(outdir, "Master_Biller_Overview.pdf"), label, per)
    reports.worklist_xlsx(os.path.join(outdir, "Rebill_Worklist.xlsx"), p_work, p_lines, p_nr, p_pay, p_plb)
    print("\nDONE. Open this folder:\n  %s" % outdir)
    print("  - Master_Biller_Overview.pdf   (for you)")
    print("  - Rebill_Worklist.xlsx         (work these claims, FIX first)")
    print("  - Providers/                   (one PDF per provider - send by SECURE email)")


if __name__ == "__main__":
    main()
