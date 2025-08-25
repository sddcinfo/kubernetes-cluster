# Generate Ansible inventory
output "ansible_inventory" {
  value = templatefile("${path.module}/templates/inventory.tpl", {
    control_nodes = {
      for name, config in local.vms : name => {
        ip   = config.ip_address
        id   = config.vm_id
      } if config.node_type == "control"
    }
    worker_nodes = {
      for name, config in local.vms : name => {
        ip   = config.ip_address
        id   = config.vm_id
      } if config.node_type == "worker"
    }
  })
}

# Save inventory to file
resource "local_file" "ansible_inventory" {
  content  = local.ansible_inventory_content
  filename = "${path.module}/../ansible/inventory/terraform-inventory.ini"
}

locals {
  ansible_inventory_content = templatefile("${path.module}/templates/inventory.tpl", {
    control_nodes = {
      for name, config in local.vms : name => {
        ip   = config.ip_address
        id   = config.vm_id
      } if config.node_type == "control"
    }
    worker_nodes = {
      for name, config in local.vms : name => {
        ip   = config.ip_address
        id   = config.vm_id
      } if config.node_type == "worker"
    }
  })
}

# Output VM details
output "vm_details" {
  value = {
    for name, vm in proxmox_virtual_environment_vm.kubernetes_nodes : name => {
      id         = vm.vm_id
      ip_address = local.vms[name].ip_address
      node       = vm.node_name
      status     = vm.status
    }
  }
}

# VIP for HA control plane
output "control_plane_vip" {
  value = "10.10.1.100"
  description = "Virtual IP for HA control plane endpoint"
}