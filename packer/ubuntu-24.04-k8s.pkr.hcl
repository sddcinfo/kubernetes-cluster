# Packer template for Ubuntu 24.04 LTS Kubernetes node
packer {
  required_plugins {
    proxmox = {
      version = ">= 1.1.3"
      source  = "github.com/hashicorp/proxmox"
    }
  }
}

variable "proxmox_url" {
  type        = string
  description = "Proxmox API URL"
  default     = "https://10.10.1.21:8006/api2/json"
}

variable "proxmox_token" {
  type        = string
  description = "Proxmox API token"
  sensitive   = true
}

variable "proxmox_user" {
  type        = string
  description = "Proxmox API user"
  default     = "packer@pam!packer"
}

variable "template_name" {
  type        = string
  description = "Template name"
  default     = "ubuntu-24.04-k8s-template"
}

variable "template_description" {
  type        = string
  description = "Template description"
  default     = "Ubuntu 24.04 LTS with Kubernetes components pre-installed"
}

source "proxmox-iso" "ubuntu-k8s" {
  # Proxmox connection
  proxmox_url              = var.proxmox_url
  token                    = var.proxmox_token
  username                 = var.proxmox_user
  insecure_skip_tls_verify = true
  
  # VM settings
  node                 = "node1"
  vm_id               = "9000"
  vm_name             = "packer-ubuntu-k8s"
  template_description = var.template_description
  
  # ISO settings
  iso_file         = "local:iso/ubuntu-24.04.1-live-server-amd64.iso"
  iso_storage_pool = "local"
  unmount_iso      = true
  
  # Hardware specs
  cores   = "4"
  memory  = "4096"
  sockets = "1"
  
  # Storage
  scsi_controller = "virtio-scsi-pci"
  disks {
    disk_size    = "32G"
    storage_pool = "rbd"
    type        = "scsi"
    format      = "raw"
  }
  
  # Network
  network_adapters {
    model    = "virtio"
    bridge   = "vmbr0"
    firewall = false
  }
  
  # Cloud-init
  cloud_init              = true
  cloud_init_storage_pool = "rbd"
  
  # Boot and installation
  boot_command = [
    "<esc><wait>",
    "linux /casper/vmlinuz --- autoinstall ds='nocloud-net;s=http://{{ .HTTPIP }}:{{ .HTTPPort }}/' ",
    "<enter><wait>",
    "initrd /casper/initrd",
    "<enter><wait>",
    "boot",
    "<enter>"
  ]
  
  boot_wait = "5s"
  
  # HTTP server for cloud-init
  http_directory = "packer/http"
  http_port_min  = 8802
  http_port_max  = 8802
  
  # SSH settings
  ssh_username         = "ubuntu"
  ssh_private_key_file = "~/.ssh/id_rsa"
  ssh_timeout          = "20m"
  ssh_handshake_attempts = 20
}

build {
  sources = ["source.proxmox-iso.ubuntu-k8s"]
  
  # Wait for cloud-init to complete
  provisioner "shell" {
    inline = [
      "while [ ! -f /var/lib/cloud/instance/boot-finished ]; do echo 'Waiting for cloud-init...'; sleep 1; done"
    ]
  }
  
  # System updates and basic packages
  provisioner "shell" {
    inline = [
      "sudo apt-get update",
      "sudo apt-get upgrade -y",
      "sudo apt-get install -y apt-transport-https ca-certificates curl gpg software-properties-common",
      "sudo apt-get install -y qemu-guest-agent"
    ]
  }
  
  # Install containerd
  provisioner "shell" {
    inline = [
      "curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg",
      "echo 'deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable' | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null",
      "sudo apt-get update",
      "sudo apt-get install -y containerd.io",
      "sudo mkdir -p /etc/containerd",
      "containerd config default | sudo tee /etc/containerd/config.toml",
      "sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml",
      "sudo systemctl enable containerd"
    ]
  }
  
  # Install Kubernetes components
  provisioner "shell" {
    inline = [
      "curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.29/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg",
      "echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.29/deb/ /' | sudo tee /etc/apt/sources.list.d/kubernetes.list",
      "sudo apt-get update",
      "sudo apt-get install -y kubelet=1.29.* kubeadm=1.29.* kubectl=1.29.*",
      "sudo apt-mark hold kubelet kubeadm kubectl"
    ]
  }
  
  # System configuration for Kubernetes
  provisioner "shell" {
    inline = [
      "sudo swapoff -a",
      "sudo sed -i '/ swap / s/^/#/' /etc/fstab",
      "echo 'net.ipv4.ip_forward=1' | sudo tee -a /etc/sysctl.conf",
      "echo 'net.bridge.bridge-nf-call-ip6tables=1' | sudo tee -a /etc/sysctl.conf",
      "echo 'net.bridge.bridge-nf-call-iptables=1' | sudo tee -a /etc/sysctl.conf",
      "sudo modprobe br_netfilter",
      "echo 'br_netfilter' | sudo tee /etc/modules-load.d/k8s.conf"
    ]
  }
  
  # Install keepalived for HA
  provisioner "shell" {
    inline = [
      "sudo apt-get install -y keepalived"
    ]
  }
  
  # Cleanup
  provisioner "shell" {
    inline = [
      "sudo apt-get autoremove -y",
      "sudo apt-get autoclean",
      "sudo rm -rf /var/lib/apt/lists/*",
      "sudo truncate -s 0 /var/log/*log",
      "history -c",
      "cat /dev/null > ~/.bash_history"
    ]
  }
  
  # Convert to template
  post-processor "shell-local" {
    inline = [
      "ssh root@node1.sddc.info 'qm template 9000'"
    ]
  }
}