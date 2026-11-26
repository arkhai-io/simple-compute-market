"""How a route resolves an exact retry: the declaration every route contract carries.

The vocabulary is data, so a contracts package declares its routes' resolution with
no dependency on the authority that enforces it.
"""

from __future__ import annotations

from enum import Enum


class ExactRetry(str, Enum):
    """A route's resolution of an exact retry of a request it has seen.

    The vocabulary has no default member: a route contract states one of the two.
    """

    #: The handler runs again and no response body is recorded. Only a route whose
    #: domain recognises the retry as already applied may declare it, so a re-run
    #: after any later write to the same resource changes nothing.
    RERUN = "rerun"
    #: The outcome is recorded for the authority's retention, and an exact retry is
    #: answered with it rather than dispatched again.
    RECORDED = "recorded"
