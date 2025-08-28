#!/usr/bin/env python3
"""
Deploy Kubernetes cluster using Kubespray integration.
This script orchestrates the complete deployment workflow.
"""
import json
import subprocess
import sys
import time
from pathlib import Path


def run_command(command, description, cwd=None, check=True):
    """Run a command with proper error handling"""
    print(f"🔄 {description}...")
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=check,
            shell=isinstance(command, str)
        )
        if result.stdout:
            print(f"✅ {result.stdout.strip()}")
        return result
    except subprocess.CalledProcessError as e:
        print(f"❌ Error: {e}")
        if e.stderr:
            print(f"Stderr: {e.stderr}")
        if check:
            sys.exit(1)
        return e


def check_prerequisites():
    """Check if all prerequisites are met"""
    print("🔍 Checking prerequisites...")
    
    # Check if we're in the right directory
    if not Path("terraform").exists() or not Path("kubespray").exists():
        print("❌ Must run from kubernetes-cluster root directory")
        sys.exit(1)
    
    # Check if terraform state exists
    terraform_state = Path("terraform/terraform.tfstate")
    if not terraform_state.exists():
        print("❌ No Terraform state found. Deploy infrastructure first.")
        sys.exit(1)
    
    # Check if SSH key exists
    ssh_key = Path("/home/sysadmin/.ssh/sysladmin_automation_key")
    if not ssh_key.exists():
        print("❌ SSH key not found: /home/sysadmin/.ssh/sysladmin_automation_key")
        sys.exit(1)
    
    print("✅ Prerequisites check passed")


def generate_inventory():
    """Generate Kubespray inventory from Terraform output"""
    print("📋 Generating Kubespray inventory...")
    result = run_command(
        ["python3", "scripts/generate-kubespray-inventory.py"],
        "Generating inventory from Terraform state"
    )
    return result.returncode == 0


def install_kubespray_requirements():
    """Install Kubespray Python requirements"""
    print("📦 Installing Kubespray requirements...")
    kubespray_dir = Path("kubespray")
    
    # Check if requirements file exists
    requirements_file = kubespray_dir / "requirements.txt"
    if not requirements_file.exists():
        print("❌ Kubespray requirements.txt not found")
        return False
    
    run_command(
        ["pip3", "install", "-r", "requirements.txt"],
        "Installing Kubespray Python dependencies",
        cwd=kubespray_dir
    )
    return True


def test_connectivity():
    """Test SSH connectivity to all nodes"""
    print("🔗 Testing SSH connectivity to cluster nodes...")
    kubespray_dir = Path("kubespray")
    inventory_file = kubespray_dir / "inventory" / "proxmox-cluster" / "inventory.ini"
    
    result = run_command(
        ["ansible", "-i", str(inventory_file), "all", "-m", "ping"],
        "Testing connectivity to all nodes",
        cwd=kubespray_dir,
        check=False
    )
    
    if result.returncode != 0:
        print("❌ Connectivity test failed. Check SSH connectivity to nodes.")
        return False
    
    print("✅ All nodes are reachable")
    return True


def deploy_cluster():
    """Deploy Kubernetes cluster using Kubespray"""
    print("🚀 Deploying Kubernetes cluster with Kubespray...")
    kubespray_dir = Path("kubespray")
    inventory_file = kubespray_dir / "inventory" / "proxmox-cluster" / "inventory.ini"
    
    start_time = time.time()
    
    result = run_command(
        [
            "ansible-playbook", 
            "-i", str(inventory_file),
            "-b",
            "cluster.yml"
        ],
        "Deploying Kubernetes cluster (this may take 15-30 minutes)",
        cwd=kubespray_dir
    )
    
    end_time = time.time()
    deploy_duration = int(end_time - start_time)
    print(f"⏱️ Deployment completed in {deploy_duration // 60}m {deploy_duration % 60}s")
    
    return result.returncode == 0


