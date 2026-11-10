"""
AGENT 4 helper - decides WHY a line was denied and WHAT to do about it.

Every denied line gets:
  category  - e.g. 'Eligibility', 'Authorization', 'Diagnosis'
  action    - FIX     (clear correction, rebill it)
              VERIFY  (check eligibility/payer first, then rebill)
              REVIEW  (needs a human look / appeal)
              EXCLUDE (do not rebill - duplicate, already paid, contractual)
  steps     - plain-language recoup instructions

Two kinds of input are understood:
  * CARC codes from 835 files (standard national codes, same for every payer)
  * the text 'reason' column in claim-status exports (e.g. Trillium Provider Direct)
"""

# --- CARC (Claim Adjustment Reason Code) -> category -----------------------
CARC = {
    # never rebill
    "18": "Duplicate", "B13": "Duplicate",
    "45": "Contractual", "253": "Contractual", "59": "Contractual", "94": "Contractual",
    "1": "Patient responsibility", "2": "Patient responsibility", "3": "Patient responsibility",
    # timely filing
    "29": "Timely filing",
    # eligibility / wrong payer
    "26": "Eligibility", "27": "Eligibility", "31": "Eligibility", "32": "Eligibility",
    "33": "Eligibility", "177": "Eligibility", "200": "Eligibility",
    "109": "Wrong payer", "24": "Wrong payer", "B11": "Wrong payer", "22": "Other insurance (COB)",
    "23": "Other insurance (COB)",
    # authorization
    "15": "Authorization", "39": "Authorization", "62": "Authorization", "197": "Authorization",
    "198": "Authorization", "288": "Authorization", "243": "Authorization",
    # diagnosis
    "11": "Diagnosis", "146": "Diagnosis", "167": "Diagnosis",
    # coding / claim data
    "4": "Coding / modifier", "181": "Coding / modifier", "182": "Coding / modifier", "6": "Coding / modifier",
    "7": "Coding / modifier", "9": "Coding / modifier", "10": "Coding / modifier", "125": "Coding / modifier",
    "16": "Missing information", "140": "Member name / ID", "A1": "Missing information",
    "5": "Place of service", "58": "Place of service",
    "151": "Units / frequency", "119": "Units / frequency", "35": "Units / frequency", "273": "Units / frequency",
    "B5": "Units / frequency",
    # provider enrollment
    "B7": "Provider enrollment", "8": "Provider enrollment", "170": "Provider enrollment",
    "185": "Provider enrollment", "52": "Provider enrollment", "242": "Provider enrollment",
    "B9": "Provider enrollment",
    # bundling / concurrent
    "97": "Bundled / concurrent", "B15": "Bundled / concurrent", "231": "Bundled / concurrent",
    "234": "Bundled / concurrent",
    # medical necessity / documentation
    "50": "Medical necessity", "56": "Medical necessity", "252": "Documentation requested",
    "96": "Non-covered service", "204": "Non-covered service", "B1": "Non-covered service",
}

ACTION = {
    "Duplicate": "EXCLUDE", "Contractual": "EXCLUDE", "Patient responsibility": "EXCLUDE",
    "Timely filing": "REVIEW", "Eligibility": "VERIFY", "Wrong payer": "VERIFY",
    "Other insurance (COB)": "VERIFY", "Authorization": "FIX", "Diagnosis": "FIX",
    "Coding / modifier": "FIX", "Missing information": "FIX", "Member name / ID": "FIX",
    "Place of service": "FIX", "Units / frequency": "FIX", "Provider enrollment": "FIX",
    "Taxonomy": "FIX", "Resubmission ref": "FIX", "Not in profile": "FIX",
    "Bundled / concurrent": "REVIEW", "Medical necessity": "REVIEW",
    "Documentation requested": "FIX", "Non-covered service": "REVIEW", "Other": "REVIEW",
}

