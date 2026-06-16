variable "iso_url" {
  type    = string
  default = "https://cloud-images.ubuntu.com/releases/24.04/release/ubuntu-24.04-server-cloudimg-amd64.img"
}

variable "iso_checksum" {
  type    = string
  default = "sha256:834af9cd766d1fd86eca156db7dff34c3713fbbc7f5507a3269be2a72d2d1820"
}

variable "disk_size" {
  type    = string
  default = "8G"
}

variable "vm_cpu" {
  type    = number
  default = 2
}

variable "vm_memory" {
  type    = number
  default = 2048
}

variable "accelerator" {
  type    = string
  default = "kvm"
}

variable "ssh_password" {
  type    = string
  default = ""
}

variable "ssh_private_key_file" {
  type    = string
  default = "/root/.ssh/id_rsa"
}

variable "build_format" {
  type    = string
  default = "qcow2"
}

variable "build_name" {
  type    = string
  default = "ubuntu_golden"
}

variable "build_version" {
  type    = string
  default = "1.0.0"
}
