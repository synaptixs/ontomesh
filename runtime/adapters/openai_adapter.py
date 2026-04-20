"""OpenAI Chat Completions adapter."""

import os
import sys
from typing import Optional

_ADAPTERS_DIR = os.path.dirname(os.path.abspath(__file__))
_RUNTIME_DIR = os.path.dirname(_ADAPTERS_DIR)
if _RUNTIME_DIR not in sys.path:
    sys.path.insert(0, _RUNTIME_DIR)

from client import BaseAdapter


class OpenAIAdapter(BaseAdapter):
    """Adapter for the OpenAI Chat Completions API.

    Requires the ``openai`` Python package.  If not installed, raises an
    :class:`ImportError` with an install hint on the first call.
    """

    def __init__(self, model: str = "gpt-4o", api_key: Optional[str] = None):
        """Initialise the OpenAI adapter.

        Args:
            model: OpenAI model identifier.  Defaults to ``"gpt-4o"``.
            api_key: OpenAI API key.  If ``None``, the ``OPENAI_API_KEY``
                environment variable is used.
        """
        super().__init__(model)
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")

    def _get_client(self):
        """Lazily import and instantiate the OpenAI client.

        Returns:
            An ``openai.OpenAI`` client instance.

        Raises:
            ImportError: If the ``openai`` package is not installed.
        """
        try:
            import openai
        except ImportError as exc:
            raise ImportError(
                "The 'openai' package is required for OpenAIAdapter. "
                "Install it with: pip install openai"
            ) from exc

        kwargs = {}
        if self._api_key:
            kwargs["api_key"] = self._api_key
        return openai.OpenAI(**kwargs)

    def complete(self, payload: dict) -> str:
        """Call the OpenAI Chat Completions API and return the response text.

        Args:
            payload: The assembled payload dict from PayloadAssembler.

        Returns:
            The response text string.

        Raises:
            ImportError: If the ``openai`` package is not installed.
        """
        client = self._get_client()

        system_text = payload.get("system", "")
        messages = payload.get("messages", [])
        token_budget = payload.get("token_budget", 4096)

        # Prepend system message in OpenAI format
        openai_messages = [{"role": "system", "content": system_text}] + list(messages)

        response = client.chat.completions.create(
            model=self._model,
            messages=openai_messages,
            max_tokens=min(token_budget, 4096),
        )

        choice = response.choices[0]
        return choice.message.content or ""

    async def complete_async(self, payload: dict) -> str:
        """Async version of :meth:`complete` using the OpenAI async client.

        Args:
            payload: The assembled payload dict.

        Returns:
            The response text string.

        Raises:
            ImportError: If the ``openai`` package is not installed.
        """
        try:
            import openai
        except ImportError as exc:
            raise ImportError(
                "The 'openai' package is required for OpenAIAdapter. "
                "Install it with: pip install openai"
            ) from exc

        kwargs = {}
        if self._api_key:
            kwargs["api_key"] = self._api_key
        async_client = openai.AsyncOpenAI(**kwargs)

        system_text = payload.get("system", "")
        messages = payload.get("messages", [])
        token_budget = payload.get("token_budget", 4096)

        openai_messages = [{"role": "system", "content": system_text}] + list(messages)

        response = await async_client.chat.completions.create(
            model=self._model,
            messages=openai_messages,
            max_tokens=min(token_budget, 4096),
        )

        choice = response.choices[0]
        return choice.message.content or ""
