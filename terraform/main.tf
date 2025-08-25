terraform {
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "~> 0.68"
    }
  }
}

provider "proxmox" {
  endpoint = "https://10.10.1.21:8006/"
  username = "terraform@pam!terraform"
  password = var.proxmox_token
  insecure = true
  
  ssh {
    agent    = true
    username = "root"
  }
}

variable "proxmox_token" {
  description = "Proxmox API token"
  type        = string
  sensitive   = true
}

variable "ssh_public_key" {
  description = "SSH public key for VM access"
  type        = string
  default     = ""
}

# Node configurations
locals {
  vms = {
    # Control Plane Nodes
    "k8s-control-01" = {
      target_node = "node1"
      cores       = 4
      memory      = 8192
      disk_size   = 64
      ip_address  = "10.10.1.101"
      vm_id       = 101
      ha_group    = "k8s-control-plane"
      node_type   = "control"
    }
    "k8s-control-02" = {
      target_node = "node2"
      cores       = 4
      memory      = 8192
      disk_size   = 64
      ip_address  = "10.10.1.102"
      vm_id       = 102
      ha_group    = "k8s-control-plane"
      node_type   = "control"
    }
    "k8s-control-03" = {
      target_node = "node3"
      cores       = 4
      memory      = 8192
      disk_size   = 64
      ip_address  = "10.10.1.103"
      vm_id       = 103
      ha_group    = "k8s-control-plane"
      node_type   = "control"
    }
    
    # Worker Nodes
    "k8s-worker-01" = {
      target_node = "node1"
      cores       = 6
      memory      = 24576
      disk_size   = 128
      ip_address  = "10.10.1.111"
      vm_id       = 111
      ha_group    = "k8s-workers"
      node_type   = "worker"
    }
    "k8s-worker-02" = {
      target_node = "node2"
      cores       = 6
      memory      = 24576
      disk_size   = 128
      ip_address  = "10.10.1.112"
      vm_id       = 112
      ha_group    = "k8s-workers"
      node_type   = "worker"
    }
    "k8s-worker-03" = {
      target_node = "node3"
      cores       = 6
      memory      = 24576
      disk_size   = 128
      ip_address  = "10.10.1.113"
      vm_id       = 113
      ha_group    = "k8s-workers"
      node_type   = "worker"
    }
    "k8s-worker-04" = {
      target_node = "node4"
      cores       = 6
      memory      = 24576
      disk_size   = 128
      ip_address  = "10.10.1.114"
      vm_id       = 114
      ha_group    = "k8s-workers"
      node_type   = "worker"
    }
  }
}

# Create VMs from template
resource "proxmox_virtual_environment_vm" "kubernetes_nodes" {
  for_each = local.vms
  
  name        = each.key
  description = "Kubernetes ${each.value.node_type} node"
  
  node_name = each.value.target_node
  vm_id     = each.value.vm_id
  
  # Clone from template
  clone {
    vm_id = 9000
  }
  
  # VM resources
  cpu {
    cores = each.value.cores
  }
  
  memory {
    dedicated = each.value.memory
  }
  
  # Storage
  disk {
    datastore_id = "rbd"
    file_id      = "9000"
    interface    = "scsi0"
    size         = each.value.disk_size
  }
  
  # Network
  network_device {
    bridge = "vmbr0"
    model  = "virtio"
  }
  
  # Cloud-init configuration
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
      keys     = [var.ssh_public_key != "" ? var.ssh_public_key : file("~/.ssh/id_rsa.pub")]
      password = "kubernetes"
      username = "ubuntu"
    }
    
    user_data_file_id = proxmox_virtual_environment_file.cloud_config[each.key].id
  }
  
  # Start VM after creation
  started = true
  
  # Enable HA
  high_availability {
    enabled = true
    group   = each.value.ha_group
  }
}

# Cloud-init configuration files
resource "proxmox_virtual_environment_file" "cloud_config" {
  for_each = local.vms
  
  content_type = "snippets"
  datastore_id = "local"
  node_name    = each.value.target_node
  
  source_raw {
    data = <<-EOF
    #cloud-config
    hostname: ${each.key}
    fqdn: ${each.key}.sddc.local
    manage_etc_hosts: true
    
    users:
      - name: ubuntu
        sudo: ALL=(ALL) NOPASSWD:ALL
        shell: /bin/bash
        ssh_authorized_keys:
          - ${var.ssh_public_key != "" ? var.ssh_public_key : file("~/.ssh/id_rsa.pub")}
    
    package_update: true
    package_upgrade: false
    
    runcmd:
      - systemctl enable qemu-guest-agent
      - systemctl start qemu-guest-agent
      - systemctl enable containerd
      - systemctl start containerd
      - sysctl --system
    EOF
    
    file_name = "${each.key}-cloud-config.yml"
  }
}

# HA Groups
resource "proxmox_virtual_environment_ha_group" "control_plane" {
  group_id = "k8s-control-plane"
  comment  = "Kubernetes Control Plane HA Group"
  
  nodes = {
    node1 = {}
    node2 = {}
    node3 = {}
    node4 = {}
  }
  
  no_failback = false
  restricted  = false
}

resource "proxmox_virtual_environment_ha_group" "workers" {
  group_id = "k8s-workers"
  comment  = "Kubernetes Workers HA Group"
  
  nodes = {
    node1 = {}
    node2 = {}
    node3 = {}
    node4 = {}
  }
  
  no_failback = false
  restricted  = false
}

# HA Resources with anti-affinity
resource "proxmox_virtual_environment_ha_resource" "control_plane_vms" {
  for_each = {
    for name, config in local.vms : name => config
    if config.node_type == "control"
  }
  
  resource_id = "vm:${each.value.vm_id}"
  group_id    = "k8s-control-plane"
  comment     = "HA resource for ${each.key}"
  enabled     = true
  max_relocate = 1
  max_restart  = 2
  
  depends_on = [
    proxmox_virtual_environment_vm.kubernetes_nodes,
    proxmox_virtual_environment_ha_group.control_plane
  ]
}

resource "proxmox_virtual_environment_ha_resource" "worker_vms" {
  for_each = {
    for name, config in local.vms : name => config
    if config.node_type == "worker"
  }
  
  resource_id = "vm:${each.value.vm_id}"
  group_id    = "k8s-workers"
  comment     = "HA resource for ${each.key}"
  enabled     = true
  max_relocate = 1
  max_restart  = 2
  
  depends_on = [
    proxmox_virtual_environment_vm.kubernetes_nodes,
    proxmox_virtual_environment_ha_group.workers
  ]
}