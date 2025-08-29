#!/bin/bash
# Quick script to activate Kubespray environment
cd "$(dirname "$0")/kubespray"
source venv/bin/activate
echo "Kubespray environment activated!"
echo "Current directory: $(pwd)"
echo "Available playbooks:"
echo "  - cluster.yml (deploy cluster)"
echo "  - scale.yml (add nodes)"
echo "  - upgrade-cluster.yml (upgrade)"
echo "  - reset.yml (destroy cluster)"
echo ""
echo "Example deployment command:"
echo "  ansible-playbook -i inventory/proxmox-cluster/inventory.ini cluster.yml"
