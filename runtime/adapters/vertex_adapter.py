"""Google Vertex AI (Gemini) adapter."""

import os
import sys
from typing import Optional

_ADAPTERS_DIR = os.path.dirname(os.path.abspath(__file__))
_RUNTIME_DIR = os.path.dirname(_ADAPTERS_DIR)
if _RUNTIME_DIR not in sys.path:
    sys.path.insert(0, _RUNTIME_DIR)

from client import BaseAdapter


class VertexAdapter(BaseAdapter):
    """Adapter for Google Vertex AI (Gemini) models.

    Uses the ``google-cloud-aiplatform`` package with the Generative AI
    SDK.  If not installed, raises :class:`ImportError` with an install hint.
    """

    def __init__(
        self,
        model: str = "gemini-1.5-pro",
        project: Optional[str] = None,
        location: str = "us-central1",
    ):
        """Initialise the Vertex AI adapter.

        Args:
            model: Vertex AI model name.  Defaults to ``"gemini-1.5-pro"``.
            project: Google Cloud project ID.  If ``None``, the
                ``GOOGLE_CLOUD_PROJECT`` environment variable is used.
            location: GCP region.  Defaults to ``"us-central1"``.
        """
        super().__init__(model)
        self._project = project or os.environ.get("GOOGLE_CLOUD_PROJECT")
        self._location = location

    def _init_vertexai(self):
        """Lazily import and initialise the Vertex AI SDK.

        Returns:
            The ``vertexai`` module after initialisation.

        Raises:
            ImportError: If ``google-cloud-aiplatform`` is not installed.
        """
        try:
            import vertexai
            from vertexai.generative_models import GenerativeModel  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "The 'google-cloud-aiplatform' package is required for VertexAdapter. "
                "Install it with: pip install google-cloud-aiplatform"
            ) from exc

        vertexai.init(project=self._project, location=self._location)
        return vertexai

    def _build_prompt(self, payload: dict) -> str:
        """Combine system prompt and user message into a single Gemini prompt.

        Vertex AI's Gemini API handles system instructions separately in newer
        SDKs.  For maximum compatibility, we concatenate them with a separator.

        Args:
            payload: The assembled payload dict.

        Returns:
            A single prompt string.
        """
        system_text = payload.get("system", "")
        messages = payload.get("messages", [])
        user_text = ""
        for msg in messages:
            if msg.get("role") == "user":
                user_text = msg.get("content", "")
                break

        parts = []
        if system_text:
            parts.append(f"[SYSTEM]\n{system_text}\n[/SYSTEM]")
        if user_text:
            parts.append(f"[USER]\n{user_text}")
        return "\n\n".join(parts)

    def complete(self, payload: dict) -> str:
        """Call the Vertex AI Gemini API and return the response text.

        Args:
            payload: The assembled payload dict from PayloadAssembler.

        Returns:
            The response text string.

        Raises:
            ImportError: If ``google-cloud-aiplatform`` is not installed.
        """
        self._init_vertexai()
        from vertexai.generative_models import GenerativeModel

        model = GenerativeModel(self._model)
        prompt = self._build_prompt(payload)

        response = model.generate_content(prompt)
        return response.text if hasattr(response, "text") else str(response)

    async def complete_async(self, payload: dict) -> str:
        """Async version of :meth:`complete`.

        Vertex AI Python SDK does not provide a native async client as of
        the current version; this method runs the synchronous call in the
        default asyncio executor.

        Args:
            payload: The assembled payload dict.

        Returns:
            The response text string.

        Raises:
            ImportError: If ``google-cloud-aiplatform`` is not installed.
        """
        import asyncio

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.complete, payload)
