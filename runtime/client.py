"""
RuntimeClient — high-level SDK for the ontology-augmented AI runtime.

Ties FlavorRegistry → Grounder → InputGate → PayloadAssembler → LLM Adapter → OutputGate
into a single call.

Usage:
    client = RuntimeClient(db_path="db/enterprise.db", adapter="anthropic")
    result = client.ask(question="Which NFs are degraded?", flavor="network-ops")
"""

import asyncio
import os
import sys
import time
from abc import ABC, abstractmethod
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from flavor_registry import FlavorRegistry
from grounder import Grounder
from assembler import PayloadAssembler
from output_gate import OutputGate
from input_gate import InputGate


# ──────────────────────────────────────────────────────────────────────────
# Base Adapter
# ──────────────────────────────────────────────────────────────────────────

class BaseAdapter(ABC):
    """Abstract base class for all LLM adapters.

    Concrete subclasses implement :meth:`complete` and :meth:`complete_async`
    for a specific LLM provider.  The adapter is responsible only for the
    network call — payload construction is done by :class:`PayloadAssembler`.
    """

    def __init__(self, model: str):
        """Initialise the adapter with a model identifier.

        Args:
            model: Provider-specific model identifier string.
        """
        self._model = model

    @property
    def model_id(self) -> str:
        """The model identifier string for this adapter."""
        return self._model

    @abstractmethod
    def complete(self, payload: dict) -> str:
        """Send the payload to the LLM and return the response text.

        Args:
            payload: The assembled payload dict (from PayloadAssembler).

        Returns:
            The raw response text from the LLM.
        """

    @abstractmethod
    async def complete_async(self, payload: dict) -> str:
        """Async version of :meth:`complete`.

        Args:
            payload: The assembled payload dict.

        Returns:
            The raw response text from the LLM.
        """


# ──────────────────────────────────────────────────────────────────────────
# Runtime Client
# ──────────────────────────────────────────────────────────────────────────

