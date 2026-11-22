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
    def route(self) -> str:
        return _RFQ_ROUTES[self]

    @property
    def is_read(self) -> bool:
        return self in {
            self.SEARCH, self.READ, self.LIST_RESPONSES, self.READ_RESPONSE,
            self.READ_INTRODUCTION,
        }

    @property
    def shares_contact(self) -> bool:
        return self in {self.RESPOND, self.RECONFIRM, self.SELECT}


_RFQ_ROUTES = {
    RfqOperation.CREATE: "/rfqs/create",
    RfqOperation.SEARCH: "/rfqs/search",
    RfqOperation.READ: "/rfqs/{rfq_id}/read",
    RfqOperation.EDIT: "/rfqs/{rfq_id}/edit",
    RfqOperation.CLOSE: "/rfqs/{rfq_id}/close",
    RfqOperation.RESPOND: "/rfqs/{rfq_id}/respond",
    RfqOperation.LIST_RESPONSES: "/rfqs/{rfq_id}/responses/list",
    RfqOperation.READ_RESPONSE: "/rfqs/{rfq_id}/responses/{response_id}/read",
    RfqOperation.RECONFIRM: "/rfqs/{rfq_id}/responses/{response_id}/reconfirm",
    RfqOperation.WITHDRAW: "/rfqs/{rfq_id}/responses/{response_id}/withdraw",
    RfqOperation.DISMISS: "/rfqs/{rfq_id}/responses/{response_id}/dismiss",
    RfqOperation.SELECT: "/rfqs/{rfq_id}/responses/{response_id}/select",
    RfqOperation.READ_INTRODUCTION: "/rfqs/introductions/{introduction_id}/read",
    RfqOperation.END_INTRODUCTION: "/rfqs/introductions/{introduction_id}/end",
}

@dataclass(frozen=True)
class RfqTarget:
    """The semantic resource a route derives independently from the request body."""

    method: ClassVar[Literal["POST"]] = "POST"
    caller_role: ClassVar[Literal["service"]] = "service"

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
    def path(self) -> str:
        return self.operation.route.format(
            rfq_id=self.rfq_id, response_id=self.response_id, introduction_id=self.introduction_id,
        )

    @staticmethod
    def bind_resource(
        rfq_id: str | None = None, response_id: str | None = None, introduction_id: str | None = None,
    ) -> str:
        if introduction_id is not None:
            return f"rfqs/introductions/{introduction_id}"
        if response_id is not None:
            return f"rfqs/{rfq_id}/responses/{response_id}"
        if rfq_id is not None:
            return f"rfqs/{rfq_id}"
        return "rfqs"

    @property
    def resource(self) -> str:
        return self.bind_resource(self.rfq_id, self.response_id, self.introduction_id)


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


class RfqInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)


class CreateRfq(RfqInput):
    kind: RfqReference
    requirements: dict[str, JsonValue]


class SearchRfqs(RfqInput):
    kind: RfqReference
    filters: dict[str, JsonValue] = Field(default_factory=dict)
    page_size: int = Field(default=25, ge=1, le=100)
    cursor: str | None = Field(default=None, min_length=1, max_length=512)


class CloseRfq(RfqInput):
    version: int = Field(ge=1)


class EditRfq(CloseRfq):
    requirements: dict[str, JsonValue]

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


class RfqSummary(BaseModel):
    """The account-visible routing reference and current request requirements."""

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    rfq_id: RfqReference
    registry: RfqAudience
    kind: RfqReference
    state: Literal["open", "closed", "expired"]
    version: int = Field(ge=1)
    terms_revision: int = Field(ge=1)
    requirements: dict[str, JsonValue]


class RfqDetail(RfqSummary):
    """The current request with the verified recipient reference."""

    buyer_reference: RfqReference


class RfqSearchPage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    results: list[RfqSummary]
    next_cursor: str | None = None