def setup_kubeconfig():
    """Setup kubeconfig for cluster access"""
    print("🔑 Setting up kubeconfig...")
    
    # Source kubeconfig from first control plane node
    kubespray_dir = Path("kubespray")
    inventory_file = kubespray_dir / "inventory" / "proxmox-cluster" / "inventory.ini"
    
    # Get admin.conf from first control plane node
    result = run_command([
        "ansible", 
        "-i", str(inventory_file),
        "kube_control_plane[0]",
        "-m", "fetch",
        "-a", "src=/etc/kubernetes/admin.conf dest=/tmp/kubeconfig flat=yes"
    ], "Fetching kubeconfig from control plane", cwd=kubespray_dir, check=False)
    
    if result.returncode == 0:
        # Move to proper location
        kubeconfig_dir = Path.home() / ".kube"
        kubeconfig_dir.mkdir(exist_ok=True)
        
        run_command([
            "cp", "/tmp/kubeconfig", str(kubeconfig_dir / "config-k8s-proxmox")
        ], "Installing kubeconfig")
        
        # Set permissions
        run_command([
            "chmod", "600", str(kubeconfig_dir / "config-k8s-proxmox")
        ], "Setting kubeconfig permissions")
        
        print("✅ Kubeconfig installed at ~/.kube/config-k8s-proxmox")
        print("💡 Set KUBECONFIG environment variable:")
        print("   export KUBECONFIG=~/.kube/config-k8s-proxmox")
        
        return True
    
    return False


def verify_cluster():
    """Verify cluster deployment"""
    print("✅ Verifying cluster deployment...")
    
    kubeconfig_path = Path.home() / ".kube" / "config-k8s-proxmox"
    if not kubeconfig_path.exists():
        print("❌ Kubeconfig not found")
        return False
    
    env = {"KUBECONFIG": str(kubeconfig_path)}
    
    # Check nodes
    result = run_command(
        ["kubectl", "get", "nodes", "-o", "wide"],
        "Checking cluster nodes",
        check=False
    )
    
    if result.returncode != 0:
        print("❌ Failed to get cluster nodes")
        return False
    
    # Check system pods
    run_command(
        ["kubectl", "get", "pods", "-A", "--field-selector=status.phase!=Running"],
        "Checking for non-running pods",
        check=False
    )
    
    # Display cluster info
    run_command(
        ["kubectl", "cluster-info"],
        "Getting cluster info",
        check=False
    )
    
    print("🎉 Cluster verification completed!")
    return True


def main():
    """Main deployment workflow"""
    print("🚀 Starting Kubespray-based Kubernetes deployment for Proxmox")
    print("=" * 60)
    
    # Phase 1: Prerequisites
    check_prerequisites()
    
    # Phase 2: Generate inventory
    if not generate_inventory():
        print("❌ Failed to generate inventory")
        sys.exit(1)
    
    # Phase 3: Install requirements
    if not install_kubespray_requirements():
        print("❌ Failed to install requirements")
        sys.exit(1)
    
    # Phase 4: Test connectivity
    if not test_connectivity():
        print("❌ Connectivity test failed")
        sys.exit(1)
    
    # Phase 5: Deploy cluster
    if not deploy_cluster():
        print("❌ Cluster deployment failed")
        sys.exit(1)
    
    # Phase 6: Setup kubeconfig
    if not setup_kubeconfig():
        print("❌ Failed to setup kubeconfig")
        sys.exit(1)
    
    # Phase 7: Verify cluster
    if not verify_cluster():
        print("❌ Cluster verification failed")
        sys.exit(1)
    
    print("\n🎉 Kubernetes cluster deployment completed successfully!")
    print("=" * 60)
    print("Next steps:")
    print("1. Set KUBECONFIG: export KUBECONFIG=~/.kube/config-k8s-proxmox")
    print("2. Verify cluster: kubectl get nodes")
    print("3. Deploy applications: kubectl apply -f your-app.yaml")


if __name__ == "__main__":
    main()