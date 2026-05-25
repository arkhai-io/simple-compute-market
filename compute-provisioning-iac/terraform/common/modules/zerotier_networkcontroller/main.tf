locals {
  display_suffix = var.resource_suffix != "" ? " ${upper(substr(var.resource_suffix, 0, 1))}${substr(var.resource_suffix, 1, -1)}" : ""
}

resource "google_compute_firewall" "zerotier_controller" {
  project = var.gcp_project_name
  name    = "${var.zerotier_networkcontroller_name}-firewall"
  network = var.gcp_network_name

  allow {
    protocol = "udp"
    ports    = ["9993"]
  }

  allow {
    protocol = "tcp"
    ports    = ["9993", "3000"]
  }

  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["zerotier-networkcontroller"]
}

resource "google_compute_address" "zerotier_controller_ip" {
  project = var.gcp_project_name
  name    = "${var.zerotier_networkcontroller_name}-ip"
  region  = var.gcp_project_region
}

resource "google_compute_disk" "zerotier_controller_disk" {
  project = var.gcp_project_name
  name    = "${var.zerotier_networkcontroller_name}-disk"
  type    = "pd-balanced"
  zone    = var.gcp_project_zone
  size    = 10
}

resource "google_service_account" "zerotier_controller" {
  project      = var.gcp_project_name
  account_id   = "ztnc-sa${var.resource_suffix != "" ? "-${var.resource_suffix}" : ""}"
  display_name = "ZeroTier Controller Service Account${local.display_suffix}"
}

resource "google_project_iam_member" "zerotier_artifact_registry_reader" {
  project = var.gcp_project_name
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.zerotier_controller.email}"
}

# Grant Logging Writer role for writing logs
resource "google_project_iam_member" "zerotier_logging_writer" {
  project = var.gcp_project_name
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.zerotier_controller.email}"
}

# Grant Monitoring Metric Writer role for metrics
resource "google_project_iam_member" "zerotier_monitoring_writer" {
  project = var.gcp_project_name
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${google_service_account.zerotier_controller.email}"
}

# Grant OS Login role if SSH access is needed
resource "google_project_iam_member" "zerotier_oslogin" {
  project = var.gcp_project_name
  role    = "roles/compute.osLogin"
  member  = "serviceAccount:${google_service_account.zerotier_controller.email}"
}

# Grant Storage Object Viewer for accessing GCS buckets if needed
resource "google_project_iam_member" "zerotier_storage_viewer" {
  project = var.gcp_project_name
  role    = "roles/storage.objectViewer"
  member  = "serviceAccount:${google_service_account.zerotier_controller.email}"
}

# Grant Compute Instance Admin for self-management capabilities
resource "google_project_iam_member" "zerotier_instance_admin" {
  project = var.gcp_project_name
  role    = "roles/compute.instanceAdmin.v1"
  member  = "serviceAccount:${google_service_account.zerotier_controller.email}"
}

# resource "google_compute_instance" "zerotier_controller" {
#   depends_on = [
#     google_compute_address.zerotier_controller_ip,
#     google_compute_disk.zerotier_controller_disk,
#     google_service_account.zerotier_controller,
#     google_project_iam_member.zerotier_artifact_registry_reader,
#     google_project_iam_member.zerotier_logging_writer,
#     google_project_iam_member.zerotier_monitoring_writer,
#     google_project_iam_member.zerotier_oslogin,
#     google_project_iam_member.zerotier_storage_viewer,
#     google_project_iam_member.zerotier_instance_admin,
#   ]
#   project      = var.gcp_project_name
#   name         = var.zerotier_networkcontroller_name
#   machine_type = var.zerotier_networkcontroller_machine_type
#   zone         = var.gcp_project_zone

#   boot_disk {
#     initialize_params {
#       image = "cos-cloud/cos-stable"  # Container-Optimized OS
#       size  = 10
#     }
#   }

#   attached_disk {
#     source      = google_compute_disk.zerotier_controller_disk.self_link
#     device_name = "zerotier-data"
#     mode        = "READ_WRITE"
#   }

#   network_interface {
#     network = var.gcp_network_name

#     access_config {
#       nat_ip = google_compute_address.zerotier_controller_ip.address
#     }
#   }

#   allow_stopping_for_update = true 

