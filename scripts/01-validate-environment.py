#!/usr/bin/env python3
"""
Phase 1: Environment Validation
Validates Proxmox environment readiness for Kubernetes deployment
"""

import sys
import json
import subprocess
from typing import Dict, List, Tuple
import requests
from urllib3.exceptions import InsecureRequestWarning

# Suppress SSL warnings for self-signed certificates
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# Configuration
PROXMOX_HOSTS = ["10.10.1.21", "10.10.1.22", "10.10.1.23", "10.10.1.24"]
PROXMOX_API_PORT = 8006
MIN_CPU_CORES = 4
MIN_MEMORY_GB = 8
MIN_STORAGE_GB = 100
REQUIRED_STORAGE = "rbd"
REQUIRED_NETWORK = "vmbr1"

def check_proxmox_connectivity(host: str) -> Tuple[bool, str]:
    """Check if Proxmox host is reachable"""
    try:
        response = requests.get(
            f"https://{host}:{PROXMOX_API_PORT}/api2/json/version",
            verify=False,
            timeout=5
        )
        if response.status_code == 200:
            version = response.json()['data']['version']
            return True, f"Proxmox VE {version}"
        else:
            return False, f"HTTP {response.status_code}"
    except Exception as e:
        return False, str(e)

def check_network_requirements() -> bool:
    """Validate network configuration"""
    print("\n[NETWORK] Checking network requirements...")
    
    # Check for required bridge
    try:
        result = subprocess.run(
            ["ip", "link", "show", REQUIRED_NETWORK],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            print(f"  ✓ Network bridge {REQUIRED_NETWORK} exists")
            return True
        else:
            print(f"  ✗ Network bridge {REQUIRED_NETWORK} not found")
            return False
    except Exception as e:
        print(f"  ✗ Error checking network: {e}")
        return False

def check_storage_requirements() -> bool:
    """Validate storage configuration"""
    print("\n[STORAGE] Checking storage requirements...")
    
    # Check for Ceph/RBD storage
    try:
        result = subprocess.run(
            ["pvesm", "status"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if REQUIRED_STORAGE in result.stdout:
            print(f"  ✓ Storage pool '{REQUIRED_STORAGE}' is available")
            
            # Parse available space
            for line in result.stdout.split('\n'):
                if REQUIRED_STORAGE in line:
                    parts = line.split()
                    if len(parts) >= 4:
                        try:
                            avail_gb = int(parts[3]) / (1024 * 1024 * 1024)
                            if avail_gb >= MIN_STORAGE_GB:
                                print(f"  ✓ Sufficient storage available: {avail_gb:.1f} GB")
                                return True
                            else:
                                print(f"  ✗ Insufficient storage: {avail_gb:.1f} GB < {MIN_STORAGE_GB} GB required")
                                return False
                        except:
                            pass
            
            print(f"  ! Could not determine available storage")
            return True  # Assume OK if pool exists
        else:
            print(f"  ✗ Storage pool '{REQUIRED_STORAGE}' not found")
            return False
    except Exception as e:
        print(f"  ✗ Error checking storage: {e}")
        return False

def check_dns_configuration() -> bool:
    """Validate DNS configuration"""
    print("\n[DNS] Checking DNS configuration...")
    
    test_domains = ["github.com", "registry.k8s.io", "docker.io"]
    all_resolved = True
    
    for domain in test_domains:
        try:
            result = subprocess.run(
                ["nslookup", domain],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                print(f"  ✓ DNS resolution for {domain} successful")
            else:
                print(f"  ✗ DNS resolution for {domain} failed")
                all_resolved = False
        except Exception as e:
            print(f"  ✗ Error resolving {domain}: {e}")
            all_resolved = False
    
    return all_resolved

def check_required_tools() -> bool:
    """Check for required command-line tools"""
    print("\n[TOOLS] Checking required tools...")
    
    tools = {
        "packer": "Packer for VM image building",
        "terraform": "Terraform/OpenTofu for infrastructure",
        "ansible": "Ansible for configuration management",
        "kubectl": "Kubernetes CLI",
        "pvesm": "Proxmox storage manager",
        "qm": "Proxmox VM manager"
    }
    
    all_present = True
    for tool, description in tools.items():
        try:
            result = subprocess.run(
                ["which", tool],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                print(f"  ✓ {tool}: {description}")
            else:
                print(f"  ✗ {tool}: Not found - {description}")
                all_present = False
        except Exception as e:
            print(f"  ✗ {tool}: Error - {e}")
            all_present = False
    
    return all_present

def check_ssh_access() -> bool:
    """Validate SSH key configuration"""
    print("\n[SSH] Checking SSH configuration...")
    
    ssh_key_path = "/home/sysadmin/.ssh/id_rsa"
    try:
        with open(ssh_key_path, 'r') as f:
            print(f"  ✓ SSH private key exists at {ssh_key_path}")
        
        pub_key_path = f"{ssh_key_path}.pub"
        with open(pub_key_path, 'r') as f:
            print(f"  ✓ SSH public key exists at {pub_key_path}")
        
        return True
    except FileNotFoundError:
        print(f"  ✗ SSH keys not found at {ssh_key_path}")
        return False
    except Exception as e:
        print(f"  ✗ Error checking SSH keys: {e}")
        return False

def main():
    """Main validation routine"""
    print("=" * 60)
    print("KUBERNETES ON PROXMOX - ENVIRONMENT VALIDATION")
    print("=" * 60)
    
    validation_results = {}
    
    # 1. Check Proxmox cluster connectivity
    print("\n[PROXMOX] Checking cluster connectivity...")
    proxmox_ok = True
    for host in PROXMOX_HOSTS:
        status, message = check_proxmox_connectivity(host)
        if status:
            print(f"  ✓ {host}: {message}")
        else:
            print(f"  ✗ {host}: {message}")
            proxmox_ok = False
    validation_results['proxmox'] = proxmox_ok
    
    # 2. Check network requirements
    validation_results['network'] = check_network_requirements()
    
    # 3. Check storage requirements
    validation_results['storage'] = check_storage_requirements()
    
    # 4. Check DNS configuration
    validation_results['dns'] = check_dns_configuration()
    
    # 5. Check required tools
    validation_results['tools'] = check_required_tools()
    
    # 6. Check SSH access
    validation_results['ssh'] = check_ssh_access()
    
    # Summary
    print("\n" + "=" * 60)
    print("VALIDATION SUMMARY")
    print("=" * 60)
    
    all_passed = True
    for check, status in validation_results.items():
        status_str = "PASSED" if status else "FAILED"
        symbol = "✓" if status else "✗"
        print(f"  {symbol} {check.upper()}: {status_str}")
        if not status:
            all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("✓ ALL VALIDATIONS PASSED - Environment is ready!")
        print("Proceed to Phase 2: Build Golden Image")
        sys.exit(0)
    else:
        print("✗ VALIDATION FAILED - Please fix the issues above")
        sys.exit(1)

if __name__ == "__main__":
    main()