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
                    
                    # Get Grafana LoadBalancer IP
                    result = self.run_command("kubectl get svc -n monitoring kube-prometheus-stack-grafana -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo 'pending'",
                                             "Get Grafana LoadBalancer IP")
                    if result.stdout.strip() != "pending":
                        self.log(f"✓ Grafana available at: http://{result.stdout.strip()}/", "SUCCESS")
                    else:
                        self.log("Grafana LoadBalancer IP pending...", "WARNING")
                else:
                    self.log("✗ Grafana not found", "ERROR")
                
                # Check AlertManager
                result = self.run_command("kubectl get statefulset -n monitoring -l app.kubernetes.io/name=alertmanager --no-headers | wc -l",
                                         "Check AlertManager")
                if int(result.stdout.strip()) > 0:
                    self.log("✓ AlertManager is deployed", "SUCCESS")
                
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
            # Grafana access
            result = self.run_command("kubectl get svc -n monitoring kube-prometheus-stack-grafana -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo 'pending'",
                                     "Get Grafana IP")
            grafana_ip = result.stdout.strip()
            
            if grafana_ip != "pending":
                print(f"""
┌─ Monitoring Stack Access ─────────────────────────────────────────┐
│                                                                    │
│  🎯 Grafana Dashboard:                                            │
│     URL: http://{grafana_ip}/                                      │
│     Username: admin                                                │
│     Password: kubernetes-admin-2024                                │
│                                                                    │
│  📊 Prometheus:                                                   │
│     Access via port-forward: kubectl port-forward -n monitoring   │
│     svc/kube-prometheus-stack-prometheus 9090:9090                 │
│                                                                    │
│  🚨 AlertManager:                                                 │
│     Access via LoadBalancer or port-forward                       │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
""")
            else:
                print(f"""
┌─ Monitoring Stack Information ────────────────────────────────────┐
│                                                                    │
│  ⏳ Grafana LoadBalancer IP is still pending                      │
│  Use port-forward for immediate access:                           │
│  kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80 │
│  Then access: http://localhost:3000                               │
│  Username: admin                                                   │
│  Password: kubernetes-admin-2024                                   │
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
│  💾 Available Storage Classes: {sc_count}                                     │
│     • proxmox-rbd (default)                                       │ 
│     • proxmox-rbd-fast                                            │
│                                                                    │
│  📋 Test persistent storage:                                      │
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
            
            # Storage deployment
            if not self.monitoring_only:
                self.deploy_storage_integration()
            
            # Monitoring deployment  
            if not self.storage_only:
                self.deploy_monitoring_stack()
            
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