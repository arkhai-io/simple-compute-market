# Compute provisioning: Ansible

`arkhai-compute-provisioning-ansible` (`compute_provisioning_ansible`) is the
compute family kit's optional Ansible implementation distribution. It provides
the `ssh` connection codec the host authority stores host connections with, and
it depends on `arkhai-compute-provisioning`; nothing in that package depends on
it, so consumers of jobs or hosts do not install Ansible mechanics.
