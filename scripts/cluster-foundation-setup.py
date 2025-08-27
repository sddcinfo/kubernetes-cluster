#!/usr/bin/env python3
"""
Kubernetes Cluster Foundation Setup
Intelligent environment preparation with state tracking and re-run optimization
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
import argparse
from datetime import datetime

# Colors for output
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    CYAN = '\033[0;36m'
    NC = '\033[0m'  # No Color

def log_info(msg: str):
    print(f"{Colors.GREEN}[INFO]{Colors.NC} {msg}")

def log_error(msg: str):
    print(f"{Colors.RED}[ERROR]{Colors.NC} {msg}")

def log_warning(msg: str):
    print(f"{Colors.YELLOW}[WARN]{Colors.NC} {msg}")

def log_step(msg: str):
    print(f"{Colors.BLUE}[STEP]{Colors.NC} {msg}")

def log_skip(msg: str):
    print(f"{Colors.CYAN}[SKIP]{Colors.NC} {msg}")

# Configuration - externalized for easier management
class Config:
    def __init__(self):
        self.PROXMOX_HOST = "10.10.1.21"
        self.BASE_VM_ID = "9002"
        self.MODIFIED_IMAGE = "ubuntu-24.04-cloudimg-amd64-modified.img"
        self.VM_NAME = "ubuntu-cloud-base"
        self.IMAGE_URL = "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"
        self.REQUIRED_NETWORKS = ["vmbr0"]
        self.SSH_KEY_PATH = Path("/home/sysadmin/.ssh/sysadmin_automation_key")
        self.SSH_PUB_KEY_PATH = Path("/home/sysadmin/.ssh/sysadmin_automation_key.pub")
        self.STATE_FILE = Path.home() / ".kube-cluster" / "foundation-state.json"
        
        # Load custom config if exists
        self._load_custom_config()
        
    def _load_custom_config(self):
        """Load custom configuration from config file if exists"""
        # Legacy JSON config support - deprecated in favor of YAML configs
        config_file = Path("scripts/foundation-config.json")
        if config_file.exists():
            try:
                with config_file.open('r') as f:
                    custom_config = json.load(f)
                    for key, value in custom_config.items():
                        if hasattr(self, key):
                            setattr(self, key, value)
                log_info("Custom configuration loaded")
            except Exception as e:
                log_warning(f"Could not load custom config: {e}")

class StateManager:
    """Manages setup state to enable intelligent re-runs"""
    
    def __init__(self, state_file: Path):
        self.state_file = state_file
        self.state = self._load_state()
    
    def _load_state(self) -> Dict:
        """Load existing state or create new"""
        if self.state_file.exists():
            try:
                with self.state_file.open('r') as f:
                    return json.load(f)
            except Exception as e:
                log_warning(f"Could not load state file: {e}")
        
        return {
            "version": "1.0",
            "created": datetime.now().isoformat(),
            "phases": {},
            "resources": {}
        }
    
    def save_state(self):
        """Save current state to file"""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state["last_updated"] = datetime.now().isoformat()
            
            with self.state_file.open('w') as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            log_error(f"Could not save state: {e}")
    
    def is_phase_complete(self, phase: str) -> bool:
        """Check if phase is already completed"""
        return self.state["phases"].get(phase, {}).get("completed", False)
    
    def mark_phase_complete(self, phase: str, details: Dict = None):
        """Mark phase as completed with optional details"""
        self.state["phases"][phase] = {
            "completed": True,
            "timestamp": datetime.now().isoformat(),
            "details": details or {}
        }
        self.save_state()
    
    def invalidate_phase(self, phase: str):
        """Invalidate a phase when resources are detected as missing"""
        if phase in self.state["phases"]:
            log_info(f"Invalidating cached state for phase: {phase}")
            del self.state["phases"][phase]
            self.save_state()
    
    def mark_resource_created(self, resource_type: str, resource_id: str, details: Dict = None):
        """Track created resources"""
        if resource_type not in self.state["resources"]:
            self.state["resources"][resource_type] = {}
        
        self.state["resources"][resource_type][resource_id] = {
            "created": datetime.now().isoformat(),
            "details": details or {}
        }
        self.save_state()
    
    def reset_state(self):
        """Reset all state - use with caution"""
        self.state = {
            "version": "1.0",
            "created": datetime.now().isoformat(),
            "phases": {},
            "resources": {}
        }
        self.save_state()

class FoundationSetup:
    """Main foundation setup class with intelligent state management"""
    
    def __init__(self, config: Config, force_rebuild: bool = False, skip_phases: List[str] = None):
        self.config = config
        self.force_rebuild = force_rebuild
        self.skip_phases = skip_phases or []
        self.state = StateManager(config.STATE_FILE)
        
        if force_rebuild:
            log_warning("Force rebuild enabled - all phases will be re-executed")
            self.state.reset_state()
    
    def run_command(self, cmd: str, check: bool = True, capture_output: bool = True, timeout: int = 30) -> subprocess.CompletedProcess:
        """Run a command with proper error handling and timeout"""
        try:
            result = subprocess.run(
                cmd, 
                shell=True, 
                check=check, 
                capture_output=capture_output,
                text=True,
                timeout=timeout
            )
            return result
        except subprocess.TimeoutExpired:
            log_error(f"Command timed out after {timeout} seconds: {cmd}")
            if check:
                raise
            return subprocess.CompletedProcess(cmd, 1, '', f'Command timed out after {timeout} seconds')
        except subprocess.CalledProcessError as e:
            if check:
                log_error(f"Command failed: {cmd}")
                log_error(f"Error: {e.stderr if e.stderr else str(e)}")
                raise
            return e
    
    def ssh_command(self, cmd: str, check: bool = True, timeout: int = 30) -> subprocess.CompletedProcess:
        """Run a command on the Proxmox host via SSH with proper timeout options"""
        ssh_opts = "-o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=3 -o StrictHostKeyChecking=no"
        full_cmd = f"ssh {ssh_opts} root@{self.config.PROXMOX_HOST} \"{cmd}\""
        return self.run_command(full_cmd, check=check, timeout=timeout)
    
    def check_vm_in_use(self, vm_id: str) -> bool:
        """Check if VM is currently running or has dependent resources"""
        try:
            result = self.ssh_command(f"qm status {vm_id}", check=False)
            if result.returncode != 0:
                return False  # VM doesn't exist
                
            # Parse status to see if running
            status_info = result.stdout.strip()
            if "status: running" in status_info:
                log_warning(f"VM {vm_id} is currently running")
                return True
            
            # Check if VM is a template with dependent clones
            result = self.ssh_command(f"qm config {vm_id} | grep template", check=False)
            if result.returncode == 0:
                # This is a template - check for clones
                result = self.ssh_command("qm list | grep -v VMID", check=False)
                if result.returncode == 0:
                    for line in result.stdout.strip().split('\n'):
                        if f"Clone of {vm_id}" in line or f"clone-{vm_id}" in line:
                            log_warning(f"Template {vm_id} has active clones")
                            return True
            
            return False
            
        except Exception as e:
            log_warning(f"Could not check VM {vm_id} status: {e}")
            return True  # Err on side of caution

    def validate_environment(self) -> bool:
        """Run comprehensive environment validation"""
        phase = "validation"
        if self.state.is_phase_complete(phase) and phase not in self.skip_phases:
            log_skip("Environment validation already completed")
            return True
        
        log_step("Validating environment...")
        
        validations = [
            ("SSH connectivity", self._check_ssh_connectivity),
            ("SSH keys", self._check_ssh_keys),
            ("Network configuration", self._check_network_requirements),
            ("RBD storage", self._check_rbd_storage),
        ]
        
        all_passed = True
        for description, check_func in validations:
            if not check_func():
                all_passed = False
        
        if all_passed:
            self.state.mark_phase_complete(phase)
            log_info("Environment validation completed")
        
        return all_passed
    
    def _check_ssh_connectivity(self) -> bool:
        """Check SSH connectivity to Proxmox host"""
        try:
            result = self.ssh_command("echo 'SSH connection test'")
            log_info("SSH connectivity verified")
            return True
        except subprocess.CalledProcessError:
            log_error(f"Cannot connect to Proxmox host {self.config.PROXMOX_HOST} via SSH")
            return False
    
    def _check_ssh_keys(self) -> bool:
        """Check for required SSH keys"""
        if not self.config.SSH_KEY_PATH.exists():
            log_error(f"SSH private key not found: {self.config.SSH_KEY_PATH}")
            return False
        
        if not self.config.SSH_PUB_KEY_PATH.exists():
            log_error(f"SSH public key not found: {self.config.SSH_PUB_KEY_PATH}")
            return False
        
        log_info("SSH keys found")
        return True
    
    def _check_network_requirements(self) -> bool:
        """Validate network configuration"""
        try:
            networks_found = []
            for bridge in self.config.REQUIRED_NETWORKS:
                result = self.ssh_command(f"ip link show {bridge}", check=False)
                if result.returncode == 0:
                    networks_found.append(bridge)
                    log_info(f"Network bridge {bridge} found")
                else:
                    log_error(f"Network bridge {bridge} not found")
            
            return len(networks_found) > 0
            
        except Exception as e:
            log_error(f"Network validation failed: {e}")
            return False
    
    def _check_rbd_storage(self) -> bool:
        """Check RBD storage availability"""
        try:
            result = self.ssh_command("rbd ls", check=False)
            if result.returncode != 0:
                log_error("RBD storage not available")
                return False
            
            log_info("RBD storage available")
            return True
            
        except Exception as e:
            log_error(f"RBD storage check failed: {e}")
            return False
    
    def setup_tools_and_storage(self) -> bool:
        """Install tools and setup RBD-ISO storage"""
        phase = "tools_storage"
        if self.state.is_phase_complete(phase) and phase not in self.skip_phases:
            # Verify RBD storage is still properly mounted
            result = self.ssh_command("test -d /mnt/rbd-iso/template/images", check=False)
            if result.returncode == 0:
                log_skip("Tools and storage setup already completed")
                return True
            else:
                log_warning("RBD storage missing, invalidating cached state and re-creating...")
                self.state.invalidate_phase(phase)
        
        log_step("Setting up tools and storage...")
        
        if not self._install_required_tools():
            return False
        
        if not self._setup_rbd_iso_storage():
            return False
        
        self.state.mark_phase_complete(phase)
        return True
    
    def _install_required_tools(self) -> bool:
        """Install required tools on Proxmox host"""
        try:
            self.ssh_command("apt-get update >/dev/null 2>&1 && apt-get install -y libguestfs-tools >/dev/null 2>&1", timeout=300)  # 5 minutes for package installation
            log_info("Required tools installed")
            return True
        except subprocess.CalledProcessError:
            log_error("Failed to install required tools")
            return False
    
    def _setup_rbd_iso_storage(self) -> bool:
        """Setup RBD-ISO storage for multi-OS support"""
        try:
            # Check if storage already exists
            result = self.ssh_command("test -d /mnt/rbd-iso/template/images", check=False)
            if result.returncode == 0:
                log_info("RBD-ISO storage already exists")
                return True
            
            # Create and setup RBD volume
            log_info("Creating RBD-ISO storage...")
            result = self.ssh_command("rbd create rbd-iso --size 16G", check=False)
            self.ssh_command("mkdir -p /mnt/rbd-iso")
            
            # Map and format if needed
            result = self.ssh_command("rbd map rbd/rbd-iso", check=False, timeout=60)
            result = self.ssh_command("blkid /dev/rbd/rbd/rbd-iso | grep ext4", check=False)
            if result.returncode != 0:
                self.ssh_command("mkfs.ext4 -F /dev/rbd/rbd/rbd-iso", timeout=60)
            
            # Mount and setup directories
            result = self.ssh_command("mount /dev/rbd/rbd/rbd-iso /mnt/rbd-iso", check=False)
            self.ssh_command("mkdir -p /mnt/rbd-iso/template/iso /mnt/rbd-iso/template/images")
            self.ssh_command("chown -R root:www-data /mnt/rbd-iso && chmod -R 755 /mnt/rbd-iso")
            
            log_info("RBD-ISO storage setup completed")
            return True
            
        except subprocess.CalledProcessError as e:
            log_error(f"Failed to setup RBD-ISO storage: {e}")
            return False
    
    def setup_packer_user(self) -> Optional[str]:
        """Setup Packer user and permissions with intelligent handling"""
        phase = "packer_user"
        
        # Check if we have a cached token
        cached_token = self.state.state["phases"].get(phase, {}).get("details", {}).get("token")
        
        if (self.state.is_phase_complete(phase) and 
            cached_token and 
            phase not in self.skip_phases and 
            not self.force_rebuild):
            
            # Verify user exists and token still works
            user_check = self.ssh_command("pveum user list | grep 'packer@pam'", check=False)
            if user_check.returncode != 0:
                log_warning("Packer user missing, invalidating cached state and re-creating...")
                self.state.invalidate_phase(phase)
            elif self._verify_packer_token(cached_token):
                log_skip("Packer user already configured and token verified")
                return cached_token
            else:
                log_warning("Cached token is invalid, regenerating...")
                self.state.invalidate_phase(phase)
        
        log_step("Setting up Packer user and permissions...")
        
        try:
            # Setup or update packer user
            result = self.ssh_command("pveum user list | grep 'packer@pam'", check=False)
            
            if result.returncode != 0:
                log_info("Creating Packer user...")
                self.ssh_command("pveum user add packer@pam --comment 'Packer automation user'")
            else:
                log_info("Packer user already exists, updating permissions...")
            
            # Setup role and permissions
            role_privs = "VM.Allocate,VM.Clone,VM.Config.CDROM,VM.Config.CPU,VM.Config.Cloudinit,VM.Config.Disk,VM.Config.HWType,VM.Config.Memory,VM.Config.Network,VM.Config.Options,VM.Audit,VM.PowerMgmt,Datastore.AllocateSpace,Datastore.Audit,SDN.Use,VM.GuestAgent.Audit,VM.GuestAgent.Unrestricted"
            
            result = self.ssh_command(f"pveum role add PackerRole -privs '{role_privs}'", check=False)
            if result.returncode != 0:
                self.ssh_command(f"pveum role modify PackerRole -privs '{role_privs}'")
            
            # Apply ACL permissions
            self.ssh_command("pveum aclmod / -user packer@pam -role PackerRole")
            
            # Create API token
            log_info("Creating API token for packer user...")
            self.ssh_command("pveum user token remove packer@pam packer", check=False)
            result = self.ssh_command("pveum user token add packer@pam packer --comment 'Packer automation token' --output-format json")
            
            token_data = json.loads(result.stdout.strip())
            packer_token = token_data.get("value")
            
            if not packer_token:
                log_error("Failed to extract Packer token")
                return None
            
            # Disable privilege separation
            self.ssh_command("pveum user token modify packer@pam packer --privsep 0")
            
            # Save state with token
            self.state.mark_phase_complete(phase, {"token": packer_token})
            
            log_info("Packer user setup completed")
            return packer_token
            
        except subprocess.CalledProcessError as e:
            log_error(f"Failed to setup Packer user: {e}")
            return None
    
    def _verify_packer_token(self, token: str) -> bool:
        """Verify that a Packer token is still valid"""
        try:
            # Test the token by making a simple API call
            test_cmd = f'curl -s -k -H "Authorization: PVEAPIToken=packer@pam!packer={token}" https://{self.config.PROXMOX_HOST}:8006/api2/json/version'
            result = self.run_command(test_cmd, check=False, timeout=10)
            
            if result.returncode == 0:
                try:
                    response = json.loads(result.stdout)
                    return "data" in response
                except json.JSONDecodeError:
                    return False
            
            return False
            
        except Exception:
            return False
    
    def prepare_cloud_image(self) -> bool:
        """Prepare cloud image with intelligent re-use"""
        phase = "cloud_image"
        if self.state.is_phase_complete(phase) and phase not in self.skip_phases:
            # Verify image still exists
            result = self.ssh_command(f"test -f /mnt/rbd-iso/template/images/{self.config.MODIFIED_IMAGE}", check=False)
            if result.returncode == 0:
                log_skip("Cloud image already prepared and exists")
                return True
            else:
                log_warning("Cloud image missing, invalidating cached state and re-creating...")
                self.state.invalidate_phase(phase)
        
        log_step("Preparing cloud image...")
        
        try:
            # Download and modify image
            log_info("Downloading Ubuntu 24.04 Noble cloud image...")
            self.ssh_command(f"cd /mnt/rbd-iso/template/images && wget -q -O {self.config.MODIFIED_IMAGE} {self.config.IMAGE_URL}", timeout=300)  # 5 minutes
            
            log_info("Installing packages and configuring image (this may take several minutes)...")
            self.ssh_command(f"cd /mnt/rbd-iso/template/images && virt-customize --quiet --install qemu-guest-agent,grub-efi-amd64,grub-efi-amd64-signed,shim-signed -a {self.config.MODIFIED_IMAGE}", timeout=600)  # 10 minutes
            
            # Reset machine-id and configure user
            result = self.ssh_command(f"cd /mnt/rbd-iso/template/images && virt-sysprep --quiet -a {self.config.MODIFIED_IMAGE}", check=False, timeout=300)
            if result.returncode != 0:
                log_warning("virt-sysprep failed, continuing anyway")
            
            # Setup sysadmin user
            log_info("Configuring sysadmin user...")
            self.ssh_command(f"cd /mnt/rbd-iso/template/images && virt-customize --quiet -a {self.config.MODIFIED_IMAGE} --run-command 'useradd -m -s /bin/bash sysadmin && usermod -aG sudo sysadmin && echo \"sysadmin:password\" | chpasswd'", timeout=300)
            
            # Inject SSH key
            self.run_command(f"scp -o ConnectTimeout=10 -o StrictHostKeyChecking=no {self.config.SSH_PUB_KEY_PATH} root@{self.config.PROXMOX_HOST}:/tmp/", timeout=60)
            self.ssh_command(f"cd /mnt/rbd-iso/template/images && virt-customize --quiet -a {self.config.MODIFIED_IMAGE} --ssh-inject sysadmin:file:/tmp/sysadmin_automation_key.pub", timeout=300)
            
            # Setup sudo access
            self.ssh_command(f"cd /mnt/rbd-iso/template/images && virt-customize --quiet -a {self.config.MODIFIED_IMAGE} --run-command 'echo \\\"sysadmin ALL=(ALL) NOPASSWD:ALL\\\" > /etc/sudoers.d/sysadmin'", timeout=300)
            
            # EFI boot setup
            log_info("Configuring EFI boot...")
            result = self.ssh_command(f"cd /mnt/rbd-iso/template/images && virt-customize --quiet -a {self.config.MODIFIED_IMAGE} --run-command 'mkdir -p /boot/efi && mount /dev/sda15 /boot/efi || mount /dev/vda15 /boot/efi'", check=False, timeout=300)
            result = self.ssh_command(f"cd /mnt/rbd-iso/template/images && virt-customize --quiet -a {self.config.MODIFIED_IMAGE} --run-command 'update-grub && grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=ubuntu --recheck'", check=False, timeout=300)
            result = self.ssh_command(f"cd /mnt/rbd-iso/template/images && virt-customize --quiet -a {self.config.MODIFIED_IMAGE} --run-command 'mkdir -p /boot/efi/EFI/BOOT && cp /boot/efi/EFI/ubuntu/grubx64.efi /boot/efi/EFI/BOOT/BOOTX64.EFI 2>/dev/null || cp /boot/efi/EFI/ubuntu/shimx64.efi /boot/efi/EFI/BOOT/BOOTX64.EFI'", check=False, timeout=300)
            
            self.state.mark_phase_complete(phase)
            log_info("Cloud image preparation completed")
            return True
            
        except subprocess.CalledProcessError as e:
            log_error(f"Failed to prepare cloud image: {e}")
            return False
    
    def create_base_template(self) -> bool:
        """Create base VM template with safety checks"""
        phase = "base_template"
        if self.state.is_phase_complete(phase) and phase not in self.skip_phases:
            # Verify template still exists AND is actually a template
            result = self.ssh_command(f"qm config {self.config.BASE_VM_ID} | grep 'template: 1'", check=False)
            if result.returncode == 0:
                log_skip("Base template already created and properly configured")
                return True
            else:
                log_warning("Base template missing or not properly configured, invalidating cached state and re-creating...")
                self.state.invalidate_phase(phase)
        
        log_step("Creating base VM template...")
        
        try:
            # Check if VM exists and is in use
            if self.check_vm_in_use(self.config.BASE_VM_ID):
                if not self.force_rebuild:
                    log_error(f"VM {self.config.BASE_VM_ID} is in use. Use --force-rebuild to override.")
                    return False
                else:
                    log_warning(f"Force removing VM {self.config.BASE_VM_ID}")
            
            # Remove existing VM if present
            result = self.ssh_command(f"qm status {self.config.BASE_VM_ID}", check=False)
            if result.returncode == 0:
                self.ssh_command(f"qm stop {self.config.BASE_VM_ID} || true && qm destroy {self.config.BASE_VM_ID} --purge")
            
            # Create VM with modern configuration
            log_info("Creating base VM...")
            self.ssh_command(f"qm create {self.config.BASE_VM_ID} --name {self.config.VM_NAME} --memory 2048 --cores 2 --net0 virtio,bridge=vmbr0 --scsihw virtio-scsi-pci --ostype l26 --cpu host --agent enabled=1 --machine q35 --bios ovmf --rng0 source=/dev/urandom,max_bytes=1024,period=1000")
            
            # Configure networking and EFI
            result = self.ssh_command(f"qm set {self.config.BASE_VM_ID} --net0 virtio,bridge=vmbr0,rombar=0", check=False)
            self.ssh_command(f"qm set {self.config.BASE_VM_ID} --efidisk0 rbd:4,efitype=4m,pre-enrolled-keys=0")
            
            # Import and configure disk
            log_info("Importing disk (this may take several minutes)...")
            self.ssh_command(f"qm importdisk {self.config.BASE_VM_ID} /mnt/rbd-iso/template/images/{self.config.MODIFIED_IMAGE} rbd --format raw", timeout=600)  # 10 minutes
            self.ssh_command(f"qm set {self.config.BASE_VM_ID} --scsi0 rbd:vm-{self.config.BASE_VM_ID}-disk-1")
            self.ssh_command(f"qm set {self.config.BASE_VM_ID} --boot order=scsi0 --bootdisk scsi0")
            
            # Add cloud-init
            self.ssh_command(f"qm set {self.config.BASE_VM_ID} --ide2 rbd:cloudinit")
            
            # Configure cloud-init
            self.run_command(f"scp -o ConnectTimeout=10 -o StrictHostKeyChecking=no {self.config.SSH_PUB_KEY_PATH} root@{self.config.PROXMOX_HOST}:/tmp/", timeout=60)
            self.ssh_command(f"qm set {self.config.BASE_VM_ID} --ciuser sysadmin --cipassword password --sshkeys /tmp/sysadmin_automation_key.pub --ipconfig0 ip=dhcp")
            
            # Resize and templateize
            result = self.ssh_command(f"qm resize {self.config.BASE_VM_ID} scsi0 32G", check=False)
            self.ssh_command(f"qm template {self.config.BASE_VM_ID}")
            
            self.state.mark_phase_complete(phase)
            self.state.mark_resource_created("template", self.config.BASE_VM_ID, {"name": self.config.VM_NAME})
            
            log_info("Base template created successfully")
            return True
            
        except subprocess.CalledProcessError as e:
            log_error(f"Failed to create base template: {e}")
            return False
    
    def setup_packer_config(self, token: str) -> bool:
        """Setup Packer configuration files"""
        phase = "packer_config"
        # Always refresh configuration files even if phase is complete
        # to ensure .env and variables.json have current token
        refresh_only = self.state.is_phase_complete(phase) and phase not in self.skip_phases
        
        if refresh_only:
            log_step("Refreshing Packer configuration files with current token...")
        else:
            log_step("Setting up Packer configuration...")
        
        try:
            # Get absolute path to project root (parent of scripts directory)
            project_root = Path(__file__).parent.parent
            packer_dir = project_root / "packer"
            
            # Ensure packer directory exists
            packer_dir.mkdir(exist_ok=True)
            
            # Write environment file
            env_content = f"""# Packer Environment Configuration
