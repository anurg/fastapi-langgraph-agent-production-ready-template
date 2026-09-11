"""This file contains the chat schema for the application."""

import re
from typing import (
    List,
    Literal,
)

from pydantic import (
    BaseModel,
    Field,
    field_validator,
)

from app.schemas.base import BaseResponse


MAX_USER_MESSAGE_LENGTH = 3000
"""Cap on a single inbound user message. Does not apply to anything the agent produces."""


class Message(BaseModel):
    """A single message, in either direction.

    This is the transport and representation model: it describes user input, agent
    output, system prompts, and replayed history alike. It deliberately carries no
    length cap and no content filtering — an assistant answer is as long as the
    model made it, a system prompt grows with long-term memory, and a code example
    containing ``<script>`` is content rather than an attack. Inbound validation
    lives on :class:`UserMessage` instead.

    Attributes:
        role: The role of the message sender.
        content: The content of the message.
    """

    model_config = {"extra": "ignore"}

    role: Literal["user", "assistant", "system"] = Field(..., description="The role of the message sender")
    content: str = Field(..., description="The content of the message", min_length=1)


class UserMessage(Message):
    """A message accepted from a client, with the inbound validation rules applied.

    Used by :class:`ChatRequest`. Keeping these constraints off :class:`Message`
    means a long or code-bearing *reply* can never fail validation and take the
    session down with it.

    Attributes:
        role: The role of the message sender.
        content: The content of the message, capped and screened.
    """

    content: str = Field(
        ...,
        description="The content of the message",
        min_length=1,
        max_length=MAX_USER_MESSAGE_LENGTH,
    )

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        """Validate inbound message content.

        Args:
            v: The content to validate

        Returns:
            str: The validated content

        Raises:
            ValueError: If the content contains disallowed patterns
        """
        # Check for potentially harmful content
        if re.search(r"<script.*?>.*?</script>", v, re.IGNORECASE | re.DOTALL):
            raise ValueError("Content contains potentially harmful script tags")

        # Check for null bytes
        if "\0" in v:
            raise ValueError("Content contains null bytes")

        return v


class ChatRequest(BaseModel):
    """Request model for chat endpoint.

    Attributes:
        messages: List of messages in the conversation.
    """

    messages: List[UserMessage] = Field(
        ...,
        description="List of messages in the conversation",
        min_length=1,
    )


class ChatResponse(BaseResponse):
    """Response model for chat endpoint.

    Attributes:
        messages: List of messages in the conversation.
    """

    messages: List[Message] = Field(..., description="List of messages in the conversation")


class StreamResponse(BaseResponse):
    """Response model for streaming chat endpoint.

    Attributes:
        content: The content of the current chunk.
        done: Whether the stream is complete.
    """

    content: str = Field(default="", description="The content of the current chunk")
    done: bool = Field(default=False, description="Whether the stream is complete")


class SessionTitle(BaseModel):
    """Structured output schema for session title generation."""

    title: str = Field(
        ...,
        min_length=1,
        max_length=60,
    )

    @field_validator("title")
    @classmethod
    def _normalize(cls, v: str) -> str:
        v = " ".join(v.split()).strip(" \"'`.,:;!?-")
        if not v:
            raise ValueError("empty title after normalization")
        return v
