# Remote state backend — Terraform state lives in a versioned GCS bucket, not on the
# local filesystem. State can hold secret values (e.g. the OpenRouter key), so the
# bucket must have uniform bucket-level access + restricted IAM. See README.md.
#
# Before `terraform init`, replace the bucket name below with your own globally-unique
# bucket, create it (see README "1. Create the state bucket"), then migrate:
#     terraform init -migrate-state
terraform {
  backend "gcs" {
    bucket = "consilium-tfstate-CHANGEME" # <-- replace with your globally-unique bucket name
    prefix = "consilium-py"
  }
}
