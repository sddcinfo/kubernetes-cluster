#!/bin/bash
set -e

# Complete Monitoring Stack Deployment Script
# Deploys Prometheus, Grafana, and Hardware Monitoring

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"

echo "============================================="
echo "Deploying Complete Monitoring Stack"
echo "============================================="
echo ""

# Step 1: Check if kube-prometheus-stack is installed
echo "→ Checking if kube-prometheus-stack is installed..."
if helm list -n monitoring | grep -q kube-prometheus-stack; then
    echo "  ✓ kube-prometheus-stack is already installed"
else
    echo "  Installing kube-prometheus-stack..."
    
    # Create namespace
    kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
    
    # Add Prometheus community Helm repo
    helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
    helm repo update
    
    # Install kube-prometheus-stack with LoadBalancer for Grafana
    helm install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
        --namespace monitoring \
        --set grafana.service.type=LoadBalancer \
        --set grafana.service.loadBalancerIP=10.10.1.50 \
        --set prometheus.prometheusSpec.retention=30d \
        --set prometheus.prometheusSpec.storageSpec.volumeClaimTemplate.spec.resources.requests.storage=50Gi \
        --wait --timeout=10m
    
    echo "  ✓ kube-prometheus-stack installed successfully"
    
    # Get Grafana admin password
    echo ""
    echo "  Grafana admin password:"
    kubectl get secret -n monitoring kube-prometheus-stack-grafana -o jsonpath="{.data.admin-password}" | base64 -d
    echo ""
fi

# Step 2: Deploy Hardware Monitoring
echo ""
echo "→ Deploying Hardware Monitoring..."
"$SCRIPT_DIR/deploy-hardware-monitoring.sh"

# Step 3: Verify everything is running
echo ""
echo "→ Verifying all monitoring components..."

# Check Prometheus
PROM_PODS=$(kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus --no-headers 2>/dev/null | wc -l)
if [ "$PROM_PODS" -gt 0 ]; then
    echo "  ✓ Prometheus: Running ($PROM_PODS pods)"
else
    echo "  ⚠ Prometheus: Not found"
fi

# Check Grafana
GRAFANA_PODS=$(kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana --no-headers 2>/dev/null | wc -l)
if [ "$GRAFANA_PODS" -gt 0 ]; then
    echo "  ✓ Grafana: Running ($GRAFANA_PODS pods)"
    GRAFANA_IP=$(kubectl get svc -n monitoring kube-prometheus-stack-grafana -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "pending")
    echo "    URL: http://${GRAFANA_IP:-10.10.1.50}"
else
    echo "  ⚠ Grafana: Not found"
fi

# Check Redfish Exporter
REDFISH_PODS=$(kubectl get pods -n monitoring -l app=redfish-exporter --no-headers 2>/dev/null | wc -l)
if [ "$REDFISH_PODS" -gt 0 ]; then
    echo "  ✓ Redfish Exporter: Running ($REDFISH_PODS pods)"
else
    echo "  ⚠ Redfish Exporter: Not found"
fi

# List all dashboards
echo ""
echo "→ Available Grafana Dashboards:"
kubectl get configmap -n monitoring -l grafana_dashboard=1 --no-headers | awk '{print "  • " $1}'

echo ""
echo "============================================="
echo "Monitoring Stack Deployment Complete!"
echo "============================================="
echo ""
echo "Access Information:"
echo "  Grafana URL: http://10.10.1.50"
echo "  Username: admin"
echo "  Password: $(kubectl get secret -n monitoring kube-prometheus-stack-grafana -o jsonpath="{.data.admin-password}" | base64 -d)"
echo ""
echo "Hardware Monitoring Dashboards:"
echo "  • Hardware Monitoring - Original dashboard with tables and panels"
echo "  • Hardware Monitoring - Graphs - Clean graph-only view"
echo ""
echo "Monitoring Coverage:"
echo "  • Kubernetes cluster metrics"
echo "  • Node and pod metrics"
echo "  • Hardware sensors (CPU, Memory, Fans)"
echo "  • Console nodes: 10.10.1.11-14"
echo ""