class RuntimeClient:
    """High-level SDK that orchestrates the full ontology-augmented AI pipeline.

    Ties together :class:`FlavorRegistry`, :class:`Grounder`,
    :class:`InputGate`, :class:`PayloadAssembler`, an LLM adapter, and
    :class:`OutputGate` into a single ``ask()`` call.

    The pipeline runs as follows:
    1. Ground the question against the DB using the Grounder.
    2. Screen grounded records through the InputGate (reject low-quality data).
    3. Assemble the LLM payload via PayloadAssembler.
    4. Call the LLM adapter.
    5. Validate and stamp the response via OutputGate.
    6. Return a consolidated result dict.
    """

    def __init__(
        self,
        db_path: str,
        adapter: str = "anthropic",
        flavors_dir: Optional[str] = None,
        out_path: str = "output",
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        min_confidence: float = 0.0,
    ):
        """Initialise the RuntimeClient.

        Args:
            db_path: Absolute path to the SQLite enterprise database.
            adapter: LLM adapter name — ``"anthropic"``, ``"openai"``,
                ``"vertex"``, or ``"ollama"``.
            flavors_dir: Optional path to the flavors directory.
            out_path: Base output directory (for saving payloads, etc.).
            model: Optional model override for the adapter.
            api_key: Optional API key override (defaults to env var).
            min_confidence: Minimum confidence score for InputGate screening.
        """
        self._db_path = db_path
        self._out_path = out_path

        self._registry = FlavorRegistry(flavors_dir)
        self._grounder = Grounder(db_path, self._registry)
        self._assembler = PayloadAssembler(self._registry, self._grounder)
        self._input_gate = InputGate(db_path, min_confidence=min_confidence)
        self._output_gate = OutputGate(db_path)
        self._adapter_instance = self._init_adapter(adapter, model, api_key)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def registry(self) -> FlavorRegistry:
        """The active FlavorRegistry instance."""
        return self._registry

    @property
    def grounder(self) -> Grounder:
        """The active Grounder instance."""
        return self._grounder

    @property
    def assembler(self) -> PayloadAssembler:
        """The active PayloadAssembler instance."""
        return self._assembler

    @property
    def input_gate(self) -> InputGate:
        """The active InputGate instance."""
        return self._input_gate

    @property
    def output_gate(self) -> OutputGate:
        """The active OutputGate instance."""
        return self._output_gate

    @property
    def adapter_instance(self) -> BaseAdapter:
        """The active LLM adapter instance."""
        return self._adapter_instance

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ask(
        self,
        question: str,
        flavor: str,
        max_records: int = 50,
        output_format: str = "json",
        save_payload: bool = False,
    ) -> dict:
        """Run the full pipeline for a single question.

        Args:
            question: The natural-language question.
            flavor: The flavor name to scope the query.
            max_records: Maximum records to retrieve from the DB.
            output_format: Desired LLM response format (``"json"``, ``"text"``, etc.).
            save_payload: If ``True``, save the assembled payload to disk.

        Returns:
            A result dict with keys: ``question``, ``flavor``, ``answer``,
            ``valid``, ``violations``, ``observation_iri``, ``prov``,
            ``model``, ``elapsed_ms``.
        """
        t_start = time.monotonic()

        # Step 1: Ground
        grounded_data = self._grounder.ground(question, flavor, max_records)

        # Step 2: Screen through InputGate
        raw_graph = grounded_data.get("@graph", [])
        accepted, rejected = self._input_gate.screen(raw_graph, flavor)
        # Update graph with screened records only
        grounded_data["@graph"] = accepted
        grounded_data["meta"]["record_count"] = len(accepted)
        grounded_data["meta"]["rejected_count"] = len(rejected)

        # Step 3: Assemble payload
        payload = self._assembler.assemble(
            question=question,
            flavor_name=flavor,
            grounded_data=grounded_data,
            output_format=output_format,
        )

        if save_payload:
            import os as _os
            payload_dir = _os.path.join(self._out_path, "payloads")
            _os.makedirs(payload_dir, exist_ok=True)
            payload_path = _os.path.join(payload_dir, f"{payload['payload_id']}.json")
            self._assembler.save(payload, payload_path)

        # Step 4: Call LLM
        llm_response = self._adapter_instance.complete(payload)

        # Step 5: Validate + stamp
        gate_result = self._output_gate.validate_and_stamp(
            response=llm_response,
            payload=payload,
            model_id=self._adapter_instance.model_id,
        )

        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        return self._build_result(payload, llm_response, gate_result, elapsed_ms)

    async def ask_async(
        self,
        question: str,
        flavor: str,
        max_records: int = 50,
        output_format: str = "json",
        save_payload: bool = False,
    ) -> dict:
        """Async version of :meth:`ask`.

        Args:
            question: The natural-language question.
            flavor: The flavor name to scope the query.
            max_records: Maximum records to retrieve from the DB.
            output_format: Desired LLM response format.
            save_payload: If ``True``, save the assembled payload to disk.

        Returns:
            A result dict (same shape as :meth:`ask`).
        """
        t_start = time.monotonic()

        # Ground and screen are synchronous (DB I/O) — run in executor
        loop = asyncio.get_event_loop()
        grounded_data = await loop.run_in_executor(
            None, self._grounder.ground, question, flavor, max_records
        )

        raw_graph = grounded_data.get("@graph", [])
        accepted, rejected = await loop.run_in_executor(
            None, self._input_gate.screen, raw_graph, flavor
        )
        grounded_data["@graph"] = accepted
        grounded_data["meta"]["record_count"] = len(accepted)
        grounded_data["meta"]["rejected_count"] = len(rejected)

        payload = self._assembler.assemble(
            question=question,
            flavor_name=flavor,
            grounded_data=grounded_data,
            output_format=output_format,
        )

        # Async LLM call
        llm_response = await self._adapter_instance.complete_async(payload)

        gate_result = self._output_gate.validate_and_stamp(
            response=llm_response,
            payload=payload,
            model_id=self._adapter_instance.model_id,
        )

        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        return self._build_result(payload, llm_response, gate_result, elapsed_ms)

    def list_flavors(self) -> list:
        """Return a sorted list of all registered flavor names."""
        return self._registry.list_flavors()

    def get_flavor_info(self, name: str) -> dict:
        """Return full flavor configuration dict for the named flavor.

        Args:
            name: Flavor name.

        Returns:
            The flavor configuration dict.
        """
        return self._registry.load(name)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_adapter(
        self, adapter_name: str, model: Optional[str], api_key: Optional[str]
    ) -> BaseAdapter:
        """Factory method: instantiate the appropriate LLM adapter.

        Args:
            adapter_name: Adapter identifier string.
            model: Optional model override.
            api_key: Optional API key.

        Returns:
            An initialised :class:`BaseAdapter` subclass instance.

        Raises:
            ValueError: If ``adapter_name`` is not recognised.
        """
        adapters_dir = os.path.join(_HERE, "adapters")
        if adapters_dir not in sys.path:
            sys.path.insert(0, adapters_dir)

        if adapter_name == "anthropic":
            from anthropic_adapter import AnthropicAdapter
            kwargs = {}
            if model:
                kwargs["model"] = model
            if api_key:
                kwargs["api_key"] = api_key
            return AnthropicAdapter(**kwargs)

        if adapter_name == "openai":
            from openai_adapter import OpenAIAdapter
            kwargs = {}
            if model:
                kwargs["model"] = model
            if api_key:
                kwargs["api_key"] = api_key
            return OpenAIAdapter(**kwargs)

        if adapter_name in ("vertex", "gemini"):
            from vertex_adapter import VertexAdapter
            kwargs = {}
            if model:
                kwargs["model"] = model
            return VertexAdapter(**kwargs)

        if adapter_name == "ollama":
            from ollama_adapter import OllamaAdapter
            kwargs = {}
            if model:
                kwargs["model"] = model
            return OllamaAdapter(**kwargs)

        raise ValueError(
            f"Unknown adapter '{adapter_name}'. "
            "Choose from: anthropic, openai, vertex, ollama"
        )

    def _build_result(
        self,
        payload: dict,
        llm_response: str,
        gate_result: dict,
        elapsed_ms: int,
    ) -> dict:
        """Build the final result dict from pipeline components.

        Args:
            payload: The assembled payload dict.
            llm_response: The raw LLM response string.
            gate_result: The OutputGate result dict.
            elapsed_ms: Total elapsed time in milliseconds.

        Returns:
            A consolidated result dict.
        """
        return {
            "question": payload.get("meta", {}).get("question", ""),
            "flavor": payload.get("flavor", ""),
            "answer": llm_response,
            "valid": gate_result.get("valid", False),
            "violations": gate_result.get("violations", []),
            "observation_iri": gate_result.get("observation_iri", ""),
            "prov": gate_result.get("prov", {}),
            "model": self._adapter_instance.model_id,
            "payload_id": payload.get("payload_id", ""),
            "elapsed_ms": elapsed_ms,
        }
