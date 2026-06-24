# 🤖 SYSTEM INITIALIZATION DIRECTIVE: WICKHAM ROOFING AI ORCHESTRATOR

## 1. PROJECT OVERVIEW

You are an autonomous AI coding agent tasked with building an asynchronous, AI-driven middleware controller for a roofing enterprise. This middleware bridges a proprietary CRM (JobNimbus) and Google's Gemini AI models.
Your goal is to build a robust, queue-driven Python backend that intercepts webhooks, hydrates flat data, translates obfuscated database fields, processes cognitive tasks via LLMs, and injects data/documents back into the CRM—all without human intervention.

## 2. TECHNOLOGY STACK (The "$0 Tier")

* **Language:** Python 3.11+
* **Framework:** FastAPI (for high-concurrency webhook ingestion)
* **Message Broker / Queue:** Redis (Upstash free tier) + Celery (or RQ/Redis-Queue)
* **AI Provider:** `google-generativeai` (Gemini 1.5 Pro/Flash)
* **PDF Generation:** `ReportLab` or `WeasyPrint`
* **Hosting Target:** Render or Railway (must be containerized/Procfile ready)

## 3. STRICT SYSTEMIC CONSTRAINTS & "LANDMINES"

You must design the codebase to navigate the following confirmed JobNimbus API quirks. Failure to account for these will cause catastrophic systemic loops or data corruption.

1. **The Webhook "Payload Trap":** Webhook payloads from JobNimbus are shallow and flat (scalar data only). You **must not** rely on webhook payload data for logic. Webhooks must be treated solely as a "ping" containing an Entity ID.
2. **Missing HMAC Security:** JobNimbus does not cryptographically sign webhooks. You must enforce a custom `x-api-key` header in the FastAPI route and reject unauthorized requests.
3. **The Infinite Loop (CRITICAL):** Every state-changing outbound API call (POST/PUT) must append `?skip=automation,notification` to the URL. If omitted, our API calls will trigger CRM automations, firing another webhook back to us, causing an infinite rate-limit crash loop.
4. **Impersonation Auditing:** Every outbound API call must append `?actor=scott@wickhamroofing.com` (or configurable email) to ensure actions are logged under a human user, not the API key.
5. **Custom Field Obfuscation:** Custom CRM fields are returned as `cf_string_1`, `cf_boolean_4`, etc. You must build a bi-directional translation dictionary to map these to human-readable keys before passing them to the LLM, and map them back before sending `PUT` requests.
6. **ElasticSearch JSON Escaping & Eventual Consistency:** Outbound JSON payloads must have special characters strictly escaped. Do NOT use `?bulk=true` parameter as it causes read-after-write eventual consistency failures.
7. **Rate Limits (429s):** Outbound API requests must be wrapped in a resilient retry loop using Exponential Backoff and Jitter.

## 4. ARCHITECTURAL DATA FLOW

Implement the following asynchronous pipeline:

* **Step 1: Ingestion & Ack:** FastAPI receives a webhook `POST`. Validates `x-api-key`. Extracts `jnid` (JobNimbus ID) and `event_type`. Pushes to Redis queue. Instantly returns `HTTP 200 OK`.
* **Step 2: Hydration (Reach-Back):** Celery/RQ worker picks up the job. Executes authenticated `GET /api1/jobs/{jnid}` or `/contacts/{jnid}` to pull the deeply nested, canonical JSON object.
* **Step 3: Translation:** Worker passes JSON through the Custom Field Dictionary to map `cf_*` keys to readable English keys.
* **Step 4: Cognitive Processing:** Data is packaged into a strict prompt and sent to the Gemini API (e.g., "Extract material list," "Draft customer SMS," "Determine next pipeline stage").
* **Step 5: Document Generation (If applicable):** If the AI generates an itemized material breakdown, bypass JobNimbus templates. Use `ReportLab` to render a physical PDF locally.
* **Step 6: Egress / Execution:** Worker executes JobNimbus commands:
* `PUT /api1/jobs/{jnid}?skip=automation,notification&actor=...` (Update statuses)
* `POST /api1/tasks?skip=automation,notification&actor=...` (Assign crew tasks)
* `POST /files/v1/uploads/url` -> `PUT` to AWS S3 -> `POST /files/fromUrl` (Attach generated PDFs).



## 5. THE "ZERO-RISK" TESTING PROTOCOL

We are testing in a live production environment. You must strictly adhere to this safety protocol:

* **The Quarantine Filter:** The FastAPI webhook ingestion route must check the payload for `status_name == "API TEST LAB"`. If it does not match, instantly drop the request and return `200 OK`. Do not queue it.
* **Read-Only Mode:** In the initial build, all Step 6 (Egress/Execution) functions must be mocked. Print the intended JSON payloads to the console/logger instead of firing them at the JobNimbus API.

## 6. AUTONOMOUS AGENT EXECUTION ROADMAP

*Agent: Please execute the following phases sequentially. Ask for human input ONLY for API keys or clarification on business logic.*

### PHASE 1: Scaffolding & Environment Setup

1. Initialize a Python environment (`venv`).
2. Generate `requirements.txt` (fastapi, uvicorn, redis, rq/celery, httpx, google-generativeai, reportlab, python-dotenv).
3. Create a clean folder structure (`/app/api/`, `/app/core/`, `/app/services/`, `/app/workers/`).
4. Set up `.env` scaffolding for `JOBNIMBUS_API_KEY`, `GEMINI_API_KEY`, `WEBHOOK_SECRET`, and `REDIS_URL`.

### PHASE 2: The Resilient API Client

1. Build `app/services/jobnimbus_client.py`.
2. Create an asynchronous HTTP client (using `httpx`) wrapper.
3. Automatically inject the `Authorization: Bearer` header.
4. Create decorator/middleware for the client that automatically handles `429 Too Many Requests` with exponential backoff.
5. Create helper methods: `get_job(jnid)`, `update_job(jnid, payload)`, `upload_document(jnid, filepath)`. Ensure `skip` and `actor` parameters are hardcoded into the mutation helpers.

### PHASE 3: Webhook Ingestion & Queue

1. Build `app/api/webhooks.py`. Create a `POST` route.
2. Implement header validation for `x-api-key`.
3. Implement the Quarantine Filter (only process jobs with status "API TEST LAB").
4. Integrate Redis/RQ. Push the `jnid` and `event` to the queue and return `200 OK`.

### PHASE 4: The Hydration & Translation Layer

1. Build `app/workers/job_processor.py`.
2. Write the queue consumer function.
3. Build `app/core/field_mapper.py`. Create a bi-directional dictionary that can translate a payload from `cf_string_1` to `date_of_loss` and vice versa.

### PHASE 5: AI Integration & PDF Generator

1. Build `app/services/ai_service.py` to wrap the Gemini API. Create a prompt template that accepts the translated JSON and outputs structured decisions.
2. Build `app/services/pdf_generator.py` using `ReportLab` to take AI JSON output (like a material list) and render a clean, branded PDF locally.
3. Link the generated PDF to the JobNimbus API client's `upload_document` method.

---

**END OF DIRECTIVE**