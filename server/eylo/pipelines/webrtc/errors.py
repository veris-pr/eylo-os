"""Closed failure categories for WebRTC negotiation and candidate admission."""

from enum import StrEnum


class IceCandidateCode(StrEnum):
    MALFORMED_CANDIDATE = "malformed_candidate"
    UNSUPPORTED_CANDIDATE = "unsupported_candidate"
    CANDIDATE_LIMIT_REACHED = "candidate_limit_reached"
    NO_PERMITTED_CANDIDATES = "no_permitted_candidates"
    NON_PUBLIC_CANDIDATE = "non_public_candidate"
    HOSTNAME_CANDIDATE_REJECTED = "hostname_candidate_rejected"
    UNSAFE_CANDIDATE = "unsafe_candidate"


class WebRTCSignalingCode(StrEnum):
    SESSION_NOT_FOUND = "session_not_found"
    NEGOTIATION_TERMINATED = "negotiation_terminated"
    PREPARE_FAILED = "prepare_failed"
    INVALID_OFFER_TYPE = "invalid_offer_type"
    PREPARE_REQUIRED = "prepare_required"
    NEGOTIATION_MISMATCH = "negotiation_mismatch"
    OFFER_CONFLICT = "offer_conflict"
    ANSWER_DELIVERY_FAILED = "answer_delivery_failed"
    NEGOTIATION_UNAVAILABLE = "negotiation_unavailable"
    ANSWER_UNAVAILABLE = "answer_unavailable"
    CANDIDATE_APPLY_FAILED = "candidate_apply_failed"
    MISSING_NEGOTIATION_ID = "missing_negotiation_id"
    MISSING_SDP = "missing_sdp"
    UNSUPPORTED_PROTOCOL_VERSION = "unsupported_protocol_version"
    OFFER_FAILED = "offer_failed"
    CANDIDATE_FAILED = "candidate_failed"
    NOT_CONFIGURED = "not_configured"


type WebRTCFailureCode = WebRTCSignalingCode | IceCandidateCode


class WebRTCSignalingError(RuntimeError):
    """A safe category, never raw SDP, candidate text or a vendor exception."""

    def __init__(self, code: WebRTCFailureCode) -> None:
        super().__init__(code.value)
        self.code = code
