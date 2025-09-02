# Cluster Recovery Procedures

This document outlines the procedures for recovering from cluster-wide outages based on lessons learned from actual incidents.

## Power Outage Recovery Checklist

### Phase 1: Infrastructure Assessment
1. **Check Proxmox Node Status**
   ```bash
   for node in node1 node2 node3 node4; do
       echo "=== $node ==="
       ping -c 1 10.10.1.1$((${node#node} + 10)) && echo "UP" || echo "DOWN"
   done
   ```

2. **Verify Ceph Cluster Health**
   ```bash
   ssh root@node1 "ceph -s"
   ssh root@node1 "ceph osd stat"
   ssh root@node1 "ceph mon stat"
   ```

### Phase 2: Ceph Recovery
If Ceph is not healthy, follow these steps:

1. **Check Monitor Status**
   ```bash
   for node in node1 node2 node3; do
       ssh root@$node "systemctl status ceph-mon@$node | grep Active:"
   done
   ```

2. **Add Firewall Rules for Ceph (if missing)**
   ```bash
   for node in node1 node2 node3 node4; do
       ssh root@$node "iptables -I INPUT -p tcp --dport 3300 -s 10.10.2.0/24 -j ACCEPT"
       ssh root@$node "iptables -I INPUT -p tcp --dport 6789 -s 10.10.2.0/24 -j ACCEPT"
   done
   ```

3. **Restart Monitors if Needed**
   ```bash
   for node in node1 node2 node3; do
       ssh root@$node "systemctl restart ceph-mon@$node"
   done
   ```

4. **Fix Manager Issues**
   ```bash
   for node in node1 node2 node3; do
       ssh root@$node "rm -f /var/run/ceph/ceph-mgr.$node.asok"
       ssh root@$node "systemctl restart ceph-mgr@$node"
   done
   ```

5. **Start OSDs**
   ```bash
   ssh root@node1 "systemctl start ceph-osd@0 ceph-osd@1" &
   ssh root@node2 "systemctl start ceph-osd@2 ceph-osd@3" &
   ssh root@node3 "systemctl start ceph-osd@4 ceph-osd@5" &
   ssh root@node4 "systemctl start ceph-osd@6 ceph-osd@7" &
   wait
   ```

### Phase 3: VM Recovery
1. **Remove Stale Lock Files**
   ```bash
   for node in node1 node2 node3 node4; do
       ssh root@$node "rm -f /var/lock/qemu-server/lock-*.conf"
   done
   ```

2. **Start Kubernetes VMs**
   ```bash
   # Control plane VMs
   ssh root@node1 "qm start 131" &  # k8s-control-1
   ssh root@node2 "qm start 132" &  # k8s-control-2
   ssh root@node3 "qm start 133" &  # k8s-control-3
   
   # Worker VMs
   ssh root@node1 "qm start 140" &  # k8s-worker-1
   ssh root@node2 "qm start 141" &  # k8s-worker-2
   ssh root@node3 "qm start 142" &  # k8s-worker-3
   ssh root@node4 "qm start 143" &  # k8s-worker-4
   
   # Load balancer
   ssh root@node4 "qm start 130" &  # k8s-haproxy
   wait
   ```

### Phase 4: Kubernetes Verification
1. **Check Node Status**
   ```bash
   kubectl --kubeconfig=/home/sysadmin/.kube/config-direct get nodes
   ```

2. **Verify Pod Status**
   ```bash
   kubectl --kubeconfig=/home/sysadmin/.kube/config-direct get pods -A
   ```

## Prevention Measures

### VM Auto-Start Configuration
Ensure all critical VMs have auto-start enabled:
```bash
# Run on each Proxmox node
ssh root@node1 "qm set 131 --onboot 1; qm set 140 --onboot 1"
ssh root@node2 "qm set 132 --onboot 1; qm set 141 --onboot 1"
ssh root@node3 "qm set 133 --onboot 1; qm set 142 --onboot 1"
ssh root@node4 "qm set 130 --onboot 1; qm set 143 --onboot 1"
```

### Monitoring Setup
- Deploy cluster monitoring stack to detect outages early
- Configure alerts for Ceph health degradation
- Monitor VM auto-start failures

### Network Configuration
- Ensure storage network (10.10.2.x) has proper firewall rules
- Avoid using fail2ban on Proxmox nodes (interferes with Ceph)
- Document network dependencies and single points of failure

## Common Issues and Solutions

### Issue: Ceph Monitors Stuck in "Probing" State
**Solution**: Check firewall rules for ports 3300 and 6789, restart monitors in sequence

### Issue: VM Lock Files Prevent Startup
**Solution**: Remove stale lock files from `/var/lock/qemu-server/`

### Issue: PGs in "Unknown" State
**Solution**: Wait for OSD startup to complete, force PG repair if necessary

### Issue: Network Connectivity Between Nodes
**Solution**: Verify physical links, check bridge configurations, test with `nc -zv`

## Emergency Contacts
- Document hosting provider contact information
- Maintain list of personnel with physical access
- Keep IPMI/iDRAC credentials accessible

## Recovery Time Expectations
- **Ceph Recovery**: 5-15 minutes after nodes are up
- **VM Startup**: 2-5 minutes per VM
- **Kubernetes Ready**: 10-15 minutes after VMs are running
- **Total Recovery**: 30-45 minutes for complete cluster restoration

## Post-Recovery Actions
1. Verify all applications are functioning
2. Check backup integrity
3. Review logs for root cause analysis
4. Update documentation with lessons learned
5. Test recovery procedures periodically