terraform {
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "0.82.1"
    }
  }
}

provider "proxmox" {
  endpoint  = "https://10.10.1.21:8006/"
  username  = "root@pam"
  password  = "proxmox123"
  insecure  = true
  
  # Performance optimizations
  tmp_dir = "/tmp"
}

# Local variables for host affinity mapping
locals {
  # Available Proxmox nodes for distribution
  proxmox_nodes = ["node1", "node2", "node3", "node4"]
  
  # Control plane host affinity strategy
  control_plane_mapping = {
    "k8s-control-1" = "node1"
    "k8s-control-2" = "node2"
    "k8s-control-3" = "node3"
  }
  
  # Worker host affinity strategy
  worker_mapping = {
    "k8s-worker-1" = "node1"
    "k8s-worker-2" = "node2"
    "k8s-worker-3" = "node3"
    "k8s-worker-4" = "node4"
  }
  
  # HAProxy load balancer
  haproxy_mapping = {
    "k8s-haproxy" = "node4"
  }
  
  # VM ID assignments
  vm_ids = {
    "k8s-haproxy"   = 130
    "k8s-control-1" = 131
    "k8s-control-2" = 132
    "k8s-control-3" = 133
    "k8s-worker-1"  = 140
    "k8s-worker-2"  = 141
    "k8s-worker-3"  = 142
    "k8s-worker-4"  = 143
  }
  
  # IP address assignments based on DNS config
  vm_ips = {
    "k8s-haproxy"   = "10.10.1.30"
    "k8s-control-1" = "10.10.1.31"
    "k8s-control-2" = "10.10.1.32"
    "k8s-control-3" = "10.10.1.33"
    "k8s-worker-1"  = "10.10.1.40"
    "k8s-worker-2"  = "10.10.1.41"
    "k8s-worker-3"  = "10.10.1.42"
    "k8s-worker-4"  = "10.10.1.43"
  }
  
  # MAC address assignments to ensure uniqueness
  vm_macs = {
    "k8s-haproxy"   = "02:00:00:00:01:30"
    "k8s-control-1" = "02:00:00:00:01:31"
    "k8s-control-2" = "02:00:00:00:01:32"
    "k8s-control-3" = "02:00:00:00:01:33"
    "k8s-worker-1"  = "02:00:00:00:01:40"
    "k8s-worker-2"  = "02:00:00:00:01:41"
    "k8s-worker-3"  = "02:00:00:00:01:42"
    "k8s-worker-4"  = "02:00:00:00:01:43"
  }
}

# HAProxy Load Balancer
resource "proxmox_virtual_environment_vm" "haproxy_lb" {
  for_each = local.haproxy_mapping

  name        = each.key
  description = "HAProxy Load Balancer for Kubernetes API - Host: ${each.value}"
  tags        = ["haproxy", "loadbalancer", "kubernetes", "host-${each.value}"]
  
  node_name = each.value
  vm_id     = local.vm_ids[each.key]

  # Match template configuration
  bios    = "ovmf"
  machine = "q35"
  
  # Reliability and migration settings
  migrate         = false   # Disable automatic migration during maintenance
  protection      = false   # Allow deletion via Terraform
  reboot          = false   # Don't auto-reboot after creation
  stop_on_destroy = false   # Shutdown gracefully on destroy

  clone {
    vm_id     = 9000  # ubuntu-base-template
    node_name = "node1"  # Template only exists on node1
    full      = true
    retries   = 3  # Retry cloning up to 3 times on failure
  }

  cpu {
    cores = 2
    type  = "host"
  }

  memory {
    dedicated = 2048
  }

  # EFI disk (matches template efidisk0)
  efi_disk {
    datastore_id      = "rbd"
    file_format       = "raw"
    type              = "4m"
    pre_enrolled_keys = false
  }

  # SCSI hardware for better performance
  scsi_hardware = "virtio-scsi-pci"
  
  disk {
    datastore_id = "rbd"
    interface    = "scsi0"
    size         = 32
    cache        = "none"    # Best for shared storage like Ceph/RBD
    discard      = "ignore"  # Optimize for RBD storage
    iothread     = false     # Disable for RBD compatibility
    ssd          = false     # Mark as rotational for Ceph
    backup       = true      # Enable backup by default
    replicate    = true      # Enable replication
  }

  network_device {
    bridge      = "vmbr0"
    model       = "virtio"
    mac_address = local.vm_macs[each.key]
    firewall    = false      # Disable Proxmox firewall for performance
    queues      = 0          # Let Proxmox determine optimal queue count
    rate_limit  = 0          # No rate limiting
  }
  
  # QEMU Guest Agent for better integration
  agent {
    enabled = true
    trim    = false
    timeout = "15m"
  }

  # Serial console (matches template)
  serial_device {
    device = "socket"
  }

  # VGA settings (matches template)
  vga {
    type   = "serial0"
    memory = 16
  }

  # Random number generator (matches template)
  rng {
    source    = "/dev/urandom"
    max_bytes = 1024
    period    = 1000
  }

  initialization {
    datastore_id = "rbd"
    
    ip_config {
      ipv4 {
        address = "${local.vm_ips[each.key]}/24"
        gateway = "10.10.1.1"
      }
    }

    user_account {
      keys     = [trimspace(file("/home/sysadmin/.ssh/sysadmin_automation_key.pub"))]
      password = "password"
      username = "sysadmin"
    }
  }

  operating_system {
    type = "l26"
  }

  started = true
  on_boot = true
  
  # Optimized timeouts for reliability and performance
  timeout_clone       = 2400  # 40 minutes for clone operations
  timeout_create      = 2400  # 40 minutes for VM creation
  timeout_start_vm    = 900   # 15 minutes for VM startup
  timeout_shutdown_vm = 900   # 15 minutes for graceful shutdown
  timeout_stop_vm     = 300   # 5 minutes for force stop
  timeout_reboot      = 900   # 15 minutes for reboot
  timeout_migrate     = 3600  # 1 hour for migration
}

