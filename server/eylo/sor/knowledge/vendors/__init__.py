"""Executable external-document vendor adapters."""

from .linear import (
    LINEAR_KNOWLEDGE_MANIFEST,
    LinearKnowledgeAdapter,
    create_linear_knowledge_adapter,
)

__all__ = [
    "LINEAR_KNOWLEDGE_MANIFEST",
    "LinearKnowledgeAdapter",
    "create_linear_knowledge_adapter",
]
