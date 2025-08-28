# Template Configuration System

## Overview

The Kubernetes cluster deployment system uses a shared YAML configuration file to manage Proxmox VM template IDs and settings across multiple repositories and scripts. This ensures consistency and makes it easy to update template configurations in one place.

## Configuration File

The template configuration is stored in: `~/proxmox-config/templates.yaml`

This provides a single, shared configuration location:
- **ansible-provisioning-server** repository (creates and configures templates)
- **kubernetes-cluster** repository (references the shared configuration)

## Configuration Structure

```yaml
templates:
  base:
    id: 9000                    # Proxmox VM ID for base template
    name: ubuntu-base-template
    description: Ubuntu 24.04 Base Template - qemu-agent + cloud-init
    memory: 2048
    cores: 2
    disk_size: 32G
    
  kubernetes:
    id: 9001                    # Proxmox VM ID for K8s template
    name: ubuntu-k8s-template
    description: Ubuntu 24.04 with Kubernetes 1.33.4 pre-installed
    memory: 4096
    cores: 4
    disk_size: 32G
    k8s_version: 1.33.4

cloud_image:
  url: https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img
  japan_mirror: https://ftp.riken.jp/Linux/ubuntu-releases
  cached_path: /mnt/rbd-iso/template/images/ubuntu-24.04-cloudimg-cached.img

ssh:
  key_path: /home/sysadmin/.ssh/sysadmin_automation_key
  public_key_path: /home/sysadmin/.ssh/sysadmin_automation_key.pub
  user: sysadmin
  
proxmox:
  host: 10.10.1.21
  storage: rbd
  bridge: vmbr0
```

## Script Updates

All scripts now load template configuration from the YAML file:

### template-manager.py
```python
def __init__(self, config_file=None):
    self.config = self.load_config(config_file)
    self.templates['base']['id'] = self.config['templates']['base']['id']
    self.templates['k8s']['id'] = self.config['templates']['kubernetes']['id']
```

### cluster-deploy.py
```python
def load_template_config(self) -> dict:
    # Loads from config/templates.yaml
    template_config = self.load_template_config()
    k8s_template_id = template_config['templates']['kubernetes']['id']
```

### provision-control-node.py
```python
template_config = load_template_config()
TEMPLATE_ID = template_config['templates']['kubernetes']['id']
```

### cluster-manager.py
```python
self.template_config = self.load_template_config()
self.templates['base']['id'] = self.template_config['templates']['base']['id']
self.templates['k8s']['id'] = self.template_config['templates']['kubernetes']['id']
```

## Configuration Setup

### Initial Setup
Run the bootstrap script from ansible-provisioning-server to create the configuration:

```bash
# From ansible-provisioning-server repository
./scripts/bootstrap-config.sh
```

This creates `~/proxmox-config/templates.yaml` with default values that you can customize.

### Configuration Lookup Order

Scripts search for the configuration file in the following locations:
1. `~/proxmox-config/templates.yaml` (primary location)
2. `/home/sysadmin/claude/ansible-provisioning-server/config/templates.yaml` (fallback)
3. `~/.config/proxmox-templates.yaml` (legacy fallback)

If no configuration file is found, scripts fall back to hardcoded defaults (9000 for base, 9001 for kubernetes).

## Migration Path

### Moving template-manager.py to ansible-provision-server

1. Copy `template-manager.py` to ansible-provision-server repo
2. Copy `config/templates.yaml` to ansible-provision-server repo
3. Both repos will share the same template ID configuration
4. Update ansible-provision-server README to note it creates templates
5. Update kubernetes-cluster README to note dependency on templates

### Synchronization

To keep template IDs synchronized between repositories:
- Option 1: Symlink the config file between repos
- Option 2: Use a git submodule for shared configuration
- Option 3: Copy the file and document the need to keep in sync
- Option 4: Use environment variables (e.g., `PROXMOX_K8S_TEMPLATE_ID`)

## Benefits

1. **Single source of truth** - Template IDs defined in one place
2. **Easy updates** - Change template IDs without modifying code
3. **Repository independence** - Scripts can move between repos
4. **Clear dependencies** - Configuration makes dependencies explicit
5. **Flexibility** - Easy to add new template types or modify existing ones

## Future Enhancements

- Add support for multiple template versions
- Include network configuration in templates.yaml
- Add template validation checksums
- Support for template inheritance/variants
- Integration with CI/CD pipelines for automated template updates