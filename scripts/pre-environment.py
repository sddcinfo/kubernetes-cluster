#!/usr/bin/env python3
"""
Comprehensive Pre-Environment Setup Script
Combines validation, cloud image preparation, and base VM creation for Kubernetes cluster deployment
"""

import subprocess
import sys
import json
import re
import time
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import asyncio
import os

# Colors for output
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    NC = '\033[0m'  # No Color

def log_info(msg: str):
    print(f"{Colors.GREEN}[INFO]{Colors.NC} {msg}")

def log_error(msg: str):
    print(f"{Colors.RED}[ERROR]{Colors.NC} {msg}")

def log_warning(msg: str):
    print(f"{Colors.YELLOW}[WARN]{Colors.NC} {msg}")

def log_step(msg: str):
    print(f"{Colors.BLUE}[STEP]{Colors.NC} {msg}")

# Configuration
PROXMOX_HOST = "10.10.1.21"
BASE_VM_ID = "9002"
GOLDEN_VM_ID = "9001"
MODIFIED_IMAGE = "ubuntu-24.04-cloudimg-amd64-modified.img"
VM_NAME = "ubuntu-cloud-base"
GOLDEN_VM_NAME = "ubuntu-2404-golden"
IMAGE_URL = "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"

# Required network bridges
REQUIRED_NETWORKS = ["vmbr0"]

# SSH key paths
SSH_KEY_PATH = Path("/home/sysadmin/.ssh/sysadmin_automation_key")
SSH_PUB_KEY_PATH = Path("/home/sysadmin/.ssh/sysadmin_automation_key.pub")

def run_command(cmd: str, check: bool = True, capture_output: bool = True) -> subprocess.CompletedProcess:
    """Run a command with proper error handling"""
    try:
        result = subprocess.run(
            cmd, 
            shell=True, 
            check=check, 
            capture_output=capture_output,
            text=True
        )
        return result
    except subprocess.CalledProcessError as e:
        if check:
            log_error(f"Command failed: {cmd}")
            log_error(f"Error: {e.stderr if e.stderr else str(e)}")
            raise
        return e

