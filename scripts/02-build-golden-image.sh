#!/bin/bash
# Phase 2: Build Golden Image with Packer
# Creates the Kubernetes-ready VM template

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
PACKER_DIR="../packer"
TEMPLATE_NAME="ubuntu-2404-vanilla-golden"
TEMPLATE_ID="9000"
UBUNTU_VERSION="24.04.3"

echo "============================================================"
echo "PHASE 2: BUILD GOLDEN IMAGE"
echo "============================================================"

# Function to print colored output
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

# Check if running from scripts directory
if [ ! -f "02-build-golden-image.sh" ]; then
    log_error "Please run this script from the scripts directory"
    exit 1
fi

# Create simplified Packer template for vanilla Ubuntu
log_info "Using vanilla Ubuntu ${UBUNTU_VERSION} Packer template..."
PACKER_TEMPLATE="${PACKER_DIR}/ubuntu-vanilla-golden.pkr.hcl"

if [ ! -f "$PACKER_TEMPLATE" ]; then
    log_error "Packer template not found: $PACKER_TEMPLATE"
    exit 1
fi

log_info "Packer template found: $PACKER_TEMPLATE"
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
  default = "ubuntu-k8s-golden"
}

variable "template_id" {
  type    = string
  default = "9000"
}

source "proxmox-clone" "ubuntu-k8s" {
  proxmox_url              = "https://${var.proxmox_host}/api2/json"
  api_token_id            = var.proxmox_token
  insecure_skip_tls_verify = true
  
  clone_vm_id             = 9001  # Base cloud-init template
  vm_name                 = var.template_name
  vm_id                   = var.template_id
  template_name           = var.template_name
  template_description    = "Ubuntu 24.04 Kubernetes Golden Image"
  
  node                    = "hp4"
  cores                   = 2
  memory                  = 4096
  
  scsi_controller         = "virtio-scsi-single"
  
  network_adapters {
    bridge   = "vmbr1"
    model    = "virtio"
    vlan_tag = ""
  }
  
  cloud_init              = true
  cloud_init_storage_pool = "rbd"
  
  ssh_username            = "ubuntu"
  ssh_private_key_file    = "~/.ssh/id_rsa"
  ssh_timeout             = "20m"
  
  unmount_iso             = true
  task_timeout            = "10m"
}

build {
  sources = ["source.proxmox-clone.ubuntu-k8s"]
  
  # Update system
  provisioner "shell" {
    inline = [
      "sudo apt-get update",
      "sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y",
      "sudo DEBIAN_FRONTEND=noninteractive apt-get dist-upgrade -y"
    ]
  }
  
  # Install Kubernetes prerequisites
  provisioner "shell" {
    inline = [
      "# Disable swap",
      "sudo swapoff -a",
      "sudo sed -i '/ swap / s/^/#/' /etc/fstab",
      
      "# Install required packages",
      "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y apt-transport-https ca-certificates curl gpg",
      
      "# Add Kubernetes repository",
      "curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.30/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg",
      "echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.30/deb/ /' | sudo tee /etc/apt/sources.list.d/kubernetes.list",
      
      "# Install containerd",
      "sudo DEBIAN_FRONTEND=noninteractive apt-get update",
      "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y containerd",
      
      "# Configure containerd",
      "sudo mkdir -p /etc/containerd",
      "sudo containerd config default | sudo tee /etc/containerd/config.toml",
      "sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml",
      "sudo systemctl restart containerd",
      "sudo systemctl enable containerd",
      
      "# Install Kubernetes components",
      "sudo DEBIAN_FRONTEND=noninteractive apt-get install -y kubelet kubeadm kubectl",
      "sudo apt-mark hold kubelet kubeadm kubectl"
    ]
  }
  
  # Configure kernel modules and sysctl
  provisioner "shell" {
    inline = [
      "# Load required kernel modules",
      "cat <<EOF | sudo tee /etc/modules-load.d/k8s.conf",
      "overlay",
      "br_netfilter",
      "EOF",
      
      "sudo modprobe overlay",
      "sudo modprobe br_netfilter",
      
      "# Configure sysctl for Kubernetes",
      "cat <<EOF | sudo tee /etc/sysctl.d/k8s.conf",
      "net.bridge.bridge-nf-call-iptables  = 1",
      "net.bridge.bridge-nf-call-ip6tables = 1",
      "net.ipv4.ip_forward                 = 1",
      "EOF",
      
      "sudo sysctl --system"
    ]
  }
  
  # Clean up
  provisioner "shell" {
    inline = [
      "sudo apt-get autoremove -y",
      "sudo apt-get clean",
      "sudo cloud-init clean --logs --seed",
      "sudo rm -rf /var/lib/cloud/instances/*",
      "sudo truncate -s 0 /etc/machine-id",
      "sudo rm -f /var/lib/dbus/machine-id",
      "history -c"
    ]
  }
}
EOF

# Validate Packer template
log_info "Validating Packer template..."
cd "$PACKER_DIR"
if packer validate ubuntu-k8s-golden.pkr.hcl; then
    log_info "Packer template is valid"
else
    log_error "Packer template validation failed"
    exit 1
fi

# Check if template already exists and remove it
log_info "Checking for existing template..."
PROXMOX_HOST="10.10.1.21"  # Primary Proxmox host
if ssh sysadmin@"$PROXMOX_HOST" "qm status $TEMPLATE_ID" &>/dev/null; then
    log_warning "Template $TEMPLATE_ID already exists, removing..."
    ssh sysadmin@"$PROXMOX_HOST" "qm destroy $TEMPLATE_ID --purge" || true
fi

# Build the golden image
log_info "Building golden image with Packer..."
log_info "This may take 10-15 minutes..."

if PACKER_LOG=1 packer build ubuntu-k8s-golden.pkr.hcl; then
    log_info "Golden image build completed successfully!"
    
    # Convert to template
    log_info "Converting VM to template..."
    ssh sysadmin@"$PROXMOX_HOST" "qm template $TEMPLATE_ID"
    
    echo ""
    echo "============================================================"
    echo -e "${GREEN}✓ PHASE 2 COMPLETED SUCCESSFULLY${NC}"
    echo "Golden image template ID: $TEMPLATE_ID"
    echo "Template name: $TEMPLATE_NAME"
    echo "Proceed to Phase 3: Provision Infrastructure"
    echo "============================================================"
else
    log_error "Packer build failed"
    echo "Check the Packer logs above for details"
    exit 1
fi