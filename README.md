# Wickham Roofing AI Pipeline (V4 "Truck Server")

The **V4 — Independent CRM & Office Pipeline** is a complete local operating system for Wickham Roofing. Running entirely on a field office laptop via **FastAPI**, **SQLite WAL mode**, and **Ngrok**, it orchestrates the full job lifecycle (intake, math, PDF generation, and QBO CSV exports) natively.

A proprietary, zero-cost, multi-agent AI pipeline and local CRM for insurance roofing operations. Built on **Python 3.11+**, **Gemini 2.5 Flash**, **FastAPI**, **ReportLab**, and **SQLite WAL**, this system completely bypasses expensive SaaS subscriptions (like JobNimbus) by running fully locally on a field office laptop.

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
│  │ AI/Math  │─▶│ EagleView│─▶│ Financials│─▶│ Material Order   │  │
│  │ Engine   │  │ Parsing  │  │ & Margins │  │ & PO Generation  │  │
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
- **SQLite WAL State Machine**: Replaced JobNimbus with an indestructible, locally hosted SQLite database utilizing Write-Ahead Logging (WAL) and hot `VACUUM INTO` backups.
- **Unified Office Dashboard**: A composite Tailwind dashboard displaying real-time metadata, production schedules, margin thresholds, and dynamic paperwork downloads.
- **Paperwork Matrix**: Generates strict Georgia Statutory Compliance documents (Notice of Cancellation, Certificate of Completion) and Supplier Purchase Orders directly from deterministic `MaterialBOM` calculations.
- **Frontend Resilience**: A lightweight Vanilla JS SPA with `localStorage` injection enforcing 2-hour cache TTLs to protect canvassers from cellular drops.

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
| Local Tunneling | Ngrok | $0 |
| PDF Generation | ReportLab | $0 |
| PDF Parsing | pdfplumber | $0 |
| Frontend | Vanilla JS + Tailwind CSS | $0 |
| Testing | Pytest (122 green tests) | $0 |

## Pre-Flight Operational Safeguards

To ensure system stability on a local field laptop, the following structural constraints are enforced:
1. **Storage Bloat Prevention**: The SQLite backup engine enforces a strict 10-file maximum retention limit. Older backups are automatically unlinked.
2. **Stale Data Protection**: The mobile canvasser form uses a 2-hour TTL cache limit. If the form hasn't been submitted in two hours, the `localStorage` payload is forcefully destroyed to prevent cross-customer data corruption.
3. **Perimeter Lockdown**: The FastAPI `CORSMiddleware` strictly rejects wildcard origins, only permitting local development ports and secure `ngrok-free.app` regex matches.

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
# Execute the full 122-test suite
python -m pytest tests/ -v

# Isolate financial math validation
python -m pytest tests/test_job_costing.py -v
python -m pytest tests/test_reconciliation.py -v

# Isolate PDF generation and form layouts
python -m pytest tests/test_pdf_generator.py -v
```

## License

Proprietary — Wickham Roofing LLC. All rights reserved.

## Legacy SaaS Integration (Deprecated)

> [!WARNING]
> In V4, all cloud-based SaaS integrations have been permanently quarantined. The local pipeline operates independently.

### JobNimbus (Quarantined)
Former webhook integration used to mutate JobNimbus API states. Code moved to `legacy_jobnimbus/`.

### AccuLynx (Quarantined)
Former endpoints configured for estimating APIs. Deprecated in favor of the local Automath Engine.
