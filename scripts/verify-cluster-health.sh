#!/bin/bash
# Cluster Health Verification Script
# Checks critical components after recovery or during routine maintenance

set -e

LOG_FILE="/var/log/cluster-health-check.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

log() {
    echo "[$TIMESTAMP] $1" | tee -a "$LOG_FILE"
}

error_exit() {
    log "ERROR: $1"
    exit 1
}

log "=========================================="
log "Starting cluster health verification"
log "=========================================="

# Check Proxmox node connectivity
log "1. Checking Proxmox node connectivity..."
NODES_UP=0
for i in 1 2 3 4; do
    ip="10.10.1.1$i"
    if ping -c 1 -W 2 "$ip" >/dev/null 2>&1; then
        log "  node$i ($ip): UP"
        NODES_UP=$((NODES_UP + 1))
    else
        log "  node$i ($ip): DOWN"
    fi
done

if [ $NODES_UP -lt 3 ]; then
    error_exit "Less than 3 Proxmox nodes are reachable. Cluster may not be functional."
fi

log "  Result: $NODES_UP/4 nodes reachable"

# Check Ceph cluster health
log "2. Checking Ceph cluster health..."
if ! ssh root@node1 "timeout 10 ceph health" >/dev/null 2>&1; then
    log "  WARNING: Cannot connect to Ceph or command timed out"
    CEPH_STATUS="UNKNOWN"
else
    CEPH_STATUS=$(ssh root@node1 "ceph health" 2>/dev/null || echo "ERROR")
    log "  Ceph health: $CEPH_STATUS"
    
    if [ "$CEPH_STATUS" != "HEALTH_OK" ]; then
        log "  Detailed Ceph status:"
        ssh root@node1 "ceph -s" 2>/dev/null | while read line; do
            log "    $line"
        done
    fi
fi

# Check Ceph monitors
log "3. Checking Ceph monitors..."
MON_COUNT=0
for node in node1 node2 node3; do
    if ssh root@$node "systemctl is-active ceph-mon@$node" >/dev/null 2>&1; then
        log "  $node monitor: ACTIVE"
        MON_COUNT=$((MON_COUNT + 1))
    else
        log "  $node monitor: INACTIVE"
    fi
done
log "  Result: $MON_COUNT/3 monitors active"

# Check Ceph OSDs
log "4. Checking Ceph OSDs..."
if [ "$CEPH_STATUS" != "ERROR" ]; then
    OSD_INFO=$(ssh root@node1 "ceph osd stat" 2>/dev/null || echo "ERROR")
    if [ "$OSD_INFO" != "ERROR" ]; then
        log "  OSD status: $OSD_INFO"
    else
        log "  WARNING: Cannot retrieve OSD status"
    fi
fi

# Check VM status
log "5. Checking Kubernetes VM status..."
VM_COUNT=0
TOTAL_VMS=8

# Define VMs: node:vmid:name
VMS="node1:131:k8s-control-1 node1:140:k8s-worker-1 node2:132:k8s-control-2 node2:141:k8s-worker-2 node3:133:k8s-control-3 node3:142:k8s-worker-3 node4:130:k8s-haproxy node4:143:k8s-worker-4"

for vm_info in $VMS; do
    node=$(echo $vm_info | cut -d: -f1)
    vmid=$(echo $vm_info | cut -d: -f2)
    name=$(echo $vm_info | cut -d: -f3)
    
    status=$(ssh root@$node "qm status $vmid 2>/dev/null | awk '{print \$2}'" || echo "ERROR")
    if [ "$status" = "running" ]; then
        log "  $name (VM $vmid on $node): RUNNING"
        VM_COUNT=$((VM_COUNT + 1))
    else
        log "  $name (VM $vmid on $node): $status"
    fi
done

log "  Result: $VM_COUNT/$TOTAL_VMS VMs running"

