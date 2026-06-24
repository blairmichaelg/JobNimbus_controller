# Wickham Roofing AI Orchestrator: Deployment Playbook

This playbook provides step-by-step instructions for a human operator to push the Wickham Roofing AI Orchestrator (v1.0) live to the Render cloud platform and configure the JobNimbus webhooks.

## Step 1: GitHub Push
The code must be pushed to a remote GitHub repository to enable automatic deployments via Render.

1. Log into your GitHub account and create a new **Private** repository (e.g., `JobNimbus_AI_Controller`).
2. Open your local terminal in the project directory.
3. Ensure all local changes are committed:
   ```bash
   git status
   ```
4. Link the local repository to your remote GitHub repo and push:
   ```bash
   git remote add origin https://github.com/YOUR_USERNAME/JobNimbus_AI_Controller.git
   git branch -M main
   git push -u origin main
   ```

## Step 2: Render Configuration
Render uses the `render.yaml` blueprint to automatically provision the required services: a FastAPI web service and a secure internal Redis instance.

1. Create a free account at [Render](https://render.com).
2. Go to your Dashboard and click **New +** -> **Blueprint**.
3. Connect your GitHub account and select the `JobNimbus_AI_Controller` repository.
4. Render will automatically detect the `render.yaml` file in the root directory.
5. Review the plan:
   - **JobNimbus AI Controller (Web Service)**: Uses Docker runtime, Free tier.
   - **JobNimbus Queue (Redis)**: Uses internal KV, Free tier.
6. Click **Apply**. Render will begin building the Docker container and spinning up the Redis instance.

## Step 3: Environment Variables
The application strictly requires the following environment variables. In your Render Dashboard, navigate to the **JobNimbus AI Controller** web service -> **Environment** tab, and inject the following:

| Key | Description / Value |
|---|---|
| `APP_ENV` | `production` |
| `LOG_LEVEL` | `INFO` |
| `JOBNIMBUS_API_KEY` | Your JobNimbus Bearer token (generate via JN Profile settings). |
| `JOBNIMBUS_ACTOR_EMAIL` | The email address associated with the API key (used for audit trails). |
| `WEBHOOK_SECRET` | A securely generated random string (e.g., `openssl rand -hex 32`). **Keep this safe.** |
| `GEMINI_API_KEY` | Your Google Gemini API Key. |
| `QUARANTINE_STATUS` | `API TEST LAB` (Keep this as the test status for safe Sandbox mode). |
| `DRY_RUN` | `True` (Change to `False` ONLY when you are ready to allow the AI to mutate real CRM data). |

*Note: The `REDIS_URL` will be automatically populated by the Render Blueprint.*

## Step 4: The JobNimbus Webhook Setup
You must configure JobNimbus to push events to your new Render web service.

1. In the Render Dashboard, locate the **URL** for your newly deployed web service (e.g., `https://jobnimbus-ai-controller-abc.onrender.com`).
2. Log into **JobNimbus** as an Admin.
3. Go to **Settings** -> **Automation** -> **Add Rule**.
4. **Trigger:** Set the trigger rules based on your business logic (e.g., "When Job is modified AND Status is API TEST LAB").
5. **Action:** Select **Webhook**.
6. **URL:** Enter your Render URL with the `/webhooks/jobnimbus` path appended:
   `https://[your-render-url].onrender.com/webhooks/jobnimbus`
7. **Method:** `POST`
8. **Headers:** You **MUST** add a custom header.
   - **Key:** `x-api-key`
   - **Value:** The exact string you used for `WEBHOOK_SECRET` in Step 3.
9. Save the Rule.

## Step 5: Live Testing (The Sandbox Rule)
Before exposing your production data to the AI:

1. Ensure `QUARANTINE_STATUS` is set to `"API TEST LAB"`.
2. Ensure `DRY_RUN` is set to `True`.
3. In JobNimbus, take a dummy Job record and move it to the **API TEST LAB** status.
4. Open the Render Dashboard and check the Logs for your Web Service.
5. You should see the webhook being received, fast-reject passing, the ARQ worker hydrating the data, translating it, the AI analyzing it, and generating a PDF. 
6. Because `DRY_RUN=True`, you will see logs indicating that the `upload_document` and `update_job` actions were simulated but skipped.
7. Once you are fully satisfied with the pipeline's behavior, flip `DRY_RUN` to `False` in Render, trigger a redeploy, and watch the AI attach the first real PDF to the CRM record.