def ssh_command(cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a command on the Proxmox host via SSH"""
    full_cmd = f"ssh root@{PROXMOX_HOST} \"{cmd}\""
    return run_command(full_cmd, check=check)

def check_ssh_connectivity() -> bool:
    """Check SSH connectivity to Proxmox host"""
    log_step("Checking SSH connectivity to Proxmox host...")
    try:
        result = ssh_command("echo 'SSH connection test'")
        log_info("SSH connectivity verified")
        return True
    except subprocess.CalledProcessError:
        log_error(f"Cannot connect to Proxmox host {PROXMOX_HOST} via SSH")
        return False

def check_ssh_keys() -> bool:
    """Check for required SSH keys"""
    log_step("Checking SSH keys...")
    
    if not SSH_KEY_PATH.exists():
        log_error(f"SSH private key not found: {SSH_KEY_PATH}")
        return False
    
    if not SSH_PUB_KEY_PATH.exists():
        log_error(f"SSH public key not found: {SSH_PUB_KEY_PATH}")
        return False
    
    log_info("SSH keys found")
    return True

def check_network_requirements() -> bool:
    """Validate network configuration"""
    log_step("Checking network requirements...")
    
    try:
        # Check for required bridges (may not exist on deployment host)
        networks_found = []
        for bridge in REQUIRED_NETWORKS:
            try:
                # Check if bridge exists on Proxmox host
                result = ssh_command(f"ip link show {bridge}", check=False)
                if result.returncode == 0:
                    networks_found.append(bridge)
                    log_info(f"Network bridge {bridge} found on Proxmox host")
                else:
                    log_warning(f"Network bridge {bridge} not found on Proxmox host")
            except Exception as e:
                log_warning(f"Could not check network bridge {bridge}: {e}")
        
        if not networks_found:
            log_error("No required network bridges found")
            return False
            
        return True
        
    except Exception as e:
        log_error(f"Network validation failed: {e}")
        return False

def check_rbd_storage() -> bool:
    """Check RBD storage availability"""
    log_step("Checking RBD storage...")
    
    try:
        # Check if RBD pool exists
        result = ssh_command("rbd ls", check=False)
        if result.returncode != 0:
            log_error("RBD storage not available or not configured")
            return False
        
        log_info("RBD storage available")
        return True
        
    except Exception as e:
        log_error(f"RBD storage check failed: {e}")
        return False

def install_required_tools() -> bool:
    """Install required tools on Proxmox host"""
    log_step("Installing required tools on Proxmox host...")
    
    try:
        ssh_command("apt-get update >/dev/null 2>&1 && apt-get install -y libguestfs-tools >/dev/null 2>&1")
        log_info("Required tools installed")
        return True
    except subprocess.CalledProcessError:
        log_error("Failed to install required tools")
        return False

def setup_rbd_iso_storage() -> bool:
    """Setup RBD-ISO storage for multi-OS support"""
    log_step("Setting up RBD-ISO storage...")
    
    try:
        # Check if storage already exists
        result = ssh_command("test -d /mnt/rbd-iso/template/images", check=False)
        if result.returncode == 0:
            log_info("RBD-ISO storage already exists")
            return True
        
        # Create RBD volume for ISO storage (16GB should be sufficient for multiple OS images)
        log_info("Creating RBD volume for ISO storage...")
        result = ssh_command("rbd create rbd-iso --size 16G", check=False)
        if result.returncode != 0:
            log_warning("RBD volume 'rbd-iso' might already exist, continuing...")
        
        # Create mount point
        ssh_command("mkdir -p /mnt/rbd-iso")
        
        # Map RBD device
        log_info("Mapping RBD device...")
        result = ssh_command("rbd map rbd/rbd-iso", check=False)
        if result.returncode != 0:
            log_warning("RBD device might already be mapped, continuing...")
        
        # Create filesystem if it doesn't exist
        result = ssh_command("blkid /dev/rbd/rbd/rbd-iso | grep ext4", check=False)
        if result.returncode != 0:
            log_info("Creating ext4 filesystem on RBD volume...")
            ssh_command("mkfs.ext4 -F /dev/rbd/rbd/rbd-iso")
        
        # Mount the RBD volume
        log_info("Mounting RBD-ISO storage...")
        result = ssh_command("mount /dev/rbd/rbd/rbd-iso /mnt/rbd-iso", check=False)
        if result.returncode != 0:
            log_warning("RBD volume might already be mounted, continuing...")
        
        # Create directory structure for multi-OS support
        ssh_command("mkdir -p /mnt/rbd-iso/template/iso /mnt/rbd-iso/template/images")
        
        # Set ownership
        ssh_command("chown -R root:www-data /mnt/rbd-iso && chmod -R 755 /mnt/rbd-iso")
        
        log_info("RBD-ISO storage setup completed")
        return True
        
    except subprocess.CalledProcessError as e:
        log_error(f"Failed to setup RBD-ISO storage: {e}")
        return False

def setup_packer_user() -> Optional[str]:
    """Setup Packer user and permissions, return API token"""
    log_step("Setting up Packer user and permissions...")
    
    try:
        # Check if packer user exists
        result = ssh_command("pveum user list | grep 'packer@pam'", check=False)
        
        if result.returncode != 0:
            log_info("Creating Packer user...")
            
            # Create packer user
            ssh_command("pveum user add packer@pam --comment 'Packer automation user'")
            
            # Set password for packer user
            ssh_command("echo 'packer' | pveum passwd packer@pam --stdin")
            
            # Create comprehensive permissions for packer user
            role_privs = "VM.Allocate,VM.Clone,VM.Config.CDROM,VM.Config.CPU,VM.Config.Cloudinit,VM.Config.Disk,VM.Config.HWType,VM.Config.Memory,VM.Config.Network,VM.Config.Options,VM.Audit,VM.PowerMgmt,Datastore.AllocateSpace,Datastore.Audit,SDN.Use,VM.GuestAgent.Audit,VM.GuestAgent.Unrestricted"
            
            result = ssh_command(f"pveum role add PackerRole -privs '{role_privs}'", check=False)
            if result.returncode != 0:
                log_warning("PackerRole might already exist, updating permissions...")
                ssh_command(f"pveum role modify PackerRole -privs '{role_privs}'")
            
            # Assign role to packer user  
            ssh_command("pveum aclmod / -user packer@pam -role PackerRole")
        else:
            log_info("Packer user already exists")
            
            # Ensure the role exists and ACL is properly set even if user exists
            role_privs = "VM.Allocate,VM.Clone,VM.Config.CDROM,VM.Config.CPU,VM.Config.Cloudinit,VM.Config.Disk,VM.Config.HWType,VM.Config.Memory,VM.Config.Network,VM.Config.Options,VM.Audit,VM.PowerMgmt,Datastore.AllocateSpace,Datastore.Audit,SDN.Use,VM.GuestAgent.Audit,VM.GuestAgent.Unrestricted"
            
            result = ssh_command(f"pveum role add PackerRole -privs '{role_privs}'", check=False)
            if result.returncode != 0:
                log_info("PackerRole already exists, updating permissions...")
                ssh_command(f"pveum role modify PackerRole -privs '{role_privs}'")
            
            # Ensure ACL is set (this was the missing piece!)
            ssh_command("pveum aclmod / -user packer@pam -role PackerRole")
        
        # Create/recreate API token for packer user
        log_info("Creating API token for packer user...")
        
        # Remove existing token if it exists
        ssh_command("pveum user token remove packer@pam packer", check=False)
        
        # Create new token
        result = ssh_command("pveum user token add packer@pam packer --comment 'Packer automation token' --output-format json")
        
        # Extract token from output
        token_data = json.loads(result.stdout.strip())
        packer_token = token_data.get("value")
        
        if not packer_token:
            log_error("Failed to extract Packer token")
            return None
        
        # Disable privilege separation for the token
        ssh_command("pveum user token modify packer@pam packer --privsep 0")
        
        log_info(f"Packer token created: packer@pam!packer={packer_token}")
        return packer_token
        
    except subprocess.CalledProcessError as e:
        log_error(f"Failed to setup Packer user: {e}")
        return None

def prepare_cloud_image() -> bool:
    """Prepare Ubuntu cloud image with qemu-guest-agent"""
    log_step("Preparing Ubuntu cloud image...")
    
    try:
        # Check if modified cloud image already exists
        result = ssh_command(f"test -f /mnt/rbd-iso/template/images/{MODIFIED_IMAGE}", check=False)
        if result.returncode == 0:
            log_info("Modified cloud image already exists")
            return True
        
        log_info("Downloading Ubuntu 24.04 Noble cloud image...")
        ssh_command(f"cd /mnt/rbd-iso/template/images && wget -q -O {MODIFIED_IMAGE} {IMAGE_URL}")
        
        log_info("Installing qemu-guest-agent and EFI boot support in cloud image...")
        ssh_command(f"cd /mnt/rbd-iso/template/images && virt-customize --quiet --install qemu-guest-agent,grub-efi-amd64,grub-efi-amd64-signed,shim-signed -a {MODIFIED_IMAGE}")
        
        log_info("Resetting machine-id to avoid DHCP conflicts...")
        result = ssh_command(f"cd /mnt/rbd-iso/template/images && virt-sysprep --quiet -a {MODIFIED_IMAGE}", check=False)
        if result.returncode != 0:
            log_warning("virt-sysprep failed, continuing anyway")
        
        log_info("Creating sysadmin user in cloud image...")
        ssh_command(f"cd /mnt/rbd-iso/template/images && virt-customize --quiet -a {MODIFIED_IMAGE} --run-command 'useradd -m -s /bin/bash sysadmin'")
        
        log_info("Setting up sysadmin user with sudo privileges...")
        ssh_command(f"cd /mnt/rbd-iso/template/images && virt-customize --quiet -a {MODIFIED_IMAGE} --run-command 'usermod -aG sudo sysadmin'")
        
        log_info("Setting sysadmin password...")
        ssh_command(f"cd /mnt/rbd-iso/template/images && virt-customize --quiet -a {MODIFIED_IMAGE} --run-command 'echo \"sysadmin:password\" | chpasswd'")
        
        log_info("Injecting SSH key for sysadmin user...")
        run_command(f"scp {SSH_PUB_KEY_PATH} root@{PROXMOX_HOST}:/tmp/")
        ssh_command(f"cd /mnt/rbd-iso/template/images && virt-customize --quiet -a {MODIFIED_IMAGE} --ssh-inject sysadmin:file:/tmp/sysadmin_automation_key.pub")
        
        log_info("Setting up sudoers for sysadmin...")
        ssh_command(f"cd /mnt/rbd-iso/template/images && virt-customize --quiet -a {MODIFIED_IMAGE} --run-command 'echo \"sysadmin ALL=(ALL) NOPASSWD:ALL\" > /etc/sudoers.d/sysadmin'")
        
        log_info("Fixing EFI boot partition and installing GRUB properly...")
        result = ssh_command(f"cd /mnt/rbd-iso/template/images && virt-customize --quiet -a {MODIFIED_IMAGE} --run-command 'mkdir -p /boot/efi && mount /dev/sda15 /boot/efi || mount /dev/vda15 /boot/efi'", check=False)
        if result.returncode != 0:
            log_warning("Failed to mount EFI partition, continuing anyway")
        
        log_info("Installing and configuring EFI bootloader...")
        result = ssh_command(f"cd /mnt/rbd-iso/template/images && virt-customize --quiet -a {MODIFIED_IMAGE} --run-command 'update-grub && grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=ubuntu --recheck'", check=False)
        if result.returncode != 0:
            log_warning("EFI bootloader installation failed, continuing anyway")
        
        log_info("Creating UEFI fallback bootloader...")
        result = ssh_command(f"cd /mnt/rbd-iso/template/images && virt-customize --quiet -a {MODIFIED_IMAGE} --run-command 'mkdir -p /boot/efi/EFI/BOOT && cp /boot/efi/EFI/ubuntu/grubx64.efi /boot/efi/EFI/BOOT/BOOTX64.EFI 2>/dev/null || cp /boot/efi/EFI/ubuntu/shimx64.efi /boot/efi/EFI/BOOT/BOOTX64.EFI'", check=False)
        if result.returncode != 0:
            log_warning("EFI fallback bootloader creation failed, continuing anyway")
        
        log_info("Cloud image prepared successfully")
        return True
        
    except subprocess.CalledProcessError as e:
        log_error(f"Failed to prepare cloud image: {e}")
        return False

def create_base_vm() -> bool:
    """Create base VM from modified cloud image"""
    log_step("Creating base VM from modified cloud image...")
    
    try:
        # Check if VM already exists
        result = ssh_command(f"qm status {BASE_VM_ID}", check=False)
        if result.returncode == 0:
            log_warning(f"Base VM {BASE_VM_ID} already exists, removing...")
            ssh_command(f"qm stop {BASE_VM_ID} || true && qm destroy {BASE_VM_ID} --purge")
            log_info("Existing base VM removed")
        
        log_info("Creating base VM with modern EFI configuration...")
        
        # Create VM with modern EFI configuration and VirtIO RNG for entropy
        ssh_command(f"qm create {BASE_VM_ID} --name {VM_NAME} --memory 2048 --cores 2 --net0 virtio,bridge=vmbr0 --scsihw virtio-scsi-pci --ostype l26 --cpu host --agent enabled=1 --machine q35 --bios ovmf --rng0 source=/dev/urandom,max_bytes=1024,period=1000")
        
        # Disable ROM bar on network interface to prevent iPXE boot
        result = ssh_command(f"qm set {BASE_VM_ID} --net0 virtio,bridge=vmbr0,rombar=0", check=False)
        if result.returncode != 0:
            log_warning("Failed to disable network ROM bar, continuing anyway")
        
        # Add EFI disk with secure boot disabled for better compatibility
        ssh_command(f"qm set {BASE_VM_ID} --efidisk0 rbd:4,efitype=4m,pre-enrolled-keys=0")
        
        # Import modified cloud image as disk
        log_info("Importing modified cloud image as VM disk...")
        ssh_command(f"qm importdisk {BASE_VM_ID} /mnt/rbd-iso/template/images/{MODIFIED_IMAGE} rbd --format raw")
        
        # Attach the imported disk as scsi0
        ssh_command(f"qm set {BASE_VM_ID} --scsi0 rbd:vm-{BASE_VM_ID}-disk-1")
        
        # Set boot configuration (order: disk first, then CD-ROM)
        ssh_command(f"qm set {BASE_VM_ID} --boot order=scsi0 --bootdisk scsi0")
        
        # Add cloud-init drive
        ssh_command(f"qm set {BASE_VM_ID} --ide2 rbd:cloudinit")
        
        # Copy SSH key to Proxmox host
        if SSH_PUB_KEY_PATH.exists():
            run_command(f"scp {SSH_PUB_KEY_PATH} root@{PROXMOX_HOST}:/tmp/")
        
        # Configure cloud-init with sysadmin user
        ssh_command(f"qm set {BASE_VM_ID} --ciuser sysadmin --cipassword password --sshkeys /tmp/sysadmin_automation_key.pub --ipconfig0 ip=dhcp")
        
        # Resize disk to reasonable size
        result = ssh_command(f"qm resize {BASE_VM_ID} scsi0 32G", check=False)
        if result.returncode != 0:
            log_warning("Failed to resize disk, continuing anyway")
        
        # Convert to template
        log_info("Converting to template...")
        ssh_command(f"qm template {BASE_VM_ID}")
        
        log_info("Base template created successfully")
        return True
        
    except subprocess.CalledProcessError as e:
        log_error(f"Failed to create base VM: {e}")
        return False

def write_packer_env_file(token: str) -> bool:
    """Write Packer environment file with token"""
    log_step("Writing Packer environment configuration...")
    
    try:
        env_content = f"""# Packer Environment Configuration
# Generated by pre-environment.py script
export PROXMOX_HOST="{PROXMOX_HOST}:8006"
export PROXMOX_TOKEN="{token}"
export PROXMOX_USER="packer@pam!packer"
"""
        
        env_file = Path("packer/.env")
        env_file.write_text(env_content)
        
        # Also create a JSON file for Packer variables
        packer_vars = {
            "proxmox_host": f"{PROXMOX_HOST}:8006",
            "proxmox_token": token,
            "template_name": GOLDEN_VM_NAME,
            "template_id": GOLDEN_VM_ID
        }
        
        vars_file = Path("packer/variables.json")
        with vars_file.open('w') as f:
            json.dump(packer_vars, f, indent=2)
        
        log_info("Packer environment files created")
        return True
        
    except Exception as e:
        log_error(f"Failed to write Packer environment files: {e}")
        return False

def update_packer_config(token: str) -> bool:
    """Update Packer configuration to use external variables"""
    log_step("Updating Packer configuration...")
    
    try:
        packer_file = Path("packer/ubuntu-golden.pkr.hcl")
        
        # Read current content
        content = packer_file.read_text()
        
        # Replace hardcoded token with variable reference
        content = re.sub(
            r'token\s*=\s*"[^"]*"',
            'token = var.proxmox_token',
            content
        )
        
        # Update the proxmox_token variable default value with the actual token
        content = re.sub(
            r'variable "proxmox_token" \{\s*type\s*=\s*string\s*default\s*=\s*"[^"]*"',
            f'variable "proxmox_token" {{\n  type    = string\n  default = "{token}"',
            content
        )
        
        # If the variable doesn't exist, add it
        if 'variable "proxmox_token"' not in content:
            # Add variable definition after existing variables
            var_insert_point = content.find('variable "template_id"')
            if var_insert_point != -1:
                # Find end of template_id variable
                end_point = content.find('}', var_insert_point) + 1
                new_var = f'\n\nvariable "proxmox_token" {{\n  type    = string\n  default = "{token}"\n}}\n'
                content = content[:end_point] + new_var + content[end_point:]
        
        # Write updated content
        packer_file.write_text(content)
        
        log_info("Packer configuration updated with token")
        return True
        
    except Exception as e:
        log_error(f"Failed to update Packer configuration: {e}")
        return False

def validate_environment() -> bool:
    """Run comprehensive environment validation"""
    print("=" * 60)
    print("COMPREHENSIVE PRE-ENVIRONMENT VALIDATION")
    print("=" * 60)
    
    validations = [
        ("SSH connectivity", check_ssh_connectivity),
        ("SSH keys", check_ssh_keys),
        ("Network configuration", check_network_requirements),
        ("RBD storage", check_rbd_storage),
    ]
    
    all_passed = True
    for description, check_func in validations:
        if not check_func():
            all_passed = False
    
    if not all_passed:
        log_error("Environment validation failed!")
        return False
    
    log_info("All environment validations passed!")
    return True

def main():
    """Main execution function"""
    print("=" * 60)
    print("COMPREHENSIVE PRE-ENVIRONMENT SETUP")
    print("=" * 60)
    
    # Step 1: Validate environment
    if not validate_environment():
        sys.exit(1)
    
    # Step 2: Install required tools
    if not install_required_tools():
        sys.exit(1)
    
    # Step 3: Setup RBD-ISO storage
    if not setup_rbd_iso_storage():
        sys.exit(1)
    
    # Step 4: Setup Packer user and get token
    packer_token = setup_packer_user()
    if not packer_token:
        sys.exit(1)
    
    # Step 5: Prepare cloud image
    if not prepare_cloud_image():
        sys.exit(1)
    
    # Step 6: Create base VM template
    if not create_base_vm():
        sys.exit(1)
    
    # Step 7: Write Packer environment files
    if not write_packer_env_file(packer_token):
        sys.exit(1)
    
    # Step 8: Update Packer configuration with token
    if not update_packer_config(packer_token):
        sys.exit(1)
    
    print()
    print("=" * 60)
    print(f"{Colors.GREEN}✓ PRE-ENVIRONMENT SETUP COMPLETED SUCCESSFULLY{Colors.NC}")
    print("=" * 60)
    print(f"Base template created: {VM_NAME} (ID: {BASE_VM_ID})")
    print(f"Packer token stored in: packer/.env")
    print(f"Packer variables stored in: packer/variables.json")
    print("Ready to run: packer build -var-file=variables.json packer/ubuntu-golden.pkr.hcl")
    print("=" * 60)

if __name__ == "__main__":
    main()