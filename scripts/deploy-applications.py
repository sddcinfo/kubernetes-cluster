#!/usr/bin/env python3
"""
Kubernetes Applications Deployment Script
Complete deployment of storage, monitoring, and ingress with full automation
"""

import json
import subprocess
import sys
import time
import yaml
import tempfile
import argparse
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse


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
        
        # Configuration files
        self.proxmox_env_file = self.project_dir / '.proxmox-csi.env'
        self.proxmox_env_template = self.project_dir / '.proxmox-csi.env.template'
        self.dns_config_script = self.project_dir / "scripts" / "deploy-dns-config.py"
        
        # Timing tracking
        self.start_time = None
        self.phase_times = {}
        
        # Proxmox configuration
        self.proxmox_config = {}
        
        # Application components
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

    # ================== Prerequisites and Setup ==================

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

    # ================== Proxmox CSI Storage Integration ==================

    def load_proxmox_config(self):
        """Load Proxmox configuration from .env file"""
        if not self.proxmox_env_file.exists():
            # Create template if it doesn't exist
            if not self.proxmox_env_template.exists():
                template_content = """# Proxmox CSI Plugin Configuration Template
# Copy this file to .proxmox-csi.env and update with your values
PROXMOX_URL="https://PROXMOX_IP:8006/api2/json"
PROXMOX_TOKEN_ID="kubernetes-csi@pve!csi"
PROXMOX_TOKEN_SECRET="YOUR_TOKEN_SECRET_HERE"
PROXMOX_REGION="cluster"
PROXMOX_STORAGE="rbd"
PROXMOX_INSECURE="true"
"""
                self.proxmox_env_template.write_text(template_content)
                
            self.log(f"Proxmox credentials file not found: {self.proxmox_env_file}", "WARNING")
            self.log(f"Copy template: cp {self.proxmox_env_template} {self.proxmox_env_file}", "INFO")
            return False

        try:
            with open(self.proxmox_env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        self.proxmox_config[key] = value.strip('"')
            
            self.log("Loaded Proxmox CSI configuration", "SUCCESS")
            return True
        except Exception as e:
            self.log(f"Failed to load Proxmox configuration: {str(e)}", "ERROR")
            return False

    def validate_proxmox_config(self):
        """Validate Proxmox configuration parameters"""
        required_keys = [
            'PROXMOX_URL', 'PROXMOX_TOKEN_ID', 'PROXMOX_TOKEN_SECRET',
            'PROXMOX_REGION', 'PROXMOX_STORAGE'
        ]
        
        missing_keys = [key for key in required_keys if key not in self.proxmox_config]
        if missing_keys:
            self.log(f"Missing required Proxmox configuration: {', '.join(missing_keys)}", "ERROR")
            return False

        # Validate URL format
        try:
            parsed_url = urlparse(self.proxmox_config['PROXMOX_URL'])
            if not all([parsed_url.scheme, parsed_url.netloc]):
                self.log("Invalid PROXMOX_URL format", "ERROR")
                return False
        except Exception:
            self.log("Invalid PROXMOX_URL format", "ERROR")
            return False

        self.log("Proxmox configuration validation passed", "SUCCESS")
        return True

    def test_proxmox_connection(self):
        """Test connection to Proxmox using provided credentials"""
        try:
            import requests
            from requests.packages.urllib3.exceptions import InsecureRequestWarning
            
            if self.proxmox_config.get('PROXMOX_INSECURE', 'false').lower() == 'true':
                requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
            
            headers = {
                'Authorization': f"PVEAPIToken={self.proxmox_config['PROXMOX_TOKEN_ID']}={self.proxmox_config['PROXMOX_TOKEN_SECRET']}"
            }
            
            verify_ssl = self.proxmox_config.get('PROXMOX_INSECURE', 'false').lower() != 'true'
            
            response = requests.get(
                f"{self.proxmox_config['PROXMOX_URL'].rstrip('/')}/version",
                headers=headers,
                verify=verify_ssl,
                timeout=10
            )
            
            if response.status_code == 200:
                self.log("Proxmox API connection successful", "SUCCESS")
                return True
            else:
                self.log(f"Proxmox API connection failed: HTTP {response.status_code}", "ERROR")
                return False
                
        except ImportError:
            self.log("requests library not available, skipping connection test", "WARNING")
            return True
        except Exception as e:
            self.log(f"Failed to test Proxmox connection: {str(e)}", "ERROR")
            return False

    def setup_proxmox_user(self):
        """Create CSI user and token in Proxmox if needed"""
        parsed_url = urlparse(self.proxmox_config['PROXMOX_URL'])
        proxmox_host = parsed_url.hostname
        
        self.log(f"Checking CSI user on Proxmox {proxmox_host}...")
        
        # Check if user exists
        result = self.run_command(
            f"ssh root@{proxmox_host} 'pveum user list | grep kubernetes-csi@pve || echo NOT_FOUND'",
            "Check CSI user", check=False
        )
        
        if "NOT_FOUND" in result.stdout:
            self.log("Creating Proxmox CSI user and token...")
            
            commands = [
                "pveum role add CSI -privs 'VM.Audit VM.Config.Disk Datastore.Allocate Datastore.AllocateSpace Datastore.Audit' || true",
                "pveum user add kubernetes-csi@pve --comment 'Kubernetes CSI Plugin User'",
                "pveum aclmod / -user kubernetes-csi@pve -role CSI",
                "pveum user token add kubernetes-csi@pve csi -privsep 0 --comment 'Kubernetes CSI Plugin Token'"
            ]
            
            for cmd in commands:
                result = self.run_command(
                    f"ssh root@{proxmox_host} \"{cmd}\"",
                    f"Setup CSI: {cmd[:30]}...", check=False
                )
                
                if result.returncode != 0 and "already exists" not in result.stderr:
                    self.log(f"Command warning: {result.stderr}", "WARNING")
                    
            self.log("Proxmox CSI user setup completed", "SUCCESS")
            self.log("Update .proxmox-csi.env with the new token!", "WARNING")
        else:
            self.log("Proxmox CSI user already exists", "SUCCESS")

    def label_nodes_for_csi(self):
        """Label Kubernetes nodes with Proxmox topology"""
        self.log("Labeling nodes with topology information...")
        
        try:
            result = self.run_command(['kubectl', 'get', 'nodes', '-o', 'json'],
                                     "Get nodes", check=True)
            
            nodes = json.loads(result.stdout)
            
            for node in nodes['items']:
                node_name = node['metadata']['name']
                
                # Extract zone from node name
                if 'control' in node_name:
                    zone_num = node_name.split('-')[-1]
                    zone = f"node{zone_num}"
                elif 'worker' in node_name:
                    zone_num = node_name.split('-')[-1]
                    zone = f"node{zone_num}"
                else:
                    zone = "node1"
                
                labels = [
                    f"topology.kubernetes.io/region={self.proxmox_config['PROXMOX_REGION']}",
                    f"topology.kubernetes.io/zone={zone}"
                ]
                
                for label in labels:
                    self.run_command(
                        ['kubectl', 'label', 'nodes', node_name, label, '--overwrite'],
                        f"Label {node_name}", check=False
                    )
                    
            self.log("Node labeling completed", "SUCCESS")
            return True
            
        except Exception as e:
            self.log(f"Failed to label nodes: {str(e)}", "ERROR")
            return False

    def deploy_proxmox_csi(self):
        """Deploy Proxmox CSI driver using official manifest"""
        self.start_phase_timer("Proxmox CSI Deployment")
        
        try:
            # Load and validate configuration
            if not self.load_proxmox_config():
                self.log("Cannot deploy CSI without configuration", "ERROR")
                return False
                
            if not self.validate_proxmox_config():
                return False
                
            if not self.test_proxmox_connection():
                self.log("Proxmox connection failed. Check credentials.", "WARNING")
            
            # Download official deployment
            self.log("Downloading official Proxmox CSI deployment...")
            result = self.run_command(
                'curl -s https://raw.githubusercontent.com/sergelogvinov/proxmox-csi-plugin/main/docs/deploy/proxmox-csi-plugin.yml',
                "Download CSI manifest"
            )
            
            if result.returncode != 0:
                self.log("Failed to download CSI manifest", "ERROR")
                return False
            
            # Parse and modify YAML
            docs = list(yaml.safe_load_all(result.stdout))
            
            # Create CSI config secret
            csi_secret = {
                'apiVersion': 'v1',
                'kind': 'Secret',
                'metadata': {
                    'name': 'proxmox-csi-plugin',
                    'namespace': 'csi-proxmox'
                },
                'type': 'Opaque',
                'stringData': {
                    'config.yaml': yaml.dump({
                        'clusters': [{
                            'url': self.proxmox_config['PROXMOX_URL'],
                            'insecure': self.proxmox_config.get('PROXMOX_INSECURE', 'false').lower() == 'true',
                            'token_id': self.proxmox_config['PROXMOX_TOKEN_ID'],
                            'token_secret': self.proxmox_config['PROXMOX_TOKEN_SECRET'],
                            'region': self.proxmox_config['PROXMOX_REGION']
                        }]
                    }, default_flow_style=False)
                }
            }
            
            # Modify storage classes and build final manifest
            final_docs = []
            storage_class_added = False
            
            for doc in docs:
                if not doc:
                    continue
                    
                # Add secret after namespace
                if doc.get('kind') == 'Namespace':
                    final_docs.append(doc)
                    final_docs.append(csi_secret)
                    
                # Replace storage classes with our RBD configuration
                elif doc.get('kind') == 'StorageClass':
                    if not storage_class_added:
                        doc['metadata']['name'] = 'proxmox-rbd'
                        doc['metadata']['annotations'] = {
                            'storageclass.kubernetes.io/is-default-class': 'true'
                        }
                        doc['parameters'] = {
                            'csi.storage.k8s.io/fstype': 'ext4',
                            'storage': self.proxmox_config['PROXMOX_STORAGE']
                        }
                        final_docs.append(doc)
                        storage_class_added = True
                        self.log(f"Configured storage class for RBD: {self.proxmox_config['PROXMOX_STORAGE']}", "SUCCESS")
                else:
                    final_docs.append(doc)
            
            # Apply the manifest
            with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
                yaml.dump_all(final_docs, f, default_flow_style=False)
                temp_file = f.name
            
            self.log("Applying Proxmox CSI deployment...")
            result = self.run_command(f'kubectl apply -f {temp_file}', "Apply CSI manifest")
            
            if result.returncode == 0:
                self.log("CSI deployment applied successfully", "SUCCESS")
                
                # Label nodes for topology
                self.label_nodes_for_csi()
                
                # Wait for CSI pods to be ready
                self.log("Waiting for CSI pods to be ready...")
                time.sleep(10)
                
                result = self.run_command(
                    "kubectl get pods -n csi-proxmox --no-headers | grep -v Running | wc -l",
                    "Check CSI pod status"
                )
                
                non_running = int(result.stdout.strip())
                if non_running == 0:
                    self.log("All CSI pods are running", "SUCCESS")
                else:
                    self.log(f"{non_running} CSI pods still starting", "WARNING")
            else:
                self.log("Failed to apply CSI deployment", "ERROR")
                return False
            
            # Clean up temp file
            Path(temp_file).unlink()
            return True
            
        except Exception as e:
            self.log(f"CSI deployment failed: {str(e)}", "ERROR")
            return False
        finally:
            self.end_phase_timer("Proxmox CSI Deployment")

    # ================== Ingress Infrastructure ==================

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

    # ================== Monitoring Stack ==================

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

    # ================== Verification ==================

    def verify_deployments(self):
        """Verify all applications are deployed and healthy"""
        self.start_phase_timer("Verification")
        
        try:
            self.log("Verifying application deployments...")
            
            # Check CSI driver
            self.log("Checking Proxmox CSI driver...")
            result = self.run_command("kubectl get pods -n csi-proxmox --no-headers 2>/dev/null | grep Running | wc -l",
                                     "Check CSI pods")
            if result.returncode == 0:
                running_pods = int(result.stdout.strip())
                if running_pods > 0:
                    self.log(f"✓ Proxmox CSI: {running_pods} pods running", "SUCCESS")
                else:
                    self.log("✗ Proxmox CSI pods not running", "WARNING")
            
            # Check storage class
            result = self.run_command("kubectl get storageclass proxmox-rbd --no-headers 2>/dev/null | wc -l",
                                     "Check storage class")
            if result.returncode == 0 and int(result.stdout.strip()) > 0:
                self.log("✓ Proxmox RBD storage class configured", "SUCCESS")
            else:
                self.log("✗ Proxmox RBD storage class not found", "WARNING")
            
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
            result = self.run_command("kubectl get deployment -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx --no-headers 2>/dev/null | wc -l",
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
            result = self.run_command("kubectl get pods --all-namespaces | grep -E '(Error|CrashLoopBackOff|ImagePullBackOff)' | wc -l",
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

    # ================== Access Information ==================

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
┌─ Applications Access via Ingress ──────────────────────────────────┐
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
┌─ Applications Access Information ──────────────────────────────────┐
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
│     • proxmox-rbd (default) - RBD storage pool                    │
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

    # ================== Main Deployment ==================

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
            
            # Storage deployment (Proxmox CSI)
            if not self.monitoring_only:
                self.deploy_proxmox_csi()
            
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
        description="Deploy Kubernetes applications with monitoring, storage, and ingress",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Deploy everything (storage + monitoring + ingress)
  python3 scripts/deploy-applications.py
  
  # Deploy only storage integration (Proxmox CSI)
  python3 scripts/deploy-applications.py --storage-only
  
  # Deploy only monitoring stack
  python3 scripts/deploy-applications.py --monitoring-only
  
  # Verify existing deployments
  python3 scripts/deploy-applications.py --verify-only
  
  # Skip prerequisites check (faster re-runs)
  python3 scripts/deploy-applications.py --skip-prerequisites
  
Configuration:
  The Proxmox CSI driver requires a .proxmox-csi.env file with credentials.
  If missing, a template will be created for you to fill in.
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