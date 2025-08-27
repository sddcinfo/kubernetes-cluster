#!/usr/bin/env python3
"""
Kubernetes Cluster Manager
Unified foundation setup and template management for Kubernetes clusters on Proxmox

This script consolidates:
- Proxmox environment preparation and validation  
- RBD storage and tools setup
- Cloud image preparation with EFI boot support
- VM template creation and management
- Comprehensive prerequisite checking

Usage:
    python3 cluster-manager.py --setup-foundation
    python3 cluster-manager.py --create-templates
    python3 cluster-manager.py --validate-prereqs
    python3 cluster-manager.py --setup-and-create
    python3 cluster-manager.py --status
"""

import subprocess
import sys
import json
import time
import logging
import argparse
import base64
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime
import os
import re

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Colors for output
class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    NC = '\033[0m'

def log_info(msg):
    print(f"{Colors.GREEN}[INFO]{Colors.NC} {msg}")

def log_error(msg):
    print(f"{Colors.RED}[ERROR]{Colors.NC} {msg}")

def log_warning(msg):
    print(f"{Colors.YELLOW}[WARN]{Colors.NC} {msg}")

def log_step(msg):
    print(f"{Colors.BLUE}[STEP]{Colors.NC} {msg}")

def log_skip(msg):
    print(f"{Colors.YELLOW}[SKIP]{Colors.NC} {msg}")

class Config:
    """Configuration management"""
    def __init__(self):
        self.PROXMOX_HOST = "10.10.1.21"
        self.SSH_KEY_PATH = "/home/sysadmin/.ssh/sysadmin_automation_key"
        self.SSH_PUB_KEY_PATH = "/home/sysadmin/.ssh/sysadmin_automation_key.pub"
        self.STATE_FILE = Path.home() / ".kube-cluster" / "foundation_state.json"
        self.MODIFIED_IMAGE = "ubuntu-24.04-cloudimg-amd64-modified.img"
        
        # Ensure state directory exists
        self.STATE_FILE.parent.mkdir(exist_ok=True)

