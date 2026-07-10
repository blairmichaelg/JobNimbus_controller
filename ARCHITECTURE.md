# SYSTEM ARCHITECTURE: WICKHAM ROOFING "TRUCK SERVER" (V4)

## 1. PROJECT OVERVIEW

The Wickham Roofing AI Controller has evolved from a JobNimbus webhook middleware (V1) into a fully standalone local CRM and AI-driven workflow engine (V4 "Truck Server"). The system runs entirely locally on a field office laptop, executing the complete roofing lifecycle—from lead intake and document extraction to strict climate-based mathematical estimating and legally binding PDF generation—with zero reliance on external SaaS CRMs.

## 2. TECHNOLOGY STACK

* **Language:** Python 3.11+
* **Framework:** FastAPI (high-concurrency async web server)
* **Local State Machine:** SQLite running in Write-Ahead Logging (WAL) mode
* **Task Queue:** ARQ (Async Redis Queue) + Local Redis
* **AI Provider:** Google Gemini 2.5 Flash via `google-genai`
* **PDF Extraction & Generation:** `pdfplumber` + `ReportLab`
* **Frontend:** Vanilla JS Single Page Application (SPA) + Tailwind CSS
* **Tunneling:** Cloudflare / Ngrok for remote canvasser access

## 3. CORE ARCHITECTURAL PIPELINES

### A. The Office Dashboard & Field Intake
The web interface is served directly from FastAPI using Jinja2 templates.
- **Intake Form:** A resilient, `localStorage`-backed form used by canvassers in the field. It enforces a 2-hour Time-to-Live (TTL) cache to prevent cross-customer data corruption in low-connectivity areas.
- **Office Dashboard:** Displays active jobs, pipeline statuses, margin calculations, and outstanding tasks.

### B. The Forensic Supplement Pipeline
The system automates the creation of complex insurance supplements by comparing EagleView roof measurements against adjuster Statements of Loss (SoL), cross-referencing local building codes, and applying deterministic math.

This pipeline is strictly bifurcated for safety and testability:
1. **`SupplementEngine` (The Pure Math Core):** Located in `app/services/supplement_engine.py`. This class is purely deterministic. It takes raw inputs (e.g., eave lengths, ridge lengths, squares) and returns exact material counts (e.g., Ice & Water Shield rolls) based on physical dimensions and climate-zone gates. It has no knowledge of databases, queues, or web requests.
2. **`SupplementProcessor` (The Orchestrator):** Located in `app/workers/supplement_processor.py`. This class runs in the background ARQ worker. It orchestrates the pipeline: extracting PDFs, generating rule-based discrepancies, catching errors, updating the database, and triggering the final ReportLab PDF build.

### C. The Fail-Loud / Resume Lifecycle
Because the supplement pipeline handles legally binding financial outputs, it implements a strict "fail-loud" mechanism.
- If the `SupplementProcessor` encounters malformed PDF data or invalid mathematical inputs (e.g., zero-length eaves), it immediately traps the exception.
- It writes a `MANUAL REVIEW REQUIRED: <error>` note to the `supplement_flags` database table and transitions the job to `JobStatus.PENDING_MANUAL_REVIEW`.
- **Flag Resolution:** The office administrator uses the `PATCH /api/field/jobs/{job_id}/flags/{flag_id}` endpoint to manually correct the discrepancy. This endpoint leaves an immutable audit trail (`RESOLVED: <note>`).
- **Resumption:** Once all flags are resolved, the `POST /api/field/jobs/{job_id}/resume-supplement` endpoint re-queues the job. The ARQ worker detects the `resume=True` flag, bypasses the extraction/gating phases, and immediately proceeds to generate the AI narrative and the final PDF document.

### D. The Paperwork Matrix
The system uses `ReportLab` to programmatically generate:
- **Statutory Compliance:** Georgia Notice of Cancellation, Certificate of Completion.
- **Material Orders:** Supplier Purchase Orders (POs) generated directly from the deterministic math engine.
- **Contingency Agreements:** Captures HTML5 canvas signatures from the field app and permanently vaults them on the local file system.

## 4. DATA INTEGRITY & SECURITY BOUNDARIES

1. **SQLite WAL & Backups:** To prevent catastrophic data loss on a local laptop, SQLite operates in WAL mode for concurrent read/writes. The `app.core.backup` module executes scheduled hot `VACUUM INTO` backups, enforcing a strict 10-file retention limit to prevent disk bloat.
2. **Environment Isolation:** A strict Dev vs. Prod separation is enforced via the `APP_ENV` variable. Backups and database operations dynamically switch scopes based on this flag.
3. **Path Traversal Defense:** All endpoints manipulating job data or flags enforce strict `uuid.UUID` validation, preventing malicious path injection.
4. **IDOR Defense:** The flag resolution endpoint uses combined `WHERE id = ? AND job_id = ?` queries to ensure operators cannot tamper with flags belonging to cross-tenant jobs.

## 5. REPOSITORY STRUCTURE

```
JobNimbus_controller/
├── app/
│   ├── api/            # FastAPI Routers (field_routes, office_routes)
│   ├── core/           # Database, Models, Pipeline Config
│   ├── services/       # AI logic, PDF Parsing, Pure Math (SupplementEngine)
│   ├── workers/        # ARQ Queue Consumers (SupplementProcessor)
│   ├── templates/      # Jinja2 HTML Views
│   └── static/         # CSS/JS Assets
├── scripts/            # Bootstrap, backup, and CLI utilities
├── tests/              # 130+ passing Pytest assertions
├── field_docs/         # Generated PDFs (Git-ignored)
└── field_photos/       # Uploaded Images (Git-ignored)
```