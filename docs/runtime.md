# Runtime layer — connecting the toolkit to AI and LLMs

How the toolkit's OWL/SHACL/JSON-LD outputs become governance gates around live LLM calls. Covers flavors, grounding, payload assembly, input/output gates, the SDK, all five LLM adapters, and OCI Generative AI setup. For the SDK reference see [sdk.md](sdk.md).

---

## 8. Runtime — connecting the toolkit to AI and LLMs

The pipeline phases (1–5, TMF) build the semantic artifacts. The runtime layer is how an enterprise *uses* those artifacts to power AI agents and LLM applications. This section describes the architecture, the five components, and the two flows every deployment follows.

### The core idea

After onboarding, an enterprise has:
- A master OWL 2 ontology describing every domain concept
- SHACL validation shapes enforcing data quality
- A JSON-LD context binding field names to ontology IRIs
- Ontology-annotated enterprise data in a relational database

The runtime layer assembles these into a governed payload sent to an LLM. The LLM responds. The response is validated, stamped with provenance, and stored back as a governed enterprise fact.

### Ontology flavors — scoped views per agent type

An enterprise has many types of AI agents. A network monitoring agent, a billing agent, and a compliance agent all work with different concepts. You do not send the entire enterprise ontology to every agent — you send the relevant slice.

Each **flavor** is a named configuration file that defines:
- The subset of OWL classes and properties relevant to this agent type
- The corresponding SHACL shape subset for validation
- A scoped JSON-LD context with only the terms this agent needs
- The sensitivity-tier access level for this agent's authorisation

Flavors are stored in `runtime/flavors/{name}.json` and auto-generated from `ontology_metadata` `sid_domain` groupings. They can be manually extended.

**Starter flavors (telecom):**

| Flavor | Classes included | Typical agent use |
|---|---|---|
| `network-ops` | Resource, NetworkFunction, Alarm, PerformanceIndicator | Network monitoring, fault detection |
| `billing` | Product, ProductOrder, CustomerAccount, Agreement | Invoice generation, payment processing |
| `compliance` | Policy, Agreement, Party, PartyRole | Regulatory checks, audit trail queries |
| `customer` | Party, Service, Product, CustomerAccount | Customer service, CX analysis |
| `fault-management` | Alarm, ServiceProblem, Resource, Service | Incident management, root cause analysis |

### Two flows

**Flow A — Semantic preparation (offline, runs when schema or ontology changes)**

```
Enterprise DB
    ↓ ontology_metadata annotations
Toolkit pipeline (Phases 1–5, TMF)
    ↓ OWL ontology + SHACL shapes + JSON-LD context
Flavor registry
    ↓ named scoped views over the master ontology
Ready for runtime consumption
```

This flow runs once per schema change or major ontology update. It populates the `output/` directory with artifacts the runtime layer reads at query time.

**Flow B — Runtime inference (per question, per agent invocation)**

```
Step 1 — Select flavor
  Incoming question → choose relevant flavor (network-ops, billing, etc.)

Step 2 — Ground the data  ← THE CRITICAL STEP MOST IMPLEMENTATIONS MISS
  Query enterprise DB for records relevant to the question
  Serialise records as JSON-LD using the flavor's scoped context
  Result: every field value is bound to its ontology IRI — not raw data

Step 3 — Validate inbound data
  Run SHACL acceptance gate on the grounded records
  Reject malformed, incomplete, or low-confidence records here
  Bad data rejected before reaching the LLM

Step 4 — Assemble the payload
  Component 1: System prompt — ontology summary + domain rules + agent role
  Component 2: Ontology flavor — class and property definitions in natural language
  Component 3: Grounded data — JSON-LD serialised enterprise records
  Component 4: PROV-O context — provenance of each data point
  Component 5: Question + output format instructions

Step 5 — Send to LLM of choice
  Anthropic, OpenAI, Google, Llama, or any custom endpoint
  The payload is LLM-agnostic — JSON-LD works with any model

Step 6 — Govern the output  ← THE MISSING STEP IN MOST DESIGNS
  SHACL validate structured response against ontology shapes
  Stamp PROV-O provenance:
    prov:wasGeneratedBy = LLM identifier + model version
    prov:generatedAtTime = timestamp
    confidence_score = extracted from model output or metadata
    derivation_method = SYNTHESIZED
  Store as ObservationRecord back into the semantic layer
```

### Why the grounding step matters

Raw enterprise data sitting next to an ontology in a prompt does not connect the two. An LLM reading a field called `status = Enabled` cannot infer that this maps to the OWL class `NetworkFunction` with `hasOperationalState = Enabled` — unless something makes that binding explicit. JSON-LD serialisation is that binding mechanism. Without it, you have data and a schema in the same prompt; with it, you have semantically typed assertions the model can reason over with precision.

### Why the output governance step matters

An LLM response is a new assertion entering your enterprise knowledge base. Without output governance, it is an ungovernable, untraceable string. With PROV-O stamping it becomes a first-class enterprise fact with a full provenance chain: who asked, which model answered, when, with what confidence, derived from which source records. This is what makes AI output auditable — and what regulators increasingly require.

### Running the runtime phase

```bash
# Validate all flavors and generate runtime MCP tools
python3 toolkit.py --phase runtime

# Ground data for a question, output JSON-LD to stdout
python3 runtime/grounder.py --flavor network-ops \
    --question "Which NFs are degraded?" \
    --db db/enterprise.db

# Validate inbound records against SHACL shapes before they reach the LLM
python3 -c "
import sys; sys.path.insert(0, 'runtime')
from input_gate import InputGate
gate = InputGate('db/enterprise.db', min_confidence=0.6)
accepted, rejected = gate.screen_db_query('tmf_resource', flavor_name='network-ops')
print(gate.summary(accepted, rejected))
"
```

