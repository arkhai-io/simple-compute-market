"""Reading a domain's progress row strictly.

The path fails closed on progress it cannot read: an unknown step, an
identity that is not a non-empty string, or a step that disagrees with the
identities recorded beside it. Reading the row never repairs it, and the
recorded resource is kept for an operator to see.
"""

from __future__ import annotations

from dataclasses import dataclass

from .ports import DeliveryStep, RecordedProgress


class ProgressUnreadable(ValueError):
    """A progress row the path cannot act on."""


#: For each step, which records must be present (True) or absent (False).
_SHAPE: dict[DeliveryStep, tuple[bool, bool, bool]] = {
    DeliveryStep.RESERVE: (False, False, False),
    DeliveryStep.COMMIT: (True, False, False),
    DeliveryStep.DISPATCH: (True, False, False),
    DeliveryStep.FULFILLMENT: (True, True, False),
    DeliveryStep.ACTIVATED: (True, True, True),
}


@dataclass(frozen=True)
class Progress:
    step: DeliveryStep
    capacity_reservation_id: str | None = None
    fulfillment_id: str | None = None
    activated_at: int | None = None


def _identity(name: str, value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ProgressUnreadable(f"recorded {name} {value!r} is not an identity")
    return value


def read_progress(recorded: object) -> Progress:
    if not isinstance(recorded, RecordedProgress):
        raise ProgressUnreadable(f"progress port returned {type(recorded).__name__}")
    try:
        step = DeliveryStep(recorded.step)
    except ValueError:
        raise ProgressUnreadable(f"unknown delivery step {recorded.step!r}") from None
    reservation = _identity("reservation", recorded.capacity_reservation_id)
    fulfillment = _identity("fulfillment", recorded.fulfillment_id)
    activated_at = recorded.activated_at
    if activated_at is not None and (
        isinstance(activated_at, bool) or not isinstance(activated_at, int) or activated_at < 0
    ):
        raise ProgressUnreadable(f"recorded activation {activated_at!r} is not an instant")
    present = (reservation is not None, fulfillment is not None, activated_at is not None)
    if present != _SHAPE[step]:
        raise ProgressUnreadable(
            f"step {step.value!r} disagrees with the recorded reservation, "
            "fulfillment and activation"
        )
    return Progress(step, reservation, fulfillment, activated_at)


def recorded_identities(recorded: object) -> tuple[str | None, str | None]:
    """Whatever readable identities an unreadable row still names, for its report."""
    if not isinstance(recorded, RecordedProgress):
        return None, None
    names = []
    for value in (recorded.capacity_reservation_id, recorded.fulfillment_id):
        names.append(value if isinstance(value, str) and value.strip() else None)
    return names[0], names[1]
