resource "google_compute_firewall" "allow_agents_async_prov_open_ports" {
  project = var.gcp_project_name
  name    = var.agents_async_prov_firewall_name
  network = var.gcp_network_name

  priority  = 1000
  direction = "INGRESS"

  allow {
    protocol = "tcp"
    ports    = ["80", "443", "8080", "8081"]
  }

  allow {
    protocol = "udp"
    ports    = ["80", "443", "8080", "8081"]
  }

  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["arkhai-agents-async-prov"]
}

resource "google_compute_address" "agents_async_prov_server_ip" {
  project = var.gcp_project_name
  name    = var.agents_async_prov_server_ip_name
  region  = var.gcp_project_region
}

resource "google_compute_disk" "agents_async_prov_server_disk" {
  project = var.gcp_project_name
  name    = var.agents_async_prov_disk_name
  type    = "pd-balanced"
  zone    = var.gcp_project_zone
  size    = var.agents_async_prov_disk_size
  image   = var.agents_async_prov_disk_image
}

# Get the default compute service account
data "google_compute_default_service_account" "default" {
  project = var.gcp_project_name
}

resource "google_compute_instance" "agents_async_prov_server" {
  depends_on = [
    google_compute_disk.agents_async_prov_server_disk,
    google_compute_address.agents_async_prov_server_ip,
    google_compute_firewall.allow_agents_async_prov_open_ports,
  ]
  project                    = var.gcp_project_name
  name                       = var.agents_async_prov_server_name
  machine_type               = var.agents_async_prov_server_machine_type
  zone                       = var.gcp_project_zone
  key_revocation_action_type = "NONE"

  boot_disk {
    source      = google_compute_disk.agents_async_prov_server_disk.self_link
    auto_delete = true
  }

  network_interface {
    network = var.gcp_network_name

    access_config {
      nat_ip = google_compute_address.agents_async_prov_server_ip.address
    }
  }

  service_account {
    email = data.google_compute_default_service_account.default.email
    scopes = [
      "https://www.googleapis.com/auth/cloud-platform"
    ]
  }
  tags = ["arkhai-agents-async-prov"]

  lifecycle {
    ignore_changes = [service_account, metadata]
  }
}
