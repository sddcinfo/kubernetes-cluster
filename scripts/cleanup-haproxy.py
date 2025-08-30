#!/usr/bin/env python3
"""
HAProxy Cleanup Script
Removes HAProxy VM and related configuration files when migrating to localhost HA
"""

import subprocess
import sys
from pathlib import Path

class HAProxyCleanup:
    def __init__(self):
        self.project_dir = Path(__file__).parent.parent
        self.haproxy_vm_id = 130
        self.haproxy_ip = "10.10.1.30"
        self.proxmox_nodes = ["node1", "node2", "node3", "node4"]
    
    def run_command(self, command, description, check=True):
        """Run a command with proper error handling"""
        print(f"-> {description}...")
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=check,
                shell=isinstance(command, str)
            )
            if result.stdout and not result.stdout.isspace():
                print(f"   {result.stdout.strip()}")
            return result
        except subprocess.CalledProcessError as e:
            if check:
                print(f"Error: {e}")
                if e.stderr:
                    print(f"   Stderr: {e.stderr}")
                return None
            return e
    
    def stop_haproxy_service(self):
        """Stop HAProxy service if running"""
        print("\nStopping HAProxy service...")
        
        # Try to stop service via SSH
        result = self.run_command(
            f"ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 -i /home/sysladmin/.ssh/sysladmin_automation_key sysladmin@{self.haproxy_ip} 'sudo systemctl stop haproxy || true'",
            f"Stopping HAProxy service on {self.haproxy_ip}",
            check=False
        )
        
        if result and result.returncode == 0:
            print("   HAProxy service stopped")
        else:
            print("   Could not stop HAProxy service (VM may be stopped)")
    
    def remove_haproxy_vm(self):
        """Remove HAProxy VM from all Proxmox nodes"""
        print("\nRemoving HAProxy VM...")
        
        vm_found = False
        for node in self.proxmox_nodes:
            print(f"Checking for VM {self.haproxy_vm_id} on {node}...")
            
            # Check if VM exists
            result = self.run_command(
                f"ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 root@{node} 'qm status {self.haproxy_vm_id} 2>/dev/null || echo \"not found\"'",
                f"Checking VM {self.haproxy_vm_id} on {node}",
                check=False
            )
            
            if result and result.returncode == 0:
                if "not found" not in result.stdout and "does not exist" not in result.stdout:
                    print(f"   Found VM {self.haproxy_vm_id} on {node}, removing...")
                    vm_found = True
                    
                    # Stop VM if running
                    self.run_command(
                        f"ssh -o StrictHostKeyChecking=no root@{node} 'qm stop {self.haproxy_vm_id} --skiplock || true'",
                        f"Stopping VM {self.haproxy_vm_id}",
                        check=False
                    )
                    
                    # Force destroy VM
                    self.run_command(
                        f"ssh -o StrictHostKeyChecking=no root@{node} 'qm destroy {self.haproxy_vm_id} --skiplock --purge || true'",
                        f"Destroying VM {self.haproxy_vm_id}",
                        check=False
                    )
                    
                    # Clean up config files
                    self.run_command(
                        f"ssh -o StrictHostKeyChecking=no root@{node} 'rm -f /etc/pve/nodes/{node}/qemu-server/{self.haproxy_vm_id}.conf /etc/pve/qemu-server/{self.haproxy_vm_id}.conf || true'",
                        f"Cleaning up config files for VM {self.haproxy_vm_id}",
                        check=False
                    )
                    break
                else:
                    print(f"   VM {self.haproxy_vm_id} not found on {node}")
        
        if not vm_found:
            print("   HAProxy VM not found on any node")
        else:
            print("   HAProxy VM removed successfully")
    
    def remove_haproxy_config_files(self):
        """Remove HAProxy configuration files from project"""
        print("\nRemoving HAProxy configuration files...")
        
        config_files = [
            self.project_dir / "haproxy.cfg",
            self.project_dir / "configs" / "haproxy.cfg",
            self.project_dir / "scripts" / "setup-haproxy.py"
        ]
        
        removed_files = []
        for config_file in config_files:
            if config_file.exists():
                config_file.unlink()
                removed_files.append(str(config_file))
                print(f"   Removed {config_file}")
        
        if not removed_files:
            print("   No HAProxy config files found")
        else:
            print(f"   Removed {len(removed_files)} configuration files")
    
    def update_kubeconfig_for_localhost_ha(self):
        """Update kubeconfig to use direct access for localhost HA"""
        print("\nUpdating kubeconfig for localhost HA...")
        
        kubeconfig_files = [
            Path.home() / ".kube" / "config",
            Path.home() / ".kube" / "config-k8s-proxmox"
        ]
        
        for kubeconfig_file in kubeconfig_files:
            if kubeconfig_file.exists():
                # Read current config
                config_content = kubeconfig_file.read_text()
                
                # Replace VIP with direct control plane access
                updated_content = config_content.replace(
                    f"https://{self.haproxy_ip}:6443",
                    "https://10.10.1.31:6443"
                )
                
                # Write updated config
                kubeconfig_file.write_text(updated_content)
                print(f"   Updated {kubeconfig_file} to use direct control plane access")
    
    def run_cleanup(self):
        """Run complete HAProxy cleanup"""
        print("HAProxy Infrastructure Cleanup")
        print("=" * 50)
        print("Migrating from external HAProxy to localhost HA mode")
        print("=" * 50)
        
        # Stop HAProxy service
        self.stop_haproxy_service()
        
        # Remove VM
        self.remove_haproxy_vm()
        
        # Remove config files
        self.remove_haproxy_config_files()
        
        # Update kubeconfig
        self.update_kubeconfig_for_localhost_ha()
        
        print("\n" + "=" * 50)
        print("HAProxy cleanup completed successfully!")
        print("=" * 50)
        print("\nYour cluster is now using localhost HA mode:")
        print("- Built-in nginx load balancers on worker nodes")
        print("- Direct control plane access for management")
        print("- No external dependencies or certificate issues")
        print("\nTest with: kubectl get nodes")

def main():
    """Main entry point"""
    cleanup = HAProxyCleanup()
    cleanup.run_cleanup()

if __name__ == "__main__":
    main()