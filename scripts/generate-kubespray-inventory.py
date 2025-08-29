#!/usr/bin/env python3
"""
Generate Kubespray inventory from Terraform output for Proxmox Kubernetes cluster.
"""
import json
import subprocess
import sys
from pathlib import Path


def get_terraform_output():
    """Get Terraform output JSON"""
    try:
        terraform_dir = Path(__file__).parent.parent / "terraform"
        result = subprocess.run(
            ["terraform", "output", "-json"],
            cwd=terraform_dir,
            capture_output=True,
            text=True,
            check=True
        )
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Error getting Terraform output: {e}")
        print(f"Stderr: {e.stderr}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error parsing Terraform JSON: {e}")
        sys.exit(1)


def generate_kubespray_inventory(terraform_output):
    """Generate Kubespray inventory from Terraform cluster summary"""
    
    cluster_summary = terraform_output.get("cluster_summary", {}).get("value", {})
    
    if not cluster_summary:
        print("No cluster_summary found in Terraform output")
        sys.exit(1)
    
    inventory = {
        "all": {"hosts": {}},
        "kube_control_plane": {"hosts": {}},
        "etcd": {"hosts": {}},
        "kube_node": {"hosts": {}},
        "k8s_cluster": {"children": ["kube_control_plane", "kube_node"]},
        "calico_rr": {"hosts": {}}
    }
    
    # Add control plane nodes
    control_planes = cluster_summary.get("control_plane", {})
    for vm_name, vm_info in control_planes.items():
        hostname = vm_info["hostname"]
        ip_address = f"10.10.1.{30 + int(vm_name.split('-')[-1])}"  # k8s-control-1 -> 31, etc.
        
        inventory["all"]["hosts"][hostname] = {
            "ansible_host": ip_address,
            "ip": ip_address,
            "access_ip": ip_address
        }
        inventory["kube_control_plane"]["hosts"][hostname] = None
        inventory["etcd"]["hosts"][hostname] = None
    
    # Add worker nodes
    workers = cluster_summary.get("workers", {})
    for vm_name, vm_info in workers.items():
        hostname = vm_info["hostname"]
        ip_address = f"10.10.1.{39 + int(vm_name.split('-')[-1])}"  # k8s-worker-1 -> 40, etc.
        
        inventory["all"]["hosts"][hostname] = {
            "ansible_host": ip_address,
            "ip": ip_address,
            "access_ip": ip_address
        }
        inventory["kube_node"]["hosts"][hostname] = None
    
    # Add global variables
    inventory["all"]["vars"] = {
        "ansible_user": "sysadmin",
        "ansible_ssh_private_key_file": "/home/sysadmin/.ssh/sysadmin_automation_key",
        "ansible_ssh_common_args": "-o StrictHostKeyChecking=no"
    }
    
    return inventory


def write_inventory_ini(inventory, output_path):
    """Write inventory in INI format for Kubespray"""
    
    lines = []
    
    # [all] section
    lines.append("[all]")
    for hostname, vars_dict in inventory["all"]["hosts"].items():
        if vars_dict:
            var_string = " ".join([f"{k}={v}" for k, v in vars_dict.items()])
            lines.append(f"{hostname} {var_string}")
        else:
            lines.append(hostname)
    lines.append("")
    
    # Other sections
    for section_name, section_data in inventory.items():
        if section_name == "all":
            continue
            
        lines.append(f"[{section_name}]")
        
        if "hosts" in section_data:
            for hostname in section_data["hosts"].keys():
                lines.append(hostname)
        elif "children" in section_data:
            # This is a children section - modify the section name
            lines[-1] = f"[{section_name}:children]"
            for child in section_data["children"]:
                lines.append(child)
        
        lines.append("")
    
    # [all:vars] section
    if "vars" in inventory["all"]:
        lines.append("[all:vars]")
        for var_name, var_value in inventory["all"]["vars"].items():
            lines.append(f"{var_name}={var_value}")
        lines.append("")
    
    # Write to file
    output_path.write_text("\n".join(lines))


def main():
    """Main function"""
    print("🔄 Generating Kubespray inventory from Terraform output...")
    
    # Get Terraform output
    terraform_output = get_terraform_output()
    
    # Generate inventory
    inventory = generate_kubespray_inventory(terraform_output)
    
    # Write inventory file
    kubespray_inventory_path = Path(__file__).parent.parent / "kubespray" / "inventory" / "proxmox-cluster" / "inventory.ini"
    kubespray_inventory_path.parent.mkdir(parents=True, exist_ok=True)
    
    write_inventory_ini(inventory, kubespray_inventory_path)
    
    print(f"Kubespray inventory generated: {kubespray_inventory_path}")
    
    # Display summary
    print("\nCluster Summary:")
    control_plane_count = len(inventory["kube_control_plane"]["hosts"])
    worker_count = len(inventory["kube_node"]["hosts"])
    print(f"  • Control Plane Nodes: {control_plane_count}")
    print(f"  • Worker Nodes: {worker_count}")
    print(f"  • Total Nodes: {control_plane_count + worker_count}")
    
    # Display inventory preview
    print(f"\nInventory Preview:")
    with open(kubespray_inventory_path, 'r') as f:
        content = f.read()
        print(content[:500] + ("..." if len(content) > 500 else ""))


if __name__ == "__main__":
    main()
