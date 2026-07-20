# Wickham Roofing AI Pipeline (V4 "Truck Server")

The **V4 — Independent CRM & Office Pipeline** is a complete local operating system for Wickham Roofing. Running entirely on a field office laptop via **FastAPI**, **SQLite WAL mode**, and **Ngrok**, it orchestrates the full job lifecycle (intake, math, PDF generation, and QBO CSV exports) natively.

A proprietary, zero-cost, multi-agent AI pipeline and local CRM for insurance roofing operations. Built on **Python 3.11+**, **Gemini 2.5 Flash**, **FastAPI**, **ReportLab**, and **SQLite WAL**, this system completely bypasses expensive SaaS subscriptions (like JobNimbus) by running fully locally on a field office laptop.

## Architecture & Operational Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                    WICKHAM ROOFING "TRUCK SERVER"                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  FIELD OPERATIONS (Mobile SPA via Ngrok)                            │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐                          │
│  │ Intake   │─▶│ Local    │─▶│ Photo     │                          │
│  │ Form     │  │ Storage  │  │ Uploads   │                          │
│  └──────────┘  └──────────┘  └───────────┘                          │
│                                                                     │
│  OFFICE DASHBOARD (Local Desktop Interface)                         │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐  ┌──────────────────┐  │
│  │ Intake   │─▶│ EV / SoL │─▶│ Climate   │─▶│ PDF Vaulting     │  │
│  │ Pipeline │  │ Parsing  │  │ Gating    │  │ & Signatures     │  │
│  └──────────┘  └──────────┘  └───────────┘  └──────────────────┘  │
│                                                                     │
│  AUTOMATED PAPERWORK MATRIX (ReportLab)                             │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐  ┌──────────────────┐  │
│  │ Evidence │  │ Supplier │  │ GA Notice │  │ Certificate of   │  │
│  │ Grid PDF │  │ PO PDF   │  │ of Cancel │  │ Completion     │  │
│  └──────────┘  └──────────┘  └───────────┘  └──────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Engine Versions & Evolution

### V4 — Local CRM Pivot ("Truck Server") ✅
The final evolution of the pipeline, transitioning the entire operational lifecycle to a standalone, zero-cloud architecture.
- **SQLite WAL State Machine**: Replaced JobNimbus with an indestructible, locally hosted SQLite database utilizing Write-Ahead Logging (WAL) and hot `VACUUM INTO` backups. Fully hardened with explicit `BEGIN IMMEDIATE` transactions to eliminate deadlocks.
- **Universal Claim AST**: Enforces mathematical determinism using Pydantic V2 `UniversalClaimAST` models to parse EagleView and Statement of Loss (SoL) PDFs securely before the logic reaches the `SupplementEngine`.
- **Role-Tailored SQL Views**: Instantly projects immutable operational metrics (like `live_material_board` and `financial_delta_view`) for zero-latency dashboard delivery.
- **Manual Review & Resume**: Automatically halts erroneous extractions and flags them for manual review. Dashboard operators can resolve these flags and seamlessly resume the pipeline to generate legally-binding PDFs.
- **Paperwork Matrix**: Generates strict Georgia Statutory Compliance documents and Supplier Purchase Orders directly from deterministic `MaterialBOM` calculations.
- **Robust Connection Manager**: Incorporates a self-healing WebSocket infrastructure with active background heartbeat monitoring to instantly sweep inactive connections.

### Phase 9 — Field Rep Identity System ✅
- **Dynamic Canvasser Identities**: Retired static `.env` PINs in favor of a dynamic `field_reps` SQLite table.
- **Admin Management UI**: Added an integrated admin interface (`/admin/reps`) to securely onboard, edit, and offboard field personnel.
- **Rich Identity JWTs**: Implemented JWT payloads that embed the canvasser's `rep_id` and `rep_name`, ensuring accurate attribution in the job intake and commission generation pipelines.

### V2 & V3 — AI Supplement & Vision Engines ✅
The core artificial intelligence layers powering the system's logic.
- **V2 Supplement Engine**: Deterministic insurance supplement generation. Extracts EagleView measurements via `pdfplumber`, reconciles discrepancies with pure-Python math, and generates professional supplement request PDFs with AI-written narratives.
- **V3 Vision Engine**: Multimodal roof damage detection pipeline using Gemini 2.5 Flash's vision capabilities. Generates ReportLab evidence grids with forensic annotations.

## Tech Stack

| Component | Technology | Monthly Cost |
|---|---|---|
| Language | Python 3.11+ | $0 |
| AI Provider | Google Gemini 2.5 Flash (free tier) | $0 |
| Local CRM | SQLite (WAL mode) | $0 |
| Web Server | FastAPI + Uvicorn | $0 |
| Task Queue | Redis + ARQ | $0 |
| Local Tunneling | Ngrok / Cloudflare | $0 |
| PDF Generation | ReportLab | $0 |
| PDF Parsing | pdfplumber | $0 |
| Frontend | Vanilla JS + Tailwind CSS | $0 |
| Testing | Pytest (209+ green tests) | $0 |

## Pre-Flight Operational Safeguards

To ensure system stability on a local field laptop, the following structural constraints are enforced:
1. **Storage Bloat Prevention**: The SQLite backup engine enforces a strict 10-file maximum retention limit. Older backups are automatically unlinked.
2. **Stale Data Protection**: The mobile canvasser form uses a 2-hour TTL cache limit.
3. **Perimeter Lockdown**: The FastAPI `CORSMiddleware` strictly rejects wildcard origins.
4. **Environment Isolation**: A strict Dev/Prod split enforced by the `APP_ENV` variable protects production data during active development.

## Quick Start

```bash
# Clone
git clone https://github.com/blairmichaelg/JobNimbus_controller.git
cd JobNimbus_controller

# Environment
python -m venv venv
.\venv\Scripts\activate          # Windows
source venv/bin/activate         # Linux/Mac
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your GEMINI_API_KEY

# Test Baseline Validation
python -m pytest tests/ -v

# Start the Truck Server (Local Field Mode)
uvicorn app.main:app --reload
```

## Testing

The system maintains a strict 100% green test baseline to prevent financial calculation errors.

```bash
# Execute the full test suite
python -m pytest tests/ -v

# Isolate forensic engine validation
python -m pytest tests/test_supplement_engine.py -v
python -m pytest tests/test_climate_gate.py -v
```

## Zero-Code Cloud Backup via Google Drive for Desktop

To ensure data resilience without relying on third-party SaaS pipelines or AWS S3 (`boto3`), the V4 Truck Server utilizes a "Zero-Code" backup strategy using Google Drive for Desktop.

1. **Install Google Drive for Desktop** on the Windows machine hosting the Truck Server.
2. **Configure Folder Sync**: Open Drive settings and select the `JobNimbus_controller/data/backups` directory to sync automatically with Google Drive.
3. **Automated SQLite Exports**: The system's cron job natively executes `VACUUM INTO` to safely dump WAL-mode snapshots into the `data/backups` folder.
4. **Hands-Free Reliability**: Google Drive for Desktop seamlessly uploads these new snapshots to the cloud in the background, providing off-site retention and disaster recovery without any custom cloud SDKs in the codebase.

## License

Proprietary — Wickham Roofing LLC. All rights reserved.
