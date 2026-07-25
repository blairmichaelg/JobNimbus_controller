# Wickham Roofing — Canvasser & Field Rep Guide

**Truck Server v4 · Field Role**

This guide covers everything a canvasser or field sales rep needs to know
to use the Wickham Roofing field app: logging in, creating leads, taking
photos, capturing signatures, and understanding how offline mode and
error recovery work.

---

## 1. Logging In

1. Open the app on your phone or tablet. You'll see the **Wickham Roofing**
   login screen with the label **"Truck Server v4."**
2. Tap **"Enter Your PIN"** and use the on-screen keypad (0–9, ⌫) to type
   your assigned 4-digit PIN.
3. If your PIN is wrong, you'll see **"✕ Incorrect PIN. Try again."**
   Re-enter carefully — don't guess repeatedly.
4. On success, you're taken straight to the **New Lead** screen.

**Security reminder:** Your PIN is yours only. Never share it, and never
let someone else work inside your session. The system checks your identity
on every job you touch — using someone else's PIN can cause job ownership
issues down the line.

---

## 2. Creating a New Lead

When you're with a homeowner and ready to start a job, you'll fill out the
**New Lead** form.

### Step-by-step

1. **Job Type** — Choose either:
   - **Insurance Restoration (Contingency)** — for storm/insurance claims.
   - **Retail Cash** — for out-of-pocket jobs.
2. **Homeowner Name** — Use their legal or billing name.
3. **Address Line 1, City, State, Zip** — Enter manually, or tap
   **📍 Auto-Fill Address from GPS** to have the app fill it in automatically.
   - ⚠️ **Always double-check the GPS address.** Rural addresses in Thomas
     County can come back slightly wrong or incomplete. If you see
     **"Failed to reverse geocode"** or a **GPS Error**, just type the
     address manually.
4. **Phone** — Required.
5. **Date of Loss (Optional)** — If the homeowner knows when the storm
   damage happened, enter it here.
6. **Property Photos (up to 15)** — Tap **📷 Tap to add photos** to open
   your camera or photo library.

---

## 3. Taking and Reviewing Photos

- You can add **up to 15 photos** per job. A counter shows **"X / 15 photos"**
  as you go.
- **If you try to add more than 15 at once:** the app keeps the first
  ones that fit and gives you two clear warnings so you don't miss it:
  - A toast message: *"Maximum of 15 photos allowed. 5 photo(s) were
    not added."*
  - The photo counter itself turns **red and bold** for about 6 seconds,
    showing something like *"15 / 15 photos — 5 rejected!"*
  
  If you see either of these, go back and manually pick which extra
  shots matter most, then remove a less important photo to make room.
- **Reviewing your photos:** Tap any thumbnail to open it full-screen and
  check focus and lighting before submitting. If a photo is blurry or
  unclear, tap the **✕** on that thumbnail to remove it and retake it.

### Photo tips
- Capture every roof slope, damage area, flashing, and accessory (vents,
  skylights, chimneys).
- Shoot in good light. Avoid heavy shadows or backlighting.
- Take a wide shot of each side of the house, then close-ups of damage.

---

## 4. Capturing the Signature (Insurance Jobs)

If the job type is **Insurance Restoration**, a signature is **required**
before you can submit — the app will block submission with **"Please lock
the signature before submitting"** if you skip it.

### How to sign
1. Have the homeowner draw their signature on the canvas under
   **"Homeowner Signature (Contingency Agreement)."**
2. If you make a mistake before locking, tap **Clear Signature** to
   wipe the canvas and start over.
3. If nothing is drawn, tapping the lock button shows
   **"Please draw a signature before locking."**
4. Once a signature is drawn, tap **Lock Signature**.
   - The button changes to **✏️ Edit Signature**, and the standalone
     **Clear Signature** button disappears — you don't need it anymore
     once locked.
   - If you or the homeowner need to redo it, tap **✏️ Edit Signature**.
     This automatically **clears the canvas** so you get a fresh, blank
     space to redraw — no overlapping ink, no extra button needed.
5. When you're satisfied, tap **Submit Lead**.

**Retail Cash jobs** do not require a signature at this stage.

---

## 5. Submitting the Lead

