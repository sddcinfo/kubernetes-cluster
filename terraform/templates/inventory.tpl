[control_plane]
%{ for name, config in control_nodes ~}
${name} ansible_host=${config.ip} vm_id=${config.id}
%{ endfor ~}

[workers]
%{ for name, config in worker_nodes ~}
${name} ansible_host=${config.ip} vm_id=${config.id}
%{ endfor ~}

[kubernetes:children]
control_plane
workers

[kubernetes:vars]
ansible_user=ubuntu
ansible_ssh_private_key_file=~/.ssh/id_rsa
ansible_ssh_common_args='-o StrictHostKeyChecking=no'
control_plane_vip=10.10.1.100