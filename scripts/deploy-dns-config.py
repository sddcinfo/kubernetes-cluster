#!/usr/bin/env python3
"""
Deploy DNS Configuration for Kubernetes Cluster
Deploys Kubernetes DNS configuration using desired state approach - 
existing configuration is always overwritten from source control.
"""

import subprocess
import sys
import argparse
from pathlib import Path
from datetime import datetime
import socket
import time

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

class DNSDeployer:
    """DNS configuration deployment using desired state approach"""
    
    def __init__(self, dns_server: str = "10.10.1.1"):
        self.dns_server = dns_server
        self.config_source = Path("configs/dnsmasq.d/kubernetes.conf")
        self.config_target = Path("/etc/dnsmasq.d/kubernetes.conf")
        self.test_records = [
            "k8s-vip.sddc.info",
            "k8s-control-1.sddc.info", 
            "k8s-worker-1.sddc.info",
            "ingress.k8s.sddc.info"
        ]
    
    def run_command(self, cmd: str, check: bool = True, capture_output: bool = True) -> subprocess.CompletedProcess:
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
    
    def check_connectivity(self) -> bool:
        """Test connectivity to DNS server"""
        log_step("Testing connectivity to DNS server...")
        
        try:
            # Use socket for more reliable connectivity test
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((self.dns_server, 22))  # SSH port
            sock.close()
            
            if result == 0:
                log_info(f"DNS server {self.dns_server} is reachable")
                return True
            else:
                # Try ping as fallback
                result = self.run_command(f"ping -c 1 -W 3 {self.dns_server}", check=False, capture_output=True)
                if result.returncode == 0:
                    log_info(f"DNS server {self.dns_server} is reachable (ping)")
                    return True
                else:
                    log_error(f"Cannot reach DNS server at {self.dns_server}")
                    return False
                    
        except Exception as e:
            log_error(f"Connectivity test failed: {e}")
            return False
    
    def validate_source_config(self) -> bool:
        """Validate source configuration file exists and has content"""
        log_step("Validating source configuration...")
        
        if not self.config_source.exists():
            log_error(f"Source DNS configuration not found: {self.config_source}")
            return False
        
        # Check if file has reasonable content
        content = self.config_source.read_text()
        if len(content.strip()) < 100:  # Minimum reasonable size
            log_error(f"Source configuration appears empty or too small")
            return False
        
        # Check for key records
        required_records = ["k8s-vip", "k8s-control-1", "k8s-worker-1"]
        missing_records = []
        
        for record in required_records:
            if record not in content:
                missing_records.append(record)
        
        if missing_records:
            log_error(f"Missing required DNS records: {', '.join(missing_records)}")
            return False
        
        log_info(f"Source configuration validated: {self.config_source}")
        return True
    
    def ensure_clean_deployment(self) -> bool:
        """Ensure clean deployment environment (desired state approach)"""
        log_step("Preparing clean deployment environment...")
        
        try:
            # Remove any backup files that might cause conflicts
            result = self.run_command(f"sudo rm -f {self.config_target}.backup.*", check=False)
            
            if self.config_target.exists():
                log_info("Existing configuration will be overwritten (desired state)")
            else:
                log_info("No existing configuration found - clean deployment")
            
            return True
            
        except Exception as e:
            log_error(f"Environment preparation failed: {e}")
            return False
    
    def deploy_configuration(self) -> bool:
        """Deploy new DNS configuration"""
        log_step("Deploying new Kubernetes DNS configuration...")
        
        try:
            # Copy configuration
            result = self.run_command(f"sudo cp {self.config_source} {self.config_target}")
            if result.returncode != 0:
                log_error("Failed to copy configuration file")
                return False
            
            # Set permissions
            self.run_command(f"sudo chmod 644 {self.config_target}")
            self.run_command(f"sudo chown root:root {self.config_target}")
            
            log_info(f"Configuration deployed to {self.config_target}")
            return True
            
        except Exception as e:
            log_error(f"Configuration deployment failed: {e}")
            return False
    
    def validate_dnsmasq_config(self) -> bool:
        """Validate dnsmasq configuration syntax"""
        log_step("Validating dnsmasq configuration syntax...")
        
        try:
            result = self.run_command(
                "sudo dnsmasq --test --conf-file=/etc/dnsmasq.conf --conf-dir=/etc/dnsmasq.d",
                check=False,
                capture_output=True
            )
            
            if result.returncode == 0:
                log_info("Configuration syntax is valid")
                return True
            else:
                log_error("Configuration syntax is invalid!")
                log_error(f"dnsmasq test output: {result.stderr}")
                
                # Show detailed error
                self.run_command(
                    "sudo dnsmasq --test --conf-file=/etc/dnsmasq.conf --conf-dir=/etc/dnsmasq.d",
                    check=False,
                    capture_output=False
                )
                return False
                
        except Exception as e:
            log_error(f"Configuration validation failed: {e}")
            return False
    
    def manage_dnsmasq_service(self) -> bool:
        """Start or reload dnsmasq service"""
        log_step("Managing dnsmasq service...")
        
        try:
            # Check if dnsmasq is running
            result = self.run_command("systemctl is-active dnsmasq", check=False, capture_output=True)
            
            if result.returncode == 0:
                log_info("dnsmasq service is running")
                
                # Always restart to ensure new configuration is loaded
                log_step("Restarting dnsmasq service...")
                result = self.run_command("sudo systemctl restart dnsmasq", check=False)
                
                if result.returncode == 0:
                    log_info("dnsmasq service restarted successfully")
                    # Give it a moment to fully restart
                    time.sleep(3)
                    return True
                else:
                    log_error("Failed to restart dnsmasq service")
                    return False
            else:
                log_warning("dnsmasq service is not running")
                log_step("Starting dnsmasq service...")
                result = self.run_command("sudo systemctl start dnsmasq", check=False)
                
                if result.returncode == 0:
                    log_info("dnsmasq service started successfully")
                    time.sleep(3)
                    return True
                else:
                    log_error("Failed to start dnsmasq service")
                    return False
                    
        except Exception as e:
            log_error(f"Service management failed: {e}")
            return False
    
    def test_dns_resolution(self) -> bool:
        """Test DNS resolution for key records"""
        log_step("Testing DNS resolution...")
        
        all_tests_passed = True
        
        for record in self.test_records:
            try:
                result = self.run_command(
                    f"nslookup {record} {self.dns_server}",
                    check=False,
                    capture_output=True
                )
                
                if result.returncode == 0 and "NXDOMAIN" not in result.stdout:
                    log_info(f"✓ DNS resolution working for {record}")
                else:
                    log_warning(f"✗ DNS resolution failed for {record}")
                    all_tests_passed = False
                    
            except Exception as e:
                log_warning(f"✗ DNS test failed for {record}: {e}")
                all_tests_passed = False
        
        return all_tests_passed
    
    def deploy(self, skip_tests: bool = False) -> bool:
        """Execute complete DNS deployment process"""
        print("=" * 60)
        print("DEPLOYING KUBERNETES DNS CONFIGURATION")
        print("=" * 60)
        
        steps = [
            ("Source Configuration Validation", self.validate_source_config),
            ("DNS Server Connectivity", self.check_connectivity),
            ("Clean Deployment Environment", self.ensure_clean_deployment),
            ("Configuration Deployment", self.deploy_configuration),
            ("DNSmasq Syntax Validation", self.validate_dnsmasq_config),
            ("DNSmasq Service Management", self.manage_dnsmasq_service),
        ]
        
        # Execute main deployment steps
        for step_name, step_func in steps:
            print(f"\n{Colors.BLUE}--- {step_name} ---{Colors.NC}")
            if not step_func():
                log_error(f"Failed at step: {step_name}")
                return False
        
        # DNS resolution testing (optional)
        if not skip_tests:
            print(f"\n{Colors.BLUE}--- DNS Resolution Testing ---{Colors.NC}")
            dns_tests_passed = self.test_dns_resolution()
        else:
            log_info("Skipping DNS resolution tests")
            dns_tests_passed = True
        
        # Summary
        print("\n" + "=" * 60)
        if dns_tests_passed:
            log_info("✓ DNS CONFIGURATION DEPLOYMENT COMPLETED SUCCESSFULLY")
        else:
            log_warning("⚠ DNS CONFIGURATION DEPLOYED WITH SOME RESOLUTION ISSUES")
        
        print("=" * 60)
        print(f"Configuration file: {self.config_target}")
        print(f"DNS server: {self.dns_server}")
        print(f"Test with: nslookup k8s-vip.sddc.info {self.dns_server}")
        print("=" * 60)
        
        return True

def main():
    """Main entry point with argument parsing"""
    parser = argparse.ArgumentParser(description="Deploy Kubernetes DNS Configuration")
    parser.add_argument("--dns-server", default="10.10.1.1",
                       help="DNS server IP address (default: 10.10.1.1)")
    parser.add_argument("--skip-tests", action="store_true",
                       help="Skip DNS resolution tests")
    parser.add_argument("--dry-run", action="store_true",
                       help="Validate configuration without deploying")
    
    args = parser.parse_args()
    
    deployer = DNSDeployer(args.dns_server)
    
    if args.dry_run:
        log_info("Dry run mode - validating configuration only")
        success = deployer.validate_source_config() and deployer.check_connectivity()
        if success:
            log_info("✓ Configuration validation passed")
        else:
            log_error("✗ Configuration validation failed")
        sys.exit(0 if success else 1)
    
    try:
        success = deployer.deploy(skip_tests=args.skip_tests)
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        log_warning("Deployment interrupted by user")
        sys.exit(1)
    except Exception as e:
        log_error(f"Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()