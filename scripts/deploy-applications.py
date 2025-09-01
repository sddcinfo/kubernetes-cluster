#!/usr/bin/env python3
"""
Kubernetes Applications Deployment Script
Deploys monitoring stack, storage integration, and observability platform
"""

import json
import subprocess
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime, timedelta


class ApplicationsDeployer:
    def __init__(self, storage_only=False, monitoring_only=False, verify_only=False, 
                 skip_prerequisites=False, verbose=False):
        self.project_dir = Path(__file__).parent.parent
        self.applications_dir = self.project_dir / "applications"
        self.max_retries = 3
        
        # Mode flags
        self.storage_only = storage_only
        self.monitoring_only = monitoring_only
        self.verify_only = verify_only
        self.skip_prerequisites = skip_prerequisites
        self.verbose = verbose
        
        # DNS configuration script path
        self.dns_config_script = self.project_dir / "scripts" / "deploy-dns-config.py"
        
        # Timing tracking
        self.start_time = None
        self.phase_times = {}
        
        # Application components
        self.storage_components = [
            "storage/proxmox-csi-plugin.yml"
        ]
        
        self.monitoring_components = [
            "monitoring/kube-prometheus-stack.yml",
            "monitoring/proxmox-exporter.yml", 
            "monitoring/grafana-dashboards.yml"
        ]
        
        self.ingress_components = [
            "ingress/complete-ingress-stack.yml",
            "ingress/metallb-ip-pool.yml",
            "config/argocd-insecure-config.yml",
            "ingress/application-ingresses.yml"
        ]

    def log(self, message, level="INFO"):
        """Enhanced logging with timestamps"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        if level == "ERROR":
            print(f"\033[91m[{timestamp}] ERROR: {message}\033[0m", file=sys.stderr)
        elif level == "SUCCESS":
            print(f"\033[92m[{timestamp}] SUCCESS: {message}\033[0m")
        elif level == "WARNING":
            print(f"\033[93m[{timestamp}] WARNING: {message}\033[0m")
        else:
            if self.verbose or level in ["INFO", "PHASE"]:
                prefix = f"\033[94m[{timestamp}] {level}:\033[0m" if level == "PHASE" else f"[{timestamp}] {level}:"
                print(f"{prefix} {message}")

    def run_command(self, cmd, description="", check=True, cwd=None, timeout=300):
        """Execute shell command with comprehensive error handling"""
        if isinstance(cmd, str):
            cmd_str = cmd
            shell = True
        else:
            cmd_str = ' '.join(cmd)
            shell = False
            
        self.log(f"Executing: {description if description else cmd_str}", "DEBUG" if not self.verbose else "INFO")
        
        try:
            result = subprocess.run(
                cmd, 
                cwd=cwd, 
                capture_output=True, 
                text=True, 
                check=check,
                timeout=timeout,
                shell=shell
            )
            
            if self.verbose and result.stdout:
                print(result.stdout)
            
            return result
        except subprocess.CalledProcessError as e:
            error_msg = f"Command failed: {cmd_str}"
            if e.stderr:
                error_msg += f"\nError: {e.stderr}"
            if e.stdout:
                error_msg += f"\nOutput: {e.stdout}"
            self.log(error_msg, "ERROR")
            if check:
                raise
            return e
        except subprocess.TimeoutExpired as e:
            self.log(f"Command timed out after {timeout}s: {cmd_str}", "ERROR")
            if check:
                raise
            return e

    def start_phase_timer(self, phase_name):
        """Start timing a deployment phase"""
        self.phase_times[phase_name] = {"start": time.time()}
        self.log(f"Starting {phase_name}", "PHASE")

    def end_phase_timer(self, phase_name):
        """End timing a deployment phase"""
        if phase_name in self.phase_times:
            duration = time.time() - self.phase_times[phase_name]["start"]
            self.phase_times[phase_name]["duration"] = duration
            self.log(f"Completed {phase_name} in {duration:.1f}s", "SUCCESS")
        
    def check_prerequisites(self):
        """Verify cluster and ArgoCD are ready for applications deployment"""
        self.start_phase_timer("Prerequisites Check")
        
        try:
            # Check kubectl connectivity
            self.log("Checking Kubernetes cluster connectivity...")
            result = self.run_command("kubectl cluster-info", "Check cluster connectivity")
            
            # Check if nodes are ready
            self.log("Verifying node readiness...")
            result = self.run_command("kubectl get nodes --no-headers | awk '{print $2}' | grep -v Ready || true", 
                                    "Check node status")
            if result.stdout.strip():
                self.log("Some nodes are not ready. Proceeding with caution...", "WARNING")
                
            # Check for storage class (if not deploying storage-only)
            if not self.storage_only:
                self.log("Checking for available storage classes...")
                result = self.run_command("kubectl get storageclass --no-headers | wc -l",
                                        "Count storage classes")
                sc_count = int(result.stdout.strip())
                if sc_count == 0:
                    self.log("No storage classes found. Consider running --storage-only first.", "WARNING")
            
            # Check ArgoCD installation
            self.log("Checking ArgoCD installation...")
            result = self.run_command("kubectl get namespace argocd", 
                                    "Check ArgoCD namespace", check=False)
            if result.returncode != 0:
                self.log("ArgoCD not found. Installing ArgoCD...", "WARNING")
                self.install_argocd()
            else:
                self.log("ArgoCD namespace found", "SUCCESS")
                
        except Exception as e:
            self.log(f"Prerequisites check failed: {str(e)}", "ERROR")
            raise
        finally:
            self.end_phase_timer("Prerequisites Check")

    def install_argocd(self):
        """Install ArgoCD for GitOps deployment"""
        self.log("Installing ArgoCD...")
        
        # Create ArgoCD namespace and install
        self.run_command("kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -",
                        "Create ArgoCD namespace")
        
        # Install ArgoCD
        self.run_command(
            "kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml",
            "Install ArgoCD"
        )
        
        # Wait for ArgoCD to be ready
        self.log("Waiting for ArgoCD to be ready...")
        self.run_command("kubectl wait --for=condition=available --timeout=300s deployment/argocd-server -n argocd",
                        "Wait for ArgoCD server")
        
        self.log("ArgoCD installed successfully", "SUCCESS")

    def deploy_storage_integration(self):
        """Deploy Proxmox CSI plugin and storage classes"""
        self.start_phase_timer("Storage Integration")
        
        try:
            self.log("Deploying Proxmox CSI storage integration...")
            
            for component in self.storage_components:
                component_path = self.applications_dir / component
                if not component_path.exists():
                    self.log(f"Component not found: {component}", "ERROR")
                    continue
                    
                self.log(f"Applying {component}...")
                self.run_command(f"kubectl apply -f {component_path}", 
                               f"Deploy {component}")
            
            # Wait for CSI driver to be ready
            self.log("Waiting for CSI driver to be ready...")
            self.run_command("kubectl wait --for=condition=available --timeout=300s deployment/proxmox-csi-controller -n csi-proxmox || true",
                           "Wait for CSI controller")
                           
            # Verify storage classes
            self.log("Verifying storage classes...")
            result = self.run_command("kubectl get storageclass", "List storage classes")
            if "proxmox-rbd" in result.stdout:
                self.log("Proxmox RBD storage class created successfully", "SUCCESS")
            else:
                self.log("Storage class creation may have failed", "WARNING")
                
        except Exception as e:
            self.log(f"Storage integration deployment failed: {str(e)}", "ERROR")
            raise
        finally:
            self.end_phase_timer("Storage Integration")

    def check_ingress_deployed(self):
        """Check if ingress stack is already deployed and healthy"""
        try:
            # Check if MetalLB controller is running
            result = self.run_command("kubectl get deployment -n metallb-system metallb-controller --no-headers 2>/dev/null | wc -l",
                                     "Check MetalLB controller", check=False)
            if result.returncode != 0:
                return False
            metallb_deployed = int(result.stdout.strip()) > 0
            
            # Check if NGINX Ingress is running
            result = self.run_command("kubectl get deployment -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx --no-headers 2>/dev/null | wc -l",
                                     "Check NGINX Ingress", check=False)
            if result.returncode != 0:
                return False
            nginx_deployed = int(result.stdout.strip()) > 0
            
            # Check if MetalLB IP pool is configured
            result = self.run_command("kubectl get ipaddresspool -n metallb-system apps-pool --no-headers 2>/dev/null | wc -l",
                                     "Check MetalLB IP pool", check=False)
            if result.returncode != 0:
                return False
            ip_pool_configured = int(result.stdout.strip()) > 0
            
            return metallb_deployed and nginx_deployed and ip_pool_configured
            
        except Exception:
            return False

    def deploy_ingress_stack(self):
        """Deploy complete ingress infrastructure (MetalLB + NGINX)"""
        self.start_phase_timer("Ingress Infrastructure")
        
        try:
            # Check if ingress stack is already deployed
            if self.check_ingress_deployed():
                self.log("Ingress stack already deployed and healthy", "SUCCESS")
                return
                
            self.log("Deploying ingress infrastructure...")
            
            # Deploy MetalLB and NGINX Ingress via ArgoCD
            ingress_stack_path = self.applications_dir / "ingress" / "complete-ingress-stack.yml"
            if ingress_stack_path.exists():
                self.log("Deploying MetalLB and NGINX Ingress Controller...")
                self.run_command(f"kubectl apply -f {ingress_stack_path}",
                               "Deploy ingress stack")
                
                # Wait for MetalLB to be ready
                self.log("Waiting for MetalLB controller...")
                self.run_command("kubectl wait --for=condition=available --timeout=300s deployment/metallb-controller -n metallb-system || true",
                               "Wait for MetalLB controller")
                
                # Wait for NGINX Ingress to be ready
                self.log("Waiting for NGINX Ingress Controller...")
                self.run_command("kubectl wait --for=condition=available --timeout=300s deployment/nginx-ingress-controller-ingress-nginx-controller -n ingress-nginx || true",
                               "Wait for NGINX Ingress")
                
                # Wait for MetalLB CRDs to be established before applying IP pool
                self.log("Waiting for MetalLB CRDs to be ready...")
                self.run_command("kubectl wait --for=condition=established --timeout=120s crd/ipaddresspools.metallb.io || true",
                               "Wait for MetalLB CRDs")
                
                # Apply MetalLB IP pool configuration
                ip_pool_path = self.applications_dir / "ingress" / "metallb-ip-pool.yml"
                if ip_pool_path.exists():
                    self.log("Configuring MetalLB IP address pool...")
                    time.sleep(10)  # Additional wait for CRDs
                    self.run_command(f"kubectl apply -f {ip_pool_path}",
                                   "Configure MetalLB IP pool")
                
                # Update DNS configuration for ingress wildcard
                self.log("Updating DNS configuration for ingress...")
                self.deploy_dns_configuration()
                
        except Exception as e:
            self.log(f"Ingress stack deployment failed: {str(e)}", "ERROR")
            raise
        finally:
            self.end_phase_timer("Ingress Infrastructure")
    
    def configure_argocd_insecure(self):
        """Configure ArgoCD for HTTP ingress access"""
        self.log("Configuring ArgoCD for HTTP ingress...")
        
        try:
            # Apply ArgoCD insecure configuration
            argocd_config_path = self.applications_dir / "config" / "argocd-insecure-config.yml"
            if argocd_config_path.exists():
                self.run_command(f"kubectl apply -f {argocd_config_path}",
                               "Configure ArgoCD insecure mode")
                
                # Restart ArgoCD server to pick up new configuration
                self.log("Restarting ArgoCD server for configuration changes...")
                self.run_command("kubectl rollout restart deployment/argocd-server -n argocd",
                               "Restart ArgoCD server")
                
                # Wait for ArgoCD server to be ready
                self.run_command("kubectl wait --for=condition=available --timeout=300s deployment/argocd-server -n argocd",
                               "Wait for ArgoCD server restart")
                
        except Exception as e:
            self.log(f"ArgoCD configuration failed: {str(e)}", "WARNING")
    
    def deploy_application_ingresses(self):
        """Deploy ingress resources for applications"""
        self.log("Deploying application ingress resources...")
        
        try:
            ingress_path = self.applications_dir / "ingress" / "application-ingresses.yml"
            if ingress_path.exists():
                self.run_command(f"kubectl apply -f {ingress_path}",
                               "Deploy application ingresses")
                
                # Verify ingress resources are created
                self.log("Verifying ingress resources...")
                result = self.run_command("kubectl get ingress --all-namespaces --no-headers | wc -l",
                                         "Count ingress resources")
                ingress_count = int(result.stdout.strip())
                if ingress_count > 0:
                    self.log(f"Created {ingress_count} ingress resources", "SUCCESS")
                else:
                    self.log("No ingress resources found", "WARNING")
                    
        except Exception as e:
            self.log(f"Application ingress deployment failed: {str(e)}", "WARNING")
    
    def deploy_dns_configuration(self):
        """Deploy DNS configuration for ingress wildcards"""
        self.log("Deploying DNS configuration...")
        
        try:
            if self.dns_config_script.exists():
                self.run_command(f"python3 {self.dns_config_script}",
                               "Update DNS configuration")
                self.log("DNS configuration updated successfully", "SUCCESS")
            else:
                self.log(f"DNS configuration script not found: {self.dns_config_script}", "WARNING")
                
        except Exception as e:
            self.log(f"DNS configuration failed: {str(e)}", "WARNING")

    def deploy_monitoring_stack(self):
        """Deploy comprehensive monitoring with Prometheus and Grafana"""
        self.start_phase_timer("Monitoring Stack")
        
        try:
            self.log("Deploying monitoring stack (Prometheus + Grafana)...")
            
            for component in self.monitoring_components:
                component_path = self.applications_dir / component
                if not component_path.exists():
                    self.log(f"Component not found: {component}", "ERROR")
                    continue
                    
                self.log(f"Applying {component}...")
                self.run_command(f"kubectl apply -f {component_path}",
                               f"Deploy {component}")
                
                # Add delay between components for proper initialization
                time.sleep(5)
            
            # Wait for monitoring namespace to be ready
            self.log("Waiting for monitoring namespace...")
            self.run_command("kubectl wait --for=condition=available --timeout=600s deployment/kube-prometheus-stack-operator -n monitoring || true",
                           "Wait for Prometheus Operator")
            
            # Wait for Grafana to be ready  
            self.log("Waiting for Grafana deployment...")
            self.run_command("kubectl wait --for=condition=available --timeout=600s deployment/kube-prometheus-stack-grafana -n monitoring || true",
                           "Wait for Grafana")
                           
            # Wait for Prometheus to be ready
            self.log("Waiting for Prometheus StatefulSet...")
            self.run_command("kubectl wait --for=condition=ready --timeout=600s pod -l app.kubernetes.io/name=prometheus -n monitoring || true",
                           "Wait for Prometheus pods")
            
        except Exception as e:
            self.log(f"Monitoring stack deployment failed: {str(e)}", "ERROR") 
            raise
        finally:
            self.end_phase_timer("Monitoring Stack")

    def verify_deployments(self):
        """Verify all applications are deployed and healthy"""
        self.start_phase_timer("Verification")
        
        try:
            self.log("Verifying application deployments...")
            
            # Check ingress infrastructure
            self.log("Checking ingress infrastructure...")
            
            # Check MetalLB
            result = self.run_command("kubectl get deployment -n metallb-system metallb-controller --no-headers 2>/dev/null | wc -l",
                                     "Check MetalLB controller")
            if int(result.stdout.strip()) > 0:
                self.log("✓ MetalLB controller is deployed", "SUCCESS")
            else:
                self.log("✗ MetalLB controller not found", "ERROR")
            
            # Check NGINX Ingress
            result = self.run_command("kubectl get deployment -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx --no-headers | wc -l",
                                     "Check NGINX Ingress")
            if int(result.stdout.strip()) > 0:
                self.log("✓ NGINX Ingress Controller is deployed", "SUCCESS")
                
                # Get ingress LoadBalancer IP
                result = self.run_command("kubectl get svc -n ingress-nginx -o jsonpath='{.items[0].status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo 'pending'",
                                         "Get NGINX Ingress LoadBalancer IP")
                if result.stdout.strip() != "pending":
                    self.log(f"✓ NGINX Ingress available at: {result.stdout.strip()}", "SUCCESS")
                else:
                    self.log("NGINX Ingress LoadBalancer IP pending...", "WARNING")
            else:
                self.log("✗ NGINX Ingress Controller not found", "ERROR")
            
            # Check ingress resources
            result = self.run_command("kubectl get ingress --all-namespaces --no-headers | wc -l",
                                     "Count ingress resources")
            ingress_count = int(result.stdout.strip())
            if ingress_count > 0:
                self.log(f"✓ {ingress_count} ingress resources configured", "SUCCESS")
            else:
                self.log("No ingress resources found", "WARNING")
            
            # Check storage integration
            if not self.monitoring_only:
                self.log("Checking storage integration...")
                result = self.run_command("kubectl get storageclass proxmox-rbd -o jsonpath='{.metadata.name}' 2>/dev/null || echo 'not-found'",
                                         "Check storage class")
                if result.stdout.strip() == "proxmox-rbd":
                    self.log("✓ Proxmox RBD storage class is available", "SUCCESS")
                else:
                    self.log("✗ Proxmox RBD storage class not found", "ERROR")
            
            # Check monitoring stack
            if not self.storage_only:
                self.log("Checking monitoring stack...")
                
                # Check Prometheus
                result = self.run_command("kubectl get statefulset -n monitoring -l app.kubernetes.io/name=prometheus --no-headers | wc -l",
                                         "Check Prometheus StatefulSet")
                if int(result.stdout.strip()) > 0:
                    self.log("✓ Prometheus is deployed", "SUCCESS")
                else:
                    self.log("✗ Prometheus not found", "ERROR")
                
                # Check Grafana
                result = self.run_command("kubectl get deployment -n monitoring -l app.kubernetes.io/name=grafana --no-headers | wc -l",
                                         "Check Grafana deployment")
                if int(result.stdout.strip()) > 0:
                    self.log("✓ Grafana is deployed", "SUCCESS")
                else:
                    self.log("✗ Grafana not found", "ERROR")
                
                # Check AlertManager
                result = self.run_command("kubectl get statefulset -n monitoring -l app.kubernetes.io/name=alertmanager --no-headers | wc -l",
                                         "Check AlertManager")
                if int(result.stdout.strip()) > 0:
                    self.log("✓ AlertManager is deployed", "SUCCESS")
                
            # Check ArgoCD ingress configuration
            result = self.run_command("kubectl get configmap argocd-cmd-params-cm -n argocd -o jsonpath='{.data.server\\.insecure}' 2>/dev/null || echo 'not-found'",
                                     "Check ArgoCD insecure config")
            if result.stdout.strip() == "true":
                self.log("✓ ArgoCD configured for HTTP ingress", "SUCCESS")
            else:
                self.log("ArgoCD HTTP ingress configuration not found", "WARNING")
                
            # Overall health check
            self.log("Checking overall application health...")
            result = self.run_command("kubectl get pods --all-namespaces | grep -E '(Error|CrashLoopBackOff|ImagePullBackOff|Pending)' | wc -l",
                                     "Check for problematic pods")
            problem_pods = int(result.stdout.strip())
            if problem_pods == 0:
                self.log("✓ All application pods are healthy", "SUCCESS")
            else:
                self.log(f"⚠ {problem_pods} pods may have issues", "WARNING")
                
        except Exception as e:
            self.log(f"Verification failed: {str(e)}", "ERROR")
            raise
        finally:
            self.end_phase_timer("Verification")

    def print_access_information(self):
        """Print information about accessing deployed services"""
        self.log("Deployment Access Information", "PHASE")
        
        try:
            # Get ingress IP for applications
            result = self.run_command("kubectl get svc -n ingress-nginx -o jsonpath='{.items[0].status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo 'pending'",
                                     "Get NGINX Ingress IP")
            ingress_ip = result.stdout.strip()
            
            if ingress_ip != "pending":
                print(f"""
