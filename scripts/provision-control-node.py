#!/usr/bin/env python3
"""
Provision a Kubernetes control plane node from template
"""

import subprocess
import time
import sys
import json
import yaml
from pathlib import Path

# Load template configuration
def load_template_config():
    """Load template configuration from YAML file"""
    config_paths = [
        Path.home() / 'proxmox-config' / 'templates.yaml',
        Path('/home/sysadmin/claude/ansible-provisioning-server/config/templates.yaml'),
        Path.home() / '.config' / 'proxmox-templates.yaml'
    ]
    
    for path in config_paths:
        if path.exists():
            with open(path, 'r') as f:
                return yaml.safe_load(f)
    
    # Fall back to hardcoded defaults
    print("[WARNING] No template config found, using defaults. Make sure ansible-provisioning-server is set up first.")
    return {'templates': {'kubernetes': {'id': 9001}}}

# Configuration
template_config = load_template_config()
TEMPLATE_ID = template_config['templates']['kubernetes']['id']
NEW_VM_ID = 131  # Using 131 to match IP 10.10.1.31
VM_NAME = "k8s-control-1"
VM_IP = "10.10.1.31"
VM_CORES = 4
VM_MEMORY = 8192
VM_DISK = "50G"
PROXMOX_HOST = "10.10.1.21"
PROXMOX_NODE = "hp4"

def run_ssh_command(command, timeout=300):
    """Run SSH command on Proxmox host"""
    ssh_cmd = [
        "ssh", "-o", "ConnectTimeout=10",
        "-o", "StrictHostKeyChecking=no",
        f"root@{PROXMOX_HOST}",
        command
    ]
    
    try:
        result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        print(f"Command timed out after {timeout} seconds")
        return 1, "", "Timeout"
    except Exception as e:
        print(f"Error running command: {e}")
        return 1, "", str(e)

