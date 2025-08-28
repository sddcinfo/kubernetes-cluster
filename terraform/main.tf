# Production-Ready OpenTofu/Terraform Configuration for Proxmox Kubernetes
# Uses our validated templates (9000 base, 9001 kubernetes-ready)

terraform {
  required_providers {
    proxmox = {
      source  = "telmate/proxmox"
      version = "3.0.2-rc04"
    }
  }
  required_version = ">= 1.0"
}

# Provider configuration
provider "proxmox" {
  pm_api_url          = "https://${var.proxmox_host}:8006/api2/json"
  pm_api_token_id     = split("=", var.proxmox_token)[0]
  pm_api_token_secret = split("=", var.proxmox_token)[1]
  pm_tls_insecure     = true
  pm_parallel         = 1  # Workaround for VM.Monitor permission issue
  
  # Optional: Enable debug logging
  # pm_log_enable = true
  # pm_log_file   = "terraform-plugin-proxmox.log"
}

# Local variables for cluster configuration
locals {
  # Determine actual node counts based on profile
  actual_control_count = var.cluster_profile == "single-node" ? 1 : (
    var.cluster_profile == "single-master" ? 1 : var.control_plane_count
  )
  
  actual_worker_count = var.cluster_profile == "single-node" ? 0 : (
    var.cluster_profile == "single-master" ? 2 : var.worker_count
  )
  
  # Generate control plane VM configurations
  control_plane_vms = {
    for i in range(local.actual_control_count) : 
    "k8s-control-${i + 1}" => {
      vm_id       = 130 + i + 1  # 131, 132, 133
      ip_address  = var.control_plane_ips[i]
      template_id = var.k8s_template_id
      cores       = var.control_plane_cores
      memory      = var.control_plane_memory
      disk_size   = var.control_plane_disk
      node_type   = "control-plane"
      target_node = var.proxmox_node
    }
  }
  
  # Generate worker VM configurations
  worker_vms = {
    for i in range(local.actual_worker_count) : 
    "k8s-worker-${i + 1}" => {
      vm_id       = 140 + i  # 140, 141, 142, 143
      ip_address  = var.worker_ips[i]
      template_id = var.k8s_template_id
      cores       = var.worker_cores
      memory      = var.worker_memory
      disk_size   = var.worker_disk
      node_type   = "worker"
      target_node = var.proxmox_node
    }
  }
  
  # Combine all VMs
  all_vms = merge(local.control_plane_vms, local.worker_vms)
}

# Kubernetes Nodes (Control Plane and Workers)
resource "proxmox_vm_qemu" "kubernetes_nodes" {
  for_each = local.all_vms
  
  # Basic settings
  name        = each.key
  description = "Kubernetes ${each.value.node_type == "control-plane" ? "Control Plane" : "Worker"} Node"
  target_node = each.value.target_node
  vmid        = each.value.vm_id
  
  # Clone from template
  clone      = each.value.template_id == var.k8s_template_id ? "ubuntu-k8s-template" : "ubuntu-base-template"
  full_clone = true
  
  # Hardware
  cpu {
    cores   = each.value.cores
    sockets = 1
  }
  memory  = each.value.memory
  balloon = 0  # Disable for Kubernetes
  
  # Boot configuration
  boot     = "order=scsi0"
  bootdisk = "scsi0"
  
  # Enable QEMU agent
  agent = 1
  
  # Cloud-init settings
  os_type    = "cloud-init"
  ipconfig0  = "ip=${each.value.ip_address}/24,gw=${var.network_gateway}"
  nameserver = var.network_gateway
  ciuser     = "sysadmin"
  cipassword = "password"  # Should be changed after deployment
  
  # SSH keys
  sshkeys = file(var.ssh_public_key_path)
  
  # Network
  network {
    id     = 0
    model  = "virtio"
    bridge = "vmbr0"
  }
  
  # Storage - will be resized from template
  disk {
    slot     = "scsi0"
    type     = "disk"
    storage  = "rbd"
    size     = each.value.disk_size
    backup   = true
    iothread = true
  }
  
  # Ensure VM starts
  onboot = true
  
  # Tags for organization
  tags = "${each.value.node_type},kubernetes,${var.cluster_profile}"
  
  # Lifecycle rules
  lifecycle {
    ignore_changes = [
      cipassword,
      disk,  # Disk inherited from template
    ]
  }
}

# Optional: HAProxy Load Balancer for HA clusters
resource "proxmox_vm_qemu" "haproxy_lb" {
  count = var.cluster_profile == "ha-cluster" ? 1 : 0
  
  name        = "k8s-haproxy"
  description = "HAProxy Load Balancer for Kubernetes API"
  target_node = var.proxmox_node
  vmid        = 130  # Use VM ID 130 for HAProxy (VIP will be 10.10.1.30)
  
  # Clone from base template
  clone      = "ubuntu-base-template"
  full_clone = true
  
  # Minimal hardware for load balancer
  cpu {
    cores   = 2
    sockets = 1
  }
  memory  = 2048
  balloon = 0
  
  # Boot configuration
  boot     = "order=scsi0"
  bootdisk = "scsi0"
  agent    = 1
  
  # Cloud-init settings - using VIP address
  os_type    = "cloud-init"
  ipconfig0  = "ip=${var.control_plane_vip}/24,gw=${var.network_gateway}"
  nameserver = var.network_gateway
  ciuser     = "sysadmin"
  cipassword = "password"
  
  # SSH keys
  sshkeys = file(var.ssh_public_key_path)
  
  # Network
  network {
    id     = 0
    model  = "virtio"
    bridge = "vmbr0"
  }
  
  # Storage
  disk {
    slot     = "scsi0"
    type     = "disk"
    storage  = "rbd"
    size     = "20G"
    backup   = true
    iothread = true
  }
  
  onboot = true
  tags   = "haproxy,loadbalancer,kubernetes"
}