class StateManager:
    """Unified state management for foundation and templates"""
    def __init__(self, state_file: Path):
        self.state_file = state_file
        self.state = self._load_state()
    
    def _load_state(self) -> Dict:
        """Load state from file"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        
        return {
            "phases": {},
            "templates": {},
            "last_update": str(datetime.now())
        }
    
    def save_state(self):
        """Save state to file"""
        self.state["last_update"] = str(datetime.now())
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f, indent=2)
    
    def is_phase_complete(self, phase: str) -> bool:
        """Check if a phase is complete"""
        return self.state["phases"].get(phase, {}).get("completed", False)
    
    def mark_phase_complete(self, phase: str, details: Dict = None):
        """Mark a phase as complete"""
        if phase not in self.state["phases"]:
            self.state["phases"][phase] = {}
        
        self.state["phases"][phase]["completed"] = True
        self.state["phases"][phase]["timestamp"] = str(datetime.now())
        if details:
            self.state["phases"][phase]["details"] = details
        
        self.save_state()
    
    def invalidate_phase(self, phase: str):
        """Invalidate a phase"""
        if phase in self.state["phases"]:
            self.state["phases"][phase]["completed"] = False
        self.save_state()

class ClusterManager:
    """Unified cluster foundation and template management"""
    
    def __init__(self, force_rebuild: bool = False, skip_phases: List[str] = None):
        self.config = Config()
        self.state = StateManager(self.config.STATE_FILE)
        self.force_rebuild = force_rebuild
        self.skip_phases = skip_phases or []
        
        # Template configuration
        self.templates = {
            'base': {
                'id': 9000,
                'name': 'ubuntu-base-template',
                'description': 'Ubuntu 24.04 Base Template - qemu-agent + updates',
                'memory': 2048,
                'cores': 2
            },
            'k8s': {
                'id': 9001, 
                'name': 'ubuntu-k8s-template',
                'description': 'Ubuntu 24.04 with Kubernetes 1.33.4',
                'memory': 4096,
                'cores': 4
            }
        }
        
        self.k8s_version = "1.33.4"
        
        # Cloud image settings with Japan mirror optimization
        self.cloud_image_url = "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"
        self.japan_cloud_image_url = "http://cloud-images.ubuntu.com.edgecastcdn.net/noble/current/noble-server-cloudimg-amd64.img"
        self.cached_image_path = "/mnt/rbd-iso/template/images/ubuntu-24.04-cloudimg-cached.img"
    
    def run_ssh_command(self, command: str, timeout: int = 300) -> Tuple[int, str, str]:
        """Execute SSH command on Proxmox host."""
        ssh_cmd = [
            "ssh", "-o", "ConnectTimeout=10",
            "-o", "StrictHostKeyChecking=no",
            f"root@{self.config.PROXMOX_HOST}",
            command
        ]
        
        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            logger.error(f"SSH command timed out after {timeout}s: {command}")
            return 1, "", "Command timed out"
        except Exception as e:
            logger.error(f"SSH command failed: {e}")
            return 1, "", str(e)
    
    def run_local_command(self, cmd: str, timeout: int = 30) -> subprocess.CompletedProcess:
        """Execute local command"""
        try:
            return subprocess.run(
                cmd,
                shell=True,
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout
            )
        except subprocess.TimeoutExpired:
            raise subprocess.CalledProcessError(1, cmd, "Command timed out")
    
    # === VALIDATION METHODS ===
    
    def validate_prerequisites(self) -> bool:
        """Comprehensive prerequisite validation"""
        logger.info("🔍 Validating prerequisites...")
        
        validations = [
            ("SSH connectivity to Proxmox", self._check_ssh_connectivity),
            ("Proxmox node status", self._check_proxmox_status),
            ("Proxmox services", self._check_proxmox_services),
            ("Ceph/RBD cluster", self._check_ceph_cluster),
            ("RBD storage", self._check_rbd_storage),
            ("Template storage directory", self._check_template_storage),
            ("Required tools", self._check_required_tools),
            ("Network bridge", self._check_network_bridge),
            ("Available resources", self._check_available_resources),
        ]
        
        all_valid = True
        for description, check_func in validations:
            try:
                if check_func():
                    logger.info(f"✅ {description}: OK")
                else:
                    logger.error(f"❌ {description}: FAILED")
                    all_valid = False
            except Exception as e:
                logger.error(f"❌ {description}: ERROR - {e}")
                all_valid = False
        
        if all_valid:
            logger.info("✅ All prerequisites validated successfully")
        else:
            logger.error("❌ Prerequisites validation failed - see errors above")
        
        return all_valid
    
    def _check_ssh_connectivity(self) -> bool:
        """Check SSH connectivity to Proxmox host."""
        try:
            returncode, stdout, stderr = self.run_ssh_command("echo 'test'", timeout=10)
            return returncode == 0 and stdout.strip() == 'test'
        except Exception:
            return False
    
    def _check_proxmox_status(self) -> bool:
        """Check Proxmox node status"""
        try:
            returncode, stdout, stderr = self.run_ssh_command("pveversion", timeout=10)
            if returncode == 0:
                logger.info(f"Proxmox version: {stdout.strip()}")
                return True
            return False
        except Exception:
            return False
    
    def _check_proxmox_services(self) -> bool:
        """Check critical Proxmox services"""
        services = ["pve-cluster", "pveproxy", "pvedaemon", "pvestatd"]
        try:
            for service in services:
                returncode, stdout, stderr = self.run_ssh_command(f"systemctl is-active {service}", timeout=10)
                if returncode != 0:
                    logger.error(f"Proxmox service {service} not running")
                    return False
            return True
        except Exception:
            return False
    
    def _check_ceph_cluster(self) -> bool:
        """Check Ceph cluster status"""
        try:
            returncode, stdout, stderr = self.run_ssh_command("ceph health", timeout=30)
            if returncode == 0:
                health_status = stdout.strip()
                if "HEALTH_OK" in health_status:
                    logger.info("Ceph cluster is healthy")
                else:
                    logger.warning(f"Ceph cluster health: {health_status}")
                return True
            return False
        except Exception:
            return False
    
    def _check_rbd_storage(self) -> bool:
        """Check RBD storage availability"""
        try:
            # Test basic RBD functionality
            returncode, stdout, stderr = self.run_ssh_command("rbd ls", timeout=30)
            if returncode != 0:
                return False
            
            # Test create/delete capability
            returncode, stdout, stderr = self.run_ssh_command(
                "rbd create test-validation --size 1M && rbd rm test-validation", timeout=30
            )
            return returncode == 0
        except Exception:
            return False
    
    def _check_template_storage(self) -> bool:
        """Check template storage directory and permissions"""
        try:
            returncode, stdout, stderr = self.run_ssh_command(
                "test -d /mnt/rbd-iso/template/images && touch /mnt/rbd-iso/template/images/.test && rm -f /mnt/rbd-iso/template/images/.test", 
                timeout=10
            )
            return returncode == 0
        except Exception:
            return False
    
    def _check_required_tools(self) -> bool:
        """Check required tools are installed"""
        required_tools = ["qm", "rbd", "virt-customize", "wget", "cp", "chown"]
        
        try:
            for tool in required_tools:
                returncode, stdout, stderr = self.run_ssh_command(f"which {tool}", timeout=10)
                if returncode != 0:
                    logger.error(f"Missing required tool: {tool}")
                    return False
            return True
        except Exception:
            return False
    
    def _check_network_bridge(self) -> bool:
        """Check network bridge configuration"""
        try:
            returncode, stdout, stderr = self.run_ssh_command(
                "ip link show vmbr0 | grep 'state UP'", timeout=10
            )
            return returncode == 0
        except Exception:
            return False
    
    def _check_available_resources(self) -> bool:
        """Check available system resources"""
        try:
            # Check available memory (recommend 8GB+)
            returncode, stdout, stderr = self.run_ssh_command(
                "free -g | awk 'NR==2{print $7}'", timeout=10
            )
            if returncode == 0:
                available_mem_gb = int(stdout.strip())
                if available_mem_gb < 4:
                    logger.warning(f"Low available memory: {available_mem_gb}GB (recommended: 8GB+)")
                
            # Check available storage (recommend 50GB+)
            returncode, stdout, stderr = self.run_ssh_command(
                "df -BG /mnt/rbd-iso/template/images | tail -1 | awk '{print $4}' | sed 's/G//'", timeout=10
            )
            if returncode == 0:
                available_storage = int(stdout.strip())
                if available_storage < 20:
                    logger.warning(f"Low available storage: {available_storage}GB (recommended: 50GB+)")
            
            return True
        except Exception:
            return False
    
    # === FOUNDATION SETUP METHODS ===
    
    def setup_foundation(self) -> bool:
        """Run foundation setup phases"""
        logger.info("🚀 Starting foundation setup")
        
        phases = [
            ("Environment Validation", self.validate_environment),
            ("Tools and Storage Setup", self.setup_tools_and_storage),
            ("Cloud Image Preparation", self.prepare_cloud_image),
        ]
        
        for phase_name, phase_func in phases:
            log_step(f"--- {phase_name} ---")
            if not phase_func():
                logger.error(f"Foundation setup failed at: {phase_name}")
                return False
        
        logger.info("✅ Foundation setup completed successfully")
        logger.info("Ready for template creation")
        return True
    
    def validate_environment(self) -> bool:
        """Run comprehensive environment validation"""
        phase = "validation"
        if self.state.is_phase_complete(phase) and phase not in self.skip_phases:
            log_skip("Environment validation already completed")
            return True
        
        log_step("Validating environment...")
        
        if self.validate_prerequisites():
            self.state.mark_phase_complete(phase)
            log_info("Environment validation completed")
            return True
        
        return False
    
    def setup_tools_and_storage(self) -> bool:
        """Install tools and setup RBD-ISO storage"""
        phase = "tools_storage"
        if self.state.is_phase_complete(phase) and phase not in self.skip_phases:
            # Verify RBD storage is still properly mounted
            returncode, stdout, stderr = self.run_ssh_command("test -d /mnt/rbd-iso/template/images", timeout=10)
            if returncode == 0:
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
            self.run_ssh_command("apt-get update >/dev/null 2>&1 && apt-get install -y libguestfs-tools >/dev/null 2>&1", timeout=300)
            log_info("Required tools installed")
            return True
        except subprocess.CalledProcessError:
            log_error("Failed to install required tools")
            return False
    
    def _setup_rbd_iso_storage(self) -> bool:
        """Setup RBD-ISO storage for multi-OS support"""
        try:
            # Check if storage already exists
            returncode, stdout, stderr = self.run_ssh_command("test -d /mnt/rbd-iso/template/images", timeout=10)
            if returncode == 0:
                log_info("RBD-ISO storage already exists")
                return True
            
            # Create and setup RBD volume
            log_info("Creating RBD-ISO storage...")
            self.run_ssh_command("rbd create rbd-iso --size 16G", timeout=60)
            self.run_ssh_command("mkdir -p /mnt/rbd-iso", timeout=60)
            
            # Map and format if needed
            self.run_ssh_command("rbd map rbd/rbd-iso", timeout=60)
            returncode, stdout, stderr = self.run_ssh_command("blkid /dev/rbd/rbd/rbd-iso | grep ext4", timeout=60)
            if returncode != 0:
                self.run_ssh_command("mkfs.ext4 -F /dev/rbd/rbd/rbd-iso", timeout=60)
            
            # Mount and setup directories
            self.run_ssh_command("mount /dev/rbd/rbd/rbd-iso /mnt/rbd-iso", timeout=60)
            self.run_ssh_command("mkdir -p /mnt/rbd-iso/template/iso /mnt/rbd-iso/template/images", timeout=60)
            self.run_ssh_command("chown -R root:www-data /mnt/rbd-iso && chmod -R 755 /mnt/rbd-iso", timeout=60)
            
            log_info("RBD-ISO storage setup completed")
            return True
            
        except subprocess.CalledProcessError as e:
            log_error(f"Failed to setup RBD-ISO storage: {e}")
            return False
    
    def prepare_cloud_image(self) -> bool:
        """Prepare cloud image with intelligent re-use"""
        phase = "cloud_image"
        if self.state.is_phase_complete(phase) and phase not in self.skip_phases:
            # Verify image still exists
            returncode, stdout, stderr = self.run_ssh_command(f"test -f /mnt/rbd-iso/template/images/{self.config.MODIFIED_IMAGE}", timeout=10)
            if returncode == 0:
                log_skip("Cloud image preparation already completed")
                return True
            else:
                log_warning("Modified cloud image missing, invalidating cached state and re-creating...")
                self.state.invalidate_phase(phase)
        
        log_step("Preparing cloud image...")
        
        try:
            # Download and prepare cloud image on Proxmox host
            ssh_key = Path(self.config.SSH_PUB_KEY_PATH).read_text().strip()
            
            cloud_prep_script = f'''#!/bin/bash
set -euo pipefail

TEMPLATE_DIR="/mnt/rbd-iso/template/images"
MODIFIED_IMAGE="{self.config.MODIFIED_IMAGE}"

cd $TEMPLATE_DIR

if [ -f "$MODIFIED_IMAGE" ]; then
    echo "Modified cloud image already exists, skipping preparation"
    exit 0
fi

echo "Modified cloud image not found: $TEMPLATE_DIR/$MODIFIED_IMAGE"
echo "Need to run prepare-cloud-image.sh first or create it now..."

echo "Installing required tools..."
apt-get update >/dev/null 2>&1 && apt-get install -y libguestfs-tools >/dev/null 2>&1

echo "Downloading Ubuntu cloud image..."
# Check if cached image exists locally first
if [ ! -f $TEMPLATE_DIR/ubuntu-24.04-cloudimg-cached.img ]; then
    echo "Downloading Ubuntu cloud image from Japan mirror..."
    wget -q -O $TEMPLATE_DIR/ubuntu-24.04-cloudimg-cached.img "{self.japan_cloud_image_url}" || \\
    wget -q -O $TEMPLATE_DIR/ubuntu-24.04-cloudimg-cached.img "{self.cloud_image_url}"
else
    echo "Using cached Ubuntu cloud image..."
fi

# Copy cached image to working image
cp $TEMPLATE_DIR/ubuntu-24.04-cloudimg-cached.img $TEMPLATE_DIR/ubuntu-24.04-cloudimg.img

echo "Preparing cloud image with EFI support and qemu-guest-agent..."
cd $TEMPLATE_DIR
cp ubuntu-24.04-cloudimg.img $MODIFIED_IMAGE

# Install essential packages including EFI bootloader (with error checking)
echo "Installing qemu-guest-agent and EFI packages..."
if ! virt-customize --install qemu-guest-agent,grub-efi-amd64,grub-efi-amd64-signed,shim-signed -a $MODIFIED_IMAGE; then
    echo "ERROR: Failed to install packages with virt-customize"
    exit 1
fi

# Verify qemu-guest-agent was installed
if ! virt-cat -a $MODIFIED_IMAGE /var/lib/dpkg/status | grep -q "Package: qemu-guest-agent"; then
    echo "ERROR: qemu-guest-agent not found after installation"
    exit 1
fi
echo "qemu-guest-agent installation verified"

# Reset machine-id (matching working script)
virt-sysprep -a $MODIFIED_IMAGE || true

# Create sysadmin user and setup SSH (matching working script)
virt-customize -a $MODIFIED_IMAGE --run-command 'useradd -m -s /bin/bash sysadmin'
virt-customize -a $MODIFIED_IMAGE --run-command 'echo "sysadmin:password" | chpasswd'
virt-customize -a $MODIFIED_IMAGE --ssh-inject sysadmin:string:'{ssh_key}'
virt-customize -a $MODIFIED_IMAGE --run-command 'echo "sysadmin ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/sysadmin'

# Fix EFI boot (matching working script approach)
virt-customize -a $MODIFIED_IMAGE --run-command 'update-grub && grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=ubuntu --recheck' || true
virt-customize -a $MODIFIED_IMAGE --run-command 'mkdir -p /boot/efi/EFI/BOOT && cp /boot/efi/EFI/ubuntu/grubx64.efi /boot/efi/EFI/BOOT/BOOTX64.EFI 2>/dev/null || cp /boot/efi/EFI/ubuntu/shimx64.efi /boot/efi/EFI/BOOT/BOOTX64.EFI' || true

echo "Cloud image prepared successfully in $TEMPLATE_DIR"
'''
            
            # Write and execute preparation script on Proxmox  
            script_b64 = base64.b64encode(cloud_prep_script.encode()).decode()
            returncode, stdout, stderr = self.run_ssh_command(f"echo '{script_b64}' | base64 -d > /tmp/prepare_cloud_image.sh", timeout=60)
            self.run_ssh_command("chmod +x /tmp/prepare_cloud_image.sh", timeout=60)
            self.run_ssh_command("/tmp/prepare_cloud_image.sh", timeout=600)
            self.run_ssh_command("rm -f /tmp/prepare_cloud_image.sh", timeout=60)
            
            self.state.mark_phase_complete(phase)
            log_info("Cloud image preparation completed")
            return True
            
        except subprocess.CalledProcessError as e:
            log_error(f"Failed to prepare cloud image: {e}")
            return False
    
    # === TEMPLATE CREATION METHODS ===
    
    def create_templates(self) -> bool:
        """Create both base and Kubernetes templates"""
        logger.info("🏗️ Creating VM templates")
        
        # Validate prerequisites first
        if not self.validate_prerequisites():
            logger.error("❌ Prerequisites validation failed - cannot proceed with template creation")
            logger.info("💡 To fix this, run: python3 cluster-manager.py --setup-foundation")
            return False
        
        # Create base template
        if not self.create_base_template():
            logger.error("Failed to create base template")
            return False
        
        # Create Kubernetes template
        if not self.create_k8s_template():
            logger.error("Failed to create Kubernetes template")
            return False
        
        logger.info("🎉 All templates created successfully!")
        self.display_templates()
        return True
    
    def create_base_template(self) -> bool:
        """Create Ubuntu base template"""
        template_config = self.templates['base']
        template_id = template_config['id']
        template_name = template_config['name']
        
        logger.info(f"Creating base template: {template_name} (ID: {template_id})")
        
        # Check if template already exists
        if self.template_exists(template_id):
            if not self.force_rebuild:
                logger.info(f"Template {template_id} already exists. Use --force-rebuild to recreate.")
                return True
            else:
                logger.info(f"Removing existing template {template_id}")
                self.remove_template(template_id)
        
        # Create cloud-based VM
        if not self.create_cloud_base_vm(template_id, template_name):
            return False
        
        # Convert to template
        logger.info("Converting to template...")
        returncode, stdout, stderr = self.run_ssh_command(f"qm template {template_id}", timeout=300)
        if returncode != 0:
            logger.error(f"Failed to convert VM {template_id} to template: {stderr}")
            return False
        
        # Store template info in state
        self.state.state["templates"][str(template_id)] = {
            "name": template_name,
            "type": "base",
            "created": str(datetime.now())
        }
        self.state.save_state()
        
        logger.info(f"✅ Base template created successfully: {template_name} (ID: {template_id})")
        return True
    
    def create_k8s_template(self) -> bool:
        """Create Kubernetes template"""
        template_config = self.templates['k8s']
        template_id = template_config['id']
        template_name = template_config['name']
        
        logger.info(f"Creating Kubernetes template: {template_name} (ID: {template_id})")
        
        # Check if template already exists
        if self.template_exists(template_id):
            if not self.force_rebuild:
                logger.info(f"Template {template_id} already exists. Use --force-rebuild to recreate.")
                return True
            else:
                logger.info(f"Removing existing template {template_id}")
                self.remove_template(template_id)
        
        # Create cloud-based VM
        if not self.create_cloud_base_vm(template_id, template_name):
            return False
        
        # Start VM for Kubernetes installation
        logger.info("Starting VM for Kubernetes installation...")
        self.run_ssh_command(f"qm start {template_id}", timeout=300)
        
        # Wait for VM to get IP and install K8s components
        vm_ip = self.get_vm_ip(template_id)
        if not vm_ip:
            logger.error("Failed to get VM IP address")
            return False
        
        logger.info(f"K8s VM IP: {vm_ip}")
        
        # Install Kubernetes components
        if not self.install_kubernetes_components(vm_ip):
            return False
        
        # Shutdown and convert to template
        logger.info("Shutting down VM...")
        self.run_ssh_command(f"qm shutdown {template_id}", timeout=300)
        time.sleep(10)  # Wait for clean shutdown
        
        logger.info("Converting to template...")
        returncode, stdout, stderr = self.run_ssh_command(f"qm template {template_id}", timeout=300)
        if returncode != 0:
            logger.error(f"Failed to convert VM {template_id} to template: {stderr}")
            return False
        
        # Store template info in state
        self.state.state["templates"][str(template_id)] = {
            "name": template_name,
            "type": "kubernetes",
            "k8s_version": self.k8s_version,
            "created": str(datetime.now())
        }
        self.state.save_state()
        
        logger.info(f"✅ Kubernetes template created successfully: {template_name} (ID: {template_id})")
        return True
    
    def create_cloud_base_vm(self, vm_id: int, vm_name: str) -> bool:
        """Create VM from cloud image with EFI support"""
        logger.info("Creating VM on Proxmox...")
        
        ssh_key = Path(self.config.SSH_PUB_KEY_PATH).read_text().strip()
        
        create_vm_script = f'''#!/bin/bash
set -euo pipefail

TEMPLATE_DIR="/mnt/rbd-iso/template/images"
MODIFIED_IMAGE="{self.config.MODIFIED_IMAGE}"

# Create VM with EFI configuration (matching working shell script)
qm create {vm_id} \\
  --name '{vm_name}' \\
  --memory 2048 \\
  --cores 2 \\
  --net0 virtio,bridge=vmbr0 \\
  --scsihw virtio-scsi-pci \\
  --ostype l26 \\
  --cpu host \\
  --agent enabled=1 \\
  --machine q35 \\
  --bios ovmf \\
  --rng0 source=/dev/urandom,max_bytes=1024,period=1000

# Add EFI disk FIRST (working configuration from shell scripts)
echo "Adding EFI disk..."
qm set {vm_id} --efidisk0 rbd:4,efitype=4m,pre-enrolled-keys=0

# Import the prepared disk from proper Proxmox storage location
echo "Importing prepared disk..."
qm importdisk {vm_id} $TEMPLATE_DIR/$MODIFIED_IMAGE rbd --format raw

# Attach the imported disk as scsi0 (disk gets auto-numbered by importdisk)
echo "Configuring main disk..."
qm set {vm_id} --scsi0 rbd:vm-{vm_id}-disk-1

# CRITICAL: Set disk-only boot order (not just --boot c)
qm set {vm_id} --boot order=scsi0 --bootdisk scsi0

# Add cloud-init drive (working configuration)
echo "Adding cloud-init..."
qm set {vm_id} --ide2 rbd:cloudinit

# Copy SSH key to Proxmox host (like working script)
echo '{ssh_key}' > /tmp/sysadmin_automation_key.pub

# Configure cloud-init (matching working script exactly)
qm set {vm_id} --ciuser sysadmin --cipassword password --sshkeys /tmp/sysadmin_automation_key.pub --ipconfig0 ip=dhcp

# Resize disk to reasonable size (like working script)
qm resize {vm_id} scsi0 32G || echo "Warning: Failed to resize disk, continuing anyway"

# Add serial console
qm set {vm_id} --serial0 socket --vga serial0

# Set description
qm set {vm_id} --description "{vm_name} - Ubuntu 24.04 cloud image base"

echo "VM {vm_id} created successfully"
'''
        
        try:
            # Write and execute VM creation script
            script_b64 = base64.b64encode(create_vm_script.encode()).decode()
            returncode, stdout, stderr = self.run_ssh_command(f"echo '{script_b64}' | base64 -d > /tmp/create_vm_{vm_id}.sh", timeout=60)
            self.run_ssh_command(f"chmod +x /tmp/create_vm_{vm_id}.sh", timeout=60)
            returncode, stdout, stderr = self.run_ssh_command(f"/tmp/create_vm_{vm_id}.sh", timeout=600)
            self.run_ssh_command(f"rm -f /tmp/create_vm_{vm_id}.sh", timeout=60)
            
            if returncode != 0:
                logger.error(f"Failed to create VM on Proxmox: {stderr}")
                return False
            
            logger.info(f"✅ Cloud-based VM created: {vm_name} (ID: {vm_id})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create VM: {e}")
            return False
    
    def get_vm_ip(self, vm_id: int, max_attempts: int = 20) -> Optional[str]:
        """Get VM IP address via guest agent."""
        for attempt in range(max_attempts):
            cmd = f"qm guest cmd {vm_id} network-get-interfaces 2>/dev/null"
            returncode, stdout, stderr = self.run_ssh_command(cmd, timeout=30)
            
            if returncode == 0 and stdout:
                try:
                    # Parse guest agent JSON response
                    data = json.loads(stdout)
                    # Handle both old format (wrapped in 'return') and new format (direct array)
                    interfaces = data.get('return', data) if isinstance(data, dict) else data
                    for interface in interfaces:
                        if interface.get('name') != 'lo':
                            for addr in interface.get('ip-addresses', []):
                                if addr.get('ip-address-type') == 'ipv4':
                                    ip = addr.get('ip-address')
                                    if ip and ip != '127.0.0.1':
                                        return ip
                except (json.JSONDecodeError, KeyError):
                    pass
            
            logger.info(f"Attempt {attempt + 1}/{max_attempts} - waiting for VM {vm_id} IP...")
            time.sleep(10)
        
        return None
    
    def install_kubernetes_components(self, vm_ip: str) -> bool:
        """Install Kubernetes components on VM"""
        logger.info("Installing Kubernetes components...")
        
        k8s_install_script = f'''#!/bin/bash
set -euo pipefail

# Update system
apt-get update
apt-get upgrade -y

# Install Kubernetes repository and components
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.33/deb/Release.key | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.33/deb/ /' | tee /etc/apt/sources.list.d/kubernetes.list

apt-get update
apt-get install -y kubelet={self.k8s_version}-1.1 kubeadm={self.k8s_version}-1.1 kubectl={self.k8s_version}-1.1
apt-mark hold kubelet kubeadm kubectl

# Install containerd
apt-get install -y containerd
mkdir -p /etc/containerd
containerd config default | tee /etc/containerd/config.toml
sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
systemctl restart containerd
systemctl enable containerd

# Configure kernel modules and sysctl
echo 'br_netfilter' | tee /etc/modules-load.d/k8s.conf
echo 'overlay' | tee -a /etc/modules-load.d/k8s.conf
modprobe br_netfilter
modprobe overlay
echo 'net.bridge.bridge-nf-call-iptables = 1' | tee /etc/sysctl.d/k8s.conf
echo 'net.bridge.bridge-nf-call-ip6tables = 1' | tee -a /etc/sysctl.d/k8s.conf
echo 'net.ipv4.ip_forward = 1' | tee -a /etc/sysctl.d/k8s.conf
sysctl --system

# Disable swap
swapoff -a
sed -i '/ swap / s/^/#/' /etc/fstab

# Install additional tools
apt-get install -y curl wget gpg lsb-release ca-certificates htop iotop nethogs iftop vim

# Clean up
apt-get autoremove -y
apt-get autoclean
rm -rf /var/cache/apt/archives/*

echo "Kubernetes components installed successfully"
'''
        
        try:
            # Copy and execute installation script
            ssh_cmd = f"ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=no -i {self.config.SSH_KEY_PATH} sysadmin@{vm_ip}"
            
            # Create script on VM using base64 encoding for safety
            script_b64 = base64.b64encode(k8s_install_script.encode()).decode()
            script_transfer = f"echo '{script_b64}' | {ssh_cmd} 'base64 -d > /tmp/install_k8s.sh'"
            self.run_local_command(script_transfer, timeout=60)
            
            # Execute script
            script_exec = f"{ssh_cmd} 'chmod +x /tmp/install_k8s.sh && sudo /tmp/install_k8s.sh'"
            self.run_local_command(script_exec, timeout=1200)  # 20 minutes timeout
            
            # Cleanup
            cleanup = f"{ssh_cmd} 'rm -f /tmp/install_k8s.sh'"
            self.run_local_command(cleanup, timeout=60)
            
            logger.info("Kubernetes components installed successfully")
            return True
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to install Kubernetes components: {e}")
            return False
    
    # === UTILITY METHODS ===
    
    def template_exists(self, template_id: int) -> bool:
        """Check if template exists"""
        returncode, stdout, stderr = self.run_ssh_command(f"qm config {template_id}", timeout=10)
        return returncode == 0
    
    def remove_template(self, template_id: int):
        """Remove existing template"""
        self.run_ssh_command(f"qm stop {template_id} || true", timeout=60)
        self.run_ssh_command(f"qm destroy {template_id} --purge", timeout=300)
    
    def display_templates(self):
        """Display created templates"""
        returncode, stdout, stderr = self.run_ssh_command("qm list | grep -E '(9000|9001)'", timeout=30)
        if returncode == 0:
            logger.info("Created templates:")
            for line in stdout.strip().split('\n'):
                logger.info(f"  {line}")
    
    def status(self):
        """Display cluster manager status"""
        print("\\n" + "=" * 50)
        print("CLUSTER MANAGER STATUS")
        print("=" * 50)
        
        # Foundation phases
        print("\\nFoundation Phases:")
        phases = ["validation", "tools_storage", "cloud_image"]
        for phase in phases:
            status = "✓ COMPLETED" if self.state.is_phase_complete(phase) else "  pending"
            timestamp = ""
            if self.state.is_phase_complete(phase):
                ts = self.state.state["phases"].get(phase, {}).get("timestamp", "")
                timestamp = f" ({ts[:19]})" if ts else ""
            print(f"  {phase:<20} {status}{timestamp}")
        
        # Templates
        print("\\nTemplates:")
        returncode, stdout, stderr = self.run_ssh_command("qm list | grep -E '(9000|9001)' || echo 'No templates found'", timeout=30)
        if returncode == 0 and stdout.strip():
            for line in stdout.strip().split('\n'):
                if 'No templates found' in line:
                    print(f"  {line}")
                else:
                    print(f"  {line}")
        else:
            print("  No templates found")
        
        print("\\nState file: " + str(self.config.STATE_FILE))
        print("=" * 50)

def main():
    """Main function"""
    parser = argparse.ArgumentParser(description="Kubernetes Cluster Manager - Foundation & Templates")
    parser.add_argument("--setup-foundation", action="store_true", help="Setup foundation (environment, tools, storage, cloud image)")
    parser.add_argument("--create-templates", action="store_true", help="Create VM templates")
    parser.add_argument("--setup-and-create", action="store_true", help="Run foundation setup and create templates")
    parser.add_argument("--validate-prereqs", action="store_true", help="Validate prerequisites only")
    parser.add_argument("--status", action="store_true", help="Show status")
    parser.add_argument("--force-rebuild", action="store_true", help="Force rebuild of existing components")
    parser.add_argument("--skip-phases", nargs="+", help="Skip specific phases (validation, tools_storage, cloud_image)")
    
    args = parser.parse_args()
    
    if not any([args.setup_foundation, args.create_templates, args.setup_and_create, args.validate_prereqs, args.status]):
        parser.print_help()
        sys.exit(1)
    
    manager = ClusterManager(force_rebuild=args.force_rebuild, skip_phases=args.skip_phases)
    
    try:
        if args.validate_prereqs:
            success = manager.validate_prerequisites()
            if success:
                logger.info("🎉 All prerequisites are satisfied!")
            else:
                logger.error("❌ Prerequisites validation failed")
            sys.exit(0 if success else 1)
        
        elif args.status:
            manager.status()
            sys.exit(0)
        
        elif args.setup_foundation:
            success = manager.setup_foundation()
            sys.exit(0 if success else 1)
        
        elif args.create_templates:
            success = manager.create_templates()
            sys.exit(0 if success else 1)
        
        elif args.setup_and_create:
            if manager.setup_foundation():
                success = manager.create_templates()
                sys.exit(0 if success else 1)
            else:
                sys.exit(1)
    
    except KeyboardInterrupt:
        logger.info("\\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()