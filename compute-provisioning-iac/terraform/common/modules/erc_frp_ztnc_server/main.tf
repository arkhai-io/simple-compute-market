resource "google_compute_firewall" "allow_vm_open_ports" {
  project = var.gcp_project_name
  name    = var.erc_frp_firewall_name
  network = var.gcp_network_name

  priority  = 1000
  direction = "INGRESS"

  allow {
    protocol = "tcp"
    ports    = ["80", "443", "7000-8000","9993","3000"]
  }

  allow {
    protocol = "udp"
    ports    = ["80", "443", "7000-8000","9993"]
  }

  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["arkhai-frp"]
}

resource "google_compute_address" "erc_frp_ztnc_server_ip" {
  project = var.gcp_project_name
  name    = var.erc_frp_ztnc_server_ip_name
  region  = var.gcp_project_region
}

resource "google_compute_disk" "erc_frp_ztnc_server_disk" {
  project = var.gcp_project_name
  name    = var.erc_frp_disk_name
  type    = "pd-balanced"
  zone    = var.gcp_project_zone
  size    = var.erc_frp_disk_size
  image   = var.erc_frp_disk_image
}

# Get the default compute service account
data "google_compute_default_service_account" "default" {
  project = var.gcp_project_name
}

resource "google_compute_instance" "erc_frp_ztnc_server" {
  depends_on = [
    google_compute_disk.erc_frp_ztnc_server_disk,
    google_compute_address.erc_frp_ztnc_server_ip,
    google_compute_firewall.allow_vm_open_ports,
  ]
  project                    = var.gcp_project_name
  name                       = var.erc_frp_ztnc_server_name
  machine_type               = var.erc_frp_ztnc_server_machine_type
  zone                       = var.gcp_project_zone
  key_revocation_action_type = "NONE"

  boot_disk {
    source      = google_compute_disk.erc_frp_ztnc_server_disk.self_link
    auto_delete = true
  }

  network_interface {
    network = var.gcp_network_name

    access_config {
      nat_ip = google_compute_address.erc_frp_ztnc_server_ip.address
    }
  }

  service_account {
    email = data.google_compute_default_service_account.default.email
    scopes = [
      "https://www.googleapis.com/auth/cloud-platform"
    ]
  }
  tags = ["arkhai-frp"]

  lifecycle {
    ignore_changes = [service_account, metadata]
  }
}