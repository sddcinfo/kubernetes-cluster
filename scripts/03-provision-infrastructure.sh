#!/bin/bash
# Phase 3: Provision Infrastructure with OpenTofu/Terraform
# Deploys VMs for Kubernetes cluster

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
TERRAFORM_DIR="../terraform"
CONTROL_NODES=3
WORKER_NODES=4

echo "============================================================"
echo "PHASE 3: PROVISION INFRASTRUCTURE"
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
if [ ! -f "03-provision-infrastructure.sh" ]; then
    log_error "Please run this script from the scripts directory"
    exit 1
fi

# Check for OpenTofu or Terraform
if command -v tofu &> /dev/null; then
    TF_CMD="tofu"
    log_info "Using OpenTofu for infrastructure provisioning"
elif command -v terraform &> /dev/null; then
    TF_CMD="terraform"
    log_info "Using Terraform for infrastructure provisioning"
else
    log_error "Neither OpenTofu nor Terraform found. Please install one."
    exit 1
fi

# Create simplified Terraform configuration
log_info "Creating Terraform configuration..."
cat > "${TERRAFORM_DIR}/main.tf" << 'EOF'
terraform {
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "~> 0.70"
    }
  }
  required_version = ">= 1.0"
}

variable "proxmox_host" {
  description = "Proxmox host"
  type        = string
  default     = "10.10.1.21"
}

variable "proxmox_token" {
  description = "Proxmox API token"
  type        = string
  default     = "packer@pam!packer=7b2a3da7-bd30-4772-a6b0-874aa9b2f3a5"
}

variable "template_id" {
  description = "Golden image template ID"
  type        = number
  default     = 9000
}

variable "control_nodes" {
  description = "Number of control plane nodes"
  type        = number
  default     = 3
}

variable "worker_nodes" {
  description = "Number of worker nodes"
  type        = number
  default     = 4
}

provider "proxmox" {
  endpoint = "https://${var.proxmox_host}:8006/"
  api_token = var.proxmox_token
  insecure = true
  
  ssh {
    agent = true
  }
}

# Control Plane Nodes
resource "proxmox_virtual_environment_vm" "control_plane" {
  count = var.control_nodes
  
  name        = "k8s-control-${count.index + 1}"
  node_name   = "hp4"
  vm_id       = 200 + count.index
  
  clone {
    vm_id = var.template_id
    full  = true
  }
  
  cpu {
    cores = 4
    type  = "host"
  }
  
  memory {
    dedicated = 8192
  }
  
  disk {
    datastore_id = "rbd"
    size         = 50
    interface    = "scsi0"
  }
  
  network_device {
    bridge = "vmbr1"
    model  = "virtio"
  }
  
  initialization {
    ip_config {
      ipv4 {
        address = "10.10.1.${100 + count.index}/24"
        gateway = "10.10.1.1"
      }
    }
    
    user_data_file_id = proxmox_virtual_environment_file.cloud_config.id
  }
  
  started = true
  
  lifecycle {
    ignore_changes = [initialization]
  }
}

# Worker Nodes
resource "proxmox_virtual_environment_vm" "worker" {
  count = var.worker_nodes
  
  name        = "k8s-worker-${count.index + 1}"
  node_name   = "hp4"
  vm_id       = 210 + count.index
  
  clone {
    vm_id = var.template_id
    full  = true
  }
  
  cpu {
    cores = 4
    type  = "host"
  }
  
  memory {
    dedicated = 16384
  }
  
  disk {
    datastore_id = "rbd"
    size         = 100
    interface    = "scsi0"
  }
  
  network_device {
    bridge = "vmbr1"
    model  = "virtio"
  }
  
  initialization {
    ip_config {
      ipv4 {
        address = "10.10.1.${110 + count.index}/24"
        gateway = "10.10.1.1"
      }
    }
    
    user_data_file_id = proxmox_virtual_environment_file.cloud_config.id
  }
  
  started = true
  
  lifecycle {
    ignore_changes = [initialization]
  }
}