# Control Plane Nodes
resource "proxmox_virtual_environment_vm" "control_plane" {
  for_each = local.control_plane_mapping

  name        = each.key
  description = "Kubernetes Control Plane Node - Host: ${each.value}"
  tags        = ["control-plane", "kubernetes", "host-${each.value}"]
  
  node_name = each.value
  vm_id     = local.vm_ids[each.key]

  # Match template configuration
  bios    = "ovmf"
  machine = "q35"
  
  # Reliability and migration settings
  migrate         = false   # Disable automatic migration during maintenance
  protection      = false   # Allow deletion via Terraform
  reboot          = false   # Don't auto-reboot after creation
  stop_on_destroy = false   # Shutdown gracefully on destroy

  clone {
    vm_id     = 9000  # ubuntu-base-template
    node_name = "node1"  # Template only exists on node1
    full      = true
    retries   = 3  # Retry cloning up to 3 times on failure
  }

  cpu {
    cores = 4
    type  = "host"
  }

  memory {
    dedicated = 8192
  }

  # EFI disk (matches template efidisk0)
  efi_disk {
    datastore_id      = "rbd"
    file_format       = "raw"
    type              = "4m"
    pre_enrolled_keys = false
  }

  # SCSI hardware for better performance
  scsi_hardware = "virtio-scsi-pci"
  
  disk {
    datastore_id = "rbd"
    interface    = "scsi0"
    size         = 32
    cache        = "none"    # Best for shared storage like Ceph/RBD
    discard      = "ignore"  # Optimize for RBD storage
    iothread     = false     # Disable for RBD compatibility
    ssd          = false     # Mark as rotational for Ceph
    backup       = true      # Enable backup by default
    replicate    = true      # Enable replication
  }

  network_device {
    bridge      = "vmbr0"
    model       = "virtio"
    mac_address = local.vm_macs[each.key]
    firewall    = false      # Disable Proxmox firewall for performance
    queues      = 0          # Let Proxmox determine optimal queue count
    rate_limit  = 0          # No rate limiting
  }
  
  # QEMU Guest Agent for better integration
  agent {
    enabled = true
    trim    = false
    timeout = "15m"
  }

  # Serial console (matches template)
  serial_device {
    device = "socket"
  }

  # VGA settings (matches template)
  vga {
    type   = "serial0"
    memory = 16
  }

  # Random number generator (matches template)
  rng {
    source    = "/dev/urandom"
    max_bytes = 1024
    period    = 1000
  }

  initialization {
    datastore_id = "rbd"
    
    ip_config {
      ipv4 {
        address = "${local.vm_ips[each.key]}/24"
        gateway = "10.10.1.1"
      }
    }

    user_account {
      keys     = [trimspace(file("/home/sysadmin/.ssh/sysadmin_automation_key.pub"))]
      password = "password"
      username = "sysadmin"
    }
  }

  operating_system {
    type = "l26"
  }

  started = true
  on_boot = true
  
  # Optimized timeouts for reliability and performance
  timeout_clone       = 2400  # 40 minutes for clone operations
  timeout_create      = 2400  # 40 minutes for VM creation
  timeout_start_vm    = 900   # 15 minutes for VM startup
  timeout_shutdown_vm = 900   # 15 minutes for graceful shutdown
  timeout_stop_vm     = 300   # 5 minutes for force stop
  timeout_reboot      = 900   # 15 minutes for reboot
  timeout_migrate     = 3600  # 1 hour for migration
}