STEPS = {
    "Eligibility": [
        "Look up the client in NCTracks (Eligibility > Recipient Eligibility) for the exact date(s) of service.",
        "Write down which plan they had that day: NC Medicaid Direct, a Standard Plan (Carolina Complete Health, Healthy Blue, AmeriHealth, UnitedHealthcare, WellCare) or a Tailored Plan (Alliance, Partners, Trillium, Vaya).",
        "If the plan on the claim was wrong, rebill to the plan they actually had (new claim, not a correction).",
        "If the plan was right, fix the Medicaid/member ID and name to match NCTracks exactly, then resubmit.",
        "If retro-eligibility is pending, wait until it shows in NCTracks, then rebill.",
    ],
    "Wrong payer": [
        "Check NCTracks for the client's plan on the date of service.",
        "Bill the claim to the correct payer as a NEW claim (frequency 1).",
        "Keep this denial as proof of timely filing in case the new payer asks.",
    ],
    "Other insurance (COB)": [
        "Ask the client / check NCTracks for other insurance (Medicare, commercial).",
        "Bill the primary insurance first, then rebill this payer with the primary's EOB attached (secondary claim).",
        "If the other insurance has ended, ask the payer/NCTracks to update the TPL record, then rebill.",
    ],
    "Authorization": [
        "Find the authorization for this client, service code and date range in the payer portal.",
        "If an auth exists, put the auth number on the claim (and make sure units/dates fall inside it), then submit a corrected claim (frequency 7) with the original claim number.",
        "If no auth exists, request a retro-authorization if the payer allows it; rebill after it is approved.",
        "If units went over the auth, request an auth update/extension, then rebill the extra units.",
    ],
    "Diagnosis": [
        "Get the client's qualifying behavioral-health diagnosis (F-code) from the CCA / PCP.",
        "Put the F-code as the PRIMARY diagnosis on the claim and make sure it is valid on the date of service.",
        "Submit a corrected claim (frequency 7) referencing the original claim number.",
    ],
    "Coding / modifier": [
        "Compare the service code and modifiers on the claim with the payer's fee schedule / your contract.",
        "Fix the code or modifier (e.g. HO/HN/HM/U-modifiers, GT/95 for telehealth) to match the service note.",
        "Submit a corrected claim (frequency 7) referencing the original claim number.",
    ],
    "Missing information": [
        "Read the remark code (RARC) on the line - it says which field is missing or wrong.",
        "Fill in / correct that field (NPI, taxonomy, auth number, diagnosis pointer, dates, units, etc.).",
        "Resubmit as a corrected claim (frequency 7).",
    ],
    "Member name / ID": [
        "Pull the client's name, DOB and Medicaid ID from NCTracks.",
        "Make the claim match exactly (spelling, ID, DOB) and resubmit.",
    ],
    "Place of service": [
        "Check the service note for where the service actually happened.",
        "Change the Place of Service to an accepted code (11 office, 12 home, 02/10 telehealth, 99 other) and resubmit.",
    ],
    "Units / frequency": [
        "Check the units on the note against the claim and the auth.",
        "If too many units were billed, correct the units; if a daily/weekly max was hit, check for an overlapping claim.",
        "Resubmit the corrected claim (frequency 7).",
    ],
    "Provider enrollment": [
        "Check the rendering and billing NPI, taxonomy and site are enrolled with THIS payer for the date of service (NCTracks + payer credentialing).",
        "If the enrollment date is wrong or missing, contact the payer's provider network team to fix the effective date.",
        "Once fixed, resubmit the claim.",
    ],
    "Taxonomy": [
        "Confirm the rendering & billing taxonomy on the claim is one the payer accepts (Trillium: 251S00000X).",
        "If different, correct it and resubmit; if already correct, ask provider network to fix the enrollment effective date, then resubmit.",
    ],
    "Resubmission ref": [
        "Look up the ORIGINAL claim number (DCN/ICN).",
        "Resubmit as a replacement claim (frequency 7) referencing that number.",
    ],
    "Not in profile": [
        "Contact the payer to add the service/modifier to the provider profile/contract for the date of service.",
        "Once confirmed active, resubmit the claim.",
    ],
    "Bundled / concurrent": [
        "Another service was paid for the same client and date - check for overlap or double units.",
        "If the services are truly separate, resubmit with the correct modifier (e.g. 59/XU) or appeal with the notes.",
    ],
    "Medical necessity": [
        "Pull the service note, PCP and CCA for the date.",
        "File a reconsideration/appeal with the payer, attaching the documentation.",
    ],
    "Documentation requested": [
        "Send the requested records (note, PCP, auth) to the payer by their deadline.",
        "Track the request - the claim reprocesses once records are received.",
    ],
    "Non-covered service": [
        "Confirm the service is in your contract with this payer for the date of service.",
        "If covered, appeal with the contract page; if not, it is a write-off or bill the correct payer.",
    ],
    "Timely filing": [
        "Find proof the claim was first sent on time (earlier denial, 999/277CA acceptance report, clearinghouse report).",
        "If you have proof, file a timely-filing appeal with it attached.",
        "If there is no proof, this is a write-off - note it for the provider.",
    ],
    "Other": [
        "Read the denial reason / remark code on the line.",
        "Correct the specific field and resubmit as a corrected claim, or call the payer for clarification.",
    ],
}


def classify_text(reason):
    """For claim-status exports that give a written reason (Trillium Provider Direct style)."""
    r = (reason or "").lower()
    if "duplicate" in r: return "Duplicate"
    if "contract rate" in r: return "Contractual"
    if "timely" in r: return "Timely filing"
    if "not enrolled" in r or "eligib" in r: return "Eligibility"
    if "author" in r: return "Authorization"
    if "diagnosis" in r: return "Diagnosis"
    if "taxonomy" in r: return "Taxonomy"
    if "place of service" in r: return "Place of service"
    if "dcn" in r or "resubmission" in r: return "Resubmission ref"
    if "provider profile" in r: return "Not in profile"
    if "concurrent" in r: return "Bundled / concurrent"
    if "modifier" in r or "procedure code" in r: return "Coding / modifier"
    if "unit" in r: return "Units / frequency"
    return "Other"


def classify_carcs(adjustments, paid):
    """adjustments = [(group, code, amount)]. Pick the code that explains the denial."""
    best = None
    rank = {"EXCLUDE": 0, "REVIEW": 1, "VERIFY": 2, "FIX": 3}
    for group, code, amt in adjustments:
        cat = CARC.get(code.upper(), "Other")
        if group == "PR" and cat == "Other":
            cat = "Patient responsibility"
        if cat in ("Contractual",) and paid > 0:
            continue
        act = ACTION.get(cat, "REVIEW")
        # Duplicate always wins (never rebill a duplicate)
        if cat == "Duplicate":
            return cat, code
        if best is None or rank[act] > rank[ACTION.get(best[0], "REVIEW")]:
            best = (cat, code)
    return best or ("Other", "")


def action_for(category):
    return ACTION.get(category, "REVIEW")


def steps_for(category):
    return STEPS.get(category, STEPS["Other"])