#   service_account {
#     email = google_service_account.zerotier_controller.email
#     scopes = [
#       "https://www.googleapis.com/auth/cloud-platform",
#       "https://www.googleapis.com/auth/compute",
#       "https://www.googleapis.com/auth/logging.write",
#       "https://www.googleapis.com/auth/monitoring.write",
#       "https://www.googleapis.com/auth/devstorage.read_only",
#       "https://www.googleapis.com/auth/servicecontrol",
#       "https://www.googleapis.com/auth/service.management.readonly",
#       "https://www.googleapis.com/auth/trace.append"
#     ]
#   }

#   tags = [
#     "http-server",
#     "https-server",
#     "zerotier-controller"
#   ]

#   metadata = {
#     cos-metrics-enabled = true
#     startup-script = <<-SCRIPT
#       #!/bin/bash
#       set -x



#       # Enable IP forwarding (required for ZeroTier)
#       echo 1 > /proc/sys/net/ipv4/ip_forward
#       echo 1 > /proc/sys/net/ipv6/conf/all/forwarding

#       # Wait for Docker to be ready
#       for i in {1..30}; do
#         if docker version &>/dev/null; then
#           echo "Docker is ready"
#           break
#         fi
#         echo "Waiting for Docker..."
#         sleep 2
#       done

#       # Configure Docker for GCR/Artifact Registry
#       docker-credential-gcr configure-docker

#       # Setup persistent disk
#       DEVICE="/dev/disk/by-id/google-zerotier-data"
#       MOUNT_POINT="/mnt/disks/zerotier-data"

#       # Wait for disk
#       for i in {1..10}; do
#         if [ -e "$DEVICE" ]; then
#           echo "Disk found"
#           break
#         fi
#         sleep 2
#       done

#       # Format if needed
#       if ! blkid "$DEVICE" 2>/dev/null; then
#         echo "Formatting disk..."
#         mkfs.ext4 -F "$DEVICE"
#       fi

#       # Mount disk
#       mkdir -p "$MOUNT_POINT"
#       mount "$DEVICE" "$MOUNT_POINT" || {
#         echo "Mount failed, checking filesystem..."
#         fsck.ext4 -y "$DEVICE"
#         mount "$DEVICE" "$MOUNT_POINT"
#       }
#       chmod 755 "$MOUNT_POINT"

#       # Stop any existing container
#       docker stop zerotier-controller 2>/dev/null || true
#       docker rm zerotier-controller 2>/dev/null || true

#       # Use public ZeroTier image (change this to your private registry if needed)
#       IMAGE="${var.zerotier_networkcontroller_image_link}"

#       # If private image fails, fallback to public
#       if ! docker pull "$IMAGE" 2>/dev/null; then
#         echo "Using public ZeroTier image"
#         IMAGE="zerotier/zerotier:latest"
#       fi

#       # Create TUN device if it doesn't exist
#       mkdir -p /dev/net
#       [ ! -c /dev/net/tun ] && mknod /dev/net/tun c 10 200
#       chmod 666 /dev/net/tun

#       # Run ZeroTier container
#       docker run -d \
#         --name zerotier-controller \
#         --restart unless-stopped \
#         --cap-add NET_ADMIN \
#         --cap-add NET_RAW \
#         --cap-add SYS_ADMIN \
#         --device /dev/net/tun \
#         --network host \
#         --privileged \
#         -v "$MOUNT_POINT:/var/lib/zerotier-one" \
#         -e ZT_ENABLE_CONTROLLER=true \
#         -e ZT_ALLOW_TCP_FALLBACK=1 \
#         -e ZT_ENABLE_API=true \
#         --log-driver gcplogs \
#         --log-opt gcp-project=${var.gcp_project_name} \
#         "$IMAGE"

#       # Wait for ZeroTier to initialize
#       sleep 15

#       # Verify ZeroTier is listening
#       echo "Checking if ZeroTier is listening on port 9993..."
#       netstat -tulpn | grep 9993 || echo "Port 9993 not found"

#       # Check ZeroTier status
#       docker exec zerotier-controller zerotier-cli status || echo "ZeroTier not ready yet"

#       # Create systemd service for persistence
#       cat > /etc/systemd/system/zerotier-startup.service <<-EOF
#       [Unit]
#       Description=ZeroTier Controller Startup
#       After=docker.service
#       Requires=docker.service

