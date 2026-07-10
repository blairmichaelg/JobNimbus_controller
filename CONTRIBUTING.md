# Contributing to Wickham Roofing CRM (V4 "Truck Server")

Welcome to the Wickham Roofing AI pipeline repository. This system powers our entire operations—calculating material orders, gating strict statutory compliance, and producing legally binding PDFs. 

Because this application runs entirely locally on field office hardware with zero remote cloud SaaS safety nets, we maintain an exceptionally high standard for code integration.

## 1. The Prime Directive: Zero-Regression Stability
This is not a web app where a bug just causes a broken button. A bug in the math engine results in Wickham Roofing under-ordering thousands of dollars of materials.

Therefore, **we strictly enforce a 100% green test baseline**. 
If you add a feature, you add tests. If you touch `supplement_engine.py`, you test every mathematical edge case (e.g. lengths of 0, `None` types, zero-clamping). If your pull request drops test coverage or causes a failure, it will be rejected.

## 2. Setting Up Your Environment
To run the system locally for development:

```bash
python -m venv venv
# Activate the environment
# Windows: .\venv\Scripts\activate
# Linux/Mac: source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
```

You must ensure that your `APP_ENV` variable in `.env` is set to `development`. This ensures that local test databases (`jobnimbus_dev.db`) are used and production backups are never polluted.

## 3. The Architecture Split
If you are contributing to the AI or Supplement features, you must understand the bifurcation:
1. **`app/services/supplement_engine.py`**: This is pure math. No databases, no external dependencies, no side-effects. It takes inputs and returns calculated outputs.
2. **`app/workers/supplement_processor.py`**: This is the orchestrator. It manages the queue, handles the database, writes the audit trails, and catches exceptions.

Do **not** mix orchestration logic into the math engine, and do **not** perform calculations in the orchestrator.

## 4. Running the Test Suite
Before committing any changes, run the full test suite and type checker:

```bash
# Run all tests
python -m pytest tests/ -v

# Run static type checking
python -m mypy .

# Run the linter
ruff check .
```

Ensure all tests pass and `mypy` returns zero errors.

## 5. Security & Hygiene
- **Never commit databases**: `*.db`, `*.db-shm`, and `*.db-wal` files are strictly ignored. Never force-add them.
- **Never commit `.env` files**: All secrets remain completely un-tracked.
- **Path Traversal & IDOR**: Any endpoint manipulating database records MUST use `uuid.UUID()` validation on its parameters and strictly verify ownership with compound SQL `WHERE` clauses.

Thank you for helping keep the Truck Server robust!
