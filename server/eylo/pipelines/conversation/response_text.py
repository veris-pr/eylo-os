"""User-facing terminal text shared by conversation and generated-widget flows."""


class ErrorMessages:
    """Stable fallback text selected from typed framework run outcomes."""

    EMPTY_RESPONSE = (
        "I apologize, but I encountered an issue generating a response. "
        "Could you please rephrase your request?"
    )
    MAX_ITERATIONS = (
        "I apologize, but I'm having trouble completing this request. "
        "Could you please try rephrasing or breaking it into smaller steps?"
    )
    REQUEST_TIMEOUT = (
        "I apologize, but this request is taking too long to process. "
        "Please try again with a simpler request."
    )
    GENERIC_ERROR = (
        "I apologize, but I encountered an error while processing your request. "
        "Please try again."
    )
    MODEL_OUTPUT_LIMIT = (
        "The model reached its response limit before finishing. "
        "Please ask for a shorter answer or have the response limit increased."
    )


def format_widget_render_fallback() -> str:
    """Return a model-safe fallback without reflecting tool or exception text."""
    return (
        "A widget could not be rendered. Do not call another widget tool "
        "during this turn. Reply to the user in normal plain text instead."
    )