# Check Kubernetes cluster
log "6. Checking Kubernetes cluster..."
if [ -f /home/sysadmin/.kube/config-direct ]; then
    K8S_NODES=$(kubectl --kubeconfig=/home/sysadmin/.kube/config-direct get nodes --no-headers 2>/dev/null | wc -l || echo "0")
    K8S_READY=$(kubectl --kubeconfig=/home/sysadmin/.kube/config-direct get nodes --no-headers 2>/dev/null | grep -c " Ready " || echo "0")
    
    log "  Kubernetes nodes: $K8S_READY/$K8S_NODES ready"
    
    if [ "$K8S_NODES" -gt 0 ]; then
        log "  Node details:"
        kubectl --kubeconfig=/home/sysadmin/.kube/config-direct get nodes 2>/dev/null | while read line; do
            log "    $line"
        done
    fi
else
    log "  WARNING: Kubernetes config not found at /home/sysadmin/.kube/config-direct"
fi

# Check critical pods
log "7. Checking critical pods..."
if [ -f /home/sysadmin/.kube/config-direct ]; then
    # Check system pods
    SYSTEM_PODS=$(kubectl --kubeconfig=/home/sysladmin/.kube/config-direct get pods -n kube-system --no-headers 2>/dev/null | wc -l || echo "0")
    SYSTEM_READY=$(kubectl --kubeconfig=/home/sysadmin/.kube/config-direct get pods -n kube-system --no-headers 2>/dev/null | grep -c " Running " || echo "0")
    
    log "  System pods: $SYSTEM_READY/$SYSTEM_PODS running"
    
    # Check for failed pods
    FAILED_PODS=$(kubectl --kubeconfig=/home/sysadmin/.kube/config-direct get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded --no-headers 2>/dev/null | wc -l || echo "0")
    if [ "$FAILED_PODS" -gt 0 ]; then
        log "  WARNING: $FAILED_PODS pods in failed state"
        kubectl --kubeconfig=/home/sysadmin/.kube/config-direct get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded 2>/dev/null | while read line; do
            log "    $line"
        done
    fi
fi

# Storage connectivity test
log "8. Testing storage connectivity..."
TEST_FILE="/tmp/ceph-connectivity-test-$$"
if ssh root@node1 "echo 'test' > $TEST_FILE && rm -f $TEST_FILE" 2>/dev/null; then
    log "  Storage connectivity: OK"
else
    log "  WARNING: Storage connectivity test failed"
fi

# Network connectivity test between nodes
log "9. Testing inter-node connectivity..."
NETWORK_OK=true
for src in 1 2 3; do
    for dst in 1 2 3; do
        if [ $src -ne $dst ]; then
            src_ip="10.10.2.2$src"
            dst_ip="10.10.2.2$dst"
            if ssh root@node$src "timeout 2 nc -zv $dst_ip 6789" >/dev/null 2>&1; then
                log "  node$src -> node$dst (Ceph): OK"
            else
                log "  node$src -> node$dst (Ceph): FAILED"
                NETWORK_OK=false
            fi
        fi
    done
done

# Summary
log "=========================================="
log "Health Check Summary"
log "=========================================="
log "Proxmox nodes: $NODES_UP/4 reachable"
log "Ceph health: $CEPH_STATUS"
log "Ceph monitors: $MON_COUNT/3 active"
log "Kubernetes VMs: $VM_COUNT/$TOTAL_VMS running"
if [ -f /home/sysadmin/.kube/config-direct ]; then
    log "Kubernetes nodes: $K8S_READY/$K8S_NODES ready"
    log "Failed pods: $FAILED_PODS"
fi
log "Network connectivity: $([ "$NETWORK_OK" = true ] && echo "OK" || echo "ISSUES DETECTED")"

# Overall health assessment
OVERALL_HEALTH="HEALTHY"
if [ $NODES_UP -lt 3 ] || [ "$CEPH_STATUS" != "HEALTH_OK" ] || [ $MON_COUNT -lt 2 ] || [ $VM_COUNT -lt 6 ]; then
    OVERALL_HEALTH="DEGRADED"
fi

if [ "$NETWORK_OK" = false ]; then
    OVERALL_HEALTH="CRITICAL"
fi

log "Overall cluster health: $OVERALL_HEALTH"
log "=========================================="

# Exit with appropriate code
case $OVERALL_HEALTH in
    "HEALTHY") exit 0 ;;
    "DEGRADED") exit 1 ;;
    "CRITICAL") exit 2 ;;
esac