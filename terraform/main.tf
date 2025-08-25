# Production-Ready Terraform Configuration for Proxmox Kubernetes
# This captures all lessons learned from our trial-and-error process

terraform {
  required_providers {
    # Based on research: BPG provider is more feature-complete, Telmate is more stable
    # We'll configure both and use the one that works
    proxmox = {
      source  = "bpg/proxmox"
      version = "~> 0.70"
    }
  }
  required_version = ">= 1.0"
}

# Variables for environment flexibility
variable "proxmox_host" {
  description = "Proxmox host IP"
  type        = string
  default     = "10.10.1.21"
}

variable "proxmox_api_token" {
  description = "Proxmox API token (format: user@realm!tokenname=secret)"
  type        = string
  sensitive   = true
  default     = "packer@pam!packer=7b2a3da7-bd30-4772-a6b0-874aa9b2f3a5"
}

variable "proxmox_user" {
  description = "Proxmox username for password auth fallback"
  type        = string
  default     = "root@pam"
}

variable "proxmox_password" {
  description = "Proxmox password for fallback auth"
  type        = string
  sensitive   = true
  default     = ""
}

variable "golden_template_id" {
  description = "Golden template VM ID to clone from"
  type        = number
  default     = 9003
}

variable "ssh_public_key" {
  description = "SSH public key for VM access"
  type        = string
  default     = ""
}

# Locals for VM configurations
locals {
  # Control plane nodes configuration
  control_plane_nodes = {
    "k8s-control-01" = {
      node_name   = "node1"
      vm_id       = 101
      ip_address  = "10.10.1.30"
      cores       = 4
      memory      = 8192
      disk_size   = 64
    }
    "k8s-control-02" = {
      node_name   = "node2"
      vm_id       = 102
      ip_address  = "10.10.1.31"
      cores       = 4
      memory      = 8192
      disk_size   = 64
    }
    "k8s-control-03" = {
      node_name   = "node3"
      vm_id       = 103
      ip_address  = "10.10.1.32"
      cores       = 4
      memory      = 8192
      disk_size   = 64
    }
  }
  
  # Worker nodes configuration
  worker_nodes = {
    "k8s-worker-01" = {
      node_name   = "node1"
      vm_id       = 111
      ip_address  = "10.10.1.33"
      cores       = 6
      memory      = 24576
      disk_size   = 128
    }
    "k8s-worker-02" = {
      node_name   = "node2"
      vm_id       = 112
      ip_address  = "10.10.1.34"
      cores       = 6
      memory      = 24576
      disk_size   = 128
    }
    "k8s-worker-03" = {
      node_name   = "node3"
      vm_id       = 113
      ip_address  = "10.10.1.35"
      cores       = 6
      memory      = 24576
      disk_size   = 128
    }
    "k8s-worker-04" = {
      node_name   = "node4"
      vm_id       = 114
      ip_address  = "10.10.1.36"
      cores       = 6
      memory      = 24576
      disk_size   = 128
    }
  }
  
  # All VMs combined
  all_vms = merge(local.control_plane_nodes, local.worker_nodes)
}

# Primary provider configuration (BPG with API token)
provider "proxmox" {
  endpoint  = "https://${var.proxmox_host}:8006/"
  api_token = var.proxmox_api_token
  insecure  = true
  
  # SSH configuration for operations requiring SSH access
  ssh {
    agent    = false
    username = "root"
    # Note: Add private key if needed for advanced operations
  }
  
  # Timeouts based on our experience
  tmp_dir = "/var/tmp"
}

# Test connectivity before proceeding
data "external" "connectivity_check" {
  program = ["bash", "-c", <<-EOF
    # Test API connectivity
    response=$(curl -k -s -H "Authorization: PVEAPIToken=${var.proxmox_api_token}" \
      "https://${var.proxmox_host}:8006/api2/json/version" 2>/dev/null || echo "")
    
    if echo "$response" | grep -q "version"; then
      echo '{"status": "success", "message": "API is accessible"}'
    else
      echo '{"status": "failed", "message": "API is not accessible"}'
      exit 1
    fi
  EOF
  ]
}

# Verify golden template exists
data "external" "template_check" {
  program = ["bash", "-c", <<-EOF
    # Check if golden template exists
    response=$(curl -k -s -H "Authorization: PVEAPIToken=${var.proxmox_api_token}" \
      "https://${var.proxmox_host}:8006/api2/json/nodes/node1/qemu/${var.golden_template_id}/config" 2>/dev/null || echo "")
    
    if echo "$response" | grep -q "template.*1"; then
      echo '{"status": "success", "template_id": "${var.golden_template_id}"}'
    else
      echo '{"status": "failed", "template_id": "${var.golden_template_id}"}'
      exit 1
    fi
  EOF
  ]
  
  depends_on = [data.external.connectivity_check]
}

