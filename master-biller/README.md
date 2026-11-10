# Master Biller

One command that reads every payer's remittance advice and claim status for **all of your
providers**, finds every claim you can still get paid for, and writes:

| File | Who it is for | What is in it |
|---|---|---|
| `Providers/<Provider>_Billing_Report_<date>.pdf` | each provider | paid by payer, checks/EFTs received, money the payer took back, why claims were denied, **every claim to rebill by client with date of service and step-by-step fix**, billed claims with no answer, clients who dropped off |
| `Master_Biller_Overview.pdf` | you | all providers on one page |
| `Rebill_Worklist.xlsx` | you | every claim to rebill, sorted FIX -> VERIFY -> REVIEW, with columns to track your work |

Payers set up: **Trillium, Alliance, Vaya, Partners, Carolina Complete Health, Healthy Blue**
(add more in `config/payers.json`). Billing systems: **Notenetic** and **ShareNote**.

---

## The 5 agents (workers) and what each one does

1. **Collector** - looks in `inbox/` and finds every file for every provider and payer.
2. **Remit Reader** - reads **835 remittance advice** files (every payer sends these). Gets paid
   amounts, denial codes, check/EFT numbers and recoupments.
3. **Status Reader** - reads claim-status downloads (like Trillium's `claimsstatusFY...csv`) and
   your **Notenetic / ShareNote billed-claims export**.
4. **Rebill Analyst** - for every line decides Paid / Denied / Pending, *why* it was denied, whether
   it can be rebilled, the timely-filing deadline, and skips anything that was **already rebilled and
   paid** (so you never double-count or double-bill).
5. **Reporter** - writes the PDFs and the Excel worklist.

---

## What the computer can and cannot do for you (please read)

- **It does not type your passwords into payer portals.** Portals (NCTracks, Provider Direct,
  Alliance, Vaya, Partners, Carolina Complete Health, Healthy Blue) need *your* login and
  two-step code, and their rules usually say only you may sign in. **You** log in and download the
  files; the Master Biller does everything after that.
- **It does not submit claims for you.** Corrected claims still go out through Notenetic,
  ShareNote, or the payer portal. The worklist tells you exactly what to fix on each one.
- Reports contain client information (PHI). Send them to providers by **secure/encrypted email or a
  secure portal**, never plain email or text.

---

## Step-by-step: first time setup (do this once)

You need **Python** (the program that runs the code).

1. **Install Python.** Go to https://www.python.org/downloads/ and click the big yellow
   "Download Python" button. Open the file you downloaded.
   **On Windows, tick the box "Add python.exe to PATH" at the bottom** before you click Install.
2. **Download this project.** On the GitHub page for `my-first-project`, click the green **Code**
   button -> **Download ZIP**. Right-click the ZIP -> **Extract All**. You now have a folder called
   `my-first-project-main`. Inside it is the `master-biller` folder.
3. **Open a terminal in the `master-biller` folder.**
   - Windows: open the `master-biller` folder, click in the address bar at the top, type `cmd`,
     press **Enter**. A black window opens.
   - Mac: right-click the `master-biller` folder -> **New Terminal at Folder**.
4. **Install the two helpers** by typing this and pressing Enter:
   ```
   pip install -r requirements.txt
   ```
   (On Mac, if it says `pip: command not found`, type `pip3` instead of `pip`.)

## Step-by-step: practice with fake data (recommended first)

In the same black window, type each line and press Enter:
```
python make_samples.py
python run_billing.py --inbox samples/inbox --out samples/output
```
(On Mac use `python3` instead of `python`.)
Open the folder `samples/output/<today's date>` and look at the PDFs and the Excel file.
Everything in there is made up.

## Step-by-step: every billing week

1. **Download from each payer** (you log in):
   - **835 remittance files** for each payer (in Notenetic/ShareNote these are usually under the
     ERA/remittance area; in payer portals look for "835", "ERA" or "Remittance").
   - **Trillium:** Provider Direct -> File Transfers -> View File Repository from MCO ->
     `claimsstatusFY....csv`.
   - **Optional - what you billed:** export your billed claims list from Notenetic or ShareNote
     (CSV or Excel). This lets the Master Biller find claims that **never got an answer**.
2. **Put the files in the inbox** - one folder per provider, then one per payer (see
   `inbox/README.txt`). Example: `inbox/Sunrise Wellness LLC/Alliance/remit_1103.835`
3. **Run it:**
   ```
   python run_billing.py --period weekly
   ```
   Other choices:
   ```
   python run_billing.py                                   (everything in the inbox)
   python run_billing.py --period monthly
   python run_billing.py --period weekly --date 2026-11-03 (a past week)
   python run_billing.py --period custom --start 2026-10-01 --end 2026-10-31
   python run_billing.py --provider "Sunrise"              (one provider only)
   ```
4. **Open `output/<today's date>/`.**
5. **Work `Rebill_Worklist.xlsx`** top to bottom:
   - **FIX** - clear correction (diagnosis, auth number, modifier, place of service, taxonomy...).
     Correct the claim in Notenetic/ShareNote and resubmit as a **corrected claim (frequency 7)**
     with the original claim number. The "How to fix" column has the steps.
   - **VERIFY** - eligibility / wrong payer. Check the client in **NCTracks** for the date of service,
     then rebill to the plan they really had.
   - **REVIEW** - needs an appeal or a closer look (medical necessity, past the filing deadline, bundling).
   - Fill in **WORKED?**, **Date resubmitted** and **New claim #** as you go.
   - Trillium cutoff is **Wednesday** (Mon-Wed submissions).
6. **Send each provider their PDF** from `output/<date>/Providers/` by secure email.
7. **Next week**, drop in the new 835s. Claims you rebilled that got paid automatically drop off
   the list ("already rebilled & paid").

---

## Changing settings (no coding needed)

- `config/payers.json` - payer names, the words used to recognise them, **timely filing days**
  (set to 365 as a starting point - check each contract), submission days, portal notes.
- `config/column_maps.json` - if a payer's or Notenetic's download uses a column name the
  program doesn't recognise, add that column name to the right list.

## Where the code lives (for later, when you want to learn it)

| File | What it does |
|---|---|
| `run_billing.py` | the command you run; calls the 5 agents in order |
| `master_biller/agents.py` | Collector, Remit Reader, Status Reader, Rebill Analyst |
| `master_biller/era835.py` | reads 835 remittance files |
| `master_biller/csv_import.py` | reads CSV / Excel downloads |
| `master_biller/denials.py` | denial codes -> category -> fix steps (edit the wording here) |
| `master_biller/reports.py` | builds the PDFs and Excel |
| `make_samples.py` | makes fake practice data |
