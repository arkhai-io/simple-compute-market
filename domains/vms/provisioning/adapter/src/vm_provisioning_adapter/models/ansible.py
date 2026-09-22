from pydantic import BaseModel, Field


class ConnectivityResult(BaseModel):
    """Result of running ``ansible -m ping`` against a single inventory host."""

    host: str = Field(description="Host alias that was tested.")
    reachable: bool = Field(
        description="True if Ansible could authenticate and execute on the host."
    )
    detail: str = Field(
        description="Ansible stdout on success, or the error message on failure."
    )
