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

    Raises ``RuntimeError`` on any network or API failure so that callers
    (e.g. ``RuntimeClient``) can distinguish a real error from an empty
    model response and avoid writing error strings into PROV-O records.
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
            The response text string from the model.

        Raises:
            RuntimeError: If the Ollama server is unreachable, returns an HTTP
                error, or the response cannot be decoded.
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
            raise RuntimeError(
                f"Ollama server unreachable at {self._base_url}: {exc}. "
                "Ensure Ollama is running and the model is pulled."
            ) from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Ollama returned non-JSON response from {url}: {exc}"
            ) from exc
        except Exception as exc:
            raise RuntimeError(f"Ollama API call failed: {exc}") from exc

    async def complete_async(self, payload: dict) -> str:
        """Async version of :meth:`complete`.

        Uses ``aiohttp`` if available for a true async HTTP call; falls back
        to running the synchronous :meth:`complete` in an asyncio executor.

        Args:
            payload: The assembled payload dict.

        Returns:
            The response text string from the model.

        Raises:
            RuntimeError: Propagated from the underlying sync or aiohttp call
                on any network or API failure.
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
            raise RuntimeError(
                f"Ollama async API call failed at {self._base_url}: {exc}. "
                "Ensure Ollama is running and the model is pulled."
            ) from exc
