#!/usr/bin/env python3
"""
Makes a PRACTICE inbox full of FAKE data in samples/inbox/ so you can try the
Master Biller without any real client information.

    python make_samples.py
    python run_billing.py --inbox samples/inbox --out samples/output
"""
import csv, os
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
INBOX = os.path.join(HERE, "samples", "inbox")
T = datetime.today()
D = lambda n: (T - timedelta(days=n))

# (first, last, medicaid id) - all made up
CLIENTS = [("Test", "Alpha", "900000001A"), ("Sample", "Bravo", "900000002B"), ("Demo", "Charlie", "900000003C"),
           ("Practice", "Delta", "900000004D"), ("Fake", "Echo", "900000005E"), ("Mock", "Foxtrot", "900000006F")]


def isa(payer, payee, npi, check, total):
    return [
        "ISA*00*          *00*          *ZZ*PAYERID        *ZZ*PROVIDERID     *%s*1200*^*00501*000000001*0*P*:" % T.strftime("%y%m%d"),
        "GS*HP*PAYERID*PROVIDERID*%s*1200*1*X*005010X221A1" % T.strftime("%Y%m%d"),
        "ST*835*0001",
        "BPR*I*%.2f*C*ACH*CCP*01*999999999*DA*123456*1234567890**01*999999999*DA*654321*%s" % (total, T.strftime("%Y%m%d")),
        "TRN*1*%s*1234567890" % check,
        "N1*PR*%s" % payer,
        "N1*PE*%s*XX*%s" % (payee, npi),
        "LX*1",
    ]


def claim(pcn, client, dos, code, mods, units, charge, paid, cas, icn, remarks=()):
    first, last, mid = client
    st = "1" if paid > 0 else "4"
    seg = ["CLP*%s*%s*%.2f*%.2f**MC*%s*11*1" % (pcn, st, charge, paid, icn),
           "NM1*QC*1*%s*%s****MI*%s" % (last.upper(), first.upper(), mid),
           "NM1*82*1*CLINICIAN*PAT****XX*1999999999",
           "DTM*232*%s" % dos.strftime("%Y%m%d"),
           "SVC*HC:%s%s*%.2f*%.2f**%d" % (code, "".join(":" + x for x in mods), charge, paid, units),
           "DTM*472*%s" % dos.strftime("%Y%m%d")]
    for g, c, a in cas:
        seg.append("CAS*%s*%s*%.2f" % (g, c, a))
    for r in remarks:
        seg.append("LQ*HE*%s" % r)
    return seg


def write_835(path, payer, payee, npi, check, claims, plb=None):
    total = sum(c[6] for c in claims) - (plb[1] if plb else 0)
    segs = isa(payer, payee, npi, check, total)
    for i, c in enumerate(claims):
        segs += claim("PCN%s%03d" % (check[-4:], i), *c)
    if plb:
        segs.append("PLB*%s*%s1231*%s*%.2f" % (npi, T.year, plb[0], plb[1]))
    segs += ["SE*%d*0001" % (len(segs) - 1), "GE*1*1", "IEA*1*000000001"]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write("~\n".join(segs) + "~\n")