# Worker Nodes
resource "proxmox_virtual_environment_vm" "workers" {
  for_each = local.worker_mapping

  name        = each.key
  description = "Kubernetes Worker Node - Host: ${each.value}"
  tags        = ["worker", "kubernetes", "host-${each.value}"]
  
  node_name = each.value
  vm_id     = local.vm_ids[each.key]

  # Match template configuration
  bios    = "ovmf"
  machine = "q35"
  
  # Reliability and migration settings
  migrate         = false   # Disable automatic migration during maintenance
  protection      = false   # Allow deletion via Terraform
  reboot          = false   # Don't auto-reboot after creation
  stop_on_destroy = false   # Shutdown gracefully on destroy

  clone {
    vm_id     = 9000  # ubuntu-base-template
    node_name = "node1"  # Template only exists on node1
    full      = true
    retries   = 3  # Retry cloning up to 3 times on failure
  }

  cpu {
    cores = 6
    type  = "host"
  }

  memory {
    dedicated = 16384
  }

  # EFI disk (matches template efidisk0)
  efi_disk {
    datastore_id      = "rbd"
    file_format       = "raw"
    type              = "4m"
    pre_enrolled_keys = false
  }

  # SCSI hardware for better performance
  scsi_hardware = "virtio-scsi-pci"
  
  disk {
    datastore_id = "rbd"
    interface    = "scsi0"
    size         = 32
    cache        = "none"    # Best for shared storage like Ceph/RBD
    discard      = "ignore"  # Optimize for RBD storage
    iothread     = false     # Disable for RBD compatibility
    ssd          = false     # Mark as rotational for Ceph
    backup       = true      # Enable backup by default
    replicate    = true      # Enable replication
  }

  network_device {
    bridge      = "vmbr0"
    model       = "virtio"
    mac_address = local.vm_macs[each.key]
    firewall    = false      # Disable Proxmox firewall for performance
    queues      = 0          # Let Proxmox determine optimal queue count
    rate_limit  = 0          # No rate limiting
  }
  
  # QEMU Guest Agent for better integration
  agent {
    enabled = true
    trim    = false
    timeout = "15m"
  }

  # Serial console (matches template)
  serial_device {
    device = "socket"
  }

  # VGA settings (matches template)
  vga {
    type   = "serial0"
    memory = 16
  }

  # Random number generator (matches template)
  rng {
    source    = "/dev/urandom"
    max_bytes = 1024
    period    = 1000
  }

  initialization {
    datastore_id = "rbd"
    
    ip_config {
      ipv4 {
        address = "${local.vm_ips[each.key]}/24"
        gateway = "10.10.1.1"
      }
    }

    user_account {
      keys     = [trimspace(file("/home/sysadmin/.ssh/sysadmin_automation_key.pub"))]
      password = "password"
      username = "sysadmin"
    }
  }

  operating_system {
    type = "l26"
  }

  started = true
  on_boot = true
  
  # Optimized timeouts for reliability and performance
  timeout_clone       = 2400  # 40 minutes for clone operations
  timeout_create      = 2400  # 40 minutes for VM creation
  timeout_start_vm    = 900   # 15 minutes for VM startup
  timeout_shutdown_vm = 900   # 15 minutes for graceful shutdown
  timeout_stop_vm     = 300   # 5 minutes for force stop
  timeout_reboot      = 900   # 15 minutes for reboot
  timeout_migrate     = 3600  # 1 hour for migration
}

# Outputs
output "cluster_summary" {
  value = {
    haproxy_lb = {
      for name, vm in proxmox_virtual_environment_vm.haproxy_lb : name => {
        vmid      = vm.vm_id
        node      = vm.node_name
        hostname  = vm.name
      }
    }
    control_plane = {
      for name, vm in proxmox_virtual_environment_vm.control_plane : name => {
        vmid     = vm.vm_id
        node     = vm.node_name
        hostname = vm.name
        memory   = vm.memory[0].dedicated
        cores    = vm.cpu[0].cores
      }
    }
    workers = {
      for name, vm in proxmox_virtual_environment_vm.workers : name => {
        vmid     = vm.vm_id
        node     = vm.node_name
        hostname = vm.name
        memory   = vm.memory[0].dedicated
        cores    = vm.cpu[0].cores
      }
    }
  }
}

output "host_affinity_distribution" {
  value = {
    node1 = ["k8s-control-1", "k8s-worker-1"]
    node2 = ["k8s-control-2", "k8s-worker-2"] 
    node3 = ["k8s-control-3", "k8s-worker-3"]
    node4 = ["k8s-haproxy", "k8s-worker-4"]
  }
}