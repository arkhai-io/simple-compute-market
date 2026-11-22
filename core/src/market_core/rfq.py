"""Market-neutral wire contracts for registry requests for quotes."""

from dataclasses import dataclass
from enum import Enum
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from market_core.registry_descriptor import (
    RegistryAuthorityName,
    RegistryPrincipal,
)

RfqReference = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")
]
_reference: TypeAdapter[str] = TypeAdapter(RfqReference)


class RfqOperation(str, Enum):
    CREATE = "rfq.create"
    SEARCH = "rfq.search"
    READ = "rfq.read"
    EDIT = "rfq.edit"
    CLOSE = "rfq.close"
    RESPOND = "rfq.respond"
    LIST_RESPONSES = "rfq.responses.list"
    READ_RESPONSE = "rfq.responses.read"
    RECONFIRM = "rfq.responses.reconfirm"
    WITHDRAW = "rfq.responses.withdraw"
    DISMISS = "rfq.responses.dismiss"
    SELECT = "rfq.responses.select"
    READ_INTRODUCTION = "rfq.introductions.read"
    END_INTRODUCTION = "rfq.introductions.end"

    @property
    def is_read(self) -> bool:
        return self in {
            self.SEARCH, self.READ, self.LIST_RESPONSES, self.READ_RESPONSE,
            self.READ_INTRODUCTION,
        }

    @property
    def shares_contact(self) -> bool:
        return self in {self.RESPOND, self.RECONFIRM, self.SELECT}


@dataclass(frozen=True)
class RfqTarget:
    """The semantic resource a route derives independently from the request body."""

    method: ClassVar[Literal["POST"]] = "POST"

    operation: RfqOperation
    rfq_id: str | None = None
    response_id: str | None = None
    introduction_id: str | None = None

    def __post_init__(self) -> None:
        for reference in (self.rfq_id, self.response_id, self.introduction_id):
            if reference is not None:
                _reference.validate_python(reference, strict=True)
        operation = self.operation
        if operation in {operation.CREATE, operation.SEARCH}:
            expected = (False, False, False)
        elif operation in {operation.READ_INTRODUCTION, operation.END_INTRODUCTION}:
            expected = (False, False, True)
        elif operation in {
            operation.READ_RESPONSE, operation.RECONFIRM, operation.WITHDRAW,
            operation.DISMISS, operation.SELECT,
        }:
            expected = (True, True, False)
        else:
            expected = (True, False, False)
        present = (
            self.rfq_id is not None, self.response_id is not None,
            self.introduction_id is not None,
        )
        if present != expected:
            raise ValueError("invalid resource references for RFQ operation")

    @property
    def resource(self) -> str:
        if self.introduction_id is not None:
            return f"rfqs/introductions/{self.introduction_id}"
        if self.response_id is not None:
            return f"rfqs/{self.rfq_id}/responses/{self.response_id}"
        if self.rfq_id is not None:
            return f"rfqs/{self.rfq_id}"
        return "rfqs"


class RfqAccountClaim(BaseModel):
    """Account admission asserted by the trusted account authority."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)

    namespace: RfqReference
    subject: str = Field(min_length=1, max_length=255, pattern=r"^[^\x00-\x1f\x7f]+$", repr=False)
    can_share_contact: bool = False


class RfqAudience(BaseModel):
    """The configured authority name and exact public registry principal."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    name: RegistryAuthorityName
    principal: RegistryPrincipal


class RfqInvocation(BaseModel):
    """The body bound to an account-authority request signature."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)

    account: RfqAccountClaim
    audience: RfqAudience
    inputs: dict[str, JsonValue] = Field(repr=False)


class RfqMutationReceipt(BaseModel):
    """The fields an RFQ mutation may retain and return on replay."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)

    resource_id: RfqReference
    state: Literal[
        "open", "closed", "pending", "superseded", "withdrawn", "dismissed",
        "selected", "ended", "expired",
    ]
    version: int = Field(ge=1)
    terms_revision: int | None = Field(default=None, ge=1)
    introduction_id: RfqReference | None = None