def main():
    A, B, C, Dd, E, F = CLIENTS
    # ---- Provider 1: Sunrise Wellness (fake) ----
    p1 = os.path.join(INBOX, "Sunrise Wellness LLC")
    write_835(os.path.join(p1, "Alliance", "alliance_remit_1.835"), "ALLIANCE HEALTH", "SUNRISE WELLNESS LLC", "1111111111", "EFT10001", [
        (A, D(20), "H0004", ["HO"], 4, 120.00, 98.40, [("CO", "45", 21.60)], "AH0001"),
        (B, D(19), "H2015", ["HT"], 8, 200.00, 0.00, [("CO", "197", 200.00)], "AH0002", ["N54"]),
        (C, D(18), "90837", [], 1, 150.00, 0.00, [("CO", "27", 150.00)], "AH0003"),
        (A, D(13), "H0004", ["HO"], 4, 120.00, 0.00, [("CO", "18", 120.00)], "AH0004"),
    ], plb=("WO", 50.00))
    write_835(os.path.join(p1, "Healthy Blue", "healthyblue_remit_1.835"), "HEALTHY BLUE", "SUNRISE WELLNESS LLC", "1111111111", "EFT20001", [
        (Dd, D(25), "90834", ["95"], 1, 110.00, 0.00, [("CO", "11", 110.00)], "HB0001"),
        (Dd, D(11), "90834", ["95"], 1, 110.00, 92.00, [("CO", "45", 18.00)], "HB0002"),
        (E, D(30), "H0031", [], 1, 180.00, 0.00, [("CO", "B7", 180.00)], "HB0003"),
    ])
    write_835(os.path.join(p1, "Carolina Complete Health", "cch_remit_1.835"), "CAROLINA COMPLETE HEALTH", "SUNRISE WELLNESS LLC", "1111111111", "EFT30001", [
        (F, D(400), "H0004", [], 4, 120.00, 0.00, [("CO", "16", 120.00)], "CC0001", ["MA130"]),
        (F, D(15), "H0004", [], 4, 120.00, 100.00, [("CO", "45", 20.00)], "CC0002"),
    ])
    os.makedirs(os.path.join(p1, "Notenetic"), exist_ok=True)
    with open(os.path.join(p1, "Notenetic", "notenetic_billed_export.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Client Name", "Medicaid ID", "DOS", "Service Code", "Units", "Billed Amount", "Payer", "Billed Date"])
        w.writerow(["Alpha, Test", A[2], D(20).strftime("%m/%d/%Y"), "H0004", 4, 120, "Alliance Health", D(18).strftime("%m/%d/%Y")])
        w.writerow(["Bravo, Sample", B[2], D(45).strftime("%m/%d/%Y"), "H2015", 8, 200, "Alliance Health", D(43).strftime("%m/%d/%Y")])
        w.writerow(["Echo, Fake", E[2], D(50).strftime("%m/%d/%Y"), "H0031", 1, 180, "Healthy Blue", D(48).strftime("%m/%d/%Y")])

    # ---- Provider 2: Riverbend Counseling (fake) ----
    p2 = os.path.join(INBOX, "Riverbend Counseling PLLC")
    write_835(os.path.join(p2, "Vaya", "vaya_remit_1.835"), "VAYA HEALTH", "RIVERBEND COUNSELING PLLC", "2222222222", "EFT40001", [
        (A, D(12), "H0036", ["HO"], 6, 240.00, 210.00, [("CO", "45", 30.00)], "VY0001"),
        (B, D(12), "H0036", ["HO"], 6, 240.00, 0.00, [("CO", "109", 240.00)], "VY0002"),
    ])
    write_835(os.path.join(p2, "Partners", "partners_remit_1.835"), "PARTNERS HEALTH MANAGEMENT", "RIVERBEND COUNSELING PLLC", "2222222222", "EFT50001", [
        (C, D(9), "H2017", [], 16, 320.00, 0.00, [("CO", "5", 320.00)], "PH0001", ["M77"]),
    ])
    os.makedirs(os.path.join(p2, "Trillium"), exist_ok=True)
    with open(os.path.join(p2, "Trillium", "claimsstatusFY2027_sample.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["processed_dt", "claim_dt", "First_name", "Last_name", "CI_Client_Id", "srvc_code", "Units", "claim_amt",
                    "claim_approved_amt", "paid_amt", "status", "reason", "CI_Claim_Num"])
        w.writerow([D(5).strftime("%m/%d/%Y"), D(14).strftime("%m/%d/%Y"), "Demo", "Charlie", "C-1003", "H2015", 8, 200, 0, 0, "Denied",
                    "Diagnosis code is missing, incomplete or invalid", "TR0001"])
        w.writerow([D(5).strftime("%m/%d/%Y"), D(14).strftime("%m/%d/%Y"), "Practice", "Delta", "C-1004", "H2015", 8, 200, 180, 0, "Approved", "", "TR0002"])
        w.writerow([D(6).strftime("%m/%d/%Y"), D(21).strftime("%m/%d/%Y"), "Fake", "Echo", "C-1005", "H0004", 4, 120, 0, 0, "Denied",
                    "Patient not enrolled on the date of service", "TR0003"])
        w.writerow([D(4).strftime("%m/%d/%Y"), D(21).strftime("%m/%d/%Y"), "Fake", "Echo", "C-1005", "H0004", 4, 120, 108, 108, "Approved", "", "TR0004"])
        w.writerow([D(4).strftime("%m/%d/%Y"), D(10).strftime("%m/%d/%Y"), "Mock", "Foxtrot", "C-1006", "H0004", 4, 120, 0, 0, "Denied",
                    "Rendering provider taxonomy invalid", "TR0005"])
    print("Fake practice inbox created in", INBOX)


if __name__ == "__main__":
    main()