┌─ Applications Access via Ingress ─────────────────────────────────┐
│                                                                    │
│  Ingress Controller IP: {ingress_ip}                              │
│                                                                    │
│  Application URLs (via *.apps.sddc.info):                        │
│  • ArgoCD:   http://argocd.apps.sddc.info/                       │
│  • Grafana:  http://grafana.apps.sddc.info/                      │
│  • Prometheus: http://prometheus.apps.sddc.info/                 │
│                                                                    │
│  ArgoCD Admin Password:                                           │
│  kubectl -n argocd get secret argocd-initial-admin-secret \\     │
│    -o jsonpath="{{.data.password}}" | base64 -d                    │
│                                                                    │
│  Grafana Login: admin / kubernetes-admin-2024                    │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
""")
            else:
                print(f"""
┌─ Applications Access Information ─────────────────────────────────┐
│                                                                    │
│  Ingress LoadBalancer IP is still pending                        │
│  Use port-forward for immediate access:                          │
│                                                                    │
│  ArgoCD:                                                          │
│  kubectl port-forward -n argocd svc/argocd-server 8080:80        │
│  Then access: http://localhost:8080                              │
│                                                                    │
│  Grafana:                                                         │
│  kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80 │
│  Then access: http://localhost:3000                              │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
""")
                
            # Storage information
            if not self.monitoring_only:
                result = self.run_command("kubectl get storageclass --no-headers | wc -l", "Count storage classes")
                sc_count = int(result.stdout.strip())
                
                print(f"""
