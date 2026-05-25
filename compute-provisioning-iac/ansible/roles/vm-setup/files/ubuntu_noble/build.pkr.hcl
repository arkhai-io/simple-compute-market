packer {
  required_plugins {
    qemu = {
      version = ">= 1.1.4"
      source  = "github.com/hashicorp/qemu"
    }
  }
}

source "qemu" "ubuntu" {
  iso_url              = var.iso_url
  iso_checksum         = var.iso_checksum

  disk_image           = true
  output_directory     = "artifacts"

  disk_interface       = "virtio"
  net_device           = "virtio-net"
  
  disk_size            = var.disk_size
  format               = var.build_format
  disk_compression     = true
  accelerator          = "${var.accelerator}"
  headless             = true

  vm_name              = "packer-${var.build_name}-${var.build_version}"

  # Simplified qemu args
  memory               = var.vm_memory
  cpus                 = var.vm_cpu

  qemuargs = [
    ["-cdrom", "cidata.iso"]
  ]

  ssh_username         = "root"
  ssh_private_key_file = "${var.ssh_private_key_file}"
  ssh_timeout          = "10m"
  shutdown_command     = "echo 'supersecret' | sudo -S shutdown -P now"
}

build {
  sources = ["source.qemu.ubuntu"]

  provisioner "file" {
    source      = "config/50-cloud-init.yaml"
    destination = "/tmp/50-cloud-init.yaml"
  }

  provisioner "file" {
    source      = "config/99-disable-network-config.cfg"
    destination = "/tmp/99-disable-network-config.cfg"
  }
  
  provisioner "shell" {
    inline = [
        "while [ ! -f /var/lib/cloud/instance/boot-finished ]; do echo 'Waiting for Cloud-Init...'; sleep 1; done",
    ]
  }

  # Ensure proper network setup
  provisioner "shell" {
    inline = [
      "sudo systemctl enable systemd-networkd",
      "sudo systemctl enable systemd-resolved",
      "sudo rm -f /etc/netplan/50-cloud-init.yaml",
      "sudo cp /tmp/50-cloud-init.yaml /etc/netplan/50-cloud-init.yaml",
      "sudo chown root:root /etc/netplan/50-cloud-init.yaml",
      "sudo chmod 600 /etc/netplan/50-cloud-init.yaml",
      "sudo netplan apply",
      "sudo cp /tmp/99-disable-network-config.cfg /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg",
      "echo 'Network configuration applied.'",
      "echo \"Ensuring SSH host keys exist...\"",
      "if ! ls /etc/ssh/ssh_host_*key >/dev/null 2>&1; then",
      "ssh-keygen -A",
      "fi",
      "ls -l /etc/ssh/ssh_host_* | echo",
      "echo \"Testing ssh config...\"",
      "ssh -t 2>&1 | echo",
      "echo \"Restarting ssh...\"",
      "sudo systemctl restart ssh",
      "echo \"SSH setup complete.\""
    ]
  }
  
  # Clean up vm for lean build
  provisioner "shell" {
    inline = [
      "sudo apt-get clean",
      "sudo rm -rf /var/lib/apt/lists/*",
      "sudo fstrim -av"
    ]
  }

  post-processor "shell-local" {
    environment_vars = ["IMAGE_NAME=${var.build_name}", "IMAGE_VERSION=${var.build_version}", "IMAGE_FORMAT=${var.build_format}"]
    script           = "scripts/prepare-image.sh"
  }
}