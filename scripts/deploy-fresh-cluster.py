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
from pathlib import Path


class ClusterDeployer:
    def __init__(self):
        self.project_dir = Path(__file__).parent.parent
        self.terraform_dir = self.project_dir / "terraform"
        self.kubespray_version = "v2.26.0"
        self.kubespray_dir = self.project_dir / "kubespray"
        self.venv_dir = self.project_dir / "kubespray" / "venv"
        self.config_dir = self.project_dir / "kubespray-config"
        self.max_retries = 3
        self.vm_count = 8  # 3 control + 4 workers + 1 haproxy
        self.vm_ids = [130, 131, 132, 133, 140, 141, 142, 143]  # VMs to clean up
        self.proxmox_nodes = ["node1", "node2", "node3", "node4"]
        
    def run_command(self, command, description, cwd=None, check=True, timeout=None):
        """Run a command with proper error handling"""
        print(f"🔄 {description}...")
        try:
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
            print(f"⏱️ Command timed out after {timeout} seconds")
            return None
        except subprocess.CalledProcessError as e:
            if check:
                print(f"❌ Error: {e}")
                if e.stderr:
                    print(f"   Stderr: {e.stderr}")
                sys.exit(1)
            return e
            
    def manual_vm_cleanup(self):
        """Manually clean up any existing VMs on all Proxmox nodes"""
        print("\n🧹 Phase -1: Manual VM Cleanup")
        print("=" * 50)
        
        for node in self.proxmox_nodes:
            print(f"\n🔍 Cleaning up VMs on {node}...")
            
            for vm_id in self.vm_ids:
                # Check if VM exists
                result = self.run_command(
                    f"ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 root@{node} 'qm status {vm_id} 2>/dev/null || echo \"not found\"'",
                    f"Checking VM {vm_id} on {node}",
                    check=False,
                    timeout=10
                )
                
                if result and result.returncode == 0:
                    if "not found" not in result.stdout and "does not exist" not in result.stdout:
                        print(f"   Found VM {vm_id} on {node}, removing...")
                        
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
                        
                    else:
                        print(f"   VM {vm_id} not found on {node}")
                else:
                    print(f"   Could not check VM {vm_id} on {node} (node may be unreachable)")
        
        print("\n✅ Manual VM cleanup completed")
        
        # Wait for cleanup to settle
        print("⏳ Waiting 10 seconds for cleanup to settle...")
        time.sleep(10)
        
    def reset_terraform(self):
        """Reset Terraform state completely"""
        print("\n📦 Phase 0: Resetting Terraform State")
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
            
        print("✅ Terraform state reset completed")
        
    def verify_terraform_output(self):
        """Verify that Terraform created all expected VMs"""
        print("🔍 Verifying Terraform output...")
        
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
                print(f"❌ Expected {self.vm_count} VMs but found {total}")
                return False
                
            print(f"✅ All {self.vm_count} VMs found in Terraform output")
            return True
            
        except (json.JSONDecodeError, KeyError) as e:
            print(f"❌ Failed to parse Terraform output: {e}")
            return False
            
    def test_vm_connectivity(self):
        """Test SSH connectivity to all VMs"""
        print("🔗 Testing SSH connectivity to all VMs...")
        
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
                    print(f"   ✅ {vm_name} ({ip}) is reachable")
                else:
                    print(f"   ❌ {vm_name} ({ip}) is NOT reachable")
                    failed_vms.append((vm_name, ip))
                    
            if failed_vms:
                print(f"\n❌ {len(failed_vms)} VMs are not reachable:")
                for vm_name, ip in failed_vms:
                    print(f"   - {vm_name} ({ip})")
                return False
                
            print(f"✅ All {len(ips)} VMs are reachable via SSH")
            return True
            
        except (json.JSONDecodeError, KeyError) as e:
            print(f"❌ Failed to get VM information: {e}")
            return False
            
    def deploy_infrastructure(self):
        """Deploy infrastructure with Terraform, retrying if needed"""
        print("\n🏗️ Phase 1: Infrastructure Deployment")
        print("=" * 50)
        
        for attempt in range(1, self.max_retries + 1):
            print(f"\n📝 Deployment attempt {attempt}/{self.max_retries}")
            
            # Run Terraform apply with serial execution (parallelism=1)
            result = self.run_command(
                ["terraform", "apply", "-auto-approve", "-parallelism=1"],
                "Running Terraform apply (serial mode)",
                cwd=self.terraform_dir,
                check=False
            )
            
            if result.returncode != 0:
                print(f"⚠️ Terraform apply failed on attempt {attempt}")
                if attempt < self.max_retries:
                    print("   Retrying...")
                    time.sleep(10)
                    continue
                else:
                    print("❌ Maximum retries reached, aborting")
                    sys.exit(1)
                    
            # Verify all VMs were created
            if not self.verify_terraform_output():
                print(f"⚠️ Not all VMs created on attempt {attempt}")
                if attempt < self.max_retries:
                    print("   Running Terraform again to create missing VMs...")
                    continue
                else:
                    print("❌ Failed to create all VMs after maximum retries")
                    sys.exit(1)
                    
            # Wait for VMs to boot
            print("⏳ Waiting 30 seconds for VMs to boot...")
            time.sleep(30)
            
            # Test connectivity
            if self.test_vm_connectivity():
                print("✅ Infrastructure deployment completed successfully!")
                return
            else:
                print(f"⚠️ Some VMs not reachable on attempt {attempt}")
                if attempt < self.max_retries:
                    print("   Waiting 30 more seconds and retrying...")
                    time.sleep(30)
                    # Try connectivity test again
                    if self.test_vm_connectivity():
                        print("✅ All VMs now reachable!")
                        return
                    print("   Still having issues, will recreate infrastructure...")
                else:
                    print("❌ VMs not reachable after maximum retries")
                    sys.exit(1)
                    
        print("❌ Infrastructure deployment failed")
        sys.exit(1)
        
    def setup_kubespray(self):
        """Setup Kubespray environment"""
        print("\n📚 Phase 2: Kubespray Setup")
        print("=" * 50)
        
        # Clean up existing kubespray directory
        if self.kubespray_dir.exists():
            print("🗑️ Removing existing Kubespray directory...")
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
        
        print("✅ Kubespray setup completed")
        
    def apply_download_optimization(self):
        """Apply download optimization configuration to Kubespray"""
        print("🚀 Applying download optimization configuration...")
        
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
containerd_version: "1.7.8"

