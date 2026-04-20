"""Anthropic Messages API adapter with prompt caching."""

import os
import sys
from typing import Optional

# Ensure parent runtime/ dir is in path for BaseAdapter import
_ADAPTERS_DIR = os.path.dirname(os.path.abspath(__file__))
_RUNTIME_DIR = os.path.dirname(_ADAPTERS_DIR)
if _RUNTIME_DIR not in sys.path:
    sys.path.insert(0, _RUNTIME_DIR)

from client import BaseAdapter


class AnthropicAdapter(BaseAdapter):
    """Adapter for the Anthropic Messages API.

    Supports prompt caching via the ``cache_control`` parameter on the
    system prompt, reducing cost for repeated ontology-context calls.

    Requires the ``anthropic`` Python package.  If not installed, raises
    an :class:`ImportError` with an install hint on the first call.
    """

    def __init__(self, model: str = "claude-sonnet-4-5", api_key: Optional[str] = None):
        """Initialise the Anthropic adapter.

        Args:
            model: Anthropic model identifier.  Defaults to
                ``"claude-sonnet-4-5"``.
            api_key: Anthropic API key.  If ``None``, the
                ``ANTHROPIC_API_KEY`` environment variable is used.
        """
        super().__init__(model)
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")

    def _get_client(self):
        """Lazily import and instantiate the Anthropic client.

        Returns:
            An ``anthropic.Anthropic`` client instance.

        Raises:
            ImportError: If the ``anthropic`` package is not installed.
        """
        try:
            import anthropic
        except ImportError as exc:
            raise ImportError(
                "The 'anthropic' package is required for AnthropicAdapter. "
                "Install it with: pip install anthropic"
            ) from exc

        kwargs = {}
        if self._api_key:
            kwargs["api_key"] = self._api_key
        return anthropic.Anthropic(**kwargs)

    def complete(self, payload: dict) -> str:
        """Call the Anthropic Messages API and return the response text.

        Uses ``cache_control: {"type": "ephemeral"}`` on the system prompt
        to enable prompt caching for repeated ontology context.

        Args:
            payload: The assembled payload dict from PayloadAssembler.

        Returns:
            The response text string.

        Raises:
            ImportError: If the ``anthropic`` package is not installed.
        """
        client = self._get_client()

        system_text = payload.get("system", "")
        messages = payload.get("messages", [])
        token_budget = payload.get("token_budget", 4096)

        response = client.messages.create(
            model=self._model,
            max_tokens=min(token_budget, 4096),
            system=[
                {
                    "type": "text",
                    "text": system_text,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=messages,
        )

        # Extract text from response content blocks
        parts = []
        for block in response.content:
            if hasattr(block, "text"):
                parts.append(block.text)
        return "\n".join(parts)

    async def complete_async(self, payload: dict) -> str:
        """Async version of :meth:`complete` using the Anthropic async client.

        Args:
            payload: The assembled payload dict.

        Returns:
            The response text string.

        Raises:
            ImportError: If the ``anthropic`` package is not installed.
        """
        try:
            import anthropic
        except ImportError as exc:
            raise ImportError(
                "The 'anthropic' package is required for AnthropicAdapter. "
                "Install it with: pip install anthropic"
            ) from exc

        kwargs = {}
        if self._api_key:
            kwargs["api_key"] = self._api_key
        async_client = anthropic.AsyncAnthropic(**kwargs)

        system_text = payload.get("system", "")
        messages = payload.get("messages", [])
        token_budget = payload.get("token_budget", 4096)

        response = await async_client.messages.create(
            model=self._model,
            max_tokens=min(token_budget, 4096),
            system=[
                {
                    "type": "text",
                    "text": system_text,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=messages,
        )

        parts = []
        for block in response.content:
            if hasattr(block, "text"):
                parts.append(block.text)
        return "\n".join(parts)
