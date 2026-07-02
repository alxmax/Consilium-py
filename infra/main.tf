terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

data "google_project" "current" {}

# Container image registry (push your image here, then reference it in var.image)
resource "google_artifact_registry_repository" "consilium" {
  location      = var.region
  repository_id = "consilium"
  format        = "DOCKER"
  description   = "consilium-py container images"
}

# Secret Manager holds the API key — never a plain Cloud Run env var, never in
# Terraform state as anything but a reference. Created only when a key is supplied.
resource "google_secret_manager_secret" "openrouter_api_key" {
  count     = var.openrouter_api_key == "" ? 0 : 1
  secret_id = "${var.service_name}-openrouter-api-key"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "openrouter_api_key" {
  count       = var.openrouter_api_key == "" ? 0 : 1
  secret      = google_secret_manager_secret.openrouter_api_key[0].id
  secret_data = var.openrouter_api_key
}

# Grant the Cloud Run service's runtime identity (default compute SA) access to the secret.
resource "google_secret_manager_secret_iam_member" "cloud_run_access" {
  count     = var.openrouter_api_key == "" ? 0 : 1
  secret_id = google_secret_manager_secret.openrouter_api_key[0].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${data.google_project.current.number}-compute@developer.gserviceaccount.com"
}

# The FastAPI server as a managed container service
resource "google_cloud_run_v2_service" "consilium" {
  name     = var.service_name
  location = var.region

  template {
    containers {
      image = var.image

      ports {
        container_port = 8000
      }

      dynamic "env" {
        for_each = var.openrouter_api_key == "" ? [] : [1]
        content {
          name = "OPENROUTER_API_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.openrouter_api_key[0].secret_id
              version = "latest"
            }
          }
        }
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }

    scaling {
      min_instance_count = 0 # scales to zero — no cost when idle
      max_instance_count = 2
    }
  }

  depends_on = [google_artifact_registry_repository.consilium]
}

# Public access is opt-in and OFF by default — the service is private (authenticated
# invokers only) unless you explicitly set var.public_access = true.
resource "google_cloud_run_v2_service_iam_member" "public" {
  count    = var.public_access ? 1 : 0
  name     = google_cloud_run_v2_service.consilium.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}
