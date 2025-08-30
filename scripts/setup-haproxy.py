#!/usr/bin/env python3
"""
HAProxy Setup Script for Kubernetes Cluster
Automates HAProxy installation and configuration for API server load balancing
"""
import subprocess
import sys
import time
from pathlib import Path


class HAProxySetup:
    def __init__(self, haproxy_ip="10.10.1.30"):
        self.haproxy_ip = haproxy_ip
        self.project_dir = Path(__file__).parent.parent
        self.haproxy_config_path = self.project_dir / "configs" / "haproxy.cfg"
        self.ssh_key = "/home/sysadmin/.ssh/sysadmin_automation_key"
        
    def run_command(self, command, description, check=True, timeout=30):
        """Run a command with proper error handling"""
        print(f"-> {description}...")
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                check=False,  # Don't raise exception, let us handle it
                timeout=timeout
            )
            
            if result.stdout and not result.stdout.isspace():
                print(f"   {result.stdout.strip()}")
            
            if result.returncode != 0:
                if result.stderr:
                    print(f"   Error: {result.stderr.strip()}")
                if check:
                    raise subprocess.CalledProcessError(result.returncode, command)
                    
            return result
            
        except subprocess.TimeoutExpired:
            print(f"   Command timed out after {timeout} seconds")
            if check:
                sys.exit(1)
            return None
        except subprocess.CalledProcessError as e:
            if check:
                print(f"   Command failed: {e}")
                sys.exit(1)
            return e
            
    def test_connectivity(self):
        """Test SSH connectivity to HAProxy VM"""
        print(f"Testing connectivity to HAProxy VM at {self.haproxy_ip}...")
        
        result = self.run_command(
            f"timeout 5 ssh -o StrictHostKeyChecking=no -o ConnectTimeout=3 -i {self.ssh_key} sysadmin@{self.haproxy_ip} 'hostname && echo Connected'",
            f"Testing SSH connectivity to {self.haproxy_ip}",
            check=False
        )
        
        if result and result.returncode == 0:
            print(f"   Successfully connected to HAProxy VM")
            return True
        else:
            print(f"   Failed to connect to HAProxy VM at {self.haproxy_ip}")
            print("   Please ensure:")
            print("   1. VM is running")
            print("   2. SSH service is active") 
            print("   3. SSH key is configured")
            return False
            
    def install_haproxy(self):
        """Install HAProxy on the target VM"""
        print("Installing HAProxy...")
        
        # Check if HAProxy is already installed
        result = self.run_command(
            f"ssh -o StrictHostKeyChecking=no -i {self.ssh_key} sysadmin@{self.haproxy_ip} 'dpkg -l | grep haproxy || echo not-installed'",
            "Checking if HAProxy is already installed",
            check=False
        )
        
        if result and result.returncode == 0 and "not-installed" not in result.stdout:
            print("   HAProxy is already installed")
            return True
        
        # Update package cache and install HAProxy
        result = self.run_command(
            f"ssh -o StrictHostKeyChecking=no -i {self.ssh_key} sysadmin@{self.haproxy_ip} 'sudo apt update && sudo apt install -y haproxy'",
            "Installing HAProxy package",
            timeout=120  # Extended timeout for package installation
        )
        
        if result.returncode == 0:
            print("   HAProxy installed successfully")
            return True
        else:
            print("   Failed to install HAProxy")
            return False
            
    def deploy_configuration(self):
        """Deploy HAProxy configuration to the target VM"""
        print("Deploying HAProxy configuration...")
        
        # Check if config file exists
        if not self.haproxy_config_path.exists():
            print(f"   HAProxy config file not found: {self.haproxy_config_path}")
            print("   Creating default configuration...")
            self.create_default_config()
        
        # Check if configuration needs updating by comparing with existing
        result = self.run_command(
            f"ssh -o StrictHostKeyChecking=no -i {self.ssh_key} sysadmin@{self.haproxy_ip} 'sudo test -f /etc/haproxy/haproxy.cfg && echo exists || echo missing'",
            "Checking existing HAProxy configuration",
            check=False
        )
        
        config_exists = result and result.returncode == 0 and "exists" in result.stdout
        
        if config_exists:
            print("   HAProxy configuration already exists, checking if update needed...")
            
            # Get checksum of local config
            local_checksum = subprocess.run(
                ["sha256sum", str(self.haproxy_config_path)],
                capture_output=True, text=True
            ).stdout.split()[0]
            
            # Get checksum of remote config
            remote_result = self.run_command(
                f"ssh -o StrictHostKeyChecking=no -i {self.ssh_key} sysadmin@{self.haproxy_ip} 'sudo sha256sum /etc/haproxy/haproxy.cfg'",
                "Getting remote configuration checksum",
                check=False
            )
            
            if remote_result and remote_result.returncode == 0:
                remote_checksum = remote_result.stdout.split()[0]
                if local_checksum == remote_checksum:
                    print("   HAProxy configuration is up to date, no changes needed")
                    return True
                else:
                    print("   HAProxy configuration differs, updating...")
            
        # Copy configuration to VM
        result = self.run_command(
            f"scp -o StrictHostKeyChecking=no -i {self.ssh_key} {self.haproxy_config_path} sysadmin@{self.haproxy_ip}:/tmp/haproxy.cfg",
            "Copying HAProxy configuration"
        )
        
        # Deploy configuration and restart service
        result = self.run_command(
            f"ssh -o StrictHostKeyChecking=no -i {self.ssh_key} sysadmin@{self.haproxy_ip} 'sudo cp /tmp/haproxy.cfg /etc/haproxy/haproxy.cfg && sudo sh -c \"echo >> /etc/haproxy/haproxy.cfg\"'",
            "Deploying configuration file"
        )
        
        if result.returncode == 0:
            print("   HAProxy configuration deployed successfully")
            return True
        else:
            print("   Failed to deploy HAProxy configuration")
            return False
            
    def validate_configuration(self):
        """Validate HAProxy configuration syntax"""
        print("Validating HAProxy configuration...")
        
        result = self.run_command(
            f"ssh -o StrictHostKeyChecking=no -i {self.ssh_key} sysadmin@{self.haproxy_ip} 'sudo haproxy -f /etc/haproxy/haproxy.cfg -c'",
            "Validating HAProxy configuration syntax",
            check=False
        )
        
        if result.returncode == 0:
            print("   HAProxy configuration is valid")
            return True
        else:
            print("   HAProxy configuration validation failed")
            return False
            
    def start_haproxy_service(self):
        """Start and enable HAProxy service"""
        print("Starting HAProxy service...")
        
        # Check if service is already running
        result = self.run_command(
            f"ssh -o StrictHostKeyChecking=no -i {self.ssh_key} sysadmin@{self.haproxy_ip} 'sudo systemctl is-active haproxy || echo inactive'",
            "Checking HAProxy service status",
            check=False
        )
        
        if result and result.returncode == 0 and "active" in result.stdout:
            print("   HAProxy service is already running")
            # Restart to apply any config changes
            result = self.run_command(
                f"ssh -o StrictHostKeyChecking=no -i {self.ssh_key} sysadmin@{self.haproxy_ip} 'sudo systemctl restart haproxy'",
                "Restarting HAProxy service to apply configuration changes"
            )
        else:
            # Enable and start service
            result = self.run_command(
                f"ssh -o StrictHostKeyChecking=no -i {self.ssh_key} sysadmin@{self.haproxy_ip} 'sudo systemctl enable haproxy && sudo systemctl start haproxy'",
                "Starting HAProxy service"
            )
        
        if result.returncode == 0:
            print("   HAProxy service started successfully")
            return True
        else:
            print("   Failed to start HAProxy service")
            return False
            
    def verify_service_status(self):
        """Verify HAProxy service is running and listening"""
        print("Verifying HAProxy service status...")
        
        # Check systemd service status
        result = self.run_command(
            f"ssh -o StrictHostKeyChecking=no -i {self.ssh_key} sysadmin@{self.haproxy_ip} 'sudo systemctl is-active haproxy'",
            "Checking HAProxy service status",
            check=False
        )
        
        if result and "active" in result.stdout:
            print("   HAProxy service is active")
        else:
            print("   HAProxy service is not active")
            return False
            
        # Check listening ports
        result = self.run_command(
            f"ssh -o StrictHostKeyChecking=no -i {self.ssh_key} sysadmin@{self.haproxy_ip} 'sudo lsof -i :6443 -i :8080'",
            "Checking HAProxy listening ports",
            check=False
        )
        
        if result and result.returncode == 0 and "haproxy" in result.stdout:
            print("   HAProxy is listening on required ports (6443, 8080)")
            return True
        else:
            print("   HAProxy is not listening on required ports")
            return False
            
    def test_load_balancer(self):
        """Test load balancer functionality"""
        print("Testing load balancer functionality...")
        
        # Test API access through HAProxy
        result = self.run_command(
            f"curl -k --connect-timeout 10 -s https://{self.haproxy_ip}:6443/version",
            "Testing Kubernetes API access through HAProxy",
            check=False,
            timeout=15
        )
        
        if result and result.returncode == 0:
            print("   Kubernetes API accessible through HAProxy")
            if "gitVersion" in result.stdout:
                print(f"   API response received successfully")
                return True
        else:
            print("   Failed to access Kubernetes API through HAProxy")
            return False
            
    def get_haproxy_stats(self):
        """Display HAProxy backend stats"""
        print("Checking HAProxy backend status...")
        
        result = self.run_command(
            f"curl -s http://{self.haproxy_ip}:8080/stats | grep -E 'k8s-control-[123].*UP|k8s-control-[123].*DOWN' || echo 'Stats not accessible'",
            "Fetching HAProxy backend status",
            check=False
        )
        
        if result and result.returncode == 0:
            lines = result.stdout.split('\n')
            backend_count = 0
            for line in lines:
                if 'k8s-control-' in line:
                    backend_count += 1
                    if 'UP' in line:
                        print(f"   Backend node is UP")
                    elif 'DOWN' in line:
                        print(f"   Backend node is DOWN")
                        
            if backend_count > 0:
                print(f"   Found {backend_count} backend nodes in stats")
                return True
        
        print("   Could not retrieve backend status")
        return False
        
    def create_default_config(self):
        """Create default HAProxy configuration if none exists"""
        default_config = """global
    daemon
    user haproxy
    group haproxy
    log stdout local0 info
    chroot /var/lib/haproxy
    stats socket /run/haproxy/admin.sock mode 660 level admin
    stats timeout 30s

defaults
    mode                    http
    log                     global
    option                  httplog
    option                  dontlognull
    option                  http-server-close
    option                  forwardfor       except 127.0.0.0/8
    option                  redispatch
    retries                 3
    timeout http-request    10s
    timeout queue           1m
    timeout connect         10s
    timeout client          1m
    timeout server          1m
    timeout http-keep-alive 10s
    timeout check           10s
    maxconn                 3000

# Kubernetes API Server Frontend
frontend k8s_api_frontend
    bind *:6443
    mode tcp
    option tcplog
    default_backend k8s_api_backend

# Kubernetes API Server Backend
backend k8s_api_backend
    mode tcp
    balance roundrobin
    option tcp-check
    server k8s-control-1 10.10.1.31:6443 check inter 2000 rise 2 fall 3
    server k8s-control-2 10.10.1.32:6443 check inter 2000 rise 2 fall 3
    server k8s-control-3 10.10.1.33:6443 check inter 2000 rise 2 fall 3

# HAProxy Stats (optional)
frontend stats
    bind *:8080
    stats enable
    stats uri /stats
    stats refresh 10s
    stats admin if TRUE
"""
        
        self.haproxy_config_path.write_text(default_config)
        print(f"   Created default HAProxy configuration at {self.haproxy_config_path}")
        
    def setup_haproxy(self):
        """Main setup method - run all setup steps"""
        print("=" * 60)
        print("HAProxy Setup for Kubernetes Cluster Load Balancing")
        print("=" * 60)
        print(f"Target HAProxy VM: {self.haproxy_ip}")
        print()
        
        # Step 1: Test connectivity
        if not self.test_connectivity():
            print("\n[FAILED] HAProxy setup failed - connectivity issue")
            return False
            
        # Step 2: Install HAProxy
        if not self.install_haproxy():
            print("\n[FAILED] HAProxy setup failed - installation failed")
            return False
            
        # Step 3: Deploy configuration
        if not self.deploy_configuration():
            print("\n[FAILED] HAProxy setup failed - configuration deployment failed")
            return False
            
        # Step 4: Validate configuration
        if not self.validate_configuration():
            print("\n[FAILED] HAProxy setup failed - configuration validation failed")
            return False
            
        # Step 5: Start service
        if not self.start_haproxy_service():
            print("\n[FAILED] HAProxy setup failed - service startup failed")
            return False
            
        # Step 6: Verify service
        if not self.verify_service_status():
            print("\n[FAILED] HAProxy setup failed - service verification failed")
            return False
            
        # Wait for service to fully initialize
        print("Waiting 5 seconds for HAProxy to fully initialize...")
        time.sleep(5)
        
        # Step 7: Test load balancer
        if not self.test_load_balancer():
            print("\n[WARNING] HAProxy setup completed but load balancer test failed")
            print("   This may be normal if Kubernetes cluster is not fully ready")
            print("   HAProxy will work once all control plane nodes are available")
        else:
            print("\n[SUCCESS] HAProxy load balancer test successful")
            
        # Step 8: Show stats
        self.get_haproxy_stats()
        
        print("\n" + "=" * 60)
        print("[SUCCESS] HAProxy Setup Complete!")
        print("=" * 60)
        print(f"HAProxy VIP: {self.haproxy_ip}")
        print(f"Kubernetes API: https://{self.haproxy_ip}:6443")
        print(f"HAProxy Stats: http://{self.haproxy_ip}:8080/stats")
        print("\nTo test the load balancer:")
        print(f"  curl -k https://{self.haproxy_ip}:6443/version")
        print("  kubectl --insecure-skip-tls-verify get nodes")
        
        return True


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Setup HAProxy for Kubernetes cluster")
    parser.add_argument("--haproxy-ip", default="10.10.1.30",
                       help="IP address of HAProxy VM (default: 10.10.1.30)")
    
    args = parser.parse_args()
    
    # Check if running from correct directory
    if not Path("terraform/kubernetes-cluster.tf").exists():
        print("Must run from kubernetes-cluster root directory")
        sys.exit(1)
        
    setup = HAProxySetup(haproxy_ip=args.haproxy_ip)
    success = setup.setup_haproxy()
    
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()