def main():
    print(f"🚀 Provisioning Kubernetes control plane node: {VM_NAME}")
    print(f"   Template: {TEMPLATE_ID}")
    print(f"   New VM ID: {NEW_VM_ID}")
    print(f"   Static IP: {VM_IP}/24")
    print(f"   Resources: {VM_CORES} cores, {VM_MEMORY}MB RAM, {VM_DISK} disk")
    print()
    
    # Step 1: Check if VM already exists
    print("1️⃣ Checking if VM already exists...")
    returncode, stdout, stderr = run_ssh_command(f"qm status {NEW_VM_ID}")
    if returncode == 0:
        print(f"   ⚠️  VM {NEW_VM_ID} already exists!")
        response = input("   Do you want to destroy it and recreate? (y/n): ")
        if response.lower() != 'y':
            print("   Aborting...")
            sys.exit(0)
        
        print(f"   Destroying existing VM {NEW_VM_ID}...")
        run_ssh_command(f"qm stop {NEW_VM_ID}")
        time.sleep(2)
        returncode, stdout, stderr = run_ssh_command(f"qm destroy {NEW_VM_ID}")
        if returncode != 0:
            print(f"   ❌ Failed to destroy VM: {stderr}")
            sys.exit(1)
        print("   ✅ Existing VM destroyed")
    else:
        print("   ✅ VM does not exist, proceeding...")
    
    # Step 2: Clone from template
    print(f"\n2️⃣ Cloning from template {TEMPLATE_ID}...")
    returncode, stdout, stderr = run_ssh_command(
        f"qm clone {TEMPLATE_ID} {NEW_VM_ID} --name {VM_NAME} --full true"
    )
    if returncode != 0:
        print(f"   ❌ Failed to clone template: {stderr}")
        sys.exit(1)
    print(f"   ✅ Successfully cloned to VM {NEW_VM_ID}")
    
    # Step 3: Configure VM resources
    print("\n3️⃣ Configuring VM resources...")
    
    # Set CPU and memory
    returncode, stdout, stderr = run_ssh_command(
        f"qm set {NEW_VM_ID} --cores {VM_CORES} --memory {VM_MEMORY}"
    )
    if returncode != 0:
        print(f"   ❌ Failed to set resources: {stderr}")
        sys.exit(1)
    print(f"   ✅ Set {VM_CORES} cores and {VM_MEMORY}MB RAM")
    
    # Resize disk
    returncode, stdout, stderr = run_ssh_command(
        f"qm resize {NEW_VM_ID} scsi0 {VM_DISK}"
    )
    if returncode != 0:
        print(f"   ⚠️  Warning: Could not resize disk: {stderr}")
    else:
        print(f"   ✅ Resized disk to {VM_DISK}")
    
    # Step 4: Configure static IP via cloud-init
    print("\n4️⃣ Configuring static IP via cloud-init...")
    returncode, stdout, stderr = run_ssh_command(
        f"qm set {NEW_VM_ID} --ipconfig0 ip={VM_IP}/24,gw=10.10.1.1"
    )
    if returncode != 0:
        print(f"   ❌ Failed to set static IP: {stderr}")
        sys.exit(1)
    print(f"   ✅ Configured static IP {VM_IP}/24")
    
    # Set nameserver
    returncode, stdout, stderr = run_ssh_command(
        f"qm set {NEW_VM_ID} --nameserver 10.10.1.1"
    )
    if returncode != 0:
        print(f"   ⚠️  Warning: Could not set nameserver: {stderr}")
    else:
        print("   ✅ Set nameserver to 10.10.1.1")
    
    # Set hostname via cloud-init
    returncode, stdout, stderr = run_ssh_command(
        f"qm set {NEW_VM_ID} --ciuser sysadmin --cipassword password"
    )
    
    # Step 5: Start the VM
    print("\n5️⃣ Starting VM...")
    returncode, stdout, stderr = run_ssh_command(f"qm start {NEW_VM_ID}")
    if returncode != 0:
        print(f"   ❌ Failed to start VM: {stderr}")
        sys.exit(1)
    print("   ✅ VM started")
    
    # Step 6: Wait for VM to be ready
    print("\n6️⃣ Waiting for VM to be ready...")
    max_attempts = 30
    for attempt in range(1, max_attempts + 1):
        print(f"   Attempt {attempt}/{max_attempts} - checking VM status...")
        
        # Check if qemu-guest-agent is responding
        returncode, stdout, stderr = run_ssh_command(
            f"qm guest cmd {NEW_VM_ID} network-get-interfaces"
        )
        
        if returncode == 0:
            try:
                # Parse the network interfaces to verify IP
                interfaces = json.loads(stdout)
                for iface in interfaces:
                    if 'ip-addresses' in iface:
                        for addr in iface['ip-addresses']:
                            if addr.get('ip-address', '').startswith('10.10.1.'):
                                detected_ip = addr['ip-address']
                                print(f"   ✅ VM is ready! Detected IP: {detected_ip}")
                                break
                        else:
                            continue
                        break
                else:
                    time.sleep(10)
                    continue
                break
            except:
                pass
        
        time.sleep(10)
    else:
        print("   ⚠️  VM did not become ready in time, but may still be booting...")
    
    # Step 7: Test SSH connectivity
    print("\n7️⃣ Testing SSH connectivity...")
    time.sleep(10)  # Give SSH service time to start
    
    ssh_test = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=no",
         "-i", "/home/sysadmin/.ssh/sysadmin_automation_key",
         f"sysadmin@{VM_IP}", "hostname"],
        capture_output=True, text=True
    )
    
    if ssh_test.returncode == 0:
        print(f"   ✅ SSH connection successful! Hostname: {ssh_test.stdout.strip()}")
    else:
        print(f"   ⚠️  SSH connection failed, VM may need more time to initialize")
    
    # Summary
    print("\n" + "="*60)
    print("✅ PROVISIONING COMPLETE!")
    print("="*60)
    print(f"VM Name: {VM_NAME}")
    print(f"VM ID: {NEW_VM_ID}")
    print(f"IP Address: {VM_IP}")
    print(f"SSH: ssh -i ~/.ssh/sysadmin_automation_key sysadmin@{VM_IP}")
    print("\nNext steps:")
    print("1. Initialize Kubernetes cluster on this node")
    print("2. Configure as control plane node")
    print("3. Install CNI (Cilium)")
    print("="*60)

if __name__ == "__main__":
    main()