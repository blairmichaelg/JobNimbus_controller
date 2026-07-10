# Changelog

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