# Generated by cluster-foundation-setup.py script
export PROXMOX_HOST="{self.config.PROXMOX_HOST}:8006"
export PROXMOX_TOKEN="{token}"
export PROXMOX_USER="packer@pam!packer"
"""
            
            env_file = packer_dir / ".env"
            env_file.write_text(env_content)
            log_info(f"Created Packer environment file: {env_file}")
            
            # Golden template removed - using cloud-base directly
            # No Packer configuration needed for deprecated golden template
            log_info("Golden template deprecated - using cloud-base directly")
            
            if not refresh_only:
                self.state.mark_phase_complete(phase)
            log_info("Packer configuration files ready")
            return True
            
        except Exception as e:
            log_error(f"Failed to setup Packer configuration: {e}")
            return False
    
    def _update_packer_hcl(self, token: str):
        """Update Packer HCL configuration"""
        project_root = Path(__file__).parent.parent
        # Note: Golden template removed - using cloud-base directly
        
        if not packer_file.exists():
            log_warning("Packer HCL file not found, skipping update")
            return
        
        content = packer_file.read_text()
        
        # Update token reference
        content = re.sub(
            r'token\s*=\s*"[^"]*"',
            'token = var.proxmox_token',
            content
        )
        
        # Update variable default
        content = re.sub(
            r'variable "proxmox_token" \{\s*type\s*=\s*string\s*default\s*=\s*"[^"]*"',
            f'variable "proxmox_token" {{\n  type    = string\n  default = "{token}"',
            content
        )
        
        # Add variable if missing
        if 'variable "proxmox_token"' not in content:
            var_insert_point = content.find('variable "template_id"')
            if var_insert_point != -1:
                end_point = content.find('}', var_insert_point) + 1
                new_var = f'\n\nvariable "proxmox_token" {{\n  type    = string\n  default = "{token}"\n}}\n'
                content = content[:end_point] + new_var + content[end_point:]
        
        packer_file.write_text(content)
    
    def run_setup(self) -> bool:
        """Run the complete foundation setup"""
        print("=" * 70)
        print("KUBERNETES CLUSTER FOUNDATION SETUP")
        print("=" * 70)
        
        steps = [
            ("Environment Validation", self.validate_environment),
            ("Tools and Storage Setup", self.setup_tools_and_storage),
            ("Packer User Configuration", self.setup_packer_user),
            ("Cloud Image Preparation", self.prepare_cloud_image),
            ("Base Template Creation", self.create_base_template),
        ]
        
        packer_token = None
        
        for step_name, step_func in steps:
            print(f"\n{Colors.BLUE}--- {step_name} ---{Colors.NC}")
            
            if step_name == "Packer User Configuration":
                packer_token = step_func()
                if not packer_token:
                    return False
            else:
                if not step_func():
                    return False
        
        # Setup Packer configuration with token
        print(f"\n{Colors.BLUE}--- Packer Configuration Setup ---{Colors.NC}")
        if not self.setup_packer_config(packer_token):
            return False
        
        print("\n" + "=" * 70)
        print(f"{Colors.GREEN}✓ FOUNDATION SETUP COMPLETED SUCCESSFULLY{Colors.NC}")
        print("=" * 70)
        print(f"Base template: {self.config.VM_NAME} (ID: {self.config.BASE_VM_ID})")
        print(f"State tracking: {self.config.STATE_FILE}")
        print(f"Using cloud-base template directly - no golden template needed")
        print("=" * 70)
        
        return True

def main():
    """Main entry point with argument parsing"""
    parser = argparse.ArgumentParser(description="Kubernetes Cluster Foundation Setup")
    parser.add_argument("--force-rebuild", action="store_true", 
                       help="Force rebuild of all components (destructive)")
    parser.add_argument("--skip-phases", nargs="+", 
                       help="Skip specific phases (validation, tools_storage, packer_user, cloud_image, base_template, packer_config)")
    parser.add_argument("--reset-state", action="store_true", 
                       help="Reset all state tracking (use with caution)")
    parser.add_argument("--status", action="store_true", 
                       help="Show current setup status")
    
    args = parser.parse_args()
    
    config = Config()
    
    # Handle status request
    if args.status:
        state = StateManager(config.STATE_FILE)
        print("\n" + "=" * 50)
        print("FOUNDATION SETUP STATUS")
        print("=" * 50)
        for phase, details in state.state.get("phases", {}).items():
            status = "✓ COMPLETED" if details.get("completed") else "✗ PENDING"
            timestamp = details.get("timestamp", "Unknown")
            print(f"{phase:20} {status} ({timestamp})")
        print("=" * 50)
        return
    
    setup = FoundationSetup(config, args.force_rebuild, args.skip_phases)
    
    if args.reset_state:
        log_warning("Resetting all state tracking...")
        setup.state.reset_state()
        log_info("State reset completed")
        return
    
    try:
        success = setup.run_setup()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        log_warning("Setup interrupted by user")
        sys.exit(1)
    except Exception as e:
        log_error(f"Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()