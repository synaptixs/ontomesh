"""Ollama local LLM adapter."""

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Optional

_ADAPTERS_DIR = os.path.dirname(os.path.abspath(__file__))
_RUNTIME_DIR = os.path.dirname(_ADAPTERS_DIR)
if _RUNTIME_DIR not in sys.path:
    sys.path.insert(0, _RUNTIME_DIR)

from client import BaseAdapter


class OllamaAdapter(BaseAdapter):
    """Adapter for Ollama local LLM server.

    Calls the Ollama REST API at ``/api/chat`` with ``stream=False``.
    Uses only Python stdlib (``urllib``) for the sync path; the async path
    uses ``aiohttp`` if available, falling back to ``asyncio``'s executor.

    If the Ollama server is unreachable, degrades gracefully and returns
    a descriptive error message rather than raising an unhandled exception.
    """

    def __init__(
        self,
        model: str = "llama3",
        base_url: str = "http://localhost:11434",
    ):
        """Initialise the Ollama adapter.

        Args:
            model: Ollama model tag.  Defaults to ``"llama3"``.
            base_url: Base URL of the Ollama server.
                Defaults to ``"http://localhost:11434"``.
        """
        super().__init__(model)
        self._base_url = base_url.rstrip("/")

    def _build_messages(self, payload: dict) -> list:
        """Build the Ollama messages list from the payload.

        Args:
            payload: The assembled payload dict.

        Returns:
            A list of Ollama-format message dicts.
        """
        system_text = payload.get("system", "")
        user_messages = payload.get("messages", [])

        ollama_messages: list[dict] = []
        if system_text:
            ollama_messages.append({"role": "system", "content": system_text})
        for msg in user_messages:
            ollama_messages.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", ""),
            })
        return ollama_messages

    def complete(self, payload: dict) -> str:
        """Call the Ollama ``/api/chat`` endpoint and return the response text.

        Args:
            payload: The assembled payload dict from PayloadAssembler.

        Returns:
            The response text string, or an error message if the server is
            unreachable.
        """
        url = f"{self._base_url}/api/chat"
        messages = self._build_messages(payload)

        body = json.dumps({
            "model": self._model,
            "messages": messages,
            "stream": False,
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                # Ollama response: {"message": {"role": "assistant", "content": "..."}}
                return data.get("message", {}).get("content", "")
        except urllib.error.URLError as exc:
            return (
                f"[OllamaAdapter] Server unreachable at {self._base_url}: {exc}. "
                "Ensure Ollama is running and the model is pulled."
            )
        except Exception as exc:
            return f"[OllamaAdapter] Error: {exc}"

    async def complete_async(self, payload: dict) -> str:
        """Async version of :meth:`complete`.

        Uses ``aiohttp`` if available for a true async HTTP call; falls back
        to running the synchronous :meth:`complete` in an asyncio executor.

        Args:
            payload: The assembled payload dict.

        Returns:
            The response text string.
        """
        try:
            import aiohttp
            return await self._complete_with_aiohttp(payload)
        except ImportError:
            import asyncio
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self.complete, payload)

    async def _complete_with_aiohttp(self, payload: dict) -> str:
        """Internal async implementation using aiohttp.

        Args:
            payload: The assembled payload dict.

        Returns:
            The response text string.
        """
        import aiohttp

        url = f"{self._base_url}/api/chat"
        messages = self._build_messages(payload)
        body = {
            "model": self._model,
            "messages": messages,
            "stream": False,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=body, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                    data = await resp.json()
                    return data.get("message", {}).get("content", "")
        except Exception as exc:
            return (
                f"[OllamaAdapter] Server unreachable at {self._base_url}: {exc}. "
                "Ensure Ollama is running and the model is pulled."
            )