#       [Service]
#       Type=oneshot
#       RemainAfterExit=yes
#       ExecStart=/bin/bash -c 'mount /dev/disk/by-id/google-zerotier-data /mnt/disks/zerotier-data || true; docker start zerotier-controller || docker run -d --name zerotier-controller --restart unless-stopped --cap-add NET_ADMIN --cap-add SYS_ADMIN --device /dev/net/tun --network host -v /mnt/disks/zerotier-data:/var/lib/zerotier-one -e ZT_ENABLE_CONTROLLER=true --log-driver gcplogs --log-opt gcp-project=${var.gcp_project_name} $IMAGE'

#       [Install]
#       WantedBy=multi-user.target
#       EOF

#       systemctl daemon-reload
#       systemctl enable zerotier-startup.service

#       # Verify container is running
#       sleep 5
#       docker ps
#       docker logs zerotier-controller

#       # Final port check
#       echo "Final port check:"
#       ss -tulpn | grep 9993
#       ss -tulpn | grep 3000
#     SCRIPT
#   }
# }

resource "google_compute_instance" "zerotier_controller" {
  depends_on = [
    google_compute_address.zerotier_controller_ip,
    google_compute_disk.zerotier_controller_disk,
    google_service_account.zerotier_controller,
    google_project_iam_member.zerotier_artifact_registry_reader,
    google_project_iam_member.zerotier_logging_writer,
    google_project_iam_member.zerotier_monitoring_writer,
    google_project_iam_member.zerotier_oslogin,
    google_project_iam_member.zerotier_storage_viewer,
    google_project_iam_member.zerotier_instance_admin,
  ]
  project      = var.gcp_project_name
  name         = var.zerotier_networkcontroller_name
  machine_type = var.zerotier_networkcontroller_machine_type
  zone         = var.gcp_project_zone

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
      size  = 20
      type  = "pd-balanced"
    }
  }

  attached_disk {
    source      = google_compute_disk.zerotier_controller_disk.self_link
    device_name = "zerotier-data"
    mode        = "READ_WRITE"
  }

  network_interface {
    network = var.gcp_network_name

    access_config {
      nat_ip = google_compute_address.zerotier_controller_ip.address
    }
  }

  service_account {
    email = google_service_account.zerotier_controller.email
    scopes = [
      "https://www.googleapis.com/auth/cloud-platform",
      "https://www.googleapis.com/auth/compute",
      "https://www.googleapis.com/auth/logging.write",
      "https://www.googleapis.com/auth/monitoring.write",
      "https://www.googleapis.com/auth/devstorage.read_only",
      "https://www.googleapis.com/auth/servicecontrol",
      "https://www.googleapis.com/auth/service.management.readonly",
      "https://www.googleapis.com/auth/trace.append"
    ]
  }

  tags = ["zerotier-networkcontroller"]

  metadata_startup_script = <<-SCRIPT
    #!/bin/bash
    set -e
    
    # Enable IP forwarding (required for ZeroTier)
    echo 1 > /proc/sys/net/ipv4/ip_forward
    echo 1 > /proc/sys/net/ipv6/conf/all/forwarding

    # Install Docker and gcloud
    apt-get update
    apt-get install -y docker.io docker-compose google-cloud-sdk
    systemctl enable docker
    systemctl start docker
    
    # Configure Docker to use gcloud for authentication
    gcloud auth configure-docker ${var.gcp_project_region}-docker.pkg.dev --quiet
    
    # Alternative: Use metadata server for authentication
    # This configures Docker to use the instance's service account
    mkdir -p /root/.docker
    cat > /root/.docker/config.json <<-DKRCNF
    {
      "credHelpers": {
        "${var.gcp_project_region}-docker.pkg.dev": "gcloud"
      }
    }
    DKRCNF
    
    # Setup persistent disk
    DEVICE="/dev/disk/by-id/google-zerotier-data"
    MOUNT_POINT="/mnt/disks/zerotier-data"  # Changed back to separate mount point
    
    # Wait for disk to be available
    for i in {1..10}; do
      if [ -e "$DEVICE" ]; then
        echo "Disk found at $DEVICE"
        break
      fi
      echo "Waiting for disk..."
      sleep 2
    done
    
    # Check if device exists before proceeding
    if [ -e "$DEVICE" ]; then
      # Format disk if not already formatted
      if ! blkid $DEVICE 2>/dev/null; then
        echo "Formatting disk..."
        mkfs.ext4 -F $DEVICE
      fi
      
      # Create mount point
      mkdir -p $MOUNT_POINT
      
      # Check if already mounted
      if mountpoint -q $MOUNT_POINT; then
        echo "Disk already mounted at $MOUNT_POINT"
      else
        echo "Mounting disk at $MOUNT_POINT"
        mount $DEVICE $MOUNT_POINT || {
          echo "Mount failed, trying to repair filesystem..."
          fsck.ext4 -y $DEVICE || true
          mount $DEVICE $MOUNT_POINT || echo "Warning: Could not mount disk, continuing anyway"
        }
      fi
      
      # Add to fstab for persistence (if not already there)
      if ! grep -q "$DEVICE" /etc/fstab; then
        echo "$DEVICE $MOUNT_POINT ext4 defaults,nofail 0 2" >> /etc/fstab
      fi
      
      chmod 755 $MOUNT_POINT
    else
      echo "Warning: Disk device not found, creating directory without persistent disk"
      mkdir -p $MOUNT_POINT
      chmod 755 $MOUNT_POINT
    fi
      
    # Stop any existing container
    docker stop zerotier-controller 2>/dev/null || true
    docker rm zerotier-controller 2>/dev/null || true
    
    # Pull the image first to verify authentication
    echo "Pulling ZeroTier image..."
    # Use public ZeroTier image (change this to your private registry if needed)
    IMAGE="${var.zerotier_networkcontroller_image_link}"
    
    # If private image fails, fallback to public
    if ! docker pull "$IMAGE" 2>/dev/null; then
      echo "Using public ZeroTier image"
      IMAGE="zerotier/zerotier:latest"
    fi
  
    # Create TUN device if it doesn't exist
    mkdir -p /dev/net
    [ ! -c /dev/net/tun ] && mknod /dev/net/tun c 10 200
    chmod 666 /dev/net/tun
    
    # Run ZeroTier with explicit port binding
    docker run -d \
      --name zerotier-controller \
      --restart unless-stopped \
      --cap-add NET_ADMIN \
      --cap-add NET_RAW \
      --cap-add SYS_ADMIN \
      --device /dev/net/tun \
      --network host \
      --privileged \
      -v "$MOUNT_POINT:/var/lib/zerotier-one" \
      -e ZT_ENABLE_CONTROLLER=true \
      -e ZT_ALLOW_TCP_FALLBACK=1 \
      -e ZT_ENABLE_API=true \
      --log-driver gcplogs \
      --log-opt gcp-project=${var.gcp_project_name} \
      "$IMAGE"
    
    # Wait for ZeroTier to initialize
    sleep 15

    # Enable controller mode
    docker exec zerotier-controller sh -c 'touch /var/lib/zerotier-one/controller.enabled'

    # Restart to apply controller mode
    docker restart zerotier-controller
    sleep 10
    
    # Verify ZeroTier is listening
    echo "Checking if ZeroTier is listening on port 9993..."
    netstat -tulpn | grep 9993 || echo "Port 9993 not found"
    
    # Check ZeroTier status
    docker exec zerotier-controller zerotier-cli status || echo "ZeroTier not ready yet"

    # Create systemd service
    cat > /etc/systemd/system/zerotier-startup.service <<-EOF
      [Unit]
      Description=ZeroTier Controller Startup
      Requires=docker.service
      After=docker.service
      
      [Service]
      Type=oneshot
      RemainAfterExit=true
      ExecStart=/bin/bash -c 'mount /dev/disk/by-id/google-zerotier-data /mnt/disks/zerotier-data || true; docker start zerotier-controller || docker run -d --name zerotier-controller --restart unless-stopped --cap-add NET_ADMIN --cap-add SYS_ADMIN --device /dev/net/tun --network host -v /mnt/disks/zerotier-data:/var/lib/zerotier-one -e ZT_ENABLE_CONTROLLER=true --log-driver gcplogs --log-opt gcp-project=${var.gcp_project_name} $IMAGE'
      
      [Install]
      WantedBy=multi-user.target
    EOF
    
    systemctl daemon-reload
    systemctl enable zerotier-startup.service
    
    # Verify container is running
    sleep 5
    docker ps
    docker logs zerotier-controller
  SCRIPT

  lifecycle {
    ignore_changes = [metadata["ssh-keys"]]
  }
}