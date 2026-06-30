# Wickham Roofing AI Controller

A proprietary, zero-cost, multi-agent AI pipeline for insurance roofing operations. Built on **Python 3.11+**, **Gemini 2.5 Flash**, **ReportLab**, and **Pydantic V2**, this system automates the full lifecycle from initial roof inspection through supplement filing — bypassing expensive CRM subscriptions entirely.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    WICKHAM ROOFING AI PIPELINE                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  V2 SUPPLEMENT ENGINE (Complete)                                    │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐  ┌──────────────────┐  │
│  │ EagleView│─▶│ Carrier  │─▶│ Reconcile │─▶│ Supplement PDF   │  │
│  │ Extractor│  │ SoL (LLM)│  │ (Pure Py) │  │ + AI Narrative   │  │
│  └──────────┘  └──────────┘  └───────────┘  └──────────────────┘  │
│                                                                     │
│  V3 INSPECTION ENGINE (Complete)                                    │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐  ┌──────────────────┐  │
│  │ Local/LAN│─▶│ Gemini   │─▶│ Forensic  │─▶│ Evidence Grid    │  │
│  │ iPad API │  │ Vision   │  │ Analysis  │  │ PDF              │  │
│  └──────────┘  └──────────┘  └───────────┘  └──────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Engine Versions

### V2 — Zero-Cost Supplement Engine ✅
Deterministic insurance supplement generation. Extracts EagleView measurements via `pdfplumber`, extracts Carrier Statements of Loss via Gemini multimodal File API, reconciles discrepancies with pure-Python math, and generates professional supplement request PDFs with AI-written narratives citing Georgia building codes.

- **Complexity Engine**: Dynamic waste factor (10–22%) based on facets, pitch, and valley footage
- **Material BOM**: Deterministic bill of materials using industry-standard coverage constants
- **Carrier Router**: Zero-temp Gemini classifier identifies Xactimate vs Symbility formats
- **Smart Code Router**: Zero-cost RAG mapping discrepancy categories to IRC/Georgia building codes

### V3 — Inspection Vision Engine ✅
Multimodal roof damage detection pipeline using Gemini 2.5 Flash's vision capabilities.

- **Inspection Models**: Flat Pydantic schemas for Gemini structured output (hail hits, crease marks, granule loss, exposed fiberglass)
- **Drive Sync Guard**: 10-second mtime staleness check + SHA256 deduplication for Google Drive folders
- **Sequential Processor**: Rate-limit-safe batch processing with exponential backoff + jitter
- **Image Resizer**: Pillow-based downsampler (800px max) preventing OOM in ReportLab
- **Performance Cache**: SQLite thread-safe DB preventing redundant API token burn
- **LAN Field UX**: FastAPI endpoints for direct iPad photo uploads and signature capture
- **PDF Evidence Grid**: ReportLab photo grid with per-image forensic annotations and signatures
- **CPA QuickBooks Bridge**: CSV exporter matching Intuit's bulk import standards


## Tech Stack

| Component | Technology | Cost |
|---|---|---|
| Language | Python 3.11+ | $0 |
| AI Provider | Google Gemini 2.5 Flash (free tier) | $0 |
| PDF Generation | ReportLab | $0 |
| PDF Parsing | pdfplumber | $0 |
| Data Contracts | Pydantic V2 | $0 |
| Image Processing | Pillow | $0 |
| Web Framework | FastAPI + Uvicorn | $0 |
| Task Queue | ARQ (async Redis) | $0 |
| Logging | structlog | $0 |

## Project Structure

```
app/
├── api/              # FastAPI webhook routes
├── core/             # Business logic & data models
│   ├── supplement_models.py    # V2 Pydantic schemas
│   ├── inspection_models.py    # V3 Pydantic schemas + Drive sync guard
│   ├── reconciliation.py       # Deterministic math engine
│   ├── complexity.py           # Dynamic waste factor calculator
│   ├── coverage_constants.py   # Industry material coverage rates
│   ├── code_router.py          # Zero-cost building code RAG
│   ├── field_mapper.py         # CRM field translation layer
│   └── temp_manager.py         # atexit temp file cleanup
├── services/         # External integrations
│   ├── ai_service.py           # Gemini SDK wrapper (V2 + V3)
│   ├── pdf_generator.py        # ReportLab document renderer
│   ├── pdf_extractor.py        # pdfplumber EagleView parser
│   └── jobnimbus_client.py     # CRM HTTP client
├── workers/          # Async task processors
│   ├── supplement_processor.py # V2 supplement pipeline orchestrator
│   └── inspection_processor.py # V3 vision engine orchestrator
└── config.py         # Pydantic Settings (env validation)

building_codes/       # IRC & Georgia amendment XML files
tests/                # pytest suite (117 tests)
```

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
# Edit .env with your GEMINI_API_KEY and other credentials

# Test
python -m pytest tests/ -v

# Run supplement engine (standalone)
python run_phase4.py
```

## Testing

```bash
# Full suite
python -m pytest tests/ -v

# Specific modules
python -m pytest tests/test_inspection_models.py -v    # V3 schemas
python -m pytest tests/test_inspection_engine.py -v    # V3 engine
python -m pytest tests/test_reconciliation.py -v       # V2 math
python -m pytest tests/test_ai_service.py -v           # AI integration
```

## License

Proprietary — Wickham Roofing LLC. All rights reserved.
