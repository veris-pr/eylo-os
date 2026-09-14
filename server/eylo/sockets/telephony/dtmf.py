"""Inbound DTMF collection helpers for telephony media streams."""

from __future__ import annotations

import time
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class DTMFCompletion(StrEnum):
    """Why the collector completed a digit sequence."""

    TIMEOUT = "timeout"
    TERMINATION_KEY = "termination_key"
    DIGIT_LIMIT = "digit_limit"
    FLUSH = "flush"


class DTMFCollectionResult(BaseModel):
    """Completed DTMF sequence ready for downstream processing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    digits: str
    completed_by: DTMFCompletion


class DTMFCollector:
    """Collect DTMF digits until termination, digit limit, or timeout."""

    def __init__(
        self,
        *,
        digit_limit: int = 16,
        termination_key: str = "#",
        timeout_ms: int = 5000,
    ) -> None:
        self.digit_limit = digit_limit
        self.termination_key = termination_key
        self.timeout_ms = timeout_ms
        self._digits: list[str] = []
        self._last_digit_at: float | None = None

    def collect(self, digits: str) -> DTMFCollectionResult | None:
        """Add provider digits and return a completed sequence when ready."""
        now = time.monotonic() * 1000
        if (
            self._last_digit_at is not None
            and now - self._last_digit_at > self.timeout_ms
            and self._digits
        ):
            result = self._complete(DTMFCompletion.TIMEOUT)
            self._append_digits(digits, now)
            return result

        self._append_digits(digits, now)
        if self.termination_key and self.termination_key in self._digits:
            return self._complete(DTMFCompletion.TERMINATION_KEY)
        if len(self._digits) >= self.digit_limit:
            return self._complete(DTMFCompletion.DIGIT_LIMIT)
        return None

    def flush(self) -> DTMFCollectionResult | None:
        """Return the current buffered digits, if any."""
        if not self._digits:
            return None
        return self._complete(DTMFCompletion.FLUSH)

    def _append_digits(self, digits: str, now: float) -> None:
        for digit in digits:
            if digit in "0123456789*#":
                self._digits.append(digit)
                self._last_digit_at = now

    def _complete(self, completed_by: DTMFCompletion) -> DTMFCollectionResult:
        digits = "".join(d for d in self._digits if d != self.termination_key)
        self._digits.clear()
        self._last_digit_at = None
        return DTMFCollectionResult(digits=digits, completed_by=completed_by)
