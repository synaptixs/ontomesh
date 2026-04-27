"""Oracle Cloud Infrastructure (OCI) Generative AI adapter.

Uses the official ``oci`` Python SDK. Authentication follows the standard
OCI config file pattern (``~/.oci/config``) by default; an explicit config
dict or profile can be provided. See:
https://docs.oracle.com/en-us/iaas/tools/python/latest/configuration.html
"""

import asyncio
import os
import sys
from typing import Optional

_ADAPTERS_DIR = os.path.dirname(os.path.abspath(__file__))
_RUNTIME_DIR = os.path.dirname(_ADAPTERS_DIR)
if _RUNTIME_DIR not in sys.path:
    sys.path.insert(0, _RUNTIME_DIR)

from client import BaseAdapter


_DEFAULT_ENDPOINT = "https://inference.generativeai.us-chicago-1.oci.oraclecloud.com"


class OCIAdapter(BaseAdapter):
    """Adapter for OCI Generative AI Inference (chat).

    Requires the ``oci`` Python package. Authentication uses the standard
    OCI config file at ``~/.oci/config`` unless overridden.

    Args:
        model: OCI model OCID or short model id (e.g. ``"cohere.command-r-plus"``).
        compartment_id: OCID of the compartment to bill/route the request to.
            Falls back to the ``OCI_COMPARTMENT_ID`` env var.
        config_path: Path to the OCI config file. Defaults to
            ``~/.oci/config`` (or ``OCI_CONFIG_FILE`` env var).
        profile: Profile name within the config file. Defaults to
            ``"DEFAULT"`` (or ``OCI_CONFIG_PROFILE`` env var).
        endpoint: Service endpoint. Defaults to the Chicago region; override
            via the ``OCI_GENAI_ENDPOINT`` env var or this argument.
        provider: ``"cohere"`` or ``"meta"``. Selects the request shape used
            by the OCI Generative AI service. Defaults to ``"cohere"``.
    """

    def __init__(
        self,
        model: str = "cohere.command-r-plus",
        compartment_id: Optional[str] = None,
        config_path: Optional[str] = None,
        profile: Optional[str] = None,
        endpoint: Optional[str] = None,
        provider: str = "cohere",
    ):
        super().__init__(model)
        self._compartment_id = compartment_id or os.environ.get("OCI_COMPARTMENT_ID")
        self._config_path = config_path or os.environ.get("OCI_CONFIG_FILE", "~/.oci/config")
        self._profile = profile or os.environ.get("OCI_CONFIG_PROFILE", "DEFAULT")
        self._endpoint = endpoint or os.environ.get("OCI_GENAI_ENDPOINT", _DEFAULT_ENDPOINT)
        self._provider = provider.lower()

    def _get_client(self):
        try:
            import oci
            from oci.generative_ai_inference import GenerativeAiInferenceClient
        except ImportError as exc:
            raise ImportError(
                "The 'oci' package is required for OCIAdapter. "
                "Install it with: pip install oci"
            ) from exc

        config = oci.config.from_file(
            file_location=os.path.expanduser(self._config_path),
            profile_name=self._profile,
        )
        return GenerativeAiInferenceClient(
            config=config,
            service_endpoint=self._endpoint,
        )

    def _build_chat_details(self, payload: dict):
        """Assemble an OCI ``ChatDetails`` request from the runtime payload."""
        from oci.generative_ai_inference import models as genai_models

        if not self._compartment_id:
            raise ValueError(
                "OCIAdapter requires a compartment OCID. Set OCI_COMPARTMENT_ID "
                "or pass compartment_id to the adapter."
            )

        system_text = payload.get("system", "")
        messages = payload.get("messages", [])
        token_budget = payload.get("token_budget", 4096)
        max_tokens = min(int(token_budget), 4096)

        serving_mode = genai_models.OnDemandServingMode(model_id=self._model)

        if self._provider == "cohere":
            history = []
            user_message = ""
            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "user":
                    user_message = content
                elif role == "assistant":
                    history.append(
                        genai_models.CohereMessage(role="CHATBOT", message=content)
                    )
            chat_request = genai_models.CohereChatRequest(
                message=user_message,
                preamble_override=system_text or None,
                chat_history=history or None,
                max_tokens=max_tokens,
            )
        else:
            generic_messages = []
            if system_text:
                generic_messages.append(
                    genai_models.Message(
                        role="SYSTEM",
                        content=[genai_models.TextContent(text=system_text)],
                    )
                )
            for msg in messages:
                role = msg.get("role", "user").upper()
                content = msg.get("content", "")
                generic_messages.append(
                    genai_models.Message(
                        role=role,
                        content=[genai_models.TextContent(text=content)],
                    )
                )
            chat_request = genai_models.GenericChatRequest(
                api_format=genai_models.BaseChatRequest.API_FORMAT_GENERIC,
                messages=generic_messages,
                max_tokens=max_tokens,
            )

        return genai_models.ChatDetails(
            compartment_id=self._compartment_id,
            serving_mode=serving_mode,
            chat_request=chat_request,
        )

    @staticmethod
    def _extract_text(response) -> str:
        """Extract response text from an OCI chat response, handling both providers."""
        chat_response = getattr(response.data, "chat_response", None)
        if chat_response is None:
            return ""

        text = getattr(chat_response, "text", None)
        if text:
            return text

        choices = getattr(chat_response, "choices", None) or []
        for choice in choices:
            msg = getattr(choice, "message", None)
            if msg is None:
                continue
            for part in getattr(msg, "content", []) or []:
                part_text = getattr(part, "text", None)
                if part_text:
                    return part_text
        return ""

    def complete(self, payload: dict) -> str:
        client = self._get_client()
        details = self._build_chat_details(payload)
        response = client.chat(details)
        return self._extract_text(response) or ""

    async def complete_async(self, payload: dict) -> str:
        # The OCI Python SDK is synchronous; offload to a thread.
        return await asyncio.to_thread(self.complete, payload)
