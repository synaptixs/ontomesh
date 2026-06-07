"""
RuntimeClient — high-level SDK for the ontology-augmented AI runtime.

Ties FlavorRegistry → Grounder → InputGate → PayloadAssembler → LLM Adapter → OutputGate
into a single call.

Usage:
    client = RuntimeClient(db_path="db/enterprise.db", adapter="anthropic")
    result = client.ask(question="Which NFs are degraded?", flavor="network-ops")
"""

import asyncio
import json
import os
import sys
import time
from abc import ABC, abstractmethod
from typing import Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from flavor_registry import FlavorRegistry
from grounder import Grounder
from assembler import PayloadAssembler
from output_gate import OutputGate
from input_gate import InputGate
from memory import AgentMemory
from hybrid_retriever import HybridRetriever


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
        drift_monitor=None,
        drift_propagator=None,
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
            drift_monitor: Optional :class:`runtime.drift.OntologyDriftMonitor`.
                When provided, every :meth:`ask` call may inject the most
                recent production drift alerts into the LLM payload (set
                ``drift_alerts > 0`` on the call). See
                ``runtime/drift/__init__.py`` for full integration notes.
            drift_propagator: Optional :class:`runtime.drift.OWLPropagator`.
                When set alongside ``drift_monitor``, every alert injected
                into the payload also fires :meth:`OWLPropagator.propagate`,
                escalating monitoring on dependent / sibling entities.
        """
        self._db_path = db_path
        self._out_path = out_path

        self._registry = FlavorRegistry(flavors_dir)
        self._grounder = Grounder(db_path, self._registry)
        self._assembler = PayloadAssembler(self._registry, self._grounder)
        self._input_gate = InputGate(db_path, min_confidence=min_confidence)
        self._output_gate = OutputGate(db_path)
        self._adapter_instance = self._init_adapter(adapter, model, api_key)
        self._memory = AgentMemory(db_path)
        # Workstream 5 — lazy per-flavor HybridRetriever cache
        self._retrievers: dict = {}
        # feature/monitordrift — production drift monitoring
        self._drift_monitor = drift_monitor
        self._drift_propagator = drift_propagator

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

    @property
    def memory(self) -> AgentMemory:
        """The active AgentMemory instance for this client."""
        return self._memory

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
        memory_recall: bool = False,
        memory_recall_limit: int = 5,
        memory_time_range: Optional[Tuple[str, str]] = None,
        retrieval: str = "structured",
        class_expression: Optional[str] = None,
        retrieval_k: int = 5,
        drift_alerts: int = 0,
    ) -> dict:
        """Run the full pipeline for a single question.

        Args:
            question: The natural-language question.
            flavor: The flavor name to scope the query.
            max_records: Maximum records to retrieve from the DB.
            output_format: Desired LLM response format (``"json"``, ``"text"``, etc.).
            save_payload: If ``True``, save the assembled payload to disk.
            memory_recall: If ``True``, prepend relevant prior reasoning from
                the memory layer to the assembled payload before calling the
                LLM.  This gives the agent access to its own prior answers
                on related topics, enabling progressive reasoning across
                invocations.
            memory_recall_limit: Maximum number of prior observations to
                prepend (default 5).  Higher values increase context richness
                but also token cost.
            memory_time_range: Optional ``(iso_from, iso_to)`` tuple to
                restrict which prior observations are recalled.  ``None``
                returns the most recent regardless of age.
            retrieval: Retrieval strategy — ``"structured"`` (default,
                SQL grounding only), ``"hybrid"`` (ontology-bounded
                vector search + SQL grounding via Workstream 5), or
                ``"vector-only"`` (skip SQL grounding).
            class_expression: OWL class expression restricting the
                hybrid retriever's search population (e.g.
                ``"tmf:NetworkFunction"`` or
                ``"tmf:Alarm | tmf:TroubleTicket"``).  Defaults to the
                flavor's declared OWL classes.
            retrieval_k: Number of hybrid-retrieval results to prepend
                to the payload (default 5).

        Returns:
            A result dict with keys: ``question``, ``flavor``, ``answer``,
            ``valid``, ``violations``, ``observation_iri``, ``prov``,
            ``model``, ``elapsed_ms``, ``memory_context_count``.
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

        # Step 2a: Hybrid retrieval — ontology-bounded vector search (Workstream 5)
        hybrid_context_count = 0
        if retrieval in ("hybrid", "vector-only"):
            retriever = self._get_retriever(flavor)
            hybrid = retriever.retrieve(
                question,
                class_expression=class_expression,
                k=retrieval_k,
                strategy="ONTOLOGY_BOUNDED",
            )
            hybrid_records = [r["jsonld"] for r in hybrid["results"] if r.get("jsonld")]
            hybrid_context_count = len(hybrid_records)
            if hybrid_records:
                if retrieval == "vector-only":
                    grounded_data["@graph"] = hybrid_records
                else:
                    grounded_data["@graph"] = hybrid_records + grounded_data["@graph"]
                grounded_data["meta"]["hybrid_context_count"] = hybrid_context_count
                grounded_data["meta"]["record_count"] = len(grounded_data["@graph"])
                grounded_data["meta"]["hybrid_resolved_classes"] = hybrid["resolved_classes"][:12]

        # Step 2b: Memory recall — prepend prior reasoning to the payload
        memory_context_count = 0
        if memory_recall:
            recall_result = self._memory.recall(
                query=question,
                flavor=flavor,
                time_range=memory_time_range,
                limit=memory_recall_limit,
            )
            prior_graph = recall_result.get("@graph", [])
            memory_context_count = len(prior_graph)
            if prior_graph:
                # Prepend prior observations to the grounded @graph so
                # PayloadAssembler includes them in the system context
                grounded_data["@graph"] = prior_graph + grounded_data["@graph"]
                grounded_data["meta"]["memory_context_count"] = memory_context_count
                grounded_data["meta"]["record_count"] += memory_context_count

        # Step 2c: Drift alerts — prepend production-drift context (feature/monitordrift)
        drift_alert_count = self._inject_drift_context(grounded_data, drift_alerts)

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
        result = self._build_result(payload, llm_response, gate_result, elapsed_ms)
        result["memory_context_count"] = memory_context_count
        result["hybrid_context_count"] = hybrid_context_count
        result["drift_alert_count"] = drift_alert_count
        result["retrieval"] = retrieval
        return result

    def retrieve(
        self,
        question: str,
        flavor: str,
        *,
        class_expression: Optional[str] = None,
        k: int = 5,
        strategy: str = "ONTOLOGY_BOUNDED",
    ) -> dict:
        """Run ontology-bounded hybrid retrieval without calling the LLM.

        Thin wrapper around :class:`HybridRetriever` for teams that want
        the retrieval layer only (Workstream 5 — hybrid retrieval for
        custom RAG pipelines).  Returns the raw
        :meth:`HybridRetriever.retrieve` output.
        """
        return self._get_retriever(flavor).retrieve(
            question,
            class_expression=class_expression,
            k=k,
            strategy=strategy,
        )

    def search(
        self,
        question: str,
        flavor: str,
        *,
        depth: str = "single_hop",
        max_tier: str = "Internal",
        k: int = 5,
        **kwargs,
    ):
        """Ontology-grounded **reasoning search** — a cited, reasoned answer.

        Convenience wrapper over :func:`runtime.reasoning_search.search` that
        reuses this client's adapter and database. Returns a ``ReasonedAnswer``
        (plan, results, citations, inferred facts, confidence, executed query,
        trace).  Imported lazily to avoid an import cycle with the package init.
        """
        from runtime.reasoning_search import search as _reasoning_search

        return _reasoning_search(
            question,
            flavor=flavor,
            db_path=self._db_path,
            adapter=self._adapter_instance,
            depth=depth,
            max_tier=max_tier,
            k=k,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # feature/monitordrift — drift context injection
    # ------------------------------------------------------------------

    def _inject_drift_context(self, grounded_data: dict, drift_alerts: int) -> int:
        """Prepend recent drift alerts as JSON-LD records and propagate.

        Symmetric with the memory-recall block above. Returns the number
        of alert records injected. When ``drift_alerts == 0`` or no
        drift_monitor is wired into this client, this is a no-op
        returning ``0``. When a propagator is also wired in, every
        alert fires :meth:`OWLPropagator.propagate` to record
        escalations on dependent entities.
        """
        if drift_alerts <= 0 or self._drift_monitor is None:
            return 0
        alerts = self._drift_monitor.recent_alerts(n=drift_alerts)
        if not alerts:
            return 0
        nodes = [self._alert_to_jsonld(a) for a in alerts]
        grounded_data["@graph"] = nodes + grounded_data.get("@graph", [])
        grounded_data["meta"]["drift_alert_count"] = len(nodes)
        grounded_data["meta"]["record_count"] = (
            grounded_data["meta"].get("record_count", 0) + len(nodes)
        )
        if self._drift_propagator is not None:
            for a in alerts:
                self._drift_propagator.propagate(a)
        return len(nodes)

    @staticmethod
    def _alert_to_jsonld(alert) -> dict:
        """Convert a :class:`drift_monitor.Alert` (or dict) to JSON-LD."""
        def _f(name, default=None):
            if hasattr(alert, name):
                return getattr(alert, name)
            if isinstance(alert, dict):
                return alert.get(name, default)
            return default
        ek = _f("entity_key", "")
        return {
            "@type":            "drift:DriftAlert",
            "@id":              f"drift:alert/{ek}/{_f('timestamp', '')}",
            "drift:entityKey":  ek,
            "drift:severity":   _f("severity"),
            "drift:metric":     _f("metric_type"),
            "drift:observed":   _f("observed"),
            "drift:threshold":  _f("threshold"),
            "drift:message":    _f("message"),
            "drift:recommendation": _f("recommendation"),
            "drift:feature":    _f("feature"),
            "drift:timestamp":  _f("timestamp"),
        }

    def _get_retriever(self, flavor: str) -> HybridRetriever:
        """Cache one :class:`HybridRetriever` per flavor."""
        if flavor not in self._retrievers:
            self._retrievers[flavor] = HybridRetriever(
                flavor=flavor,
                db_path=self._db_path,
            )
        return self._retrievers[flavor]

    def remember(
        self,
        subject: str,
        flavor: Optional[str] = None,
        limit: int = 20,
        time_range: Optional[Tuple[str, str]] = None,
    ) -> dict:
        """Convenience method: recall prior observations about a subject.

        Wraps :meth:`AgentMemory.recall` for ergonomic use alongside
        :meth:`ask`.  Returns a typed JSON-LD dict ready for inspection
        or direct injection into a custom payload.

        Args:
            subject: Free-text subject string — matched against stored
                     ``value_text`` and ``source_ref`` fields.
            flavor: Optional flavor scope restriction.
            limit: Maximum records to return (default 20).
            time_range: Optional ``(iso_from, iso_to)`` tuple.

        Returns:
            A ``MemoryRecallResult`` JSON-LD dict (same as
            :meth:`AgentMemory.recall`).

        Example::

            client = RuntimeClient(db_path="db/enterprise.db")
            prior = client.remember("AMF-East-01", flavor="network-ops")
            print(f"Found {prior['result_count']} prior observations")
        """
        return self._memory.recall(
            query=subject,
            flavor=flavor,
            time_range=time_range,
            limit=limit,
        )

    async def ask_async(
        self,
        question: str,
        flavor: str,
        max_records: int = 50,
        output_format: str = "json",
        save_payload: bool = False,
        memory_recall: bool = False,
        memory_recall_limit: int = 5,
        memory_time_range: Optional[Tuple[str, str]] = None,
        retrieval: str = "structured",
        class_expression: Optional[str] = None,
        retrieval_k: int = 5,
        drift_alerts: int = 0,
    ) -> dict:
        """Async version of :meth:`ask`.

        Args:
            question: The natural-language question.
            flavor: The flavor name to scope the query.
            max_records: Maximum records to retrieve from the DB.
            output_format: Desired LLM response format.
            save_payload: If ``True``, save the assembled payload to disk.
            memory_recall: If ``True``, prepend relevant prior reasoning to
                the payload before the LLM call (same as sync :meth:`ask`).
            memory_recall_limit: Maximum prior observations to prepend.
            memory_time_range: Optional ``(iso_from, iso_to)`` time filter.

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

        # Hybrid retrieval (async-compatible: DB I/O in executor)
        hybrid_context_count = 0
        if retrieval in ("hybrid", "vector-only"):
            retriever = self._get_retriever(flavor)
            hybrid = await loop.run_in_executor(
                None,
                lambda: retriever.retrieve(
                    question,
                    class_expression=class_expression,
                    k=retrieval_k,
                    strategy="ONTOLOGY_BOUNDED",
                ),
            )
            hybrid_records = [r["jsonld"] for r in hybrid["results"] if r.get("jsonld")]
            hybrid_context_count = len(hybrid_records)
            if hybrid_records:
                if retrieval == "vector-only":
                    grounded_data["@graph"] = hybrid_records
                else:
                    grounded_data["@graph"] = hybrid_records + grounded_data["@graph"]
                grounded_data["meta"]["hybrid_context_count"] = hybrid_context_count
                grounded_data["meta"]["record_count"] = len(grounded_data["@graph"])
                grounded_data["meta"]["hybrid_resolved_classes"] = hybrid["resolved_classes"][:12]

        # Memory recall (async-compatible: DB I/O in executor)
        memory_context_count = 0
        if memory_recall:
            recall_result = await loop.run_in_executor(
                None,
                lambda: self._memory.recall(
                    query=question,
                    flavor=flavor,
                    time_range=memory_time_range,
                    limit=memory_recall_limit,
                ),
            )
            prior_graph = recall_result.get("@graph", [])
            memory_context_count = len(prior_graph)
            if prior_graph:
                grounded_data["@graph"] = prior_graph + grounded_data["@graph"]
                grounded_data["meta"]["memory_context_count"] = memory_context_count
                grounded_data["meta"]["record_count"] += memory_context_count

        # Drift alerts (feature/monitordrift) — same helper as sync ask()
        drift_alert_count = self._inject_drift_context(grounded_data, drift_alerts)

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
        result = self._build_result(payload, llm_response, gate_result, elapsed_ms)
        result["memory_context_count"] = memory_context_count
        result["hybrid_context_count"] = hybrid_context_count
        result["drift_alert_count"] = drift_alert_count
        result["retrieval"] = retrieval
        return result

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

        if adapter_name == "oci":
            from oci_adapter import OCIAdapter
            kwargs = {}
            if model:
                kwargs["model"] = model
            return OCIAdapter(**kwargs)

        raise ValueError(
            f"Unknown adapter '{adapter_name}'. "
            "Choose from: anthropic, openai, vertex, ollama, oci"
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