# Cloud-init configuration
resource "proxmox_virtual_environment_file" "cloud_config" {
  content_type = "snippets"
  datastore_id = "local"
  node_name    = "hp4"
  
  source_raw {
    data = <<-EOT
    #cloud-config
    users:
      - name: ubuntu
        sudo: ALL=(ALL) NOPASSWD:ALL
        groups: users, admin
        shell: /bin/bash
        ssh_authorized_keys:
          - ${file("~/.ssh/id_rsa.pub")}
    
    package_update: true
    package_upgrade: false
    
    runcmd:
      - systemctl restart systemd-networkd
      - systemctl restart systemd-resolved
    EOT
    
    file_name = "k8s-cloud-config.yaml"
  }
}

# Outputs for Ansible inventory
output "control_plane_ips" {
  value = {
    for i, vm in proxmox_virtual_environment_vm.control_plane :
    vm.name => "10.10.1.${100 + i}"
  }
}

output "worker_ips" {
  value = {
    for i, vm in proxmox_virtual_environment_vm.worker :
    vm.name => "10.10.1.${110 + i}"
  }
}

output "ansible_inventory" {
  value = templatefile("${path.module}/templates/inventory.tpl", {
    control_nodes = proxmox_virtual_environment_vm.control_plane
    worker_nodes  = proxmox_virtual_environment_vm.worker
  })
}
EOF

# Create inventory template
mkdir -p "${TERRAFORM_DIR}/templates"
cat > "${TERRAFORM_DIR}/templates/inventory.tpl" << 'EOF'
[control_plane]
%{ for i, node in control_nodes ~}
${node.name} ansible_host=10.10.1.${100 + i} ansible_user=ubuntu
%{ endfor ~}

[workers]
%{ for i, node in worker_nodes ~}
${node.name} ansible_host=10.10.1.${110 + i} ansible_user=ubuntu
%{ endfor ~}

[k8s_cluster:children]
control_plane
workers

[k8s_cluster:vars]
ansible_ssh_private_key_file=~/.ssh/id_rsa
ansible_ssh_common_args='-o StrictHostKeyChecking=no'
EOF

# Initialize Terraform
log_info "Initializing Terraform..."
cd "$TERRAFORM_DIR"
$TF_CMD init

# Validate configuration
log_info "Validating Terraform configuration..."
if $TF_CMD validate; then
    log_info "Terraform configuration is valid"
else
    log_error "Terraform validation failed"
    exit 1
fi

# Plan the deployment
log_info "Planning infrastructure deployment..."
$TF_CMD plan -out=tfplan

# Apply the configuration
log_warning "About to provision ${CONTROL_NODES} control plane and ${WORKER_NODES} worker nodes"
read -p "Do you want to proceed? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    log_info "Deployment cancelled"
    exit 0
fi

log_info "Provisioning infrastructure..."
if $TF_CMD apply tfplan; then
    log_info "Infrastructure provisioned successfully!"
    
    # Generate Ansible inventory
    log_info "Generating Ansible inventory..."
    $TF_CMD output -raw ansible_inventory > ../ansible/inventory.yml
    
    # Wait for VMs to be fully ready
    log_info "Waiting for VMs to be fully ready (30 seconds)..."
    sleep 30
    
    # Test connectivity to all nodes
    log_info "Testing SSH connectivity to all nodes..."
    for ip in 10.10.1.{100..102} 10.10.1.{110..113}; do
        if ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no ubuntu@$ip "echo 'SSH OK'" &>/dev/null; then
            echo -e "  ${GREEN}✓${NC} $ip: SSH connection successful"
        else
            echo -e "  ${RED}✗${NC} $ip: SSH connection failed"
        fi
    done
    
    echo ""
    echo "============================================================"
    echo -e "${GREEN}✓ PHASE 3 COMPLETED SUCCESSFULLY${NC}"
    echo "Infrastructure provisioned:"
    echo "  - Control plane nodes: ${CONTROL_NODES}"
    echo "  - Worker nodes: ${WORKER_NODES}"
    echo "Proceed to Phase 4: Bootstrap Kubernetes"
    echo "============================================================"
else
    log_error "Infrastructure provisioning failed"
    exit 1
fi