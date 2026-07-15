# Changelog

## [0.7.0] - 2026-07-15
### Added & Fixed
- **State Machine Hardening**: Split `JobStatus` into Processing (ARQ) and Business (Operator) tracks with explicit API gates.
- **Strict Schedule Guards**: Added database-level SQLite blockers preventing installation scheduling before `MATERIALS_ON_SITE` is confirmed.
- **Append-Only Document Vault**: Refactored `job_documents` from a destructive UPSERT model to an immutable, append-only architecture for complete historical versioning.
- **Orchestrator Halt**: Modified the Master Office Pipeline to halt at `PENDING_OPERATOR_REVIEW` instead of automatically advancing states, ensuring human-in-the-loop validation.
- **Strict EagleView Extraction**: Upgraded the `pdf_extractor` to deterministically extract `Hips` and `Predominant Pitch`, failing loudly on unsupported formats, and returning SHA256 fingerprints natively.
- **Evidence-Bearing AST**: Expanded `UniversalClaimAST` to enforce strict provenance tracking (`source_doc_sha256`, `source_doc_id`, `ast_version`).
- **Anti-Hallucination Parser**: Replaced the obsolete ESX parser with a three-layer Statement of Loss (SoL) ingestion pipeline featuring structural (`pdfplumber`), semantic (`Gemini`), and mathematical (`Pydantic`) verification.
- **Automated Carrier Math Audits**: Wired the `process_supplement` ARQ worker to automatically flag carrier math inconsistencies from SoL parsing, intentionally halting the job into `PENDING_MANUAL_REVIEW` to prevent bad data progression.

## [0.6.1] - 2026-07-13
### Added & Fixed
- **Pre-Demo Stability Audit**: Resolved 7 critical and high-priority bugs identified during system audit.
- **Pipeline Lifecycle**: Fixed premature status transitions; EagleView uploads now transition to `EV_PARSED` instead of auto-invoicing via QBO export.
- **Data Integrity**: Corrected EagleView field name mapping in inspection letters and wired live database lookups for inspection addresses.
- **PDF Generation**: Hardened the supplement generator to dynamically filter and inject only job-specific, climate-triggered rules via explicit SQL JOINs.
- **File System Stability**: Centralized and synchronized all `FIELD_DOCS_DIR` path resolution across the orchestration layer and endpoints.
- **Error Handling**: Patched fatal `ImportError` exceptions in the material order route to ensure pristine demonstration stability.

## [0.6.0] - 2026-07-13
### Added & Fixed
- **Architectural Refactor**: Comprehensive backend hardening for the V4 Truck Server.
- **SQLite Concurrency**: Enforced explicit `BEGIN IMMEDIATE` transaction blocks and PRAGMA configurations (WAL, mmap, busy_timeout) to eliminate read-to-write database locks.
- **Universal Claim AST**: Built `ingestion_models.py` leveraging Pydantic V2 for mathematically deterministic extraction of adjustor claims.
- **Role-Tailored Projections**: Deployed `live_material_board` and `financial_delta_view` SQL Views for immediate operations and accounting insights.
- **WebSocket Zombie Sweeper**: Upgraded `Notifier` to `RobustConnectionManager` with an active background `asyncio` heartbeat loop isolating dead connections.

## [0.5.2] - 2026-07-13
### Added & Fixed
- **System Stability**: Resolved critical asynchronous Coroutine execution bugs in the V4 Truck Server pipeline affecting inspection doc generation.
- **Type Safety**: Enforced strict typing compliance (100% `mypy` passing) across `pdf_generator.py` ReportLab bindings.
- **Code Cleanliness**: Resolved all `ruff` static analysis linting errors by pruning unused imports, unused variables, and organizing module imports.
- **Testing Reliability**: Migrated `MagicMock` patches to `AsyncMock` to accommodate the newly refactored async pipeline architecture.

## [0.5.1] - 2026-07-10
### Added & Fixed
- **Security Hardening**: Patched UUID path traversal vulnerabilities across all `field_routes.py` mutation endpoints.
- **Backup Environment Targeting**: Scoped the SQLite hot backup system to only execute in production (`APP_ENV=production`), protecting production data from local development pollution.
- **Deterministic Math Engine**: Wired the pure mathematical `calculate_ice_and_water_rolls` function into the orchestrator pipeline for climate-gated calculations.
- **Fail-Loud Pipeline Resume**: Built the `PENDING_MANUAL_REVIEW` halting flow and a manual flag resolution `PATCH` endpoint, complete with IDOR defenses and an immutable audit trail.

## [0.5.0] - 2026-07-06
### Added
- **Infrastructure Hardening**: Implemented automated nightly ARQ garbage collection for `.tmp` artifacts.
- **Cryptographic Deduplication**: Replaced redundant file processing with SHA-256 stream hashing and API short-circuiting.
- **Atomic Concurrency**: Refactored SQLite state machine to use `json_insert()`, eliminating Optimistic Concurrency crash risks.

## [0.4.0] - 2026-06-30
### Added
- **V4 Local CRM Pivot (Truck Server)**: Full independent pipeline replacing SaaS CRMs.
- **SQLite WAL State Machine**: Replaced JobNimbus with a robust, concurrent local database.
- **Unified Office Dashboard**: Local UI displaying metadata, schedules, margins, and artifacts.
- **Paperwork Matrix**: Generates Supplier POs and Georgia Statutory Compliance Documents locally.

## [0.3.0]
### Added
- **V3 Vision Engine**: Multimodal roof damage detection using Gemini Flash.
- **Evidence Grids**: Auto-generates forensic photo grids for insurance adjusters.

## [0.2.0]
### Added
- **V2 Supplement Engine**: Deterministic insurance supplement generation based on EagleView logic.
- **Automath Engine**: Computes exact BOM and discrepancy reports.

## [0.1.0]
### Added
- Initial JobNimbus webhook orchestration framework.
