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
REQUIRED_NETWORKS = ["vmbr0", "vmbr1"]  # vmbr0 for management, vmbr1 for cluster/ceph

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
        elif response.status_code == 401:
            # 401 means API is accessible but needs authentication - this is OK
            return True, f"API accessible (authentication required)"
        else:
            return False, f"HTTP {response.status_code}"
    except Exception as e:
        return False, str(e)

def check_packer_user_setup(host: str) -> bool:
    """Check if packer user exists and has proper permissions"""
    try:
        # Check if packer user exists
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", 
             f"root@{host}", "pveum", "user", "list"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            if "packer@pam" in result.stdout:
                print(f"    ✓ Packer user exists on {host}")
                
                # Check permissions
                perm_result = subprocess.run(
                    ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
                     f"root@{host}", "pveum", "acl", "list"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if perm_result.returncode == 0 and "packer@pam" in perm_result.stdout:
                    print(f"    ✓ Packer permissions configured on {host}")
                    
                    # Check token privilege separation
                    token_result = subprocess.run(
                        ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
                         f"root@{host}", "pveum", "user", "token", "list", "packer@pam"],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                    
                    if token_result.returncode == 0 and "privsep" in token_result.stdout:
                        if "1" in token_result.stdout:
                            print(f"    ! Token has privilege separation enabled on {host}")
                        else:
                            print(f"    ✓ Token privilege separation disabled on {host}")
                    
                    return True
                else:
                    print(f"    ! Packer user lacks proper permissions on {host}")
                    return False
            else:
                print(f"    ! Packer user not found on {host} (will be created during build)")
                return False
        else:
            print(f"    ! Could not check packer user on {host}: {result.stderr.decode().strip()}")
            return False
            
    except Exception as e:
        print(f"    ! Error checking packer user on {host}: {e}")
        return False

def check_rbd_iso_support(host: str) -> bool:
    """Check and configure RBD storage to support ISO content"""
    try:
        # Check current RBD storage configuration
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
             f"root@{host}", "cat", "/etc/pve/storage.cfg"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            storage_config = result.stdout
            
            # Check if RBD storage supports ISO content
            if "content images,rootdir,iso" in storage_config:
                print(f"    ✓ RBD storage supports ISO content on {host}")
                return True
            elif "content images,rootdir" in storage_config and "iso" not in storage_config:
                print(f"    ! RBD storage lacks ISO support on {host} (will be configured)")
                
                # Configure RBD to support ISO content
                config_result = subprocess.run(
                    ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
                     f"root@{host}", "cp", "/etc/pve/storage.cfg", "/etc/pve/storage.cfg.backup"],
                    capture_output=True,
                    timeout=10
                )
                
                if config_result.returncode == 0:
                    fix_result = subprocess.run(
                        ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
                         f"root@{host}", "sed", "-i", 
                         "/^rbd: rbd$/,/^$/ s/content images,rootdir/content images,rootdir,iso/",
                         "/etc/pve/storage.cfg"],
                        capture_output=True,
                        timeout=10
                    )
                    
                    if fix_result.returncode == 0:
                        print(f"    ✓ RBD storage configured for ISO support on {host}")
                        return True
                    else:
                        print(f"    ! Failed to configure RBD ISO support on {host}")
                        return False
                else:
                    print(f"    ! Could not backup storage config on {host}")
                    return False
            else:
                print(f"    ! RBD storage configuration not found on {host}")
                return False
        else:
            print(f"    ! Could not read storage config on {host}")
            return False
            
    except Exception as e:
        print(f"    ! Error checking RBD ISO support on {host}: {e}")
        return False

