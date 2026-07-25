# Wickham Roofing — Operations Guide

**Truck Server v4 · Operations Role (Scott)**

This guide covers the Operations Command board: tracking material
orders, confirming deliveries, and scheduling install crews. Your role
is focused on keeping jobs moving through the production pipeline once
a supplement has been approved.

---

## 1. Logging In

1. Open the app and enter your assigned 4-digit PIN.
2. On success, you're taken to **"Scott's Operations Board"** — your
   main working screen.

**Note:** Your access is scoped specifically to production logistics.
You will not be able to view financials, commissions, or the Admin
control panel — those are restricted to the Tech Admin and Accounting
roles by design. If you ever try to open a restricted page directly,
the system will block you with a security error rather than showing
any data.

---

## 2. Understanding the Operations Board

The board is organized into three panels, each representing a stage a
job passes through after its supplement is approved and before
installation begins.

### Panel 1: Alert — Materials Needed
**"Supplement approved. Awaiting material order placement."**

Jobs appear here the moment a supplement is approved and no material
order has been placed yet. This is your cue to place the order with
your supplier.

- Click **"Mark Ordered"** once you've placed the order.
- If no jobs are waiting, you'll see: **"No pending material orders."**

### Panel 2: Awaiting Delivery
**"Materials ordered. Waiting for arrival on site."**

Jobs appear here once you've marked materials as ordered, but before
they've physically arrived on site.

- Click **"Mark On Site"** once the materials have actually arrived at
  the job location.
- If no jobs are waiting, you'll see: **"No materials awaiting delivery."**

### Panel 3: Ready to Build
**"Materials on site. Awaiting crew assignment."**

Jobs appear here once materials have arrived. This is where you assign
a crew and set an install date.

- If no jobs are ready, you'll see: **"No jobs ready to build."**

---

## 3. Marking Materials as Ordered

1. Find the job under **"Alert: Materials Needed."**
2. Click **"Mark Ordered."**
3. You'll be asked to confirm: **"Confirm materials have been ordered
   for this job?"**
4. Once confirmed, the page reloads and the job moves into the
   **Awaiting Delivery** panel.

If something goes wrong, you'll see a popup: **"Error updating
status."** If this happens, try again, and contact the Tech Admin if
it persists.

---

## 4. Marking Materials as On Site

1. Find the job under **"Awaiting Delivery."**
2. Once the materials have physically arrived, click **"Mark On Site."**
3. You'll be asked to confirm: **"Confirm materials have arrived on
   site for this job?"**
4. Once confirmed, the page reloads and the job moves into the
   **Ready to Build** panel, ready for crew scheduling.

**Important:** Only click this once materials have actually arrived —
this step drives the entire pipeline forward, and other roles rely on
this status being accurate. Marking it too early can cause a crew to
be scheduled before materials are actually on hand.

---

## 5. Scheduling a Crew

1. Find the job under **"Ready to Build."**
2. Fill in:
   - **Assign Crew** — type the crew name (e.g. "Alpha Team").
   - **Install Date** — pick the date using the date picker.
3. Click **"Schedule Installation."**
4. You'll be asked to confirm with your exact entries, for example:
   **"Schedule Alpha Team for install on 2026-07-28?"**
5. Once confirmed, the page reloads once the job is scheduled.

Double-check the crew name and date before confirming — the confirmation
message shows exactly what you typed, so use that as a chance to catch
typos before committing.

If something goes wrong, you'll see a popup: **"Error scheduling
crew."** Double-check the crew name and date, then try again.

---

## 6. What You Cannot Do (By Design)

For security and role isolation, your access is intentionally limited:

- You cannot view job financials, commissions, or accounting data.
- You cannot access the Admin control panel, Triage, or the Emergency
  Override tool.
- You cannot view or edit EagleView/Statement of Loss documents,
  supplements, or carrier correspondence.

If you ever try to access a restricted page directly, you'll be blocked
with a security error — this is expected and protects sensitive
homeowner and financial data.

---

## FAQ

**Q: I marked materials as ordered by mistake. Can I undo it?**
There is a confirmation step before this action fires, so double-check
before confirming. If you've already confirmed in error, contact the
Tech Admin to correct the job's status.

**Q: A job isn't showing up on my board at all. What's wrong?**
Jobs only appear once their supplement has been approved. If a job
should be here but isn't, check with the Tech Admin — it may still be
in the supplement/carrier approval stage.

**Q: What's the difference between "Mark Ordered" and "Mark On Site"?**
"Mark Ordered" means you've placed the order with your supplier. "Mark
On Site" means the materials have physically arrived at the job
location and crew scheduling can begin. Don't mark something on site
until it's actually there — this drives the real-world production
schedule and downstream crew assignment.

**Q: Can I see how much a job is worth or what the crew is being paid?**
No — financials and commissions are handled by Accounting and Admin.
Your board is focused purely on logistics: ordering, delivery, and
scheduling.

**Q: What happens if I try to access an admin page directly?**
You'll be blocked with an access error. This is intentional — Operations
access is scoped to production logistics only, and this protection
applies even if you know the exact web address of a restricted page.

**Q: I typed the wrong crew name or date. What happens?**
Before anything is saved, you'll see a confirmation popup showing
exactly what you entered — for example, "Schedule Alpha Team for
install on 2026-07-28?" Use that moment to check your entry. If you
already confirmed with a mistake, contact the Tech Admin to correct it.

---

*This guide reflects the Operations workflow as of commit `350d753`.
If new panels, buttons, or workflows are added in future updates, this
guide should be reviewed and updated to match.*
