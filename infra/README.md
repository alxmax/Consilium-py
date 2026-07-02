# infra/

Terraform for deploying consilium-py's FastAPI server to GCP Cloud Run.

## State is REMOTE (GCS)

State lives in a **versioned Google Cloud Storage bucket** (`backend "gcs"`, see `backend.tf`),
not on the local filesystem. State can contain secret values (e.g. the OpenRouter key, a
Terraform limitation for any `sensitive` resource), so the bucket uses **uniform
bucket-level access** with **object versioning** and should have restricted IAM. `*.tfstate`
files are git-ignored and must never be committed.

`apply` is still run locally by a single operator (no CI-driven `apply`, no Workload Identity
Federation) — the GCS backend gives durable, versioned, shareable state without introducing a
concurrent-write problem. The CI workflow stays validate-only.

The service is **private by default** (`var.public_access = false`) and the API key, if
supplied, is stored in Secret Manager rather than a plain environment variable.

## Prerequisites

- A GCP project with **billing enabled**, and `PROJECT_ID` to hand.
- `gcloud` authenticated for both the CLI and Terraform's provider (ADC):
  ```bash
  gcloud auth login
  gcloud auth application-default login
  gcloud config set project <PROJECT_ID>
  ```
- `terraform >= 1.6`.
- **No local Docker required** — the image is built with Cloud Build (`gcloud builds submit`).
  (If you prefer local Docker, the equivalent `docker build`/`docker push` still works.)

## Deploy runbook

Set these once (bucket must be globally unique):

```bash
export PROJECT_ID=<your-project-id>
export BUCKET=<your-globally-unique-bucket>      # also put this in backend.tf
export REGION=europe-central2
export IMAGE=$REGION-docker.pkg.dev/$PROJECT_ID/consilium/consilium-py:v0.1.1
```

### 1. Create the state bucket (remote backend)

```bash
gcloud storage buckets create gs://$BUCKET --location=$REGION --uniform-bucket-level-access
gcloud storage buckets update gs://$BUCKET --versioning
```

Then edit `backend.tf` and set `bucket = "<your bucket>"`.

### 2. Migrate state to the bucket

```bash
cd infra
terraform init -migrate-state    # confirm 'yes' to copy existing state into GCS
```

### 3. Enable the required APIs

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com
```

### 4. Create the Artifact Registry repo FIRST

The image has to exist before the Cloud Run service can reference it, so apply only the
registry to begin with:

```bash
terraform apply -target=google_artifact_registry_repository.consilium \
  -var project_id=$PROJECT_ID -var image=placeholder
```

### 5. Build + push the image (Cloud Build — no local Docker)

Run from the **repo root** (where the `Dockerfile` is):

```bash
gcloud builds submit --tag $IMAGE .
```

<details><summary>Local-Docker equivalent (if you'd rather)</summary>

```bash
gcloud auth configure-docker $REGION-docker.pkg.dev
docker build -t $IMAGE .
docker push $IMAGE
```
</details>

### 6. Full apply

```bash
cd infra
terraform apply \
  -var project_id=$PROJECT_ID \
  -var image=$IMAGE \
  -var public_access=true          # false for a private (authenticated-only) service
# add -var openrouter_api_key=$OPENROUTER_API_KEY only if you want /deliberate live
```

The key, if supplied, goes to Secret Manager and is read by reference (`secret_key_ref`) — it
never appears as a plain env var and must never be hardcoded or passed any way but `-var`.

### 7. Verify

```bash
terraform output service_url
curl -i "$(terraform output -raw service_url)/"
```

If the service is **private** (`public_access=false`), that `curl` returns `403` without an
identity token — use `curl -H "Authorization: Bearer $(gcloud auth print-identity-token)"` to
reach it, or set `public_access=true` for an open demo.

## Deployed instance

> **Status: not yet deployed.** Fill this in after running the runbook above.

| Field | Value |
|---|---|
| Project | `<PROJECT_ID>` |
| Region | `europe-central2` |
| Service URL | `<terraform output service_url>` |
| Public access | `<true / false>` |
| Image | `<…/consilium/consilium-py:v0.1.1>` |

Screenshot of the live service:

<!-- ![consilium-py on Cloud Run](./deployed-screenshot.png) -->
_(add `deployed-screenshot.png` here once deployed)_

## Teardown

```bash
terraform destroy -var project_id=$PROJECT_ID -var image=<any>
```
