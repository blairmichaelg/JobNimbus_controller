# Wickham Roofing V4 "Truck Server" - Field Runbook

This runbook provides emergency operational procedures for Scott during the first live dry run. If the V4 CRM behaves unexpectedly, execute the diagnostics below before escalating.

## 1. If the Upload Hangs (Mobile Field App)
- **Symptom**: The mobile browser spins indefinitely after tapping "Submit".
- **Diagnosis**: The `ngrok` tunnel may have expired or crashed.
- **Action**:
  1. Go to the office laptop terminal running `ngrok http 8000`.
  2. Verify the session status is `online`. If disconnected, press `CTRL+C` and restart the command.
  3. Send the *new* Ngrok URL to the canvasser. Note: The mobile app uses `localStorage` caching, so no field data was lost. They just need to reload with the new URL and tap submit again.

## 2. If the Margin is Red (Office Dashboard)
- **Symptom**: The Financials Card shows a red warning banner (Margin < 35%).
- **Diagnosis**: The dynamic math engine triggered a low-margin safety threshold based on your inputs.
- **Action**:
  1. Double-check the "Total Revenue" input vs the "Carrier RCV". Ensure no zeros are missing.
  2. Verify the Supplier PO PDF to ensure the `MaterialBOM` did not over-calculate the waste factor.
  3. If the math is correct, the roof is genuinely unprofitable.

## 3. If the PDF Doesn't Generate
- **Symptom**: Clicking "Download Estimate" or "Supplier PO" returns an error or a broken link.
- **Diagnosis**: The automated math engine (ReportLab) threw an exception during PDF rendering.
- **Action**:
  1. Open a new terminal on the office laptop.
  2. Run the diagnostic tool: `python scripts/analyze_logs.py`
  3. This will scan the `structlog` output for exact stack traces and identify the `job_id` that crashed. Send this trace to engineering.

## 4. If the Database is Locked (State Machine Stuck)
- **Symptom**: The job is stuck in `EV_PARSED` but you know the `MaterialBOM` was calculated.
- **Diagnosis**: An async task crashed halfway, leaving the claim orphaned from the state machine.
- **Action**:
  1. Identify the `job_id` from the dashboard URL.
  2. Use the SRE override tool to force the state machine forward:
     ```bash
     python scripts/recover_job.py <job_id> SUPPLEMENT_SUBMITTED
     ```
  3. Refresh the office dashboard. The job will now be unlocked.

> [!CAUTION]
> Never manually edit the `data/truck_server.db` SQLite file with external viewers (like DBeaver) while Uvicorn is running. The Write-Ahead Log (WAL) mode requires FastAPI to maintain the file lock. Use `recover_job.py` instead.
