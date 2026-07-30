# Wickham Roofing — Accounting Guide

**Truck Server v4 · Accounting Role (Debi)**

This guide covers the Accounting Ledger: tracking ACV and Supplement
checks with real dollar amounts, managing canvasser commissions
(including manual adjustments), exporting invoices to QuickBooks
Online, and reviewing full job details.

---

## 1. Logging In

1. Open the app and enter your assigned 4-digit PIN.
2. On success, you're taken to the **"Accounting Ledger."** The Wickham
   Roofing logo appears in the header alongside the title.

To log out, click **Logout** in the top-right corner of the dashboard.

**Note:** Your access covers financial data across all jobs and all
reps. You can see every rep's commission data — this is intentional,
since aggregating and paying commissions is your core responsibility.

---

## 2. Understanding the Ledger

At the top of your dashboard, you'll see two metric cards:

- **"Supplemented RCV Added"** — the total additional RCV value your
  team has won through approved supplements.
- **"QBO Export Queue"** — the number of jobs currently waiting to be
  exported to QuickBooks Online.

Below that, you'll find your working tables: ACV/Supplement check
tracking, commissions ready to pay, and the QBO export tool.

If a table has nothing to show — no pending checks, or no commissions
ready to pay — you'll see a clear message like **"No pending checks to
record"** or **"No commissions currently ready to pay"** instead of a
blank, confusing table.

### Viewing full job details
Every job row in the ledger includes a **"View Details →"** link that
opens the full job detail page. This gives you complete access to all
job information — including financials, margins, measurement data, all
documents, and supplements. Admin, Operations, and Accounting all share
this same unified detail view with no restrictions between these three
office roles.

---

## 3. Recording ACV & Supplement Checks

Unlike a simple "received" checkbox, this system captures the **actual
dollar amount and date** for every check, so you can catch carrier
short-pays before they become a problem.

### How to record a check
1. Find the job under the ACV or Supplement section, currently marked
   **"Pending."**
2. Click it to open the check entry form.
3. Enter:
   - **Amount** — the actual dollar figure from the check.
   - **Date received** (labeled above the date field).
4. Click **"Confirm Received."**

### Understanding the short-pay warning
This system knows the difference between an ACV check and a Supplement
check, and compares each against the correct expected amount:

- **Expected ACV** = Carrier RCV minus Recoverable Depreciation (the
  portion the carrier withholds until the job is finished).
- **Expected Supplement** = the Recoverable Depreciation amount itself.

If the amount you enter is meaningfully below the correct expected
value (roughly 2% or more short), the system will stop and ask:

> *"This amount ($X) is less than the expected $Y. This may indicate a
> carrier short-pay. Continue anyway?"*

This isn't an error — it's a flag for your judgment. If the carrier
genuinely shorted the payment, confirm and follow up with them
separately. If it's a data entry mistake, double-check your numbers
before confirming.

**Note:** For older jobs missing a recorded depreciation value, this
warning is automatically skipped rather than comparing against the
wrong number — you won't see a false warning on those jobs, but you
also won't get short-pay protection until that job's financials are
filled in by Admin.

### If you leave a field blank
You'll be prompted to enter both the amount and the date — both fields
are required and the system won't accept a partial entry.

---

## 4. Commissions

### Default commission rate
Every job defaults to a canvasser commission of **10% of total
revenue** (the full roof sale price) — this is not based on profit,
and permit fees are not deducted from the commission calculation.

### Adjusting a commission manually
Sometimes a specific job needs a different rate — a special
arrangement with a rep, for example. You can override the default on
a per-job basis:

1. Find the job's commission amount and click **"Adjust %."**
2. An input field appears, pre-filled with the current rate (10% by
   default).
3. Enter the new percentage (0–100).
4. Click **"Save."**
5. You'll be asked to confirm: **"Set commission for this job to X% of
   revenue (overriding the default 10%)?"**
6. Once confirmed, the commission amount recalculates immediately.

### Resetting a job back to the default
1. Click **"Reset"** next to the job.
2. Confirm when prompted: **"Reset this job's commission back to the
   default 10%?"**
3. The commission recalculates back to the standard 10% rate.

**Important:** Overrides apply only to the specific job you edit —
every other job continues to use the 10% default automatically unless
you individually adjust it.

### Downloading commission documents
Click **"Download PDF"** next to a rep's commission entry to get a
formatted document for payout records.

---

## 5. Exporting to QuickBooks Online

1. Click **"Export QBO CSV."**
2. The button changes to **"Exporting..."** while the file is prepared.
3. A CSV file downloads automatically, containing one row per job with:
   - Customer name
   - Invoice date (today's date)
   - Due date (Net 30 from today)
   - Terms (Net 30)
   - Item description ("Roofing Services")
   - Amount (based on carrier RCV)
   - Memo (invoice ID and claim number)

### Duplicate export protection
Once a job is exported, it's automatically marked as exported and will
**not** appear in future export batches — you cannot accidentally
double-export the same job.

### If there's nothing to export
If no jobs are currently pending export, you'll see a popup:
**"No jobs pending QBO export."** No file will download — there's
nothing to export, so nothing is generated.

### If something goes wrong
You'll see a popup: **"Export failed: [error]"** or **"Network error
during export."** Try again, and contact the Tech Admin if it
persists.

---

## 6. What You Cannot Do (By Design)

- You cannot access the Admin control panel, Triage, or Emergency
  Override tools.
- You cannot access Field rep intake screens or Operations' material/
  crew scheduling tools.
- You cannot create or manage field rep accounts.

**What you CAN do:** Via the "View Details →" links on your ledger
rows, you have full access to any job's detail page, including
financials, margins, measurement data, and all documents. This is the
same unified view that Admin and Operations see — there is no
restriction between these three office roles on job data.

You can also see every rep's commission data — this is intentional,
since aggregating and paying commissions is your core responsibility.

---

## FAQ

**Q: Why does commission use revenue instead of profit?**
By design — Wickham Roofing pays canvassers 10% of the total roof sale
price, not a share of profit. This is intentional and applies to every
job unless manually adjusted.

**Q: I need to pay a rep a different percentage on one specific job.
How do I do that without changing everyone else's rate?**
Use the **"Adjust %"** button on that specific job only. It does not
affect the default rate for any other job — every other job keeps
using 10% automatically.

**Q: I made a mistake adjusting a commission percentage. Can I undo it?**
Yes — click **"Reset"** on that job to instantly revert it back to the
standard 10% rate.

**Q: Why is my ACV check amount always supposed to be less than the
carrier RCV?**
That's normal, not a short-pay. Carriers typically withhold recoverable
depreciation until the job is finished, so the ACV check is intentionally
lower than the total RCV. The system now compares your entry against
the *correct* expected ACV (RCV minus depreciation), not the full RCV,
so you'll only see a warning if the amount is actually short.

**Q: What if the check amount I enter is genuinely less than expected?**
Confirm the entry anyway and follow up with the carrier separately —
this is now visible and trackable instead of hidden behind a simple
checkbox.

**Q: Can I export the same job to QuickBooks twice by accident?**
No — once a job is exported, it's automatically excluded from future
export batches.

**Q: Can I see other reps' commissions, or only my own calculations?**
You can see all reps' commissions — this is intentional for your role,
unlike Field reps, who can only see their own.

**Q: Can I see a job's full financials and documents?**
Yes — click the **"View Details →"** link on any job row. You'll see
the full job detail page with all financials, margins, documents, and
supplements.

---

*This guide reflects the Accounting workflow as of commit `da9b80b`.
If new fields, buttons, or workflows are added in future updates, this
guide should be reviewed and updated to match.*
