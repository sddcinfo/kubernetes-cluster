#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING: $1${NC}"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $1${NC}"
}

# Check prerequisites
check_prerequisites() {
    log "Checking prerequisites..."
    
    # Check if running as root or with sudo
    if [[ $EUID -eq 0 ]]; then
        error "This script should not be run as root. Please run as a regular user with sudo privileges."
        exit 1
    fi
    
    # Check required tools
    local tools=("packer" "terraform" "ansible-playbook" "ssh-keygen")
    local missing_tools=()
    
    for tool in "${tools[@]}"; do
        if ! command -v "$tool" &> /dev/null; then
            missing_tools+=("$tool")
        fi
    done
    
    if [ ${#missing_tools[@]} -gt 0 ]; then
        error "Missing required tools: ${missing_tools[*]}"
        log "Please install the missing tools and try again."
        exit 1
    fi
    
    # Check SSH key
    if [ ! -f ~/.ssh/id_rsa.pub ]; then
        log "Generating SSH key pair..."
        ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa -N ""
    fi
    
    log "Prerequisites check completed successfully."
}

# Deploy the entire Kubernetes cluster
deploy_cluster() {
    log "Starting Kubernetes cluster deployment on Proxmox..."
    
    # Phase 1: Build VM template with Packer
    log "Phase 1: Building VM template with Packer..."
    cd packer
    
    if [ ! -f "terraform.tfvars" ]; then
        error "Please create packer/variables.json with your Proxmox credentials:"
        echo '{
  "proxmox_url": "https://10.10.1.21:8006/api2/json",
  "proxmox_token": "your-api-token-here",
  "proxmox_user": "packer@pam!packer"
}'
        exit 1
    fi
    
    log "Building Ubuntu 24.04 Kubernetes template..."
    packer build -var-file="variables.json" ubuntu-24.04-k8s.pkr.hcl
    
    cd ..
    
    # Phase 2: Provision VMs with Terraform
    log "Phase 2: Provisioning VMs with Terraform..."
    cd terraform
    
    if [ ! -f "terraform.tfvars" ]; then
        error "Please create terraform/terraform.tfvars with your configuration:"
        echo 'proxmox_token = "your-api-token-here"
ssh_public_key = ""  # Leave empty to use ~/.ssh/id_rsa.pub'
        exit 1
    fi
    
    terraform init
    terraform plan
    terraform apply -auto-approve
    
    cd ..
    
    # Phase 3: Configure and bootstrap Kubernetes with Ansible
    log "Phase 3: Bootstrapping Kubernetes cluster with Ansible..."
    cd ansible
    
    # Wait for VMs to be ready
    log "Waiting for VMs to be ready..."
    sleep 60
    
    # Run Ansible playbook
    log "Running Ansible playbook to configure Kubernetes cluster..."
    ansible-playbook -i inventory/terraform-inventory.ini playbook.yml
    
    cd ..
    
    log "Kubernetes cluster deployment completed successfully!"
    log "Access your cluster using: kubectl --kubeconfig ./ansible/kubeconfig get nodes"
}

# Deploy monitoring stack
deploy_monitoring() {
    log "Deploying monitoring and logging stack..."
    
    # Apply monitoring manifests
    kubectl apply -f monitoring/
    
    log "Monitoring stack deployed. Access Grafana at the LoadBalancer IP."
}

# Deploy backup solution
deploy_backup() {
    log "Deploying backup solution..."
    
    kubectl create namespace backup --dry-run=client -o yaml | kubectl apply -f -
    kubectl apply -f backup/
    
    log "Backup solution deployed."
}

# Main deployment function
main() {
    log "=== Kubernetes on Proxmox Deployment Script ==="
    log "This script will deploy a production-grade Kubernetes cluster on your Proxmox infrastructure."
    log ""
    
    case "${1:-all}" in
        "prerequisites")
            check_prerequisites
            ;;
        "cluster")
            check_prerequisites
            deploy_cluster
            ;;
        "monitoring")
            deploy_monitoring
            ;;
        "backup")
            deploy_backup
            ;;
        "all")
            check_prerequisites
            deploy_cluster
            deploy_monitoring
            deploy_backup
            ;;
        *)
            echo "Usage: $0 [prerequisites|cluster|monitoring|backup|all]"
            echo ""
            echo "  prerequisites  - Check and install prerequisites"
            echo "  cluster       - Deploy the Kubernetes cluster"
            echo "  monitoring    - Deploy monitoring and logging"
            echo "  backup        - Deploy backup solution"
            echo "  all           - Deploy everything (default)"
            exit 1
            ;;
    esac
    
    log "=== Deployment completed successfully! ==="
}

# Run main function
main "$@"