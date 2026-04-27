"""
runtime.adapters — LLM provider adapters for the Ontology Runtime.

Exposes all four adapters so callers can do:
    from runtime.adapters import AnthropicAdapter, OpenAIAdapter, VertexAdapter, OllamaAdapter

Each adapter degrades gracefully if its provider SDK is not installed.
"""

from .anthropic_adapter import AnthropicAdapter
from .openai_adapter import OpenAIAdapter
from .vertex_adapter import VertexAdapter
from .ollama_adapter import OllamaAdapter
from .oci_adapter import OCIAdapter

__all__ = [
    "AnthropicAdapter",
    "OpenAIAdapter",
    "VertexAdapter",
    "OllamaAdapter",
    "OCIAdapter",
]