# Control Plane VMs
resource "proxmox_virtual_environment_vm" "control_plane" {
  for_each = local.control_plane_nodes
  
  name        = each.key
  description = "Kubernetes Control Plane Node - ${each.key}"
  node_name   = each.value.node_name
  vm_id       = each.value.vm_id
  
  # Clone from golden template
  clone {
    vm_id   = var.golden_template_id
    full    = true
    retries = 3
  }
  
  # VM Resources
  cpu {
    cores = each.value.cores
  }
  
  memory {
    dedicated = each.value.memory
  }
  
  # Storage
  disk {
    datastore_id = "rbd"  # Use Ceph RBD for production
    interface    = "scsi0"
    size         = each.value.disk_size
  }
  
  # Network
  network_device {
    bridge = "vmbr0"
    model  = "virtio"
  }
  
  # Basic cloud-init for hostname and networking
  initialization {
    ip_config {
      ipv4 {
        address = "${each.value.ip_address}/24"
        gateway = "10.10.1.1"
      }
    }
    
    dns {
      servers = ["10.10.1.1", "8.8.8.8"]
    }
    
    user_account {
      keys     = var.ssh_public_key != "" ? [var.ssh_public_key] : [file("~/.ssh/sysadmin_automation_key.pub")]
      password = "kubernetes"
      username = "ubuntu"
    }
    
    # Hostname set via cloud-init user-data
  }
  
  # Agent for better integration
  agent {
    enabled = true
    timeout = "15m"
  }
  
  # Start VMs
  started = true
  
  # Lifecycle management
  lifecycle {
    ignore_changes = [
      # Ignore changes to these after initial creation
      clone,
    ]
  }
  
  depends_on = [data.external.template_check]
}

# Worker VMs
resource "proxmox_virtual_environment_vm" "workers" {
  for_each = local.worker_nodes
  
  name        = each.key
  description = "Kubernetes Worker Node - ${each.key}"
  node_name   = each.value.node_name
  vm_id       = each.value.vm_id
  
  # Clone from golden template
  clone {
    vm_id   = var.golden_template_id
    full    = true
    retries = 3
  }
  
  # VM Resources
  cpu {
    cores = each.value.cores
  }
  
  memory {
    dedicated = each.value.memory
  }
  
  # Storage
  disk {
    datastore_id = "rbd"  # Use Ceph RBD for production
    interface    = "scsi0"
    size         = each.value.disk_size
  }
  
  # Network
  network_device {
    bridge = "vmbr0"
    model  = "virtio"
  }
  
  # Basic cloud-init for hostname and networking
  initialization {
    ip_config {
      ipv4 {
        address = "${each.value.ip_address}/24"
        gateway = "10.10.1.1"
      }
    }
    
    dns {
      servers = ["10.10.1.1", "8.8.8.8"]
    }
    
    user_account {
      keys     = var.ssh_public_key != "" ? [var.ssh_public_key] : [file("~/.ssh/sysladmin_automation_key.pub")]
      password = "kubernetes"
      username = "ubuntu"
    }
    
    # Hostname set via cloud-init user-data
  }
  
  # Agent for better integration
  agent {
    enabled = true
    timeout = "15m"
  }
  
  # Start VMs
  started = true
  
  # Lifecycle management
  lifecycle {
    ignore_changes = [
      # Ignore changes to these after initial creation
      clone,
    ]
  }
  
  depends_on = [data.external.template_check]
}

# Outputs for Ansible inventory and verification
output "control_plane_ips" {
  description = "Control plane node IP addresses"
  value = {
    for name, vm in proxmox_virtual_environment_vm.control_plane : name => {
      ip_address = vm.ipv4_addresses[0][0]
      vm_id      = vm.vm_id
      node_name  = vm.node_name
    }
  }
}

output "worker_ips" {
  description = "Worker node IP addresses"
  value = {
    for name, vm in proxmox_virtual_environment_vm.workers : name => {
      ip_address = vm.ipv4_addresses[0][0]
      vm_id      = vm.vm_id
      node_name  = vm.node_name
    }
  }
}

output "deployment_summary" {
  description = "Deployment summary"
  value = {
    golden_template_id     = var.golden_template_id
    total_vms_created     = length(local.all_vms)
    control_plane_count   = length(local.control_plane_nodes)
    worker_count         = length(local.worker_nodes)
    deployment_timestamp = timestamp()
  }
}