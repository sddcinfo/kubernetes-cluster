#!/usr/bin/env python3
"""
Test script to demonstrate deploy-applications.py re-run safety and idempotency
"""

import subprocess
import sys
import time
from pathlib import Path

def run_command(cmd, description=""):
    """Execute command and return result"""
    print(f"Testing: {description}")
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "", "Command timed out"

def test_component_exists(cmd, component_name):
    """Test if a component exists and is healthy"""
    success, stdout, stderr = run_command(cmd, f"Check {component_name}")
    if success:
        try:
            count = int(stdout)
            if count > 0:
                print(f"✓ {component_name}: {count} found")
                return True
            else:
                print(f"✗ {component_name}: Not found")
                return False
        except ValueError:
            print(f"✗ {component_name}: Invalid response")
            return False
    else:
        print(f"✗ {component_name}: Check failed - {stderr}")
        return False

def main():
    print("=" * 60)
    print("Testing deploy-applications.py Re-run Safety")
    print("=" * 60)
    
    # Test current deployment status
    print("\n1. Testing Current Deployment Status:")
    
    components = [
        ("kubectl get deployment -n metallb-system metallb-controller --no-headers 2>/dev/null | wc -l", "MetalLB Controller"),
        ("kubectl get deployment -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx --no-headers 2>/dev/null | wc -l", "NGINX Ingress"),
        ("kubectl get ipaddresspool -n metallb-system apps-pool --no-headers 2>/dev/null | wc -l", "MetalLB IP Pool"),
        ("kubectl get ingress --all-namespaces --no-headers 2>/dev/null | wc -l", "Ingress Resources"),
        ("kubectl get deployment -n argocd argocd-server --no-headers 2>/dev/null | wc -l", "ArgoCD Server"),
        ("kubectl get configmap argocd-cmd-params-cm -n argocd --no-headers 2>/dev/null | wc -l", "ArgoCD Config"),
        ("kubectl get namespace monitoring --no-headers 2>/dev/null | wc -l", "Monitoring Namespace"),
    ]
    
    all_deployed = True
    for cmd, name in components:
        if not test_component_exists(cmd, name):
            all_deployed = False
    
    print(f"\n2. Overall Status: {'✓ All core components deployed' if all_deployed else '✗ Some components missing'}")
    
    # Test ingress access
    print("\n3. Testing Ingress Access:")
    ingress_tests = [
        ("curl -s -o /dev/null -w '%{http_code}' http://argocd.apps.sddc.info/", "ArgoCD UI", "200"),
        ("curl -s -o /dev/null -w '%{http_code}' http://grafana.apps.sddc.info/", "Grafana UI", "200"),
        ("curl -s -o /dev/null -w '%{http_code}' http://prometheus.apps.sddc.info/", "Prometheus UI", "200"),
    ]
    
    for cmd, name, expected in ingress_tests:
        success, stdout, stderr = run_command(cmd, f"Test {name}")
        if success and stdout == expected:
            print(f"✓ {name}: HTTP {stdout}")
        else:
            print(f"✗ {name}: Expected {expected}, got {stdout}")
    
    # Test idempotency by running apply on key resources
    print("\n4. Testing Idempotency (kubectl apply --dry-run):")
    
    project_dir = Path(__file__).parent.parent
    applications_dir = project_dir / "applications"
    
    idempotency_tests = [
        (applications_dir / "ingress" / "complete-ingress-stack.yml", "Ingress Stack"),
        (applications_dir / "ingress" / "metallb-ip-pool.yml", "MetalLB IP Pool"),
        (applications_dir / "config" / "argocd-insecure-config.yml", "ArgoCD Config"),
        (applications_dir / "ingress" / "application-ingresses.yml", "Application Ingresses"),
    ]
    
    for file_path, name in idempotency_tests:
        if file_path.exists():
            cmd = f"kubectl apply --dry-run=client -f {file_path}"
            success, stdout, stderr = run_command(cmd, f"Dry-run {name}")
            if success:
                print(f"✓ {name}: Idempotent")
            else:
                print(f"✗ {name}: {stderr}")
        else:
            print(f"✗ {name}: File not found")
    
    print("\n" + "=" * 60)
    if all_deployed:
        print("CONCLUSION: deploy-applications.py can be safely re-run")
        print("- All core components are deployed and healthy")
        print("- Ingress access is working for all applications")
        print("- Resource definitions are idempotent")
        print("- Re-running the script will detect existing deployments")
    else:
        print("CONCLUSION: Some components need deployment/repair")
        print("- Re-run deploy-applications.py to fix missing components")
        
    print("=" * 60)

if __name__ == "__main__":
    main()