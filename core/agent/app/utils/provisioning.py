# DEPRECATED — kept for backward compat. Import from service.clients directly.
# - HTTP provisioning: service.clients.provisioning
# - Ansible provisioning: service.clients.ansible_provisioning
# - Mock/test double: service.clients.mock_provisioning
from service.clients.mock_provisioning import (  # noqa: F401
    provision_machine_async,
    schedule_vm_shutdown_async,
    get_vm_available_resources,
)
from service.clients.ansible_provisioning import (  # noqa: F401
    _cleanup_temp_file,
    _find_project_root,
    _extract_external_port,
    _extract_tenant_user,
    _lookup_vm_host_ip,
)