### Runtime SDK

```python
import sys; sys.path.insert(0, 'runtime')
from client import RuntimeClient

client = RuntimeClient(
    db_path="db/enterprise.db",
    adapter="anthropic",         # or "openai", "vertex", "ollama"
    model="claude-sonnet-4-5",
)

result = client.ask(
    question="Which 5G network functions are currently degraded and what is their impact on active services?",
    flavor="network-ops",
    output_format="json",
)

print(result["answer"])           # LLM response text
print(result["valid"])            # True if output gate SHACL check passed
print(result["observation_iri"])  # IRI of the PROV-O ObservationRecord stored
print(result["prov"])             # Full provenance dict: model, timestamp, confidence
```

### Supported LLM adapters

| Adapter | `adapter=` key | Default model | Install |
|---|---|---|---|
| Anthropic Messages API | `"anthropic"` | `claude-sonnet-4-5` | `pip install anthropic` |
| OpenAI Chat Completions | `"openai"` | `gpt-4o` | `pip install openai` |
| Google Vertex AI (Gemini) | `"vertex"` | `gemini-1.5-pro` | `pip install google-cloud-aiplatform` |
| Ollama (local) | `"ollama"` | `llama3` | Ollama server running at `localhost:11434` |
| Oracle Cloud (OCI Generative AI) | `"oci"` | `cohere.command-r-plus` | `pip install oci` — see [OCI Generative AI setup](#8x-oci-generative-ai-setup) below |

All adapters are optional — the core runtime modules (`grounder`, `assembler`, `input_gate`, `output_gate`) have zero external dependencies. Install only the adapter you need. The Anthropic adapter uses prompt caching on the system prompt for reduced latency and cost.

### Runtime MCP tools

The runtime phase generates `output/jsonld/runtime-mcp-tools.json` with four MCP tool definitions: `ground_data`, `assemble_payload`, `validate_response`, and `ask_ontology`. These tools let any MCP-compatible agent call the runtime pipeline directly.

### What the runtime layer does NOT do

The runtime layer is not a replacement for the toolkit pipeline. It does not generate ontologies, create SHACL shapes, or manage database schemas. Those are the pipeline's responsibility. The runtime layer is strictly a consumption layer — it reads the pipeline's outputs and uses them to power governed, auditable LLM interactions.

The runtime layer also does not choose which LLM to use. That is an enterprise decision. The payload it assembles is LLM-agnostic, and adapters for Anthropic, OpenAI, Google Vertex, and Ollama handle API-specific mechanics while the semantic payload remains identical.

### Runtime components

| Component | Output |
|---|---|
| FlavorRegistry | 5 starter flavors, auto-discovery from `runtime/flavors/` |
| Grounder | JSON-LD nodes with `@type`, ontology IRI bindings, PROV-O grounding record |
| InputGate | SHACL acceptance screening, rejection log to `semantic_loss_log` |
| PayloadAssembler | 5-component payload, token budget, LLM-agnostic dict output |
| OutputGate | SHACL response validation, PROV-O stamping, `ObservationRecord` storage |
| RuntimeClient | Full pipeline in one call, async support, 4 LLM adapters |

### 8.x OCI Generative AI setup

The runtime layer ships with an Oracle Cloud Infrastructure (OCI) adapter alongside Anthropic, OpenAI, Vertex AI, and Ollama. Use it when you want to route the toolkit's governed payloads to Cohere or Llama models hosted on OCI Generative AI.

**1. Install the SDK**

```bash
pip install oci
```

**2. Configure credentials**

The adapter follows the standard OCI config-file pattern documented at [docs.oracle.com — Python SDK Configuration](https://docs.oracle.com/en-us/iaas/tools/python/latest/configuration.html). Create `~/.oci/config` (or run `oci setup config`) with at least:

```ini
[DEFAULT]
user=ocid1.user.oc1..<your-user-ocid>
fingerprint=<api-key-fingerprint>
key_file=~/.oci/oci_api_key.pem
tenancy=ocid1.tenancy.oc1..<your-tenancy-ocid>
region=us-chicago-1
```

**3. Set the compartment**

OCI Generative AI requires a compartment OCID for routing and billing:

```bash
export OCI_COMPARTMENT_ID=ocid1.compartment.oc1..<your-compartment-ocid>
```

Optional environment overrides:

| Variable | Default | Purpose |
|---|---|---|
| `OCI_CONFIG_FILE` | `~/.oci/config` | Path to the OCI config file |
| `OCI_CONFIG_PROFILE` | `DEFAULT` | Profile name within the config file |
| `OCI_GENAI_ENDPOINT` | `https://inference.generativeai.us-chicago-1.oci.oraclecloud.com` | Service endpoint (set this for non-Chicago regions) |

**4. Use it from the runtime**

```python
from runtime import RuntimeClient

client = RuntimeClient(
    db_path="db/enterprise.db",
    adapter="oci",
    model="cohere.command-r-plus",   # or a Meta/Llama model OCID
)

result = client.ask(question="Which network functions are degraded?", flavor="network-ops")
print(result["answer"])
```

The adapter defaults to the Cohere request shape. To target a Meta/generic model, instantiate `OCIAdapter` directly with `provider="meta"` and pass it via `RuntimeClient(adapter=<instance>)`.

---

