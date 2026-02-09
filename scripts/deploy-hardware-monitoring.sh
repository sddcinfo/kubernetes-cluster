#!/bin/bash
set -e

# Hardware Monitoring Deployment Script
# This script deploys the complete Redfish hardware monitoring stack

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
MONITORING_DIR="$BASE_DIR/applications/monitoring"

echo "==========================================="
echo "Deploying Hardware Monitoring Stack"
echo "==========================================="

# Ensure monitoring namespace exists
echo "→ Ensuring monitoring namespace exists..."
kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -

# Step 1: Create Redfish credentials secret with CORRECT credentials
echo "→ Creating Redfish credentials secret..."
kubectl delete secret redfish-credentials -n monitoring 2>/dev/null || true
kubectl create secret generic redfish-credentials -n monitoring \
  --from-literal="redfish_credentials=REDFISH_AUTH=\"${REDFISH_AUTH:?Set REDFISH_AUTH env var}\""

# Step 2: Update the redfish-exporter.yml with correct IPs if needed
echo "→ Verifying console node IPs are correct (10.10.1.11-14)..."
if ! grep -q "10.10.1.11" "$MONITORING_DIR/redfish-exporter.yml"; then
    echo "  ⚠ Updating console node IPs in redfish-exporter.yml..."
    sed -i 's/10\.10\.1\.21/10.10.1.11/g' "$MONITORING_DIR/redfish-exporter.yml"
    sed -i 's/10\.10\.1\.22/10.10.1.12/g' "$MONITORING_DIR/redfish-exporter.yml"
    sed -i 's/10\.10\.1\.23/10.10.1.13/g' "$MONITORING_DIR/redfish-exporter.yml"
    sed -i 's/10\.10\.1\.24/10.10.1.14/g' "$MONITORING_DIR/redfish-exporter.yml"
fi

# Step 3: Deploy the Redfish exporter
echo "→ Deploying Redfish exporter..."
kubectl apply -f "$MONITORING_DIR/redfish-exporter.yml"

# Step 4: Deploy the hardware monitoring dashboards
echo "→ Deploying Grafana dashboards..."

# Fix the original dashboard if it has the wrong color mode
if grep -q '"mode": "value"' "$MONITORING_DIR/hardware-dashboard.yml" 2>/dev/null; then
    echo "  ⚠ Fixing color mode in hardware-dashboard.yml..."
    sed -i 's/"mode": "value"/"mode": "thresholds"/g' "$MONITORING_DIR/hardware-dashboard.yml"
fi

kubectl apply -f "$MONITORING_DIR/hardware-dashboard.yml" 2>/dev/null || true
kubectl apply -f "$MONITORING_DIR/hardware-graphs-dashboard.yml"

# Step 5: Wait for deployment to be ready
echo "→ Waiting for Redfish exporter to be ready..."
kubectl rollout status deployment/redfish-exporter -n monitoring --timeout=300s

# Step 6: Verify the exporter is running
echo "→ Verifying Redfish exporter status..."
POD_NAME=$(kubectl get pods -n monitoring -l app=redfish-exporter -o jsonpath='{.items[0].metadata.name}')
if [ -n "$POD_NAME" ]; then
    echo "  ✓ Redfish exporter pod is running: $POD_NAME"
    
    # Check if it's collecting metrics
    echo "→ Checking metrics collection (this may take up to 60 seconds)..."
    sleep 10
    
    if kubectl exec -n monitoring "$POD_NAME" -- timeout 5 curl -s http://localhost:9101/health > /dev/null 2>&1; then
        echo "  ✓ Health endpoint is responding"
    fi
    
    # Check for actual metrics
    METRICS_COUNT=$(kubectl exec -n monitoring "$POD_NAME" -- timeout 30 curl -s http://localhost:9101/metrics 2>/dev/null | grep -c "redfish_temperature_celsius{" || echo "0")
    if [ "$METRICS_COUNT" -gt 0 ]; then
        echo "  ✓ Collecting hardware metrics: $METRICS_COUNT temperature sensors found"
    else
        echo "  ⚠ No metrics found yet - collection may still be in progress"
    fi
else
    echo "  ⚠ Redfish exporter pod not found"
fi

# Step 7: Check Prometheus integration
echo "→ Checking Prometheus integration..."
PROMETHEUS_SVC=$(kubectl get svc -n monitoring | grep prometheus | grep -v node-exporter | grep -v operator | head -1 | awk '{print $1}')
if [ -n "$PROMETHEUS_SVC" ]; then
    # Port forward in background
    kubectl port-forward -n monitoring "svc/$PROMETHEUS_SVC" 19091:9090 > /dev/null 2>&1 &
    PF_PID=$!
    sleep 5
    
    # Check if Prometheus has the target
    TARGET_STATUS=$(curl -s "http://localhost:19091/api/v1/targets" 2>/dev/null | jq -r '.data.activeTargets[] | select(.labels.job=="redfish-exporter") | .health' | head -1)
    
    if [ "$TARGET_STATUS" = "up" ]; then
        echo "  ✓ Prometheus is successfully scraping Redfish exporter"
        
        # Check for actual metrics in Prometheus
        PROM_METRICS=$(curl -s "http://localhost:19091/api/v1/query?query=redfish_temperature_celsius" 2>/dev/null | jq '.data.result | length')
        if [ "$PROM_METRICS" -gt 0 ]; then
            echo "  ✓ Prometheus has $PROM_METRICS temperature metrics"
        fi
    elif [ "$TARGET_STATUS" = "down" ]; then
        echo "  ⚠ Prometheus target is down - may need more time to collect"
    else
        echo "  ⚠ Prometheus target not found - checking ServiceMonitor..."
        kubectl get servicemonitor -n monitoring redfish-exporter > /dev/null 2>&1 && echo "  ✓ ServiceMonitor exists"
    fi
    
    # Clean up port forward
    kill $PF_PID 2>/dev/null || true
fi

echo ""
echo "==========================================="
echo "Hardware Monitoring Deployment Complete!"
echo "==========================================="
echo ""
echo "Access points:"
echo "  • Grafana: http://$(kubectl get svc -n monitoring kube-prometheus-stack-grafana -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "10.10.1.50")"
echo "  • Dashboard: Hardware Monitoring - Graphs"
echo ""
echo "Monitoring:"
echo "  • Console nodes: 10.10.1.11-14"
echo "  • Collection interval: 60 seconds"
echo "  • Sensors: CPU, System, Memory, Network, Fans"
echo ""
echo "To troubleshoot:"
echo "  kubectl logs -n monitoring -l app=redfish-exporter --tail=20"
echo ""