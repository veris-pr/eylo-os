"""Typed optional-value sentinel retained for voice adapter compatibility."""


class _NotGiven:
    """Identity-only marker distinct from both an omitted value and ``None``."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "NOT_GIVEN"


NOT_GIVEN = _NotGiven()
type NotGivenOr[Value] = Value | _NotGiven

__all__ = ["NOT_GIVEN", "NotGivenOr"]
