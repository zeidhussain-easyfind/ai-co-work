# Module 02 - Meta Catalog Automation (`meta-catalog`)

Advanced, multimodal property extraction and catalog-publishing pipeline for EasyFind Property Solutions.

This module accepts property listings and uploaded images/screenshots via Slack, extracts structured data using a high-precision, multimodal Gemini AI model, establishes isolated discussion and editing threads in Slack, and publishes verified records to Google Sheets, Cloudinary, and the Meta Product Catalog.

---

## Architecture

1. **Slack Ingest (`ingest_handler.py`):** Receives raw Slack event payloads, validates signatures, claims event IDs to prevent duplicates, uploads attachments to S3, and routes the work payload to SQS.
2. **SQS Queue (`efps-meta-catalog-queue`):** Buffers and coordinates tasks sequentially.
3. **Worker Handler (`worker_handler.py`):**
   - **`EXTRACT`:** Triggers the multimodal fallback chain to parse text and images into structured fields. Replies back inside the original Slack thread with interactive edit blocks.
   - **`EDIT_REPLY`:** Captures in-thread user corrections and updates the staging record in DynamoDB.
   - **`CONFIRM_PUBLISH`:** Transitions the status to lock the record and triggers the Step Functions State Machine.
4. **Step Functions (`efps-meta-catalog-sm`):** Runs retryable task sequences:
   - `UploadImages`: Moves S3 screenshots to high-fidelity production Cloudinary assets.
   - `PublishMeta`: Updates/creates the product in the Meta Catalog using Graph API losslessly.
   - `Finalize`: Appends the 12-column record to Google Sheets (`Live Inventory`) and posts the final confirmation report inside the Slack thread.

---

## Naming Standards & AWS Resources

All resources are named strictly according to the EFPS naming standards:

| Resource | AWS Name | Region |
|:---|:---|:---|
| Ingest Lambda | `efps-meta-catalog-ingest-fn` | ap-south-1 |
| Worker Lambda | `efps-meta-catalog-worker-fn` | ap-south-1 |
| SQS Event Queue | `efps-meta-catalog-queue` | ap-south-1 |
| SQS Dead-Letter Queue | `efps-meta-catalog-dlq` | ap-south-1 |
| DynamoDB Jobs Table | `efps-meta-catalog-table` | ap-south-1 |
| S3 Storage Bucket | `efps-meta-catalog-bucket` | ap-south-1 |
| Step Functions SM | `efps-meta-catalog-sm` | ap-south-1 |
| Lambda Execution Role | `efps-meta-catalog-lambda-role` | global |

---

## Secrets Structure

All secrets reside in AWS Secrets Manager under the path `efps/meta-catalog/*` and are loaded at cold-start:

```json
// Slack: efps/meta-catalog/slack-secrets
{
  "signing_secret": "...",
  "bot_token": "xoxb-..."
}

// LLM Keys: efps/meta-catalog/llm-secrets
{
  "gemini_api_key": "...",
  "groq_api_key": "...",
  "openrouter_api_key": "...",
  "mistral_api_key": "..."
}

// Cloudinary: efps/meta-catalog/cloudinary-secrets
{
  "cloud_name": "...",
  "api_key": "...",
  "api_secret": "..."
}

// Google: efps/meta-catalog/google-secrets
{
  "spreadsheet_id": "...",
  "service_account_json": "{...}",
  "tab_name": "Live Inventory"
}

// Meta: efps/meta-catalog/meta-secrets
{
  "catalog_id": "...",
  "access_token": "...",
  "currency": "INR",
  "graph_version": "v20.0"
}
```
