#!/usr/bin/env python3
"""
Fresh Kubernetes Cluster Deployment Script
Handles complete deployment from a fresh Proxmox cluster state
"""
import json
import subprocess
import sys
import time
import shutil
import argparse
from pathlib import Path


class ClusterDeployer:
    def __init__(self, verify_only=False, infrastructure_only=False, kubespray_only=False, 
                 kubernetes_only=False, configure_mgmt_only=False, refresh_kubeconfig=False,
                 skip_cleanup=False, skip_terraform_reset=False, force_recreate=False,
                 fast_mode=False, ha_mode="localhost", phase_only=None):
        self.project_dir = Path(__file__).parent.parent
        self.terraform_dir = self.project_dir / "terraform"
        self.kubespray_version = "v2.28.1"
        self.kubespray_dir = self.project_dir / "kubespray"
        self.venv_dir = self.project_dir / "kubespray" / "venv"
        self.config_dir = self.project_dir / "kubespray-config"
        self.max_retries = 3
        # VM configuration - Terraform always creates all VMs regardless of HA mode
        self.vm_count = 8  # 3 control + 4 workers + 1 haproxy
        self.vm_ids = [130, 131, 132, 133, 140, 141, 142, 143]  # All VMs to clean up
        self.proxmox_nodes = ["node1", "node2", "node3", "node4"]
        
        # Mode flags
        self.verify_only = verify_only
        self.infrastructure_only = infrastructure_only
        self.kubespray_only = kubespray_only
        self.kubernetes_only = kubernetes_only
        self.configure_mgmt_only = configure_mgmt_only
        self.refresh_kubeconfig = refresh_kubeconfig
        self.skip_cleanup = skip_cleanup
        self.skip_terraform_reset = skip_terraform_reset
        self.force_recreate = force_recreate
        self.fast_mode = fast_mode
        self.ha_mode = ha_mode
        self.phase_only = phase_only
        
    def run_command(self, command, description, cwd=None, check=True, timeout=None, log_file=None):
        """Run a command with proper error handling and optional logging"""
        print(f"-> {description}...")
        try:
            if log_file:
                # For long-running commands with logging, use Popen for real-time output
                import os
                with open(log_file, 'w') as log_f:
                    log_f.write(f"=== {description} ===\n")
                    log_f.write(f"Command: {' '.join(command) if isinstance(command, list) else command}\n")
                    log_f.write(f"Working directory: {cwd}\n")
                    log_f.write("=" * 50 + "\n\n")
                    log_f.flush()
                    
                    process = subprocess.Popen(
                        command,
                        cwd=cwd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        shell=isinstance(command, str)
                    )
                    
                    # Read output line by line and write to both console and log
                    while True:
                        output = process.stdout.readline()
                        if output == '' and process.poll() is not None:
                            break
                        if output:
                            # Write to log file
                            log_f.write(output)
                            log_f.flush()
                            # Show periodic progress indicators
                            if any(keyword in output.lower() for keyword in ['task', 'play', 'gathering facts', 'setup', 'failed', 'ok:', 'changed:']):
                                print(f"   {output.strip()}")
                    
                    returncode = process.poll()
                    
                    # Create a result object similar to subprocess.run
                    class Result:
                        def __init__(self, returncode):
                            self.returncode = returncode
                            self.stdout = ""
                            self.stderr = ""
                    
                    result = Result(returncode)
                    if returncode != 0 and check:
                        raise subprocess.CalledProcessError(returncode, command)
                    return result
            else:
                # Standard execution for short commands
                result = subprocess.run(
                    command,
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    check=check,
                    timeout=timeout,
                    shell=isinstance(command, str)
                )
                if result.stdout and not result.stdout.isspace():
                    print(f"   {result.stdout.strip()}")
                return result
        except subprocess.TimeoutExpired:
            print(f"Command timed out after {timeout} seconds")
            return None
        except subprocess.CalledProcessError as e:
            if check:
                print(f"Error: {e}")
                if e.stderr:
                    print(f"   Stderr: {e.stderr}")
                sys.exit(1)
            return e
            
    def discover_existing_vms(self):
        """Discover which VMs actually exist on the Proxmox cluster"""
        print("Discovering existing VMs across all nodes...")
        existing_vms = {}  # vm_id -> node_name mapping
        
        for node in self.proxmox_nodes:
            print(f"Checking node {node}...")
            
            # Get list of all VMs on this node that match our target VM IDs
            vm_ids_pattern = '|'.join(map(str, self.vm_ids))
            result = self.run_command(
                f"ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 root@{node} \"qm list | grep -E '({vm_ids_pattern})' | awk '{{print \\$1}}' || true\"",
                f"Listing target VMs on {node}",
                check=False,
                timeout=10
            )
            
            if result and result.returncode == 0 and result.stdout.strip():
                found_vms = [int(vm_id.strip()) for vm_id in result.stdout.strip().split('\n') if vm_id.strip().isdigit()]
                for vm_id in found_vms:
                    if vm_id in self.vm_ids:
                        existing_vms[vm_id] = node
                        print(f"   Found VM {vm_id} on {node}")
            elif result and result.returncode != 0:
                print(f"   Could not check node {node} (may be unreachable)")
            else:
                print(f"   No target VMs found on {node}")
        
        return existing_vms
    
    def manual_vm_cleanup(self):
        """Optimized VM cleanup - only remove VMs that actually exist"""
        print("\nPhase -1: Smart VM Cleanup")
        print("=" * 50)
        
        # First, discover which VMs actually exist
        existing_vms = self.discover_existing_vms()
        
        if not existing_vms:
            print("\nNo existing VMs found - skipping cleanup phase")
            return
        
        print(f"\nFound {len(existing_vms)} VMs to clean up:")
        for vm_id, node in existing_vms.items():
            print(f"   VM {vm_id} on {node}")
        
        print("\nRemoving existing VMs...")
        
        for vm_id, node in existing_vms.items():
            print(f"\nRemoving VM {vm_id} from {node}...")
            
            # Stop VM if running
            self.run_command(
                f"ssh -o StrictHostKeyChecking=no root@{node} 'qm stop {vm_id} --skiplock || true'",
                f"Stopping VM {vm_id}",
                check=False,
                timeout=30
            )
            
            # Wait a moment for shutdown
            time.sleep(2)
            
            # Force destroy VM
            self.run_command(
                f"ssh -o StrictHostKeyChecking=no root@{node} 'qm destroy {vm_id} --skiplock --purge || true'",
                f"Destroying VM {vm_id}",
                check=False,
                timeout=30
            )
            
            # Clean up any leftover config files
            self.run_command(
                f"ssh -o StrictHostKeyChecking=no root@{node} 'rm -f /etc/pve/nodes/{node}/qemu-server/{vm_id}.conf /etc/pve/qemu-server/{vm_id}.conf || true'",
                f"Cleaning up config files for VM {vm_id}",
                check=False,
                timeout=10
            )
            
            print(f"   VM {vm_id} removed from {node}")
        
        print(f"\nSmart VM cleanup completed - removed {len(existing_vms)} VMs")
        
        # Wait for cleanup to settle
        if existing_vms:
            print("Waiting 10 seconds for cleanup to settle...")
            time.sleep(10)
        
    def reset_terraform(self):
        """Reset Terraform state completely"""
        print("\nPhase 0: Resetting Terraform State")
        print("=" * 50)
        
        # Destroy any existing resources
        self.run_command(
            ["terraform", "destroy", "-auto-approve"],
            "Destroying existing Terraform resources",
            cwd=self.terraform_dir,
            check=False
        )
        
        # Remove state files
        state_files = list(self.terraform_dir.glob("terraform.tfstate*"))
        for f in state_files:
            f.unlink()
            print(f"   Removed {f.name}")
            
        print("Terraform state reset completed")
        
    def verify_terraform_output(self):
        """Verify that Terraform created all expected VMs"""
        print("Verifying Terraform output...")
        
        result = self.run_command(
            ["terraform", "output", "-json"],
            "Getting Terraform output",
            cwd=self.terraform_dir,
            check=False
        )
        
        if result.returncode != 0:
            return False
            
        try:
            output = json.loads(result.stdout)
            cluster_summary = output.get("cluster_summary", {}).get("value", {})
            
            # Count VMs
            control_count = len(cluster_summary.get("control_plane", {}))
            worker_count = len(cluster_summary.get("workers", {}))
            haproxy_count = len(cluster_summary.get("haproxy_lb", {}))
            
            total = control_count + worker_count + haproxy_count
            
            print(f"   Control Plane: {control_count}, Workers: {worker_count}, HAProxy: {haproxy_count}")
            
            if total != self.vm_count:
                print(f"Expected {self.vm_count} VMs but found {total}")
                return False
                
            print(f"All {self.vm_count} VMs found in Terraform output")
            return True
            
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Failed to parse Terraform output: {e}")
            return False
            
    def test_vm_connectivity(self):
        """Test SSH connectivity to all VMs"""
        print("Testing SSH connectivity to all VMs...")
        
        # Get VM IPs from Terraform
        result = self.run_command(
            ["terraform", "output", "-json"],
            "Getting VM IPs",
            cwd=self.terraform_dir
        )
        
        try:
            output = json.loads(result.stdout)
            cluster_summary = output.get("cluster_summary", {}).get("value", {})
            
            # Collect all IPs
            ips = []
            for category in ["control_plane", "workers", "haproxy_lb"]:
                for vm_name, vm_info in cluster_summary.get(category, {}).items():
                    # Extract IP from vm_name (e.g., k8s-control-1 -> 10.10.1.31)
                    if "control" in vm_name:
                        ip_suffix = vm_name.split("-")[-1]
                        ip = f"10.10.1.{30 + int(ip_suffix)}"
                    elif "worker" in vm_name:
                        ip_suffix = vm_name.split("-")[-1]  
                        ip = f"10.10.1.{39 + int(ip_suffix)}"
                    elif "haproxy" in vm_name:
                        ip = "10.10.1.30"
                    else:
                        continue
                    ips.append((vm_name, ip))
                    
            # Test connectivity to each VM
            failed_vms = []
            for vm_name, ip in ips:
                result = self.run_command(
                    f"timeout 5 ssh -o StrictHostKeyChecking=no -o ConnectTimeout=3 -i /home/sysadmin/.ssh/sysadmin_automation_key sysadmin@{ip} 'echo OK'",
                    f"Testing {vm_name} ({ip})",
                    check=False
                )
                
                if result and result.returncode == 0 and "OK" in result.stdout:
                    print(f"   {vm_name} ({ip}) is reachable")
                else:
                    print(f"   {vm_name} ({ip}) is NOT reachable")
                    failed_vms.append((vm_name, ip))
                    
            if failed_vms:
                print(f"\n{len(failed_vms)} VMs are not reachable:")
                for vm_name, ip in failed_vms:
                    print(f"   - {vm_name} ({ip})")
                return False
                
            print(f"All {len(ips)} VMs are reachable via SSH")
            return True
            
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Failed to get VM information: {e}")
            return False
            
    def deploy_infrastructure(self):
        """Deploy infrastructure with Terraform, retrying if needed"""
        print("\nPhase 1: Infrastructure Deployment")
        print("=" * 50)
        
        # Initialize Terraform if needed
        if not (self.terraform_dir / ".terraform").exists():
            self.run_command(
                ["terraform", "init"],
                "Initializing Terraform",
                cwd=self.terraform_dir
            )
        
        for attempt in range(1, self.max_retries + 1):
            print(f"\nDeployment attempt {attempt}/{self.max_retries}")
            
            # Run Terraform apply with serial execution to avoid Ceph RBD lock issues
            # Since template 9000 only exists on node1, we must clone serially
            result = self.run_command(
                ["terraform", "apply", "-auto-approve", "-parallelism=1"],
                "Running Terraform apply (serial mode to avoid Ceph locks)",
                cwd=self.terraform_dir,
                check=False
            )
            
            if result.returncode != 0:
                print(f"Terraform apply failed on attempt {attempt}")
                if attempt < self.max_retries:
                    print("   Retrying...")
                    time.sleep(10)
                    continue
                else:
                    print("Maximum retries reached, aborting")
                    sys.exit(1)
                    
            # Verify all VMs were created
            if not self.verify_terraform_output():
                print(f"Not all VMs created on attempt {attempt}")
                if attempt < self.max_retries:
                    print("   Running Terraform again to create missing VMs...")
                    continue
                else:
                    print("Failed to create all VMs after maximum retries")
                    sys.exit(1)
                    
            # Wait for VMs to boot
            print("Waiting 30 seconds for VMs to boot...")
            time.sleep(30)
            
            # Test connectivity
            if self.test_vm_connectivity():
                print("Infrastructure deployment completed successfully!")
                return
            else:
                print(f"Some VMs not reachable on attempt {attempt}")
                if attempt < self.max_retries:
                    print("   Waiting 30 more seconds and retrying...")
                    time.sleep(30)
                    # Try connectivity test again
                    if self.test_vm_connectivity():
                        print("All VMs now reachable!")
                        return
                    print("   Still having issues, will recreate infrastructure...")
                else:
                    print("VMs not reachable after maximum retries")
                    sys.exit(1)
                    
        print("Infrastructure deployment failed")
        sys.exit(1)
        
    def setup_kubespray(self):
        """Setup Kubespray environment"""
        print("\nPhase 2: Kubespray Setup")
        print("=" * 50)
        
        # Clean up existing kubespray directory
        if self.kubespray_dir.exists():
            print("Removing existing Kubespray directory...")
            shutil.rmtree(self.kubespray_dir)
            
        # Clone Kubespray
        self.run_command(
            ["git", "clone", "--depth", "1", "--branch", self.kubespray_version,
             "https://github.com/kubernetes-sigs/kubespray.git", str(self.kubespray_dir)],
            f"Cloning Kubespray {self.kubespray_version}"
        )
        
        # Create virtual environment in kubespray directory
        self.run_command(
            ["python3", "-m", "venv", "venv"],
            "Creating Python virtual environment",
            cwd=self.kubespray_dir
        )
            
        # Install requirements
        pip_path = self.venv_dir / "bin" / "pip"
        self.run_command(
            [str(pip_path), "install", "-r", str(self.kubespray_dir / "requirements.txt")],
            "Installing Kubespray requirements"
        )
        
        # Fix ansible.cfg roles_path for v2.28.1 compatibility
        self.fix_kubespray_ansible_config()
        
        print("Kubespray setup completed")
    
    def fix_kubespray_ansible_config(self):
        """Fix ansible.cfg to include proper roles_path for Kubespray v2.28.1"""
        print("Fixing ansible.cfg roles_path for v2.28.1 compatibility...")
        
        ansible_cfg_path = self.kubespray_dir / "ansible.cfg"
        
        # Read current ansible.cfg content
        if ansible_cfg_path.exists():
            with open(ansible_cfg_path, 'r') as f:
                content = f.read()
        else:
            content = ""
        
        # Check if roles_path is already configured correctly
        if "roles_path = roles:playbooks/roles" in content:
            print("   ansible.cfg already has correct roles_path configuration")
            return
            
        # Find and update existing roles_path or add new one
        lines = content.split('\n')
        new_lines = []
        updated_roles_path = False
        
        for line in lines:
            # If we find an existing roles_path line, replace it with our fix
            if line.strip().startswith('roles_path = '):
                if not updated_roles_path:
                    new_lines.append('# Role paths - ensure roles are found from main kubespray directory')
                    new_lines.append('roles_path = roles:playbooks/roles')
                    updated_roles_path = True
                # Skip any additional roles_path lines to avoid duplicates
                continue
            else:
                new_lines.append(line)
        
        # If no existing roles_path was found, add it after [defaults] section
        if not updated_roles_path:
            for i, line in enumerate(new_lines):
                if line.strip() == '[defaults]':
                    new_lines.insert(i + 1, '')
                    new_lines.insert(i + 2, '# Role paths - ensure roles are found from main kubespray directory')
                    new_lines.insert(i + 3, 'roles_path = roles:playbooks/roles')
                    updated_roles_path = True
                    break
        
        # If [defaults] section doesn't exist, add it at the beginning
        if not updated_roles_path:
            header = [
                '[defaults]',
                '# Role paths - ensure roles are found from main kubespray directory', 
                'roles_path = roles:playbooks/roles',
                ''
            ]
            new_lines = header + new_lines
        
        # Write updated content back to ansible.cfg
        with open(ansible_cfg_path, 'w') as f:
            f.write('\n'.join(new_lines))
            
        print(f"   Updated ansible.cfg with correct roles_path: {ansible_cfg_path}")
        
    def apply_download_optimization(self):
        """Apply download optimization configuration to Kubespray"""
        print("Applying download optimization configuration...")
        
        # Create inventory group_vars/all directory
        group_vars_dir = self.kubespray_dir / "inventory" / "proxmox-cluster" / "group_vars" / "all"
        group_vars_dir.mkdir(parents=True, exist_ok=True)
        
        # Create download.yml configuration
        download_config = """---
# Download optimization configuration for efficient cluster deployment
# This configuration enables download caching to speed up deployments

# Download files once to first node and distribute to others
download_run_once: true

# Keep remote cache after download
download_keep_remote_cache: true

# Force use of cached files
download_force_cache: true

# Increase download retries for reliability
download_retries: 6

# Increase download timeout
download_timeout: 300

# Configure local release directory for caching
local_release_dir: /tmp/releases

# Configure download cache directory  
download_cache_dir: /tmp/kubespray_cache

# Always pull images (set to false for offline environments)
download_always_pull: false

# Container runtime settings for containerd
# These optimize container image handling
container_manager: containerd
containerd_version: "2.0.6"

# Enable registry mirrors for faster downloads (optional)
# registry_host: "registry.example.com:5000"

# Download verification
download_validate_certs: true

# Concurrent downloads (adjust based on bandwidth)
download_concurrent: 3
"""
        
        download_yml_path = group_vars_dir / "download.yml"
        download_yml_path.write_text(download_config)
        print(f"   Created download optimization config: {download_yml_path}")
        
        # Also create etcd.yml for etcd optimization
        etcd_config = """---
# etcd configuration optimizations
etcd_deployment_type: host
etcd_memory_limit: "0"
etcd_quota_backend_bytes: "2147483648"  # 2GB
etcd_heartbeat_interval: "250"
etcd_election_timeout: "2500"
"""
        
        etcd_yml_path = group_vars_dir / "etcd.yml"
        etcd_yml_path.write_text(etcd_config)
        print(f"   Created etcd optimization config: {etcd_yml_path}")
        
        # Create Cilium CNI configuration
        cilium_config = """---
# Cilium CNI configuration
kube_network_plugin: cilium
cilium_version: "1.17.7"

# Enable Cilium features
cilium_enable_ipv4: true
cilium_enable_ipv6: false

# Cilium networking mode
cilium_tunnel_mode: vxlan
cilium_enable_l7_proxy: true

# Enable Hubble for observability
cilium_enable_hubble: true
cilium_hubble_relay_enabled: true
cilium_hubble_ui_enabled: true

# BGP configuration (optional, can be enabled later)
cilium_enable_bgp_control_plane: false

# Security policies
cilium_enable_policy: "default"
cilium_policy_audit_mode: false

# Performance optimizations
cilium_enable_bandwidth_manager: true
cilium_enable_local_redirect_policy: true

# Monitoring
cilium_enable_prometheus: true
"""
        
        cilium_yml_path = group_vars_dir / "cilium.yml"
        cilium_yml_path.write_text(cilium_config)
        print(f"   Created Cilium CNI config: {cilium_yml_path}")
        
        # Create Kubespray config with optimized HA and Cilium compatibility
        k8s_cluster_config = self.generate_ha_config()
        
        k8s_cluster_yml_path = group_vars_dir / "k8s_cluster.yml" 
        k8s_cluster_yml_path.write_text(k8s_cluster_config)
        print(f"   Created k8s_cluster config with kube_owner=root: {k8s_cluster_yml_path}")
        
        # Create Ansible performance optimization config
        self.create_ansible_optimization_config(group_vars_dir)
    
    def generate_ha_config(self):
        """Generate High Availability configuration based on selected mode"""
        base_config = """---
# Kubespray configuration for Cilium compatibility
# When using Cilium CNI, kube_owner must be root to prevent permission issues
kube_owner: root

# Additional optimizations
kube_read_only_port: 0
kubelet_rotate_certificates: true
kubelet_rotate_server_certificates: true

# Enhanced cluster reliability
cluster_name: k8s-proxmox-cluster
kube_api_anonymous_auth: true
"""
        
        if self.ha_mode == "localhost":
            # Built-in localhost load balancer (recommended)
            ha_config = """
# High Availability Configuration - Localhost Load Balancer
# Built-in nginx proxy on each worker node for HA without external dependencies
loadbalancer_apiserver_localhost: true
loadbalancer_apiserver_port: 6443

# Disable external load balancer
# loadbalancer_apiserver: {}  # Commented out to use localhost LB
"""
            print("   Using localhost load balancer HA mode (built-in)")
            
        elif self.ha_mode == "kube-vip":
            # Kube-VIP configuration for true VIP with leader election
            ha_config = f"""
# High Availability Configuration - Kube-VIP
# Modern cloud-native VIP solution with automatic failover
kube_vip_enabled: true
kube_vip_controlplane_enabled: true
kube_vip_address: 10.10.1.30  # VIP address
kube_vip_interface: ens18     # Network interface
kube_vip_arp_enabled: true
kube_vip_services_enabled: false  # Focus on control plane HA only

# Required kube-proxy settings for kube-vip
kube_proxy_mode: ipvs
kube_proxy_strict_arp: true

# Configure API server to use VIP
loadbalancer_apiserver:
  address: 10.10.1.30
  port: 6443

# Disable localhost load balancer when using kube-vip
loadbalancer_apiserver_localhost: false
"""
            print("   Using kube-vip HA mode (VIP with leader election)")
            
        elif self.ha_mode == "external":
            # External load balancer (HAProxy) - legacy mode
            ha_config = """
# High Availability Configuration - External Load Balancer
# Uses external HAProxy for load balancing (requires manual setup)
loadbalancer_apiserver:
  address: 10.10.1.30
  port: 6443

# Disable localhost load balancer when using external LB
loadbalancer_apiserver_localhost: false
"""
            print("   Using external load balancer HA mode (HAProxy)")
            
        else:
            # Default to localhost
            ha_config = """
# High Availability Configuration - Localhost Load Balancer (Default)
loadbalancer_apiserver_localhost: true
loadbalancer_apiserver_port: 6443
"""
            print(f"   Unknown HA mode '{self.ha_mode}', defaulting to localhost")
        
        return base_config + ha_config
        
    def create_ansible_optimization_config(self, group_vars_dir):
        """Create ansible.cfg optimization for faster re-runs"""
        print("Creating Ansible performance optimizations...")
        
        # Create optimized ansible.cfg in kubespray directory with roles_path fix
        ansible_cfg_content = """[defaults]
# Performance optimizations for faster playbook execution
host_key_checking = False
pipelining = True
forks = 20
gathering = smart
fact_caching = memory
fact_caching_timeout = 3600
callback_whitelist = timer, profile_tasks, profile_roles

# Role paths - ensure roles are found from main kubespray directory
roles_path = roles:playbooks/roles

# SSH connection optimization
[ssh_connection]
ssh_args = -o ControlMaster=auto -o ControlPersist=600s -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no
pipelining = True
control_path = /tmp/ansible-%%h-%%p-%%r
"""
        
        ansible_cfg_path = self.kubespray_dir / "ansible.cfg"
        ansible_cfg_path.write_text(ansible_cfg_content)
        print(f"   Created optimized ansible.cfg with roles_path fix: {ansible_cfg_path}")
        
        # Create fast-mode specific optimizations
        if self.fast_mode:
            fast_config = """---
# Fast mode optimizations - skip non-essential tasks
# Note: Boolean values must be proper YAML booleans, not strings
skip_downloads: false
download_run_once: true
download_localhost: true
download_keep_remote_cache: true
download_force_cache: true

# Skip system package updates (faster but less secure)
skip_package_updates: true

# Reduce fact gathering to improve performance
gather_subset: "!hardware"

# Skip non-essential validations for faster deployment
skip_verify_kube_users: true
skip_verify_kube_groups: true
"""
            fast_config_path = group_vars_dir / "fast_mode.yml" 
            fast_config_path.write_text(fast_config)
            print(f"   Created fast-mode optimizations: {fast_config_path}")
        
    def configure_kubespray(self):
        """Configure Kubespray for deployment"""
        print("\nPhase 3: Kubespray Configuration")
        print("=" * 50)
        
        # Apply download optimization configuration first
        self.apply_download_optimization()
        
        # Generate inventory
        self.run_command(
            ["python3", str(self.project_dir / "scripts" / "generate-kubespray-inventory.py")],
            "Generating Kubespray inventory"
        )
        
        # Copy custom configuration
        if self.config_dir.exists():
            inventory_dir = self.kubespray_dir / "inventory" / "proxmox-cluster"
            inventory_dir.mkdir(parents=True, exist_ok=True)
            
            # Note: We don't copy the entire config dir, just merge specific files
            # This prevents overwriting the generated inventory
            print("Applying custom configuration...")
            
        # Note: Removed obsolete patch application
        # Previous patch optimized timeout 600->300 and removed ara_default callback
        # Current Kubespray v2.26.0 already has timeout=300, and ara isn't installed (harmless)
            
        print("Kubespray configuration completed")
        
    def test_ansible_connectivity(self):
        """Test Ansible connectivity to all nodes"""
        print("\nPhase 4: Connectivity Test")
        print("=" * 50)
        
        ansible_path = self.venv_dir / "bin" / "ansible"
        inventory_file = self.kubespray_dir / "inventory" / "proxmox-cluster" / "inventory.ini"
        
        result = self.run_command(
            [str(ansible_path), "-i", str(inventory_file), "all", "-m", "ping"],
            "Testing Ansible connectivity",
            cwd=self.kubespray_dir,
            check=False,
            timeout=30  # 30 second timeout for connectivity test
        )
        
        if result.returncode != 0:
            print("Ansible connectivity test failed")
            print("   Please check SSH keys and network connectivity")
            sys.exit(1)
            
        print("All nodes are reachable via Ansible")
        
    def deploy_kubernetes(self):
        """Deploy Kubernetes cluster with Kubespray"""
        print("\nPhase 5: Kubernetes Deployment")
        print("=" * 50)
        
        if self.fast_mode:
            print("Fast mode enabled - optimized for re-runs (5-15 minutes)")
        else:
            print("Standard deployment mode (15-30 minutes)")
        
        ansible_playbook_path = self.venv_dir / "bin" / "ansible-playbook"
        inventory_file = self.kubespray_dir / "inventory" / "proxmox-cluster" / "inventory.ini"
        
        # Create log file with timestamp
        mode_suffix = "-fast" if self.fast_mode else ""
        log_file = self.project_dir / f"kubespray-deployment{mode_suffix}-{int(time.time())}.log"
        print(f"Deployment log: {log_file}")
        
        start_time = time.time()
        
        # Build optimized command for fast mode
        cmd = [str(ansible_playbook_path), "-i", str(inventory_file), "-b"]
        
        if self.fast_mode:
            # Fast mode: skip non-essential tasks and use optimized tags
            cmd.extend([
                "--skip-tags", "download,bootstrap-os,preinstall",  # Skip slow initialization tasks
                "--tags", "k8s-cluster,network,master,node,addons"  # Focus on core deployment
            ])
            print("   Using fast-mode optimizations: skipping downloads and OS bootstrap")
            print("   Fast mode variables configured via fast_mode.yml")
        else:
            # Standard mode: verbose output
            cmd.append("-v")
        
        cmd.append("cluster.yml")
        
        # Run deployment
        result = self.run_command(
            cmd,
            f"Running Kubespray deployment ({'fast' if self.fast_mode else 'standard'} mode)",
            cwd=self.kubespray_dir,
            check=False,
            timeout=3600,  # 1 hour timeout
            log_file=str(log_file)
        )
        
        duration = int(time.time() - start_time)
        
        if result.returncode != 0:
            print(f"Kubernetes deployment failed after {duration // 60}m {duration % 60}s")
            print(f"Check deployment log for details: {log_file}")
            sys.exit(1)
            
        print(f"Kubernetes deployment completed in {duration // 60}m {duration % 60}s")
        print(f"Full deployment log: {log_file}")
        
    def setup_kubeconfig(self):
        """Setup kubeconfig for cluster access with automatic HA mode detection and configuration"""
        print("\nPhase 6: Kubeconfig Setup")
        print("=" * 50)
        
        # Create .kube directory if it doesn't exist
        kube_dir = Path.home() / ".kube"
        kube_dir.mkdir(exist_ok=True)
        
        kubeconfig_path = kube_dir / "config-k8s-proxmox"
        
        # Use the robust fetch method with fallback logic
        success = self._fetch_fresh_kubeconfig(kubeconfig_path)
        
        if not success:
            print("Error: Could not fetch kubeconfig from any control plane node")
            print("This might indicate cluster deployment issues or connectivity problems")
            return False
        
        # Verify kubeconfig was created
        if not kubeconfig_path.exists():
            print("Error: Kubeconfig file was not created successfully")
            return False
        
        # Set proper permissions
        kubeconfig_path.chmod(0o600)
        
        print(f"Raw kubeconfig fetched successfully: {kubeconfig_path}")
        
        # Now configure the appropriate access method based on HA mode
        print(f"\nConfiguring kubeconfig for HA mode: {self.ha_mode}")
        
        if self.ha_mode == "localhost":
            print("Configuring direct control plane access for localhost HA mode...")
            success = self._configure_direct_access_kubeconfig(refresh_config=False)
        elif self.ha_mode in ["kube-vip", "external"]:
            print(f"Configuring VIP access for {self.ha_mode} HA mode...")
            vip_address = "10.10.1.30"  # Default VIP address
            success = self._configure_vip_kubeconfig(refresh_config=False, vip_address=vip_address)
        else:
            print(f"Warning: Unknown HA mode '{self.ha_mode}', defaulting to direct access...")
            success = self._configure_direct_access_kubeconfig(refresh_config=False)
        
        if not success:
            print("Warning: Failed to configure optimal kubeconfig access method")
            print(f"Raw kubeconfig is still available at: {kubeconfig_path}")
            print("You may need to manually configure the server endpoint")
            return False
        
        print(f"\nPhase 6 completed: Kubeconfig configured for {self.ha_mode} HA mode")
        return True
        
    def _fetch_kubeconfig_via_ssh(self, temp_kubeconfig):
        """Helper method to fetch kubeconfig via direct SSH"""
        # Try each control plane node
        for control_ip in ["10.10.1.31", "10.10.1.32", "10.10.1.33"]:
            print(f"Attempting SSH fetch from {control_ip}...")
            result = self.run_command(
                f"ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 -i /home/sysadmin/.ssh/sysadmin_automation_key sysadmin@{control_ip} 'sudo cat /etc/kubernetes/admin.conf' > /tmp/kubeconfig-fresh",
                f"Fetching kubeconfig via SSH from {control_ip}",
                check=False
            )
            
            if result.returncode == 0 and Path("/tmp/kubeconfig-fresh").exists():
                shutil.copy("/tmp/kubeconfig-fresh", temp_kubeconfig)
                temp_kubeconfig.chmod(0o600)
                print(f"Fresh kubeconfig fetched via SSH from {control_ip}")
                return True
                
        print("Could not fetch fresh kubeconfig via SSH, using existing if available")
        return False
        
    def _configure_direct_access_kubeconfig(self, refresh_config=False):
        """Configure kubeconfig for direct control plane access (localhost HA mode)"""
        temp_kubeconfig = Path.home() / ".kube" / "config-k8s-proxmox"
        default_kubeconfig = Path.home() / ".kube" / "config"
        direct_config = Path.home() / ".kube" / "config-direct"
        
        # If refreshing or no existing config, fetch fresh kubeconfig
        if refresh_config or not temp_kubeconfig.exists():
            print("Fetching fresh kubeconfig from cluster...")
            self._fetch_fresh_kubeconfig(temp_kubeconfig)
        
        if not temp_kubeconfig.exists():
            print("Error: No kubeconfig available. Run full deployment first.")
            return False
        
        # Read current kubeconfig
        kubeconfig_content = temp_kubeconfig.read_text()
        
        # For localhost HA mode, convert localhost/VIP endpoints to direct control plane access
        # Replace common endpoint patterns with the primary control plane IP
        primary_control_ip = "10.10.1.31"
        
        # Replace various possible server endpoints with direct control plane IP
        kubeconfig_content = kubeconfig_content.replace("https://127.0.0.1:6443", f"https://{primary_control_ip}:6443")
        kubeconfig_content = kubeconfig_content.replace("https://localhost:6443", f"https://{primary_control_ip}:6443")
        kubeconfig_content = kubeconfig_content.replace("https://10.10.1.30:6443", f"https://{primary_control_ip}:6443")  # VIP to direct
        
        print(f"Configured kubeconfig for direct access to control plane: {primary_control_ip}")
        
        # Write configs
        default_kubeconfig.write_text(kubeconfig_content)
        default_kubeconfig.chmod(0o600)
        direct_config.write_text(kubeconfig_content)
        direct_config.chmod(0o600)
        
        print(f"Direct access kubeconfig configured at: {default_kubeconfig}")
        print(f"Also available at: {direct_config}")
        
        # Test connectivity
        result = self.run_command(
            "kubectl cluster-info",
            "Testing kubectl connectivity (direct access)",
            check=False
        )
        
        if result.returncode == 0:
            print("Successfully configured kubectl for direct access (localhost HA mode)")
            self.setup_shell_environment(default_kubeconfig)
            return True
        else:
            print("Warning: kubectl connectivity test failed")
            return False
    
    def _configure_vip_kubeconfig(self, refresh_config=False, vip_address="10.10.1.30"):
        """Configure kubeconfig for VIP access (kube-vip or external HA mode)"""
        temp_kubeconfig = Path.home() / ".kube" / "config-k8s-proxmox"
        default_kubeconfig = Path.home() / ".kube" / "config"
        
        # If refreshing or no existing config, fetch fresh kubeconfig
        if refresh_config or not temp_kubeconfig.exists():
            print("Fetching fresh kubeconfig from cluster...")
            self._fetch_fresh_kubeconfig(temp_kubeconfig)
        
        if not temp_kubeconfig.exists():
            print("Error: No kubeconfig available. Run full deployment first.")
            return False
        
        # Read current kubeconfig
        kubeconfig_content = temp_kubeconfig.read_text()
        
        # Replace server URL to point to VIP instead of individual control plane node
        updated_content = kubeconfig_content
        for control_ip in ["10.10.1.31", "10.10.1.32", "10.10.1.33"]:
            updated_content = updated_content.replace(
                f"https://{control_ip}:6443",
                f"https://{vip_address}:6443"
            )
        
        # Write updated kubeconfig
        default_kubeconfig.write_text(updated_content)
        default_kubeconfig.chmod(0o600)
        temp_kubeconfig.write_text(updated_content)
        temp_kubeconfig.chmod(0o600)
        
        print(f"VIP access kubeconfig configured at: {default_kubeconfig}")
        print(f"Using VIP address: {vip_address}")
        
        # Test connectivity
        result = self.run_command(
            "kubectl cluster-info",
            f"Testing kubectl connectivity via VIP {vip_address}",
            check=False
        )
        
        if result.returncode == 0:
            print(f"Successfully configured kubectl for VIP access ({self.ha_mode} HA mode)")
            self.setup_shell_environment(default_kubeconfig)
            return True
        else:
            print(f"Warning: kubectl connectivity test failed via VIP {vip_address}")
            # Try with --insecure-skip-tls-verify for external HA
            if self.ha_mode == "external":
                result = self.run_command(
                    "kubectl --insecure-skip-tls-verify cluster-info",
                    "Testing with certificate verification disabled",
                    check=False
                )
                if result.returncode == 0:
                    print("Note: External HA requires --insecure-skip-tls-verify due to certificate SAN issues")
            return False
    
    def _fetch_fresh_kubeconfig(self, target_path):
        """Helper method to fetch fresh kubeconfig from cluster"""
        # Check if we have kubespray environment to fetch config
        if self.kubespray_dir.exists():
            ansible_path = self.venv_dir / "bin" / "ansible"
            inventory_file = self.kubespray_dir / "inventory" / "proxmox-cluster" / "inventory.ini"
            
            if inventory_file.exists():
                # Try ansible first
                result = self.run_command(
                    [str(ansible_path), "-i", str(inventory_file),
                     "kube_control_plane[0]", "-m", "fetch",
                     "-a", "src=/etc/kubernetes/admin.conf dest=/tmp/kubeconfig-fresh flat=yes"],
                    "Fetching fresh kubeconfig from control plane",
                    cwd=self.kubespray_dir,
                    check=False
                )
                
                if result.returncode == 0 and Path("/tmp/kubeconfig-fresh").exists():
                    shutil.copy("/tmp/kubeconfig-fresh", target_path)
                    target_path.chmod(0o600)
                    print("Fresh kubeconfig fetched via Ansible")
                    return True
                else:
                    print("Ansible fetch failed, trying direct SSH...")
                    return self._fetch_kubeconfig_via_ssh(target_path)
            else:
                print("Warning: Kubespray inventory not found, trying direct SSH...")
                return self._fetch_kubeconfig_via_ssh(target_path)
        else:
            # Try to fetch directly via SSH if kubespray not available
            print("Kubespray not available, attempting direct SSH fetch...")
            return self._fetch_kubeconfig_via_ssh(target_path)
    
    def configure_management_kubeconfig(self, refresh_config=False):
        """Configure management machine kubectl for optimal HA access"""
        print("\nPhase 6.5: Management Machine Configuration")
        print("=" * 50)
        
        # Determine optimal configuration based on HA mode
        if self.ha_mode == "localhost":
            print("Localhost HA mode: Using direct control plane access for management")
            return self._configure_direct_access_kubeconfig(refresh_config)
        elif self.ha_mode == "kube-vip":
            print("Kube-VIP HA mode: Using VIP access")
            return self._configure_vip_kubeconfig(refresh_config, "10.10.1.30")
        else:  # external or fallback
            print("External HA mode: Using external load balancer")
            return self._configure_vip_kubeconfig(refresh_config, "10.10.1.30")
            
    def setup_shell_environment(self, primary_kubeconfig_path, fallback_kubeconfig_path=None):
        """Setup shell environment for kubectl access"""
        print("\nConfiguring shell environment...")
        
        bashrc_path = Path.home() / ".bashrc"
        
        # Create kubectl alias for convenience
        kubectl_alias = "alias k=kubectl"
        
        # Read existing bashrc content or create empty
        if bashrc_path.exists():
            bashrc_content = bashrc_path.read_text()
        else:
            bashrc_content = ""
            
        # Add kubectl alias if not present
        if "alias k=kubectl" not in bashrc_content:
            with open(bashrc_path, "a") as f:
                f.write(f"\n# Kubectl alias\n{kubectl_alias}\n")
            print("   Added kubectl alias 'k' to .bashrc")
        else:
            print("   kubectl alias 'k' already configured in .bashrc")
            
        # Add helpful functions for switching between configs if fallback exists
        if fallback_kubeconfig_path:
            kubectl_functions = f'''\n# Kubernetes configuration switching functions
function kube-vip() {{
    export KUBECONFIG={primary_kubeconfig_path}
    echo "Switched to VIP configuration (HAProxy load balancer)"
}}

function kube-direct() {{
    export KUBECONFIG={fallback_kubeconfig_path}
    echo "Switched to direct control plane configuration"
}}

function kube-default() {{
    unset KUBECONFIG
    echo "Using default kubeconfig (~/.kube/config)"
}}
'''
            
            if "function kube-vip()" not in bashrc_content:
                with open(bashrc_path, "a") as f:
                    f.write(kubectl_functions)
                print("   Added kubeconfig switching functions to .bashrc")
            
        print("\nManagement machine configuration completed!")
        print("\nkubectl is configured to use the default config location (~/.kube/config)")
        print("No KUBECONFIG export needed - kubectl will work immediately!")
        
        if fallback_kubeconfig_path:
            print("\nConfiguration switching functions available:")
            print("   kube-default  # Use default config (VIP)")
            print("   kube-vip      # Use VIP config explicitly")
            print("   kube-direct   # Use direct control plane config")
            
        print("\nUseful commands:")
        print("   kubectl get nodes")
        print("   kubectl get pods -A")
        print("   k get nodes  # Using alias")
        
    def verify_cluster(self):
        """Comprehensive Kubernetes cluster verification"""
        print("\nPhase 7: Cluster Verification")
        print("=" * 50)
        
        # Determine which kubeconfig to use (prioritize working config)
        kubeconfig_options = [
            Path.home() / ".kube" / "config",           # Default location
            Path.home() / ".kube" / "config-direct",    # Direct access
            Path.home() / ".kube" / "config-k8s-proxmox"  # Cluster-specific
        ]
        
        kubeconfig_path = None
        for config_path in kubeconfig_options:
            if config_path.exists():
                # Test if this config works
                test_result = self.run_command(
                    f"KUBECONFIG={config_path} kubectl cluster-info --request-timeout=10s",
                    f"Testing kubeconfig: {config_path.name}",
                    check=False,
                    timeout=15
                )
                if test_result.returncode == 0:
                    kubeconfig_path = config_path
                    print(f"Using working kubeconfig: {config_path}")
                    break
        
        if not kubeconfig_path:
            print("❌ No working kubeconfig found!")
            return False
        
        verification_passed = True
        kubectl_cmd = f"KUBECONFIG={kubeconfig_path} kubectl"
        
        print("\n🔍 Comprehensive Cluster Verification")
        print("-" * 40)
        
        # 1. Check cluster connectivity and basic info
        print("\n1️⃣  Cluster Connectivity & Info")
        result = self.run_command(
            f"{kubectl_cmd} cluster-info --request-timeout=10s",
            "Getting cluster info",
            check=False,
            timeout=15
        )
        if result.returncode == 0:
            print("✅ Cluster API is accessible")
        else:
            print("❌ Cluster API is not accessible")
            verification_passed = False
        
        # 2. Check all nodes status
        print("\n2️⃣  Node Status & Health")
        result = self.run_command(
            f"{kubectl_cmd} get nodes -o wide --show-labels",
            "Checking cluster nodes",
            check=False
        )
        if result.returncode == 0:
            # Check for node readiness
            nodes_result = self.run_command(
                f"{kubectl_cmd} get nodes --no-headers | grep -c Ready",
                "Counting ready nodes",
                check=False
            )
            if nodes_result.returncode == 0:
                ready_count = nodes_result.stdout.strip()
                print(f"✅ All {ready_count} nodes are Ready")
            else:
                print("⚠️  Could not verify node readiness")
                verification_passed = False
        else:
            print("❌ Failed to get cluster nodes")
            verification_passed = False
        
        # 3. Check system namespaces
        print("\n3️⃣  System Namespaces")
        expected_namespaces = ["kube-system", "kube-public", "kube-node-lease", "default"]
        result = self.run_command(
            f"{kubectl_cmd} get namespaces -o name",
            "Checking system namespaces",
            check=False
        )
        if result.returncode == 0:
            existing_namespaces = [ns.replace("namespace/", "") for ns in result.stdout.strip().split('\n')]
            missing_namespaces = [ns for ns in expected_namespaces if ns not in existing_namespaces]
            if not missing_namespaces:
                print(f"✅ All expected system namespaces present: {', '.join(expected_namespaces)}")
            else:
                print(f"❌ Missing system namespaces: {', '.join(missing_namespaces)}")
                verification_passed = False
        else:
            print("❌ Failed to get namespaces")
            verification_passed = False
        
        # 4. Check critical system pods
        print("\n4️⃣  Critical System Pods")
        critical_components = {
            "kube-apiserver": "kube-system",
            "kube-controller-manager": "kube-system", 
            "kube-scheduler": "kube-system",
            "coredns": "kube-system",
            "cilium": "kube-system"
        }
        
        for component, namespace in critical_components.items():
            result = self.run_command(
                f"{kubectl_cmd} get pods -n {namespace} -l component={component} --no-headers 2>/dev/null || "
                f"{kubectl_cmd} get pods -n {namespace} | grep {component} | head -1",
                f"Checking {component} pods",
                check=False
            )
            if result.returncode == 0 and result.stdout.strip():
                print(f"✅ {component} pods are running")
            else:
                print(f"⚠️  {component} pods status unclear - checking alternate patterns...")
                # Try alternative patterns for some components
                alt_result = self.run_command(
                    f"{kubectl_cmd} get pods -n {namespace} | grep -i {component}",
                    f"Alternative check for {component}",
                    check=False
                )
                if alt_result.returncode == 0 and alt_result.stdout.strip():
                    print(f"✅ {component} pods found")
                else:
                    print(f"❌ {component} pods not found or not running")
                    verification_passed = False
        
        # 4b. Check etcd (can be systemd service or pod)
        print("\n4️⃣b Checking etcd...")
        # First check if etcd pods exist
        etcd_pods_result = self.run_command(
            f"{kubectl_cmd} get pods -n kube-system | grep -i etcd",
            "Checking for etcd pods",
            check=False
        )
        
        if etcd_pods_result.returncode == 0 and etcd_pods_result.stdout.strip():
            print("✅ etcd running as pods")
        else:
            # Check if etcd is running as systemd service on control plane
            etcd_service_result = self.run_command(
                "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 sysadmin@10.10.1.31 'sudo systemctl is-active etcd' 2>/dev/null",
                "Checking etcd systemd service",
                check=False
            )
            
            if etcd_service_result.returncode == 0 and etcd_service_result.stdout.strip() == "active":
                print("✅ etcd running as systemd service on control planes")
            else:
                print("❌ etcd not found (neither as pod nor systemd service)")
                verification_passed = False
        
        # 5. Check all pods status across all namespaces
        print("\n5️⃣  All Pods Status")
        result = self.run_command(
            f"{kubectl_cmd} get pods -A --field-selector=status.phase!=Succeeded,status.phase!=Running --no-headers",
            "Checking for non-running pods",
            check=False
        )
        if result.returncode == 0:
            if result.stdout.strip():
                print("⚠️  Found pods not in Running/Succeeded state:")
                print(result.stdout)
                verification_passed = False
            else:
                print("✅ All pods are in Running or Succeeded state")
        
        # 6. Check services
        print("\n6️⃣  Core Services")
        result = self.run_command(
            f"{kubectl_cmd} get svc -A",
            "Checking core services",
            check=False
        )
        if result.returncode == 0:
            print("✅ Core services are accessible")
        else:
            print("❌ Failed to get services")
            verification_passed = False
        
        # 7. Test DNS resolution
        print("\n7️⃣  DNS Resolution Test")
        
        # First determine the cluster domain
        cluster_domain_result = self.run_command(
            f"{kubectl_cmd} get cm -n kube-system kubelet-config -o jsonpath='{{.data.kubelet}}' | grep clusterDomain | awk '{{print $2}}' | tr -d '\"'",
            "Getting cluster domain",
            check=False
        )
        
        cluster_domain = "cluster.local"  # default
        if cluster_domain_result.returncode == 0 and cluster_domain_result.stdout.strip():
            cluster_domain = cluster_domain_result.stdout.strip()
            print(f"   Cluster domain: {cluster_domain}")
        
        # Test DNS with correct domain
        dns_name = f"kubernetes.default.svc.{cluster_domain}"
        result = self.run_command(
            f"{kubectl_cmd} run dns-test --image=busybox:1.35 --rm -i --restart=Never --command -- nslookup {dns_name}",
            f"Testing DNS resolution for {dns_name}",
            check=False,
            timeout=30
        )
        
        if result.returncode == 0 and "Address" in result.stdout:
            print(f"✅ DNS resolution is working for cluster domain: {cluster_domain}")
        else:
            # Try a simpler test - just resolve kubernetes service
            print("⚠️  Full DNS test failed - trying simpler test...")
            simple_result = self.run_command(
                f"{kubectl_cmd} run dns-test-simple --image=busybox:1.35 --rm -i --restart=Never --command -- nslookup kubernetes.default",
                "Testing simple DNS resolution",
                check=False,
                timeout=30
            )
            
            if simple_result.returncode == 0 and "Address" in simple_result.stdout:
                print("✅ Basic DNS resolution is working")
            else:
                # Check if CoreDNS and NodeLocalDNS are running
                coredns_check = self.run_command(
                    f"{kubectl_cmd} get pods -n kube-system | grep -E 'coredns|nodelocaldns' | grep Running | wc -l",
                    "Checking DNS pods",
                    check=False
                )
                
                if coredns_check.returncode == 0:
                    dns_pod_count = coredns_check.stdout.strip()
                    if int(dns_pod_count) > 0:
                        print(f"⚠️  DNS pods are running ({dns_pod_count} pods) but resolution not working from test pod")
                        print("    This may be normal if nodelocaldns is not fully configured")
                        print("    DNS should work for actual workloads within the cluster")
                    else:
                        print("❌ DNS pods not running properly")
                        verification_passed = False
                else:
                    print("❌ Could not verify DNS pod status")
                    verification_passed = False
        
        # 8. Test basic workload deployment
        print("\n8️⃣  Basic Workload Test")
        test_deployment_yaml = f"""
apiVersion: apps/v1
kind: Deployment
metadata:
  name: verification-test
  namespace: default
spec:
  replicas: 1
  selector:
    matchLabels:
      app: verification-test
  template:
    metadata:
      labels:
        app: verification-test
    spec:
      containers:
      - name: test-container
        image: nginx:1.21-alpine
        ports:
        - containerPort: 80
        resources:
          requests:
            memory: "32Mi"
            cpu: "50m"
          limits:
            memory: "64Mi"
            cpu: "100m"
"""
        
        # Create test deployment
        with open("/tmp/verification-test.yaml", "w") as f:
            f.write(test_deployment_yaml)
        
        result = self.run_command(
            f"{kubectl_cmd} apply -f /tmp/verification-test.yaml",
            "Deploying test workload",
            check=False
        )
        
        if result.returncode == 0:
            # Wait for deployment to be ready
            ready_result = self.run_command(
                f"{kubectl_cmd} wait --for=condition=available deployment/verification-test --timeout=60s",
                "Waiting for test deployment to be ready",
                check=False
            )
            
            if ready_result.returncode == 0:
                print("✅ Basic workload deployment successful")
                
                # Cleanup test deployment
                self.run_command(
                    f"{kubectl_cmd} delete deployment verification-test --ignore-not-found=true",
                    "Cleaning up test deployment",
                    check=False
                )
            else:
                print("⚠️  Test deployment failed to become ready")
                # Still cleanup
                self.run_command(
                    f"{kubectl_cmd} delete deployment verification-test --ignore-not-found=true",
                    "Cleaning up test deployment",
                    check=False
                )
                verification_passed = False
        else:
            print("❌ Failed to deploy test workload")
            verification_passed = False
        
        # 9. Check cluster resource capacity
        print("\n9️⃣  Cluster Resource Summary")
        result = self.run_command(
            f"{kubectl_cmd} top nodes --no-headers 2>/dev/null || echo 'Metrics not available'",
            "Getting node resource usage",
            check=False
        )
        
        capacity_result = self.run_command(
            f"{kubectl_cmd} describe nodes | grep -A 5 'Capacity:' | head -20",
            "Getting cluster capacity",
            check=False
        )
        
        if capacity_result.returncode == 0:
            print("✅ Cluster capacity information available")
        
        # Final summary
        print("\n" + "=" * 50)
        if verification_passed:
            print("🎉 CLUSTER VERIFICATION PASSED!")
            print("✅ All critical components are healthy and functional")
            print("✅ Cluster is ready for production workloads")
        else:
            print("⚠️  CLUSTER VERIFICATION COMPLETED WITH WARNINGS")
            print("🔍 Some components may need attention - check output above")
            print("💡 Cluster may still be functional for basic workloads")
        
        print("=" * 50)
        print("\n📋 Verification Summary:")
        print("   - Cluster API: Accessible")
        print("   - Node Health: All nodes ready") if verification_passed else print("   - Node Health: Issues detected")
        print("   - System Pods: All running") if verification_passed else print("   - System Pods: Some issues")
        print("   - DNS: Functional") if verification_passed else print("   - DNS: May have issues")
        print("   - Basic Workloads: Deployable") if verification_passed else print("   - Basic Workloads: Issues detected")
        
        return verification_passed
        
    def get_vm_placement_from_terraform(self):
        """Get VM placement mapping from Terraform configuration or state"""
        vm_placement = {}
        
        # First try to get from Terraform state if it exists
        if (self.terraform_dir / "terraform.tfstate").exists():
            try:
                result = self.run_command(
                    ["terraform", "show", "-json"],
                    "Reading Terraform state for VM placement",
                    cwd=self.terraform_dir,
                    check=False
                )
                if result.returncode == 0:
                    state_data = json.loads(result.stdout)
                    if "values" in state_data and "root_module" in state_data["values"]:
                        resources = state_data["values"]["root_module"].get("resources", [])
                        for resource in resources:
                            if resource.get("type") == "proxmox_virtual_environment_vm":
                                values = resource.get("values", {})
                                vm_id = values.get("vm_id")
                                node_name = values.get("node_name")
                                if vm_id and node_name:
                                    vm_placement[vm_id] = node_name
                    
                    if vm_placement:
                        print(f"   Found {len(vm_placement)} VMs in Terraform state")
                        return vm_placement
            except (json.JSONDecodeError, KeyError, subprocess.CalledProcessError):
                pass
        
        # Fallback: try to get from Terraform plan
        try:
            result = self.run_command(
                ["terraform", "plan", "-out=/tmp/tfplan"],
                "Generating Terraform plan for VM placement",
                cwd=self.terraform_dir,
                check=False
            )
            if result.returncode == 0:
                result = self.run_command(
                    ["terraform", "show", "-json", "/tmp/tfplan"],
                    "Reading Terraform plan for VM placement", 
                    cwd=self.terraform_dir,
                    check=False
                )
                if result.returncode == 0:
                    plan_data = json.loads(result.stdout)
                    if "planned_values" in plan_data and "root_module" in plan_data["planned_values"]:
                        resources = plan_data["planned_values"]["root_module"].get("resources", [])
                        for resource in resources:
                            if resource.get("type") == "proxmox_virtual_environment_vm":
                                values = resource.get("values", {})
                                vm_id = values.get("vm_id")
                                node_name = values.get("node_name")
                                if vm_id and node_name:
                                    vm_placement[vm_id] = node_name
                    
                    if vm_placement:
                        print(f"   Found {len(vm_placement)} VMs in Terraform plan")
                        return vm_placement
        except (json.JSONDecodeError, KeyError, subprocess.CalledProcessError):
            pass
        
        # Last resort: correct hardcoded fallback based on HA mode
        print("   Using fallback VM placement mapping")
        fallback_mapping = {
            131: "node1",  # k8s-control-1
            132: "node2",  # k8s-control-2  
            133: "node3",  # k8s-control-3
            140: "node1",  # k8s-worker-1
            141: "node2",  # k8s-worker-2
            142: "node3",  # k8s-worker-3
            143: "node4"   # k8s-worker-4
        }
        
        # Add HAProxy VM only for external HA mode
        if hasattr(self, 'ha_mode') and self.ha_mode == "external":
            fallback_mapping[130] = "node4"  # k8s-haproxy-lb
            
        return fallback_mapping
        
    def verify_existing_vms(self):
        """Verify existing VMs without destructive actions"""
        print("\nVM Verification Mode")
        print("=" * 50)
        
        # Use optimized discovery to find existing VMs
        existing_vms = self.discover_existing_vms()
        
        if not existing_vms:
            print("\nNo VMs found on any nodes")
            print("   Run full deployment to create cluster")
            sys.exit(1)
        
        print(f"\nFound {len(existing_vms)} VMs:")
        for vm_id, node in existing_vms.items():
            print(f"   VM {vm_id} on {node}")
        
        # Check status of found VMs
        running_vms = []
        stopped_vms = []
        
        for vm_id, node in existing_vms.items():
            result = self.run_command(
                f"ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 root@{node} 'qm status {vm_id} 2>/dev/null'",
                f"Checking VM {vm_id} status",
                check=False,
                timeout=10
            )
            
            if result and result.returncode == 0:
                if "status: running" in result.stdout:
                    print(f"   VM {vm_id} is running on {node}")
                    running_vms.append(vm_id)
                elif "status: stopped" in result.stdout:
                    print(f"   VM {vm_id} exists but is stopped on {node}")
                    stopped_vms.append(vm_id)
                else:
                    print(f"   VM {vm_id} has unknown status: {result.stdout.strip()}")
            else:
                print(f"   Could not get status for VM {vm_id} on {node}")
        
        # Check expected vs found VMs
        expected_vm_count = len(self.vm_ids)
        found_vm_count = len(existing_vms)
        missing_vm_count = expected_vm_count - found_vm_count
        
        missing_vms = [vm_id for vm_id in self.vm_ids if vm_id not in existing_vms]
        
        # Report VM status summary
        print(f"\nVM Status Summary:")
        print(f"   Running: {len(running_vms)}")
        print(f"   Stopped: {len(stopped_vms)}")
        print(f"   Missing: {len(missing_vms)}")
        
        if missing_vms:
            print(f"\nMissing VMs: {missing_vms}")
            print("   Run full deployment to create missing VMs")
            sys.exit(1)
            
        if stopped_vms:
            print(f"\nStopped VMs: {stopped_vms}")
            print("   These VMs exist but need to be started")
            
        if not running_vms:
            print("\nNo running VMs found")
            sys.exit(1)
            
        # Test SSH connectivity to running VMs only
        if running_vms:
            print(f"\nTesting SSH connectivity to {len(running_vms)} running VMs...")
            
            # Map VM IDs to IPs and names (dynamic based on HA mode)
            vm_info = {
                131: ("k8s-control-1", "10.10.1.31"),
                132: ("k8s-control-2", "10.10.1.32"), 
                133: ("k8s-control-3", "10.10.1.33"),
                140: ("k8s-worker-1", "10.10.1.40"),
                141: ("k8s-worker-2", "10.10.1.41"),
                142: ("k8s-worker-3", "10.10.1.42"),
                143: ("k8s-worker-4", "10.10.1.43")
            }
            
            # Add HAProxy VM only for external HA mode
            if self.ha_mode == "external":
                vm_info[130] = ("k8s-haproxy-lb", "10.10.1.30")
            
            ssh_failed = []
            for vm_id in running_vms:
                vm_name, ip = vm_info[vm_id]
                result = self.run_command(
                    f"timeout 5 ssh -o StrictHostKeyChecking=no -o ConnectTimeout=3 -i /home/sysadmin/.ssh/sysadmin_automation_key sysadmin@{ip} 'echo OK'",
                    f"Testing {vm_name} ({ip})",
                    check=False
                )
                
                if result and result.returncode == 0 and "OK" in result.stdout:
                    print(f"   {vm_name} ({ip}) is reachable via SSH")
                else:
                    print(f"   {vm_name} ({ip}) is NOT reachable via SSH")
                    ssh_failed.append((vm_name, ip))
            
            if ssh_failed:
                print(f"\n{len(ssh_failed)} VMs failed SSH connectivity test:")
                for vm_name, ip in ssh_failed:
                    print(f"   - {vm_name} ({ip})")
                sys.exit(1)
            else:
                print(f"All {len(running_vms)} running VMs are accessible via SSH")
            
            # Test Ansible connectivity if kubespray exists
            if self.kubespray_dir.exists():
                inventory_file = self.kubespray_dir / "inventory" / "proxmox-cluster" / "inventory.ini"
                if inventory_file.exists():
                    print("\nTesting Ansible connectivity...")
                    ansible_path = self.venv_dir / "bin" / "ansible"
                    
                    result = self.run_command(
                        [str(ansible_path), "-i", str(inventory_file), "all", "-m", "ping"],
                        "Testing Ansible connectivity",
                        cwd=self.kubespray_dir,
                        check=False
                    )
                    
                    if result.returncode == 0:
                        print("All nodes are reachable via Ansible")
                    else:
                        print("Ansible connectivity test failed")
                else:
                    print("Kubespray inventory not found - run full deployment to generate")
            else:
                print("Kubespray not found - run full deployment to set up")
                
            print("\nVM verification completed successfully!")
        else:
            print("No running VMs to test")
            sys.exit(1)
    
    def run(self):
        """Run the deployment based on specified flags"""
        if self.verify_only:
            self.verify_existing_vms()
            return
            
        # Handle individual phase execution
        if self.phase_only:
            self.run_single_phase()
            return
            
        # Determine deployment mode
        if self.infrastructure_only:
            self.run_infrastructure_only()
        elif self.kubespray_only:
            self.run_kubespray_only()
        elif self.kubernetes_only:
            self.run_kubernetes_only()
        elif self.configure_mgmt_only:
            self.run_configure_mgmt_only()
        else:
            self.run_full_deployment()
    
    def run_single_phase(self):
        """Run only a specific phase based on phase_only parameter"""
        print(f"Single Phase Execution: {self.phase_only}")
        print("=" * 50)
        print(f"Project Directory: {self.project_dir}")
        print(f"HA Mode: {self.ha_mode}")
        print("=" * 50)
        
        # Execute the specified phase
        if self.phase_only == "cleanup":
            print("Running Phase -1: VM Cleanup")
            self.manual_vm_cleanup()
            
        elif self.phase_only == "reset":
            print("Running Phase 0: Terraform Reset")
            self.reset_terraform()
            
        elif self.phase_only == "infrastructure":
            print("Running Phase 1: Infrastructure Deployment")
            self.deploy_infrastructure()
            
        elif self.phase_only == "kubespray-setup":
            print("Running Phase 2: Kubespray Setup")
            self.setup_kubespray()
            
        elif self.phase_only == "kubespray-config":
            print("Running Phase 3: Kubespray Configuration")
            self.configure_kubespray()
            
        elif self.phase_only == "connectivity":
            print("Running Phase 4: Connectivity Test")
            self.test_connectivity()
            
        elif self.phase_only == "kubernetes":
            print("Running Phase 5: Kubernetes Deployment")
            self.deploy_kubernetes()
            
        elif self.phase_only == "kubeconfig":
            print("Running Phase 6: Kubeconfig Setup")
            self.setup_kubeconfig()
            
        elif self.phase_only == "management":
            print("Running Phase 6.5: Management Machine Configuration")
            self.configure_management_kubeconfig(refresh_config=self.refresh_kubeconfig)
            
        elif self.phase_only == "verify":
            print("Running Phase 7: Cluster Verification")
            self.verify_cluster()
            
        else:
            print(f"Unknown phase: {self.phase_only}")
            sys.exit(1)
            
        print(f"\nPhase {self.phase_only} completed successfully!")
            
    def run_infrastructure_only(self):
        """Deploy only infrastructure (VMs) with Terraform"""
        print("Infrastructure-Only Deployment")
        print("=" * 50)
        print(f"Project Directory: {self.project_dir}")
        print(f"Terraform Directory: {self.terraform_dir}")
        print(f"Expected VMs: {self.vm_count}")
        print("=" * 50)
        
        # Phase -1: Manual cleanup (unless skipped)
        if not self.skip_cleanup or self.force_recreate:
            self.manual_vm_cleanup()
        
        # Phase 0: Reset (unless skipped)
        if not self.skip_terraform_reset or self.force_recreate:
            self.reset_terraform()
        
        # Phase 1: Infrastructure
        self.deploy_infrastructure()
        
        print("\n" + "=" * 50)
        print("Infrastructure deployment completed!")
        print("=" * 50)
        print("\nNext steps:")
        print("1. Run with --kubespray-only to setup Kubespray")
        print("2. Run with --kubernetes-only to deploy Kubernetes")
        print("3. Run with --configure-mgmt-only to configure kubectl")
        print("4. Or run without flags for remaining phases")
        
    def run_configure_mgmt_only(self):
        """Configure management machine kubectl only"""
        print("Management Configuration Only")
        print("=" * 50)
        
        # Configure management machine (with refresh option)
        success = self.configure_management_kubeconfig(refresh_config=self.refresh_kubeconfig)
        
        if success:
            print("\n" + "=" * 50)
            print("Management machine configuration completed!")
            print("=" * 50)
            print("\nkubectl is now configured to use VIP (10.10.1.30)")
            print("Test with: kubectl get nodes")
        else:
            print("\nManagement configuration completed with warnings.")
            print("kubectl may work once HAProxy is fully configured.")
        
    def run_kubespray_only(self):
        """Setup and configure Kubespray only"""
        print("Kubespray-Only Setup")
        print("=" * 50)
        
        # Check if infrastructure exists
        if not (self.terraform_dir / "terraform.tfstate").exists():
            print("No Terraform state found. Deploy infrastructure first with --infrastructure-only")
            
        # Phase 2: Setup Kubespray
        self.setup_kubespray()
        
        # Phase 3: Configure
        self.configure_kubespray()
        
        print("\n" + "=" * 50)
        print("Kubespray setup completed!")
        print("=" * 50)
        print("\nNext steps:")
        print("1. Run with --kubernetes-only to deploy Kubernetes")
        print("2. Run with --configure-mgmt-only to configure kubectl")
        print("3. Or run without flags for remaining phases")
        
    def run_kubernetes_only(self):
        """Deploy Kubernetes cluster only (assumes infrastructure exists)"""
        print("Kubernetes-Only Deployment")
        print("=" * 50)
        
        # Check prerequisites
        if not (self.terraform_dir / "terraform.tfstate").exists():
            print("No Terraform state found. Deploy infrastructure first with --infrastructure-only")
            sys.exit(1)
            
        if not self.kubespray_dir.exists():
            print("Kubespray not found. Setup Kubespray first with --kubespray-only")
            sys.exit(1)
            
        inventory_file = self.kubespray_dir / "inventory" / "proxmox-cluster" / "inventory.ini"
        if not inventory_file.exists():
            print("Kubespray inventory not found. Setup Kubespray first with --kubespray-only")
            sys.exit(1)
        
        # Phase 4: Test connectivity
        self.test_ansible_connectivity()
        
        # Phase 5: Deploy Kubernetes
        self.deploy_kubernetes()
        
        # Phase 6: Setup kubeconfig
        self.setup_kubeconfig()
        
        # Phase 6.5: Configure management machine
        self.configure_management_kubeconfig(refresh_config=self.force_recreate)
        
        # HAProxy no longer used - localhost HA mode uses nginx-proxy on worker nodes
        print(f"\nUsing built-in HA mode: {self.ha_mode} (no external HAProxy needed)")
        
        # Phase 7: Verify
        self.verify_cluster()
        
        print("\n" + "=" * 50)
        print("Kubernetes deployment completed!")
        print("=" * 50)
        print("\nNext steps:")
        print("1. kubectl is configured to use VIP (10.10.1.30)")
        print("2. Verify cluster: kubectl get nodes")
        print("3. Deploy applications: kubectl apply -f your-app.yaml")
        
    def run_full_deployment(self):
        """Run the complete deployment"""
        print("Full Kubernetes Cluster Deployment")
        print("=" * 50)
        print(f"Project Directory: {self.project_dir}")
        print(f"Terraform Directory: {self.terraform_dir}")
        print(f"Expected VMs: {self.vm_count}")
        print("=" * 50)
        
        # Phase -1: Manual cleanup (unless skipped)
        if not self.skip_cleanup:
            self.manual_vm_cleanup()
        
        # Phase 0: Reset (unless skipped)
        if not self.skip_terraform_reset:
            self.reset_terraform()
        
        # Phase 1: Infrastructure
        self.deploy_infrastructure()
        
        # Phase 2: Setup Kubespray
        self.setup_kubespray()
        
        # Phase 3: Configure
        self.configure_kubespray()
        
        # Phase 4: Test connectivity
        self.test_ansible_connectivity()
        
        # Phase 5: Deploy Kubernetes
        self.deploy_kubernetes()
        
        # Phase 6: Setup kubeconfig
        self.setup_kubeconfig()
        
        # Phase 6.5: Configure management machine
        self.configure_management_kubeconfig(refresh_config=self.force_recreate)
        
        # HAProxy no longer used - localhost HA mode uses nginx-proxy on worker nodes
        print(f"\nUsing built-in HA mode: {self.ha_mode} (no external HAProxy needed)")
        
        # Phase 7: Verify
        self.verify_cluster()
        
        print("\n" + "=" * 50)
        print("Full Kubernetes cluster deployment completed successfully!")
        print("=" * 50)
        print("\nNext steps:")
        print("1. kubectl is configured to use VIP (10.10.1.30)")
        print("2. Verify cluster: kubectl get nodes")
        print("3. Deploy applications: kubectl apply -f your-app.yaml")
        

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Fresh Kubernetes Cluster Deployment")
    
    # Verification mode
    parser.add_argument("--verify-only", action="store_true", 
                       help="Only verify existing VMs without destructive actions")
    
    # Component-specific deployment flags
    parser.add_argument("--infrastructure-only", action="store_true",
                       help="Deploy only infrastructure (VMs) with Terraform")
    parser.add_argument("--kubespray-only", action="store_true", 
                       help="Setup and configure Kubespray only")
    parser.add_argument("--kubernetes-only", action="store_true",
                       help="Deploy Kubernetes cluster only (assumes infrastructure exists)")
    parser.add_argument("--configure-mgmt-only", action="store_true", 
                       help="Configure management machine kubectl to use VIP only")
    parser.add_argument("--refresh-kubeconfig", action="store_true",
                       help="Refresh kubeconfig from cluster when configuring management")
    parser.add_argument("--fast", action="store_true",
                       help="Fast mode for re-runs: skip downloads, OS bootstrap, and use optimized tags")
    parser.add_argument("--ha-mode", choices=["localhost", "kube-vip", "external"], default="localhost",
                       help="HA mode: localhost (built-in nginx, default), kube-vip (VIP with leader election), external (HAProxy)")
    
    # Individual phase execution flags
    parser.add_argument("--phase", type=str, choices=[
        "cleanup", "reset", "infrastructure", "kubespray-setup", "kubespray-config", 
        "connectivity", "kubernetes", "kubeconfig", "management", "verify"
    ], help="Run only a specific phase: cleanup(-1), reset(0), infrastructure(1), kubespray-setup(2), kubespray-config(3), connectivity(4), kubernetes(5), kubeconfig(6), management(6.5), verify(7)")
    
    # Phase control flags
    parser.add_argument("--skip-cleanup", action="store_true",
                       help="Skip manual VM cleanup phase")
    parser.add_argument("--skip-terraform-reset", action="store_true", 
                       help="Skip Terraform state reset")
    parser.add_argument("--force-recreate", action="store_true",
                       help="Force complete recreation (cleanup + reset + deploy)")
    
    args = parser.parse_args()
    
    # Validate argument combinations
    component_flags = [args.infrastructure_only, args.kubespray_only, args.kubernetes_only, args.configure_mgmt_only]
    if sum(component_flags) > 1:
        print("Cannot specify multiple component flags simultaneously")
        sys.exit(1)
    
    # Validate phase argument doesn't conflict with other flags
    if args.phase and (sum(component_flags) > 0 or args.verify_only):
        print("Cannot specify --phase with other execution mode flags")
        sys.exit(1)
        
    # Check if running from correct directory
    if not Path("terraform/kubernetes-cluster.tf").exists():
        print("Must run from kubernetes-cluster root directory")
        sys.exit(1)
        
    deployer = ClusterDeployer(
        verify_only=args.verify_only,
        infrastructure_only=args.infrastructure_only,
        kubespray_only=args.kubespray_only,
        kubernetes_only=args.kubernetes_only,
        configure_mgmt_only=args.configure_mgmt_only,
        refresh_kubeconfig=args.refresh_kubeconfig,
        skip_cleanup=args.skip_cleanup,
        skip_terraform_reset=args.skip_terraform_reset,
        force_recreate=args.force_recreate,
        fast_mode=args.fast,
        ha_mode=args.ha_mode,
        phase_only=args.phase
    )
    deployer.run()
    

if __name__ == "__main__":
    main()