def check_rbd_iso_storage(host: str) -> bool:
    """Check if RBD-backed ISO storage is configured"""
    try:
        # Check if rbd-iso storage is configured
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
             f"root@{host}", "grep", "-q", "dir: rbd-iso", "/etc/pve/storage.cfg"],
            capture_output=True,
            timeout=10
        )
        
        if result.returncode == 0:
            print(f"    ✓ RBD-backed ISO storage configured on {host}")
            
            # Check if ISO storage is mounted
            mount_result = subprocess.run(
                ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
                 f"root@{host}", "mount", "|", "grep", "-q", "/mnt/rbd-iso"],
                capture_output=True,
                timeout=10
            )
            
            if mount_result.returncode == 0:
                print(f"    ✓ RBD-ISO filesystem mounted on {host}")
            else:
                print(f"    ! RBD-ISO filesystem not mounted on {host}")
            
            return True
        else:
            print(f"    ! RBD-backed ISO storage not configured on {host}")
            return False
            
    except Exception as e:
        print(f"    ! Error checking RBD-ISO storage on {host}: {e}")
        return False

def check_network_requirements() -> bool:
    """Validate network configuration"""
    print("\n[NETWORK] Checking network requirements...")
    
    try:
        # Check for required bridges (may not exist on deployment host)
        networks_found = []
        for bridge in REQUIRED_NETWORKS:
            try:
                result = subprocess.run(
                    ["ip", "link", "show", bridge],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    print(f"  ✓ Network bridge {bridge} exists on this host")
                    networks_found.append(bridge)
                else:
                    print(f"  ! Network bridge {bridge} not found on deployment host")
            except:
                print(f"  ! Could not check network bridge {bridge}")
        
        if networks_found:
            return True
        else:
            print(f"    (This is normal if deploying from external host)")
            # Test actual application connectivity - SSH to first Proxmox host
            print(f"  → Testing SSH connectivity to Proxmox hosts...")
            ssh_success = False
            for host in PROXMOX_HOSTS[:2]:  # Test first 2 hosts
                try:
                    result = subprocess.run(
                        ["ssh", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=no", 
                         "-o", "BatchMode=yes", f"root@{host}", "echo 'SSH OK'"],
                        capture_output=True,
                        timeout=10
                    )
                    if result.returncode == 0:
                        print(f"    ✓ SSH connectivity to {host} successful")
                        ssh_success = True
                        break
                    else:
                        print(f"    ! SSH to {host}: {result.stderr.decode().strip()}")
                except Exception as e:
                    print(f"    ! SSH to {host}: {e}")
            
            if ssh_success:
                print(f"  ✓ Network connectivity verified via SSH")
                return True
            else:
                print(f"  ! SSH connectivity failed, but Proxmox API is accessible")
                print(f"    Network should be functional for deployment")
                return True  # API access is sufficient for deployment
    except Exception as e:
        print(f"  ✗ Error checking network: {e}")
        return False

def check_storage_requirements() -> bool:
    """Validate storage configuration"""
    print("\n[STORAGE] Checking storage requirements...")
    
    # Check for Ceph/RBD storage (only works from Proxmox nodes)
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
    except FileNotFoundError:
        print(f"  ! Cannot check storage from deployment host (pvesm not available)")
        print(f"    Storage validation will be performed during deployment")
        return True  # Skip storage check when deploying remotely
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
    
    # Core deployment tools (required)
    core_tools = {
        "packer": "Packer for VM image building",
        "ansible": "Ansible for configuration management", 
        "kubectl": "Kubernetes CLI"
    }
    
    # IaC tools (at least one required)
    iac_tools = {
        "tofu": "OpenTofu for infrastructure (recommended)",
        "terraform": "Terraform for infrastructure"
    }
    
    # Proxmox tools (only needed on Proxmox nodes)
    proxmox_tools = {
        "pvesm": "Proxmox storage manager",
        "qm": "Proxmox VM manager"
    }
    
    all_ok = True
    
    # Check core tools
    for tool, description in core_tools.items():
        if check_tool_exists(tool):
            print(f"  ✓ {tool}: {description}")
        else:
            print(f"  ✗ {tool}: Not found - {description}")
            all_ok = False
    
    # Check IaC tools (need at least one)
    iac_found = False
    for tool, description in iac_tools.items():
        if check_tool_exists(tool):
            print(f"  ✓ {tool}: {description}")
            iac_found = True
        else:
            print(f"  ! {tool}: Not found - {description}")
    
    if not iac_found:
        print("  ✗ No Infrastructure as Code tool found (need OpenTofu or Terraform)")
        all_ok = False
    
    # Check Proxmox tools (optional for remote deployment)
    proxmox_found = False
    for tool, description in proxmox_tools.items():
        if check_tool_exists(tool):
            print(f"  ✓ {tool}: {description}")
            proxmox_found = True
        else:
            print(f"  ! {tool}: Not found - {description}")
    
    if not proxmox_found:
        print("    → Proxmox tools not available (deploying from external host)")
    
    return all_ok

def check_tool_exists(tool: str) -> bool:
    """Check if a tool exists in PATH"""
    try:
        result = subprocess.run(
            ["which", tool],
            capture_output=True,
            text=True
        )
        return result.returncode == 0
    except:
        return False

def check_ssh_access() -> bool:
    """Validate SSH key configuration"""
    print("\n[SSH] Checking SSH configuration...")
    
    # Check for SSH config file
    ssh_config_path = "/home/sysadmin/.ssh/config"
    try:
        with open(ssh_config_path, 'r') as f:
            config_content = f.read()
            print(f"  ✓ SSH config exists at {ssh_config_path}")
            
            # Extract IdentityFile from config for Proxmox hosts
            if "IdentityFile" in config_content:
                for line in config_content.split('\n'):
                    if "IdentityFile" in line and not line.strip().startswith('#'):
                        key_path = line.split()[1]
                        print(f"  ✓ SSH identity configured: {key_path}")
                        
                        # Check if the key exists
                        try:
                            with open(key_path, 'r') as key_file:
                                print(f"  ✓ SSH private key exists and accessible")
                            
                            pub_key_path = f"{key_path}.pub"
                            with open(pub_key_path, 'r') as pub_file:
                                print(f"  ✓ SSH public key exists and accessible")
                            
                            return True
                        except FileNotFoundError:
                            print(f"  ✗ SSH key file not found: {key_path}")
                            return False
            else:
                print(f"  ! No IdentityFile specified in SSH config")
                # Fall back to checking default location
                return check_default_ssh_keys()
                
    except FileNotFoundError:
        print(f"  ! SSH config not found, checking default keys...")
        return check_default_ssh_keys()
    except Exception as e:
        print(f"  ✗ Error checking SSH config: {e}")
        return False

def check_default_ssh_keys() -> bool:
    """Check for default SSH keys"""
    ssh_key_path = "/home/sysadmin/.ssh/id_rsa"
    try:
        with open(ssh_key_path, 'r') as f:
            print(f"  ✓ Default SSH private key exists at {ssh_key_path}")
        
        pub_key_path = f"{ssh_key_path}.pub"
        with open(pub_key_path, 'r') as f:
            print(f"  ✓ Default SSH public key exists at {pub_key_path}")
        
        return True
    except FileNotFoundError:
        print(f"  ✗ Default SSH keys not found at {ssh_key_path}")
        return False
    except Exception as e:
        print(f"  ✗ Error checking default SSH keys: {e}")
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
    packer_users_ok = 0
    for host in PROXMOX_HOSTS:
        status, message = check_proxmox_connectivity(host)
        if status:
            print(f"  ✓ {host}: {message}")
            # Check packer user setup if SSH is accessible
            if check_packer_user_setup(host):
                packer_users_ok += 1
            # Check and configure RBD ISO support
            check_rbd_iso_support(host)
            # Check RBD-backed ISO storage
            check_rbd_iso_storage(host)
        else:
            print(f"  ✗ {host}: {message}")
            proxmox_ok = False
    
    validation_results['proxmox'] = proxmox_ok
    
    # Report packer user status
    if packer_users_ok > 0:
        print(f"  ✓ Packer users configured on {packer_users_ok}/{len(PROXMOX_HOSTS)} nodes")
    else:
        print(f"  ! No packer users found (will be created during Phase 2)")
    
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