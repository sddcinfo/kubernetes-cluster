# Hardware Monitoring Stack

This directory contains the Kubernetes manifests and dashboards for hardware monitoring via Redfish API.

## Overview

The hardware monitoring stack collects sensor data from Supermicro IPMI interfaces using the Redfish API and exposes metrics to Prometheus for visualization in Grafana.

## Architecture

```
Console Nodes (IPMI) → Redfish Exporter → Prometheus → Grafana Dashboards
  10.10.1.11-14          (Pod in K8s)      (Scraping)    (Visualization)
```

## Components

### Files

- `redfish-exporter.yml` - Main deployment with ConfigMap-based approach
- `redfish-exporter-simple.yml` - Alternative deployment with embedded script
- `hardware-dashboard.yml` - Original comprehensive dashboard
- `hardware-graphs-dashboard.yml` - Clean graph-only dashboard
- `README.md` - This documentation

### Scripts

- `/scripts/deploy-hardware-monitoring.sh` - Deploy hardware monitoring only
- `/scripts/deploy-complete-monitoring.sh` - Deploy entire monitoring stack

## Important Configuration

### Console Node IPs (CORRECT)
- console-node1: **10.10.1.11** (NOT 10.10.1.21)
- console-node2: **10.10.1.12** (NOT 10.10.1.22)
- console-node3: **10.10.1.13** (NOT 10.10.1.23)
- console-node4: **10.10.1.14** (NOT 10.10.1.24)

**Note**: 10.10.1.21-24 are the Proxmox host IPs. We monitor via the Supermicro IPMI/console IPs at 10.10.1.11-14.

### Credentials (CORRECT)
- Username: **admin**
- Password: **[see ~/.redfish_credentials]**
- Auth String: **admin:[see ~/.redfish_credentials]**

**Note**: Do NOT use root:calvin - this doesn't work with our Supermicro IPMI setup.

## Deployment

### Quick Deploy (Recommended)

Deploy the complete monitoring stack:
```bash
/home/sysadmin/claude/kubernetes-cluster/scripts/deploy-complete-monitoring.sh
```

### Manual Deploy

1. Create namespace and credentials:
```bash
kubectl create namespace monitoring
kubectl create secret generic redfish-credentials -n monitoring \
  --from-literal="redfish_credentials=REDFISH_AUTH=\"admin:[see ~/.redfish_credentials]\""
```

2. Deploy Redfish exporter:
```bash
kubectl apply -f redfish-exporter.yml
```

3. Deploy dashboards:
```bash
kubectl apply -f hardware-dashboard.yml
kubectl apply -f hardware-graphs-dashboard.yml
```

## Verification

Check if metrics are being collected:
```bash
# Check pod status
kubectl get pods -n monitoring -l app=redfish-exporter

# Check logs
kubectl logs -n monitoring -l app=redfish-exporter --tail=20

# Test metrics endpoint
POD=$(kubectl get pods -n monitoring -l app=redfish-exporter -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n monitoring $POD -- curl -s http://localhost:9101/metrics | grep redfish_temperature
```

## Dashboards

Access Grafana at http://10.10.1.50

### Available Dashboards

1. **Hardware Monitoring** - Comprehensive dashboard with tables and multiple panel types
2. **Hardware Monitoring - Graphs** - Clean, focused graph-only view

### Metrics Collected

- **Temperature Sensors**:
  - CPU Temperature
  - System Temperature
  - Memory (DIMM) Temperatures
  - 10G Network Card Temperature
  - Peripheral Temperature

- **Fan Speeds**:
  - FAN1-4 RPM readings

## Troubleshooting

### No Data in Dashboard

1. Check correct IPs (10.10.1.11-14, not .21-24)
2. Check credentials (admin:[see ~/.redfish_credentials], not root:calvin)
3. Verify network connectivity:
```bash
kubectl run test --image=nicolaka/netshoot --rm --restart=Never -- ping -c 3 10.10.1.11
```

### Collection Timeouts

The Redfish API calls can be slow. Collection interval is set to 60 seconds with appropriate timeouts.

### Dashboard Errors

If you see color mode errors, ensure dashboard uses `"mode": "thresholds"` not `"mode": "value"`.

## Key Lessons Learned

1. **IP Confusion**: Console nodes (Supermicro IPMI) are at 10.10.1.11-14, NOT the Proxmox host IPs
2. **Credentials**: Must use admin:[see ~/.redfish_credentials], not the default root:calvin
3. **Network Access**: Kubernetes pods CAN reach the console network (10.10.1.x)
4. **Dashboard Compatibility**: Grafana color modes must use "thresholds" not "value"
5. **Collection Timing**: Redfish API is slow, need appropriate timeouts and caching

## Files That Were Fixed

During deployment, these issues were corrected:
- nodes.json: IPs changed from .21-24 to .11-14
- Secret: Credentials changed from root:calvin to admin:[see ~/.redfish_credentials]
- Dashboard: Color mode changed from "value" to "thresholds"
- Container paths: Fixed nodes.json location and credentials path