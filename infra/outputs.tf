output "service_url" {
  value       = google_cloud_run_v2_service.consilium.uri
  description = "URL of the deployed consilium-py server (only publicly reachable if var.public_access = true)"
}

output "registry" {
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.consilium.repository_id}"
  description = "Artifact Registry path to push images to"
}