When you tap **Submit Lead**, you'll see a progress modal with messages like:
- "Creating Lead..."
- "Uploading Photo X of Y..."
- "Generating Contract..." *(this is the final step you'll see before completion)*

If everything succeeds, you'll see **"Lead Captured"** and
**"The office has been notified."** — the job is now live in the system.

---

## 6. If Something Goes Wrong Mid-Submission (Server Errors)

Sometimes the server itself rejects a step — for example, a photo file is
too large, or there's a temporary server issue. This is different from
having no signal (covered in Section 7).

### What you'll see
If a photo or the signature upload fails due to a server-side error, the
app **stops the submission** and shows a message like:

> *"Photo 3 failed: [error detail] — Tap Submit Lead again to retry the
> remaining steps."*

### What to do — and why it's safe and efficient
**Just tap Submit Lead again.** The app is smart about retries:

- It will **not** create a duplicate job — it remembers the lead was
  already created and picks up exactly where it left off.
- It will **not** re-upload photos that already succeeded. If photo 3
  out of 15 failed, retrying only re-attempts photo 3 onward — photos
  1 and 2 are already safely on the server and won't be sent again.
- If all your photos succeeded but the signature failed, retrying only
  re-sends the signature — none of your photos get re-uploaded.

This means you don't need to worry about wasting time or mobile data
re-sending things that already worked. The app only retries the exact
step that failed.

### If it keeps failing
If retrying doesn't work after 2–3 attempts, note the job address and
contact the office — there may be an issue with a specific file (for
example, a corrupted photo) that needs a fresh photo taken instead.

---

## 7. Working Offline (No Signal / Weak Signal)

The app is built to handle bad service in the field, whether you have zero
signal or a connection that drops partway through a submission.

### If you're fully offline when you submit
You'll see: **"Offline Mode: Lead, photos, and signature saved locally.
Will sync automatically when connection returns."**

### If your connection drops mid-submission
The app saves **everything** — the lead info, all photos, and the
signature — as one complete package, tied to the job that was already
created if it got that far. You do not need to worry about photos or
signatures getting lost, and you will not end up with a duplicate job
once it syncs.

### How you know something is still waiting to sync
Look for a small badge in the corner of the screen showing **"X pending
sync."** This badge stays visible — it does not disappear after a few
seconds like the offline banner does — so you always know if work is
still waiting to reach the office.

- **Yellow badge** — normal. Items are waiting for a connection and will
  sync automatically. The count goes down as items succeed.
- **Red badge saying "FAILED — contact office"** — something is
  permanently stuck (for example, a corrupted photo file that the server
  keeps rejecting). This will not fix itself by waiting. **Contact the
  office right away** so they can help resolve that specific job.

### What to do if you see a pending sync badge
- **Yellow:** No action needed beyond getting to a signal area. It syncs
  automatically.
- **Red:** Note the job/address shown and contact the office immediately
  — this item needs manual attention and won't clear on its own.

---

## 8. Common Situations & What They Mean

| What you see | What it means | What to do |
|---|---|---|
| "✕ Incorrect PIN. Try again." | Wrong PIN entered | Re-enter your PIN carefully |
| "Failed to reverse geocode." | GPS couldn't find an address | Type the address manually |
| "Photo X failed: [error] — Tap Submit Lead again to retry" | A server error stopped the submission | Tap Submit Lead again — it's safe, skips completed photos, and won't duplicate the job |
| "Maximum of 15 photos allowed..." toast + red "X rejected!" counter | You selected more than 15 photos | Remove a less important photo, then re-add the one you need |
| "Please draw a signature before locking." | Signature canvas is empty | Have the homeowner draw their signature |
| "Please lock the signature before submitting." | Signature was drawn but never locked | Tap Lock Signature before submitting |
| Yellow "X pending sync" badge | Work is saved locally, waiting for a connection | Get to a signal area — it will sync automatically |
| Red "FAILED — contact office" badge | An item is permanently stuck and needs help | Contact the office with the job details |
| "Offline Mode: Lead, photos, and signature saved locally." | You were offline when you submitted | No action needed — it will sync when connected |

---

## 9. What You Cannot Do (By Design)

For security, the field app strictly limits what canvassers can access:
- You cannot see or open jobs that aren't yours.
- You cannot access office, admin, or accounting screens.
- You cannot view other reps' commissions or job lists.

This is intentional — it protects homeowner data and keeps each rep's
work isolated and auditable.

---

## FAQ

**Q: Do I need to type my name every time I create a lead?**
No — the system already knows who you are from your PIN login and
attaches your identity automatically.

**Q: What if I lose signal right after I hit Submit?**
Nothing is lost. The entire lead — including photos and signature — is
saved as one package on your device and will sync automatically,
without creating a duplicate job, once you're back online.

**Q: A photo failed with an error message. Did I lose my lead, and will I have to re-upload everything?**
No to both. Your lead is safe, and any photos that already uploaded
successfully will NOT be sent again. Just tap **Submit Lead** — it only
retries the exact step that failed.

**Q: Can I take more than 15 photos?**
No, 15 is the maximum per job. If you try to add more, the app warns
you two ways: a toast message, and the photo counter briefly turning
red to show exactly how many were rejected.

**Q: What if the homeowner wants to redo their signature?**
Tap **✏️ Edit Signature** — it automatically clears the canvas so they
can draw a clean, fresh signature. This does not delete or restart the lead.

**Q: How do I know my offline lead actually made it to the office?**
Watch the pending-sync badge in the corner. Once it disappears (or the
count drops), it has successfully synced. If it ever turns red, that
means something needs office attention — it won't resolve itself.

**Q: Can I create a lead without a signature?**
Only for Retail Cash jobs. Insurance Restoration jobs require a locked
signature before you can submit.

**Q: What happens if GPS gives me the wrong address?**
Just overwrite the address fields manually — GPS is a shortcut, not a
guarantee, especially in rural areas.

**Q: I retried a failed submission a few times and it's still failing. What now?**
Stop retrying after 2–3 attempts. Note the job and the exact error
message, then contact the office — there may be a bad file or a larger
issue that needs manual review rather than repeated retries.

**Q: Who do I contact if something seems broken?**
Contact the office/Tech Admin if:
- You see a red "FAILED — contact office" badge.
- Retrying a failed submission doesn't resolve after a few tries.
- You believe a job was duplicated.
- Photos are consistently failing to upload.
- You're unsure whether a signature was captured correctly.

---

*This guide reflects the field app as of commit `c1d7bb6`. If the app's
screens, buttons, or error messages change in a future update, this
guide should be reviewed and updated to match.*
