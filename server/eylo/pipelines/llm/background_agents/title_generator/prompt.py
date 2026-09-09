"""Utility for building prompts for LLM-based title generation."""

from ..framework_prompt import BackgroundPrompt


def build_title_generation_prompt(
    conversation_string: str,
) -> BackgroundPrompt:
    """Build the instruction and conversation text for one title request."""
    system_prompt = """
        You are an AI assistant tasked with generating conversation titles.

        Extract the main topic or purpose of the user-assistant conversation.
        Use noun phrases focusing on the core subject matter.
        Avoid actions, emotions, narrative descriptions, or conversational style.

        Output only the summary text directly with no labels or prefixes.

        Requirements:
        - Maximum 10 words
        - Focus on the core subject matter, not the conversational style
        - Use noun phrases rather than full sentences
        - Avoid actions, emotions, or narrative descriptions
        - Do not include formatting, punctuation beyond necessary commas, or prefixes
        - If no clear topic exists, return an empty string
        - Important: generate title in PLAIN TEXT and not markdown, or html or anyother format

        Good examples:
        - Booking a meeting room for a team event
        - Weather forecast for New York City
        - Booking a meeting room about vendor visit
        - Python debugging assistance
        - Current time inquiry
        - Time inquiry

        Bad examples:
        - The current time in Russia is 11:52 PM.
        - Title: Room booking request
        - "Room booking request"
        - User asks about room booking
        - "*loudly* THE TIME IS NOW!"
        - "User asks about the weather today"
        - "Help me with this problem please"
    """

    return BackgroundPrompt(
        system_prompt=system_prompt, user_content=conversation_string
    )
