# infra/

Terraform for deploying consilium-py's FastAPI server to GCP Cloud Run.

State is local (no remote backend) — this is a single-operator setup with no CI-driven
`apply`, so there's no concurrent-write problem to solve yet. Add a `backend "gcs" {}`
block if that changes (e.g. CI starts running `terraform apply`).

The service is **private by default** (`var.public_access = false`) and the API key, if
supplied, is stored in Secret Manager rather than a plain environment variable.

## Deploy

```bash
# 1. Build and push the image
gcloud auth configure-docker europe-central2-docker.pkg.dev
docker build -t europe-central2-docker.pkg.dev/<project>/consilium/consilium-py:v0.1.0 ..
docker push europe-central2-docker.pkg.dev/<project>/consilium/consilium-py:v0.1.0

# 2. Apply
cd infra
terraform init
terraform apply \
  -var project_id=<project> \
  -var image=europe-central2-docker.pkg.dev/<project>/consilium/consilium-py:v0.1.0
```

To expose the service publicly (e.g. for a demo), add `-var public_access=true`. To supply
an API key, add `-var openrouter_api_key=<key>` — it's written to Secret Manager and the
Cloud Run container reads it by reference (`secret_key_ref`), so it never appears as a
plain env var readable from the Cloud Run console or `gcloud run services describe`.
Note: `terraform.tfstate` still records the secret value (a Terraform limitation for any
resource with a `sensitive` attribute) — treat local state as sensitive, and switch to a
GCS backend with restricted IAM if you stop being the only one with filesystem access to it.

## Teardown

```bash
terraform destroy -var project_id=<project> -var image=<any>
```
