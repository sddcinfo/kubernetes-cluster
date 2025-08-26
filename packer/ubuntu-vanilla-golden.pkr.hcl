packer {
  required_plugins {
    proxmox = {
      version = ">= 1.1.8"
      source  = "github.com/hashicorp/proxmox"
    }
  }
}

variable "proxmox_host" {
  type    = string
  default = "10.10.1.21:8006"
}

variable "proxmox_token" {
  type    = string
  default = "packer@pam!packer=7b2a3da7-bd30-4772-a6b0-874aa9b2f3a5"
}

variable "template_name" {
  type    = string
  default = "ubuntu-2404-vanilla-golden"
}

variable "template_id" {
  type    = string
  default = "9000"
}

variable "ubuntu_mirror" {
  type    = string
  default = "http://10.10.1.1/provisioning/ubuntu24.04"
  description = "Ubuntu mirror URL - defaults to local provisioning server"
}

source "proxmox-iso" "ubuntu-vanilla" {
  proxmox_url              = "https://${var.proxmox_host}/api2/json"
  username                = "packer@pam"
  token                   = var.proxmox_token
  insecure_skip_tls_verify = true
  
  vm_name                 = var.template_name
  vm_id                   = var.template_id
  template_name           = var.template_name
  template_description    = "Ubuntu 24.04.3 Vanilla Golden Image with qemu-guest-agent"
  
  node                    = "hp4"
  cores                   = 2
  memory                  = 2048
  
  scsi_controller         = "virtio-scsi-single"
  
  disks {
    disk_size         = "20G"
    format            = "raw"
    storage_pool      = "rbd"
    type              = "scsi"
  }
  
  network_adapters {
    bridge   = "vmbr1"
    model    = "virtio"
    vlan_tag = ""
  }
  
  # Use Ubuntu 24.04.3 Server ISO - local provisioning server first, then fallback to internet
  boot_iso {
    iso_url          = var.ubuntu_mirror != "" ? "${var.ubuntu_mirror}/ubuntu-24.04.3-live-server-amd64.iso" : "https://releases.ubuntu.com/24.04.3/ubuntu-24.04.3-live-server-amd64.iso"
    iso_checksum     = "sha256:c3514bf0056180d09376462a7a1b4f213c1d6e8ea67fae5c25099c6fd3d8274b"
    iso_storage_pool = "rbd"
  }
  
  # Cloud-init configuration
  cloud_init              = true
  cloud_init_storage_pool = "rbd"
  
  # SSH configuration
  ssh_username            = "sysadmin"
  ssh_private_key_file    = "/home/sysadmin/.ssh/sysadmin_automation_key"
  ssh_timeout             = "20m"
  
  # Boot configuration
  boot_wait      = "5s"
  boot_command   = [
    "<esc><wait>",
    "linux /casper/vmlinuz --- autoinstall ds='nocloud-net;s=http://{{.HTTPIP}}:{{.HTTPPort}}/'",
    "<enter><wait>",
    "initrd /casper/initrd",
    "<enter><wait>",
    "boot",
    "<enter>"
  ]
  
  # HTTP server for autoinstall
  http_directory = "http"
  http_bind_address = "0.0.0.0"
  http_port_min = 8080
  http_port_max = 8080
}

build {
  sources = ["source.proxmox-iso.ubuntu-vanilla"]
  
  # Wait for cloud-init to complete
  provisioner "shell" {
    inline = [
      "while [ ! -f /var/lib/cloud/instance/boot-finished ]; do echo 'Waiting for cloud-init...'; sleep 1; done",
      "sudo cloud-init status --wait"
    ]
  }
  
  # Update system
  provisioner "shell" {
    inline = [
      "sudo apt-get update",
      "sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y"
    ]
  }
  
  # Install and configure qemu-guest-agent
  provisioner "shell" {
    inline = [
      "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y qemu-guest-agent",
      "sudo systemctl enable qemu-guest-agent",
      "sudo systemctl start qemu-guest-agent"
    ]
  }
  
  # Basic system optimization
  provisioner "shell" {
    inline = [
      "# Remove unnecessary packages",
      "sudo apt-get autoremove -y",
      "sudo apt-get autoclean",
      
      "# Clear logs and temporary files", 
      "sudo truncate -s 0 /var/log/*log",
      "sudo rm -rf /var/lib/cloud/instances/*",
      "sudo rm -rf /tmp/* /var/tmp/*",
      
      "# Clear bash history",
      "history -c",
      "cat /dev/null > ~/.bash_history"
    ]
  }
  
  # Final cleanup for template
  provisioner "shell" {
    inline = [
      "# Reset machine-id for template",
      "sudo truncate -s 0 /etc/machine-id",
      "sudo rm -f /var/lib/dbus/machine-id",
      
      "# Clean cloud-init for template use",
      "sudo cloud-init clean --logs --seed",
      
      "# Final sync",
      "sync"
    ]
  }
}