┌─ Storage Integration ──────────────────────────────────────────────┐
│                                                                    │
│  Available Storage Classes: {sc_count}                            │
│     • proxmox-rbd (default)                                       │ 
│     • proxmox-rbd-fast                                            │
│                                                                    │
│  Test persistent storage:                                         │
│     kubectl apply -f - <<EOF                                      │
│     apiVersion: v1                                                │
│     kind: PersistentVolumeClaim                                   │
│     metadata:                                                     │
│       name: test-pvc                                              │
│     spec:                                                         │
│       accessModes: [ReadWriteOnce]                               │
│       resources:                                                  │
│         requests:                                                 │
│           storage: 1Gi                                            │
│     EOF                                                           │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
""")
                
        except Exception as e:
            self.log(f"Failed to get access information: {str(e)}", "WARNING")

    def print_timing_summary(self):
        """Print deployment timing summary"""
        total_time = time.time() - self.start_time
        
        print(f"""
┌─ Deployment Timing Summary ───────────────────────────────────────┐
│                                                                    │""")
        
        for phase, times in self.phase_times.items():
            if "duration" in times:
                duration = times["duration"]
                print(f"│  {phase:<30} {duration:>8.1f}s                      │")
        
        print(f"""│                                                                    │
│  Total Deployment Time:        {total_time:>8.1f}s                      │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
""")

    def deploy(self):
        """Main deployment orchestrator"""
        self.start_time = time.time()
        
        try:
            self.log("Starting Kubernetes Applications Deployment", "PHASE")
            self.log(f"Mode: {'Storage Only' if self.storage_only else 'Monitoring Only' if self.monitoring_only else 'Full Deployment'}")
            
            # Prerequisites check
            if not self.skip_prerequisites:
                self.check_prerequisites()
            
            # Deploy ingress infrastructure first (required for application access)
            self.deploy_ingress_stack()
            
            # Configure ArgoCD for HTTP ingress
            self.configure_argocd_insecure()
            
            # Storage deployment
            if not self.monitoring_only:
                self.deploy_storage_integration()
            
            # Monitoring deployment  
            if not self.storage_only:
                self.deploy_monitoring_stack()
                
            # Deploy application ingresses
            self.deploy_application_ingresses()
            
            # Verification
            if not self.verify_only:
                self.verify_deployments()
            
            # Success summary
            self.log("Applications deployment completed successfully!", "SUCCESS")
            self.print_access_information()
            self.print_timing_summary()
            
        except KeyboardInterrupt:
            self.log("Deployment interrupted by user", "WARNING")
            sys.exit(1)
        except Exception as e:
            self.log(f"Deployment failed: {str(e)}", "ERROR")
            sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Deploy Kubernetes applications with monitoring and storage integration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Deploy everything (storage + monitoring)
  python3 scripts/deploy-applications.py
  
  # Deploy only storage integration
  python3 scripts/deploy-applications.py --storage-only
  
  # Deploy only monitoring stack
  python3 scripts/deploy-applications.py --monitoring-only
  
  # Verify existing deployments
  python3 scripts/deploy-applications.py --verify-only
  
  # Skip prerequisites check (faster re-runs)
  python3 scripts/deploy-applications.py --skip-prerequisites
        """
    )
    
    parser.add_argument("--storage-only", action="store_true", help="Deploy only storage integration")
    parser.add_argument("--monitoring-only", action="store_true", help="Deploy only monitoring stack")
    parser.add_argument("--verify-only", action="store_true", help="Only verify existing deployments")
    parser.add_argument("--skip-prerequisites", action="store_true", help="Skip prerequisites check")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")
    
    args = parser.parse_args()
    
    # Validate argument combinations
    if args.storage_only and args.monitoring_only:
        parser.error("Cannot use --storage-only and --monitoring-only together")
    
    deployer = ApplicationsDeployer(
        storage_only=args.storage_only,
        monitoring_only=args.monitoring_only,
        verify_only=args.verify_only,
        skip_prerequisites=args.skip_prerequisites,
        verbose=args.verbose
    )
    
    deployer.deploy()


if __name__ == "__main__":
    main()