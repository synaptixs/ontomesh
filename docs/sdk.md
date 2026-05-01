# Ontology Toolkit — Python SDK Reference

**Version:** 3.0.0 · **Package:** `ontology-toolkit` · **Audience:** application developers, integration engineers

This is the canonical reference for the toolkit's public Python API. Each entry follows a fixed shape: signature, description, parameters, returns, raises, example. Use the table of contents to jump directly to the call you need.

---

## Table of contents

- [Quick start](#quick-start)
- [Module map](#module-map)
- [`runtime.RuntimeClient`](#runtimeruntimeclient) — top-level orchestrator
- [`runtime.FlavorRegistry`](#runtimeflavorregistry) — ontology flavor configs
- [`runtime.Grounder`](#runtimegrounder) — DB → JSON-LD payloads
- [`runtime.PayloadAssembler`](#runtimepayloadassembler) — full LLM payload builder
- [`runtime.InputGate`](#runtimeinputgate) — pre-LLM SHACL screening
- [`runtime.OutputGate`](#runtimeoutputgate) — post-LLM SHACL + PROV-O stamping
- [`runtime.AgentMemory`](#runtimeagentmemory) — temporal recall / diff / consolidation
- [`runtime.HybridRetriever`](#runtimehybridretriever) — ontology-bounded hybrid retrieval
- [`runtime.ConsolidationDaemon`](#runtimeconsolidationdaemon) — background memory consolidation
- [`runtime.drift.*`](#runtimedrift--production-drift-monitoring) — production drift monitoring (P1–P5)
- [`runtime.adapters.*`](#runtimeadapters--llm-adapters) — Anthropic / OpenAI / Vertex / OCI / Ollama
- [`runtime.embeddings.*`](#runtimeembeddings--vector-retrieval) — embedding pipeline + vector stores
- [`runtime.temporal_queries`](#runtimetemporal_queries) — SPARQL template helpers
- [Pipeline modules (`src.*`)](#pipeline-modules-src) — toolkit phases (CLI-orchestrated)

---

## Quick start

```python
from runtime import RuntimeClient

client = RuntimeClient(
    db_path="db/enterprise.db",
    adapter="anthropic",                # "anthropic" | "openai" | "vertex" | "oci" | "ollama"
    model="claude-sonnet-4-5",
)

result = client.ask(
    question="Which network functions are degraded?",
    flavor="network-ops",
    output_format="json",
)
print(result["answer"])
print(result["payload"]["records"])      # grounded JSON-LD
print(result["provenance"]["model_id"])  # PROV-O stamp
```

The `RuntimeClient` orchestrates: `FlavorRegistry → Grounder → InputGate → PayloadAssembler → adapter.complete → OutputGate`. Every step is independently usable.

---

## Module map

| Layer | Modules | Purpose |
|---|---|---|
| **Public SDK** | `runtime.RuntimeClient` | Single entry point |
| **Configuration** | `runtime.FlavorRegistry` | Domain flavor JSON loader/validator |
| **Pipeline** | `runtime.Grounder` · `runtime.PayloadAssembler` · `runtime.InputGate` · `runtime.OutputGate` | DB → payload → gate cycle |
| **Memory** | `runtime.AgentMemory` · `runtime.ConsolidationDaemon` · `runtime.temporal_queries` | Temporal observation graph |
| **Retrieval** | `runtime.HybridRetriever` · `runtime.embeddings.*` | Ontology-bounded vector search |
| **Drift** | `runtime.drift.OntologyDriftMonitor` · `DriftEnricher` · `SHACLGate` · `OWLPropagator` | Production drift monitoring (infodrift) |
| **Adapters** | `runtime.adapters.{Anthropic,OpenAI,Vertex,OCI,Ollama}Adapter` | LLM backends |
| **Pipeline (CLI)** | `src.*` | Schema introspection, OWL/SHACL generation, conflict resolution, evolution review |

---

## `runtime.RuntimeClient`

High-level SDK that orchestrates the full ontology-augmented AI pipeline.

### `RuntimeClient(...)`

```python
RuntimeClient(
    db_path: str,
    adapter: str = "anthropic",
    flavors_dir: Optional[str] = None,
    out_path: str = "output",
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    min_confidence: float = 0.0,
    drift_monitor=None,
    drift_propagator=None,
)
```

Initialise the client. The `adapter` argument may also be a pre-instantiated `BaseAdapter` subclass (use this to inject a custom OCI provider, mock adapter, etc.).

| Parameter | Type | Default | Description |
|---|---|---|---|
| `db_path` | `str` | — | Path to enterprise SQLite DB (or driver URI for non-SQLite) |
| `adapter` | `str \| BaseAdapter` | `"anthropic"` | LLM adapter name or instance |
| `flavors_dir` | `Optional[str]` | `runtime/flavors/` | Override flavor JSON directory |
| `out_path` | `str` | `"output"` | Where payloads / logs are persisted |
| `model` | `Optional[str]` | adapter default | Model ID (e.g. `"claude-sonnet-4-5"`) |
| `api_key` | `Optional[str]` | env var | API key (defaults to provider env var) |
| `min_confidence` | `float` | `0.0` | InputGate floor for record confidence |
| `drift_monitor` | `OntologyDriftMonitor \| None` | `None` | Optional drift monitor for `drift_alerts` injection |
| `drift_propagator` | `OWLPropagator \| None` | `None` | Optional OWL alert propagator |

### `RuntimeClient.ask(...)`

```python
ask(
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
) -> dict
```

Run the full pipeline for a single question.

| Parameter | Type | Description |
|---|---|---|
| `question` | `str` | Natural-language question |
| `flavor` | `str` | Registered flavor name (e.g. `"network-ops"`) |
| `max_records` | `int` | Cap for grounded records |
| `output_format` | `str` | `"json"` (structured) or `"text"` |
| `save_payload` | `bool` | Persist the assembled payload to `out_path/` |
| `memory_recall` | `bool` | Prepend top-k AgentMemory observations to payload |
| `memory_recall_limit` | `int` | k for memory recall |
| `memory_time_range` | `(start_iso, end_iso) \| None` | Temporal filter for recall |
| `retrieval` | `"structured" \| "hybrid"` | If `"hybrid"`, also runs `HybridRetriever` |
| `class_expression` | `str \| None` | OWL class IRI to bound retrieval |
| `retrieval_k` | `int` | k for hybrid retrieval |
| `drift_alerts` | `int` | Inject N most recent drift alerts into payload |

**Returns** — `dict`

```jsonc
{
  "answer": "...",                   // raw LLM text or parsed JSON
  "payload": { ... },                // full LLM input (system, context, records)
  "provenance": {
    "model_id": "claude-sonnet-4-5",
    "validated_at": "2026-04-30T12:34:56Z",
    "shacl_violations": [],
    "confidence": 0.92
  },
  "input_gate": { "accepted": 42, "rejected": 0 },
  "memory": [ ... ],                 // present if memory_recall=True
  "retrieval": { ... },              // present if retrieval="hybrid"
  "drift": [ ... ]                   // present if drift_alerts > 0
}
```

**Raises** — `ValueError` if `flavor` is unregistered. `RuntimeError` on adapter or SHACL failure.

**Example**

```python
result = client.ask(
    "Which UPF instances breached latency SLO last hour?",
    flavor="network-ops",
    retrieval="hybrid",
    class_expression="http://example.org/onto/UPF",
    retrieval_k=10,
    drift_alerts=3,
)
```

### `RuntimeClient.ask_async(...)`

Same signature as `ask` but `async` and uses the adapter's async client. **Returns** `Awaitable[dict]`.

### `RuntimeClient.retrieve(...)`

```python
retrieve(
    question: str,
    flavor: str,
    *,
    class_expression: Optional[str] = None,
    k: int = 5,
    strategy: str = "ONTOLOGY_BOUNDED",
) -> dict
```

Run ontology-bounded hybrid retrieval **without** calling the LLM. Useful for debug/inspection. `strategy` ∈ `{"UNFILTERED_VECTOR", "ONTOLOGY_BOUNDED", "PURE_SPARQL"}`.

**Returns** — `{"results": [{"iri": ..., "score": ..., "owl_class": ..., "snippet": ...}, ...], "strategy": ..., "k": ...}`

### `RuntimeClient.remember(...)`

```python
remember(
    subject: str,
    flavor: Optional[str] = None,
    limit: int = 20,
    time_range: Optional[Tuple[str, str]] = None,
) -> dict
```

Convenience for `client.memory.recall(query=subject, ...)`. **Returns** `{"observations": [...], "count": int}`.

### Properties

| Property | Type | Notes |
|---|---|---|
| `registry` | `FlavorRegistry` | The active flavor registry |
| `grounder` | `Grounder` | |
| `assembler` | `PayloadAssembler` | |
| `input_gate` | `InputGate` | |
| `output_gate` | `OutputGate` | |
| `adapter_instance` | `BaseAdapter` | The active LLM adapter |
| `memory` | `AgentMemory` | |

### Other methods

- `list_flavors() -> list[str]` — names of all registered flavors.
- `get_flavor_info(name: str) -> dict` — full flavor JSON.

---

## `runtime.FlavorRegistry`

Loads and validates flavor JSON files. A *flavor* is a domain-scoped configuration: which OWL classes are in-scope, the JSON-LD `@context`, the system prompt preamble, memory-sharing policy, and embedding model.

### `FlavorRegistry(flavors_dir: Optional[str] = None)`

If `flavors_dir` is `None`, defaults to `runtime/flavors/` in the installed package.

### Methods

| Method | Signature | Returns |
|---|---|---|
| `load(name)` | `(name: str) -> dict` | Full flavor dict |
| `list_flavors()` | `() -> list[str]` | Sorted flavor names |
| `validate(flavor)` | `(flavor: dict) -> list[str]` | List of validation errors (empty = valid) |
| `get_context(name)` | `(name: str) -> dict` | JSON-LD `@context` |
| `get_system_prompt(name)` | `(name: str) -> str` | System prompt preamble |
| `get_memory_sharing_policy(name)` | `(name: str) -> dict` | Memory access policy |
| `check_memory_access(req, target, tier)` | `(str, str, str) -> bool` | Whether `req` flavor may read `target` flavor at `tier` |
| `get_embedding_config(name)` | `(name: str) -> dict` | `{"model_id": ..., "dim": ..., ...}` |
| `register(flavor_dict, save=False)` | `(dict, bool) -> None` | Register in-memory; persist if `save=True` |

**Example**

```python
from runtime import FlavorRegistry

reg = FlavorRegistry()
print(reg.list_flavors())   # ['customer', 'fault-management', 'fiveg', 'network-ops', 'retail']

errors = reg.validate(my_flavor_dict)
if errors:
    raise ValueError(errors)
```

---

## `runtime.Grounder`

Bridges enterprise database records to JSON-LD payloads.

### `Grounder(db_path, flavor_registry=None)`

| Parameter | Type | Default |
|---|---|---|
| `db_path` | `str` | — |
| `flavor_registry` | `FlavorRegistry \| None` | new registry |

### `Grounder.ground(question, flavor_name, max_records=50) -> dict`

Ground a question by querying the DB and returning a JSON-LD payload.

**Returns**

```jsonc
{
  "@context": { ... },           // flavor JSON-LD context
  "records": [ {...}, ... ],     // typed JSON-LD records
  "table_set": ["NetworkFunction", "Alarm"],
  "sparql": "SELECT ...",        // SPARQL fingerprint
  "ts": "2026-04-30T12:34:56Z"
}
```

### `Grounder.record_grounding(grounding_result) -> str`

Insert an `ObservationRecord` for the grounding event into the memory graph. **Returns** the record IRI.

---

## `runtime.PayloadAssembler`

Assembles the complete LLM input payload from five components: system prompt, ontology flavor, grounded data, PROV-O context, question.

### `PayloadAssembler(flavor_registry, grounder=None)`

### `PayloadAssembler.assemble(...) -> dict`

```python
assemble(
    question: str,
    flavor_name: str,
    grounded_data: Optional[dict] = None,
    output_format: str = "json",
    max_tokens: int = 4000,
) -> dict
```

If `grounded_data` is `None`, the assembler will call `grounder.ground(...)` itself.

**Returns**

```jsonc
{
  "system": "...",                 // ontology summary + agent role
  "context": { ... },              // JSON-LD @context
  "records": [ ... ],              // grounded data
  "provenance_context": { ... },
  "question": "...",
  "format": "json",
  "max_tokens": 4000
}
```

### `PayloadAssembler.save(payload, out_path) -> None`

Write the payload dict to a JSON file.

---

## `runtime.InputGate`

Validates enterprise data against SHACL shapes **before** it enters the LLM payload. Rejected records are logged with `loss_type=REJECTED_AT_RUNTIME_GATE`.

### `InputGate(db_path, shapes_dir=None, min_confidence=0.0)`

### Methods

| Method | Signature | Returns |
|---|---|---|
| `screen(records, flavor_name)` | `(list, str) -> tuple[list, list]` | `(accepted, rejected)` |
| `screen_db_query(table, where="1=1", flavor_name=...)` | `(str, str, str) -> tuple[list, list]` | Same |
| `summary(accepted, rejected)` | `(list, list) -> dict` | `{accepted_count, rejected_count, by_violation: {...}}` |

**Example**

```python
gate = InputGate("db/enterprise.db", min_confidence=0.7)
accepted, rejected = gate.screen(records, flavor_name="network-ops")
print(gate.summary(accepted, rejected))
```

---

## `runtime.OutputGate`

Validates LLM response output and stamps PROV-O provenance.

### `OutputGate(db_path, shapes_dir=None)`

### `OutputGate.validate_and_stamp(...) -> dict`

```python
validate_and_stamp(
    response: Union[str, dict],
    payload: dict,
    model_id: str,
    confidence: Optional[float] = None,
) -> dict
```

**Returns**

```jsonc
{
  "answer": ...,                    // string or parsed dict
  "shacl_violations": [],           // empty if valid
  "provenance": {
    "wasGeneratedBy": "...",
    "wasAttributedTo": "model:claude-sonnet-4-5",
    "generatedAtTime": "2026-04-30T...",
    "wasDerivedFrom": [record IRIs]
  },
  "confidence": 0.92
}
```

**Raises** — `ValueError` if SHACL validation fails (when configured to be strict).

---

## `runtime.AgentMemory`

Long-term semantic memory — temporal queries over `ObservationRecord` graph.

### `AgentMemory(db_path, temporal_queries_dir=None)`

### Methods

#### `recall(...) -> dict`

```python
recall(
    query: str,
    flavor: Optional[str] = None,
    time_range: Optional[Tuple[str, str]] = None,
    record_type: Optional[str] = None,
    limit: int = 50,
) -> dict
```

Retrieve prior reasoning observations matching a query. **Returns** `{"observations": [...], "count": int, "sparql": "..."}`.

#### `diff(agent_a, agent_b, subject=None, limit=100) -> dict`

Identify assertions where two agent flavors disagreed. **Returns** `{"disagreements": [{"subject", "a_value", "b_value", "ts"}, ...]}`.

#### `consolidate(older_than_days=90, dry_run=False) -> dict`

Run memory consolidation across three strategies: redundancy collapse, low-confidence pruning, supersession. **Returns** `{"consolidated": int, "strategies": {...}, "dry_run": bool}`.

#### `snapshot(at, entity_iri=None, flavor=None) -> dict`

Return the ontology state as observed at a specific timestamp `at` (ISO 8601). **Returns** `{"as_of": ..., "entities": [...]}`.

#### `influence_graph(agent=None, limit=200) -> dict`

Return the agent-to-agent influence graph via PROV-O `wasDerivedFrom` links.

---

## `runtime.HybridRetriever`

Ontology-bounded vector retrieval + graph enrichment.

### Constructor

```python
HybridRetriever(
    *,
    flavor: str,
    db_path: str = "db/enterprise.db",
    flavors_dir: Optional[str] = None,
    connection_string: Optional[str] = None,    # vector store URI
    model_id: Optional[str] = None,             # embedding model
    ontology_path: Optional[str] = None,
)
```

### `retrieve(question, *, class_expression=None, k=5, over_fetch=3, strategy="ONTOLOGY_BOUNDED", min_score=0.0) -> dict`

| `strategy` | Behaviour |
|---|---|
| `"UNFILTERED_VECTOR"` | Pure cosine similarity, no class filter |
| `"ONTOLOGY_BOUNDED"` | Vector search restricted to OWL subgraph of `class_expression` |
| `"PURE_SPARQL"` | SPARQL only, no vectors |

**Returns** `{"results": [{"iri", "score", "owl_class", "snippet", "metadata"}, ...], "strategy", "k", "over_fetch"}`.

### Properties

- `adapter` — underlying `VectorStoreAdapter`
- `model_id` — active embedding model ID
- `connection` — vector store connection string

---

## `runtime.ConsolidationDaemon`

Background process that runs consolidation strategies on a schedule.

### `ConsolidationDaemon(db_path, config_path="runtime/consolidation_config.json")`

| Method | Signature | Description |
|---|---|---|
| `run_once(dry_run=None)` | `(Optional[bool]) -> dict` | One pass over enabled strategies |
| `run_scheduled()` | `() -> None` | Blocking loop — honours `schedule_cron` in config |

The config file declares strategies, `older_than_days`, and `schedule_cron`.

---

## `runtime.drift.*` — Production drift monitoring

Wraps the [infodrift](https://github.com/nrohilla-fibonacci/infodrift) `drift_monitor` library so it is driven by OWL individuals, validates DataFrames against SHACL, enriches reports as JSON-LD ObservationRecords, and propagates alerts along the OWL class graph.

Phases (P1–P5):

| Phase | Class / function | Purpose |
|---|---|---|
| P1 — namespace | `runtime.drift.iri_to_entity_key` | OWL IRI → drift_monitor entity key |
| P2 — register | `OntologyDriftMonitor` | Discover individuals, register baselines |
| P3 — gate | `SHACLGate` | Pre-flight DataFrame validation |
| P4 — enrich | `DriftEnricher` | Wrap reports as JSON-LD + PROV-O |
| P5 — propagate | `OWLPropagator` | Escalate to related entities |

### `OntologyDriftMonitor`

```python
OntologyDriftMonitor(
    ontology_path: str | Path = DEFAULT_ONTOLOGY_PATH,
    namespace: str = DEFAULT_NAMESPACE,
    slo_config: dict | None = None,
    alert_buffer: int = 256,
    **orchestrator_kwargs,
)
```

| Method | Signature | Description |
|---|---|---|
| `discover_individuals()` | `() -> list[str]` | Entity keys under `namespace` |
| `register_all(...)` | see below | Register every discovered individual that has a baseline |
| `run(entity_key, prod_df=None, prod_logs=None, *, window_id="latest", **kw)` | `-> list[Alert]` | One drift_monitor pass; appends to alert buffer |
| `recent_alerts(n=5)` | `-> list[Alert]` | Newest-last alerts |
| `latest_report(entity_key)` | passthrough to `DriftOrchestrator.latest_report` |
| `orchestrator` | property | Underlying `DriftOrchestrator` |
| `registered_entities` | property | `list[str]` |
| `namespace` | property | `str` |
| `ontology` | property | `rdflib.Graph` |

```python
register_all(
    baseline_features: dict[str, Any],
    baseline_logs: dict[str, list[str]] | None = None,
    numeric_features: list[str] | None = None,
    categorical_features: list[str] | None = None,
    *,
    skip_unknown: bool = True,
) -> list[str]
```

### `DriftEnricher`

Wrap a drift report as a JSON-LD ObservationRecord and persist it to a JSONL store.

```python
DriftEnricher(
    context_path = DEFAULT_CONTEXT_PATH,
    obs_db_path  = DEFAULT_OBS_DB,
    entity_namespace = DEFAULT_NAMESPACE,
    drift_namespace  = DRIFT_NAMESPACE,
)
```

| Method | Signature | Returns |
|---|---|---|
| `enrich(raw_report, *, baseline_id, window_id, run_iri=None)` | builds JSON-LD (no I/O) | `dict` |
| `store(enriched)` | append to JSONL | `Path` |
| `enrich_and_store(...)` | one-shot | `dict` |

### `SHACLGate`

Pre-flight SHACL validator for any production DataFrame.

```python
SHACLGate(
    shapes_path: str | Path = DEFAULT_SHAPES_PATH,
    namespace: str = DEFAULT_NAMESPACE,
    df_to_rdf: Callable[[pd.DataFrame, str, str], Graph] | None = None,
)
```

- `validate(df, entity_key, *, abort_on_first=False) -> pd.DataFrame` — returns `df` unchanged if it conforms; raises `SHACLValidationError` otherwise.
- `is_active() -> bool` — `True` if the shapes graph has any constraints loaded.
- `shapes_path` — `Path` property.

`SHACLValidationError(message, report_graph=None, report_text=None)` — exposes `.report_graph` (rdflib `Graph`) and `.report_text`.

### `OWLPropagator`

```python
OWLPropagator(ontology_path=DEFAULT_ONTOLOGY_PATH, namespace=DEFAULT_NAMESPACE)
```

| Method | Signature | Description |
|---|---|---|
| `related_classes(owl_class)` | `(URIRef) -> set[URIRef]` | Sibling classes |
| `related_individuals(owl_class, suffix)` | `(URIRef, str) -> set[str]` | Individuals matching suffix |
| `dependents(entity_key)` | `(str) -> list[str]` | Deduplicated related entity keys |
| `propagate(alert, monitor=None)` | `(Alert, OntologyDriftMonitor \| None) -> list[str]` | Record escalations |
| `escalations_for(entity_key)` | `(str) -> list[dict]` | Per-entity escalation log |
| `escalations` | `dict[str, list[dict]]` | All escalations |
| `clear()` | `() -> None` | Reset |

**Example — full P1–P5 wiring**

```python
from runtime.drift import OntologyDriftMonitor, SHACLGate, DriftEnricher, OWLPropagator

mon = OntologyDriftMonitor(ontology_path="output/onto/master.ttl")
gate = SHACLGate(shapes_path="output/shapes/drift-shapes.ttl")
enricher = DriftEnricher()
prop = OWLPropagator(ontology_path="output/onto/master.ttl")

mon.register_all(baseline_features={...}, numeric_features=["latency_ms", "throughput"])
df = gate.validate(prod_df, entity_key="onto::UPF::upf-1")
alerts = mon.run("onto::UPF::upf-1", prod_df=df, window_id="2026-04-30T12:00")
for a in alerts:
    enricher.enrich_and_store(mon.latest_report("onto::UPF::upf-1"),
                              baseline_id="2026-04-29", window_id="2026-04-30T12:00")
    prop.propagate(a, monitor=mon)
```

---

## `runtime.adapters.*` — LLM adapters

All adapters subclass `BaseAdapter` and expose `complete(payload) -> str` and `complete_async(payload) -> str`. `payload` is the dict produced by `PayloadAssembler.assemble`.

### `BaseAdapter(model: str)`

| Method / Property | Returns |
|---|---|
| `model_id` (property) | `str` |
| `complete(payload)` | `str` |
| `complete_async(payload)` | `str` (awaitable) |

### `AnthropicAdapter`

```python
AnthropicAdapter(model: str = "claude-sonnet-4-5", api_key: Optional[str] = None)
```

Uses Messages API with prompt caching. `api_key` defaults to `ANTHROPIC_API_KEY`.

### `OpenAIAdapter`

```python
OpenAIAdapter(model: str = "gpt-4o", api_key: Optional[str] = None)
```

`api_key` defaults to `OPENAI_API_KEY`.

### `VertexAdapter`

```python
VertexAdapter(model: str = "gemini-1.5-pro", project: Optional[str] = None, location: str = "us-central1")
```

Uses Application Default Credentials. `project` defaults to `GOOGLE_CLOUD_PROJECT`.

### `OCIAdapter`

```python
OCIAdapter(
    model: str = "cohere.command-r-plus",
    compartment_id: Optional[str] = None,
    config_path: Optional[str] = None,
    profile: Optional[str] = None,
    endpoint: Optional[str] = None,
    provider: str = "cohere",        # or "meta"
)
```

`compartment_id` defaults to `OCI_COMPARTMENT_ID`. See README → "OCI Generative AI setup".

### `OllamaAdapter`

```python
OllamaAdapter(model: str = "llama3", base_url: str = "http://localhost:11434")
```

For local, no-key models.

---

## `runtime.embeddings.*` — Vector retrieval

### `runtime.embeddings.pipeline`

| Function | Signature | Returns |
|---|---|---|
| `index_flavor(flavor_name, *, db_path=..., flavors_dir=None, connection_string=None, model_id=None, force=False, limit=None)` | indexes every row from the flavor's DB tables | `dict` summary |
| `reindex_all(*, db_path=..., flavors_dir=None, force=False)` | reindex every registered flavor | `list[dict]` |
| `list_indexes(db_path=...)` | enumerate registered indexes with row counts | `list[dict]` |

### `runtime.embeddings.embedder`

| Function | Signature | Returns |
|---|---|---|
| `resolve_model(model_id)` | model registry entry | `dict` |
| `embed_text(text, model_id=None)` | embed text (default = hash embedder, zero-install) | `list[float]` |
| `cosine_similarity(a, b)` | cosine of two equal-length vectors | `float` |

### `runtime.embeddings.class_filter`

| Function | Signature | Returns |
|---|---|---|
| `resolve_class_hierarchy(class_iri, *, ontology_path=None)` | full set of OWL class IRIs in the subgraph | `list[str]` |
| `build_metadata_filter(class_expression=None, *, flavor=None, flavors_dir=None, ontology_path=None, requesting_tier="Internal")` | portable metadata filter | `dict` |
| `passes_filter(record_meta, metadata_filter)` | predicate evaluator | `bool` |

### `runtime.embeddings.adapters` — Vector store adapters

All adapters implement the `VectorStoreAdapter` interface:

```python
class VectorStoreAdapter:
    def ensure_index(self, dim: int, metadata_fields: Iterable[str]) -> None
    def upsert(self, records: List[Dict[str, Any]]) -> int
    def search(self, vector: List[float], metadata_filter: Dict[str, Any], k: int = 5) -> List[Dict[str, Any]]
    def delete(self, record_iris: List[str]) -> int
    def count(self) -> int
    def health_check(self) -> Dict[str, Any]
```

Concrete adapters:

| Class | Backend | Filter dialect |
|---|---|---|
| `MemoryAdapter` | SQLite reference impl | portable |
| `QdrantAdapter` | Qdrant | `must` / `match` payload filter |
| `ChromaAdapter` | Chroma | `where` clause `$in` |
| `WeaviateAdapter` | Weaviate | GraphQL filter |
| `PgVectorAdapter` | PostgreSQL pgvector | SQL `<=>` cosine operator |

Helpers:

| Function | Signature | Returns |
|---|---|---|
| `get_adapter(connection_string, index_name, *, db_path=...)` | resolve URI → adapter | `VectorStoreAdapter` |
| `list_supported_backends()` | `()` | `list[str]` |
| `pack_vector(vec)` / `unpack_vector(b64)` | base64 float32 codec | `str` / `list[float]` |

### `runtime.embeddings.benchmark`

```python
run_benchmark(
    *,
    db_path=..., out_path=...,
    queries: Optional[List[Dict[str, Any]]] = None,
    k: int = 5,
    strategies: Tuple[str, ...] = ("UNFILTERED_VECTOR", "ONTOLOGY_BOUNDED", "PURE_SPARQL"),
) -> dict
```

Emits per-strategy precision@k, MRR, and p50/p95 latency. `read_latest_benchmark(db_path=...)` returns the last persisted result.

### `runtime.embeddings.dashboard`

`write_summary(*, out_path: str, db_path: str) -> dict[str, str]` — writes `retrieval_summary.html` + `retrieval_indexes.csv`.

---

## `runtime.temporal_queries`

Parameterised SPARQL templates for the memory layer.

| Function | Signature | Returns |
|---|---|---|
| `load_template(name)` | `(str) -> str` | Raw SPARQL with `{{PARAM}}` placeholders |
| `fill_template(name, params)` | `(str, dict) -> str` | SPARQL with substitutions |
| `list_templates()` | `() -> list[str]` | All available template names (e.g. `"TQ-01"`) |

---

## Pipeline modules (`src.*`)

The `src/` package contains the pipeline phases invoked by the `ontology-toolkit` CLI. They are usable directly when you need a single phase. Highlights:

### `src.db_introspector`

Introspect a DB schema and emit a class/property inventory. Entry point: `run_introspect(db_path, out_path) -> dict`.

### `src.db_connector`

Unified database abstraction. Connectors: `SQLiteConnector`, `PostgreSQLConnector`, `MySQLConnector`, plus MSSQL/Oracle/DB2 variants. The `Connector` base class exposes:

- `get_tables() -> list[str]`
- `get_columns(table) -> list[ColInfo]`
- `execute(sql, params=()) -> list[dict]`
- `execute_script(sql) -> None`
- `dialect() -> str`
- `close() -> None`
- `table_exists`, `get_row_count`, `get_distinct_values`, `get_sample_rows`

`ColInfo` fields: `name, data_type, is_nullable, is_pk, fk_table, column_default`.

### `src.ontology_generator` · `src.shacl_generator` · `src.jsonld_generator` · `src.rbac_generator` · `src.tmf_mapper`

Phase 2/3/5 generators. Each exposes a `run_*` function that takes `(db_path, out_path)` and returns a status dict.

### `src.conflict_resolver`

| Function | Signature | Description |
|---|---|---|
| `run_conflict_resolution(db_path, out_path)` | `(str, str) -> dict` | Full 3-tier pass |
| `run_tier1_checks(conn)` | `(sqlite3.Connection) -> list[dict]` | SHACL-equivalent SQL checks |
| `resolve_tier2(a, b)` | `(dict, dict) -> tuple[dict, dict, str]` | Derivation-method priority chain |
| `record_invalidation(conn, loser, winner, conflict)` | `-> None` | PROV-O `wasInvalidatedBy` |
| `escalate_to_human(conn, conflict, assigned_to=None)` | `-> None` | Tier-3 escalation |

### `src.evolution_reviewer`

| Function | Signature | Description |
|---|---|---|
| `list_pending(db_path, band=None, limit=100)` | `-> list[dict]` | Pending proposals by confidence |
| `get_proposal(db_path, proposal_id)` | `-> dict \| None` | Proposal detail |
| `record_decision(db_path, proposal_id, action, reviewer_id, note="", version_target=None, defer_until=None)` | `-> dict` | APPROVE / REJECT / DEFER |
| `apply_approved(db_path, out_path, proposal_id, *, open_pr=False, dry_run=False)` | `-> dict` | Apply through CI/CD gate |

### `src.evolution_monitor` · `src.evolution_scorer`

Anomaly detection (4 strategies) and 5-dim candidate scoring. Entry points: `run_evolution_monitor(db_path, out_path)` and `run_evolution_scorer(db_path, out_path)`.

### `src.log_connector`

| Function | Signature | Description |
|---|---|---|
| `ingest_logs(db_path, log_path, fmt="auto", custom_regex=None, dry_run=False, output_dir=None)` | `-> dict` | Parse logs, match entities, write rows |
| `run_log_ingest(db_path, out_path, log_path, fmt="auto", ...)` | `-> dict` | Phase entry-point used by `toolkit.py` |

`LogRecord` and `EntityMatcher` are the underlying primitives.

### `src.reasoner`

ROBOT framework integration for OWL 2 reasoning.

| Function | Signature | Returns |
|---|---|---|
| `run_reasoner(ontology_path, output_path, profile="OWL 2 EL")` | `-> dict` | Classify with ROBOT |
| `snapshot_hierarchy(classified_path, snapshot_path)` | `-> dict` | Save class hierarchy |
| `diff_hierarchy(old, new)` | `-> dict` | Hierarchy diff |
| `find_unsatisfiable(ontology_path)` | `-> list[dict]` | Unsatisfiable class findings |
| `run_and_report(ontology_path, output_dir, profile="OWL 2 EL")` | `-> dict` | reason → snapshot → diff → report |

### `src.drift_detector`

Phase-3 drift ontology extension (separate from production `runtime.drift.*`).

| Function | Signature | Returns |
|---|---|---|
| `run_drift_detection(out_path)` | `-> dict` | Generate `drift.ttl`, `drift-shapes.ttl`, `drift-skos.ttl` |
| `compute_psi(baseline, current, epsilon=1e-6)` | `-> float` | Population Stability Index |
| `severity_from_psi(psi)` / `severity_from_js(js)` | `-> str` | `"none" \| "warning" \| "critical"` |

### `src.template_loader`

Industry templates (Energy, Logistics, Government, Insurance, Pharma, …).

| Function | Signature |
|---|---|
| `list_templates()` |
| `load_template(name)` |
| `generate_sql_schema(tmpl)` |
| `generate_owl_module(tmpl)` |
| `generate_cq_catalog(tmpl)` |
| `run_templates(out_path, template_name="all")` |

---

## Versioning & stability

| Surface | Stability |
|---|---|
| `runtime.RuntimeClient` public methods | **Stable** — additive changes only |
| `runtime.adapters.BaseAdapter` interface | **Stable** |
| `runtime.drift.*` (P1–P5) | **Stable as of v3.0** |
| `runtime.embeddings.*` adapter interface | **Stable** |
| `src.*` phase entry-points (`run_*`) | **Stable** — used by `toolkit.py` CLI |
| Anything starting with `_` | **Private** — no compatibility guarantees |

---

*Generated for ontology-toolkit v3.0.0 · April 2026 · Source of truth: docstrings + signatures in `runtime/` and `src/`.*