# Enable registry mirrors for faster downloads (optional)
# registry_host: "registry.example.com:5000"

# Download verification
download_validate_certs: true

# Concurrent downloads (adjust based on bandwidth)
download_concurrent: 3
"""
        
        download_yml_path = group_vars_dir / "download.yml"
        download_yml_path.write_text(download_config)
        print(f"   ✅ Created download optimization config: {download_yml_path}")
        
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
        print(f"   ✅ Created etcd optimization config: {etcd_yml_path}")
        
    def configure_kubespray(self):
        """Configure Kubespray for deployment"""
        print("\n⚙️ Phase 3: Kubespray Configuration")
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
            print("📋 Applying custom configuration...")
            
        # Apply patches
        patch_file = self.project_dir / "patches" / "kubespray-ansible-cfg.patch"
        if patch_file.exists():
            self.run_command(
                ["git", "apply", "--ignore-whitespace", str(patch_file)],
                "Applying ansible.cfg patch",
                cwd=self.kubespray_dir,
                check=False
            )
            
        print("✅ Kubespray configuration completed")
        
    def test_ansible_connectivity(self):
        """Test Ansible connectivity to all nodes"""
        print("\n🔌 Phase 4: Connectivity Test")
        print("=" * 50)
        
        ansible_path = self.venv_dir / "bin" / "ansible"
        inventory_file = self.kubespray_dir / "inventory" / "proxmox-cluster" / "inventory.ini"
        
        result = self.run_command(
            [str(ansible_path), "-i", str(inventory_file), "all", "-m", "ping"],
            "Testing Ansible connectivity",
            cwd=self.kubespray_dir,
            check=False
        )
        
        if result.returncode != 0:
            print("❌ Ansible connectivity test failed")
            print("   Please check SSH keys and network connectivity")
            sys.exit(1)
            
        print("✅ All nodes are reachable via Ansible")
        
    def deploy_kubernetes(self):
        """Deploy Kubernetes cluster with Kubespray"""
        print("\n☸️ Phase 5: Kubernetes Deployment")
        print("=" * 50)
        print("⏳ This will take 15-30 minutes...")
        
        ansible_playbook_path = self.venv_dir / "bin" / "ansible-playbook"
        inventory_file = self.kubespray_dir / "inventory" / "proxmox-cluster" / "inventory.ini"
        
        start_time = time.time()
        
        result = self.run_command(
            [str(ansible_playbook_path), "-i", str(inventory_file), "-b", "cluster.yml"],
            "Running Kubespray deployment",
            cwd=self.kubespray_dir,
            check=False
        )
        
        duration = int(time.time() - start_time)
        
        if result.returncode != 0:
            print(f"❌ Kubernetes deployment failed after {duration // 60}m {duration % 60}s")
            sys.exit(1)
            
        print(f"✅ Kubernetes deployment completed in {duration // 60}m {duration % 60}s")
        
    def setup_kubeconfig(self):
        """Setup kubeconfig for cluster access"""
        print("\n🔑 Phase 6: Kubeconfig Setup")
        print("=" * 50)
        
        ansible_path = self.venv_dir / "bin" / "ansible"
        inventory_file = self.kubespray_dir / "inventory" / "proxmox-cluster" / "inventory.ini"
        
        # Fetch kubeconfig
        self.run_command(
            [str(ansible_path), "-i", str(inventory_file),
             "kube_control_plane[0]", "-m", "fetch",
             "-a", "src=/etc/kubernetes/admin.conf dest=/tmp/kubeconfig flat=yes"],
            "Fetching kubeconfig from control plane",
            cwd=self.kubespray_dir
        )
        
        # Install kubeconfig
        kube_dir = Path.home() / ".kube"
        kube_dir.mkdir(exist_ok=True)
        
        kubeconfig_path = kube_dir / "config-k8s-proxmox"
        shutil.copy("/tmp/kubeconfig", kubeconfig_path)
        kubeconfig_path.chmod(0o600)
        
        print(f"✅ Kubeconfig installed at {kubeconfig_path}")
        print("💡 Set environment variable:")
        print(f"   export KUBECONFIG={kubeconfig_path}")
        
    def verify_cluster(self):
        """Verify Kubernetes cluster is working"""
        print("\n✔️ Phase 7: Cluster Verification")
        print("=" * 50)
        
        kubeconfig_path = Path.home() / ".kube" / "config-k8s-proxmox"
        
        if not kubeconfig_path.exists():
            print("❌ Kubeconfig not found")
            return False
            
        # Check nodes
        result = self.run_command(
            f"KUBECONFIG={kubeconfig_path} kubectl get nodes -o wide",
            "Checking cluster nodes",
            check=False
        )
        
        if result.returncode != 0:
            print("❌ Failed to get cluster nodes")
            return False
            
        # Check system pods
        self.run_command(
            f"KUBECONFIG={kubeconfig_path} kubectl get pods -A",
            "Checking system pods",
            check=False
        )
        
        # Get cluster info
        self.run_command(
            f"KUBECONFIG={kubeconfig_path} kubectl cluster-info",
            "Getting cluster info",
            check=False
        )
        
        print("✅ Cluster verification completed!")
        return True
        
    def run(self):
        """Run the complete deployment"""
        print("🚀 Fresh Kubernetes Cluster Deployment")
        print("=" * 50)
        print(f"Project Directory: {self.project_dir}")
        print(f"Terraform Directory: {self.terraform_dir}")
        print(f"Expected VMs: {self.vm_count}")
        print("=" * 50)
        
        # Phase -1: Manual cleanup
        self.manual_vm_cleanup()
        
        # Phase 0: Reset
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
        
        # Phase 7: Verify
        self.verify_cluster()
        
        print("\n" + "=" * 50)
        print("🎉 Fresh Kubernetes cluster deployment completed successfully!")
        print("=" * 50)
        print("\nNext steps:")
        print("1. Set KUBECONFIG: export KUBECONFIG=~/.kube/config-k8s-proxmox")
        print("2. Verify cluster: kubectl get nodes")
        print("3. Deploy applications: kubectl apply -f your-app.yaml")
        

def main():
    """Main entry point"""
    # Check if running from correct directory
    if not Path("terraform/kubernetes-cluster.tf").exists():
        print("❌ Must run from kubernetes-cluster root directory")
        sys.exit(1)
        
    deployer = ClusterDeployer()
    deployer.run()
    

if __name__ == "__main__":
    main()