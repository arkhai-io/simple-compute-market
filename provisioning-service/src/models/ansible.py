from pydantic import BaseModel, Field


class InventoryHost(BaseModel):
    """A single host entry parsed from the Ansible INI inventory."""

    name: str = Field(description="Host alias as it appears in the inventory.")
    ansible_host: str | None = Field(
        default=None, description="IP address or hostname resolved for SSH."
    )
    vars: dict[str, str] = Field(
        default_factory=dict,
        description="Remaining inline variables from the inventory line.",
    )


class InventoryResponse(BaseModel):
    """All hosts returned from the current Ansible inventory file."""

    inventory_path: str = Field(
        description="Absolute path to the inventory file that was parsed."
    )
    hosts: list[InventoryHost] = Field(description="Parsed host entries.")


class ConnectivityResult(BaseModel):
    """Result of running ``ansible -m ping`` against a single inventory host."""

    host: str = Field(description="Host alias that was tested.")
    reachable: bool = Field(
        description="True if Ansible could authenticate and execute on the host."
    )
    detail: str = Field(
        description="Ansible stdout on success, or the error message on failure."
    )
