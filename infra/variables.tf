variable "project_id" {
  type        = string
  description = "GCP project ID"
}

variable "region" {
  type    = string
  default = "europe-central2" # Warsaw — closest GCP region to Romania
}

variable "service_name" {
  type    = string
  default = "consilium-py"
}

variable "image" {
  type        = string
  description = "Full Artifact Registry image path, e.g. europe-central2-docker.pkg.dev/<project>/consilium/consilium-py:v0.1.1"
}

variable "openrouter_api_key" {
  type        = string
  default     = ""
  sensitive   = true
  description = "Optional. Stored in Secret Manager and referenced by reference — never written as a plain Cloud Run env var. Leave empty to deploy without it."
}

variable "public_access" {
  type        = bool
  default     = false
  description = "Grant allUsers roles/run.invoker (unauthenticated public access). Defaults to false — the service is private until you explicitly opt in."
}
