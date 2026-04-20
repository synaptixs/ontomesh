"""
Payload Assembler — constructs the full LLM input payload from five components:
  1. System prompt (ontology summary + domain rules + agent role)
  2. Ontology flavor (class + property definitions in natural language)
  3. Grounded data (JSON-LD records from Grounder)
  4. PROV-O context (provenance of each data point)
  5. Question + output format instructions

LLM-agnostic: returns a plain dict that any adapter can consume.
"""

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from flavor_registry import FlavorRegistry
from grounder import Grounder

# One-line class descriptions for the ~20 core ontology classes
CLASS_DESCRIPTIONS: dict[str, str] = {
    "TmfEntity":               "Root superclass of all TM Forum SID entities; carries identity IRI and lifecycle status.",
    "Resource":                "A logical or physical telecom resource instance (TMF639) — NetworkFunction, Equipment, IP address, etc.",
    "NetworkFunction":         "A 5G/4G network function (AMF, SMF, UPF, gNB) modelled as a LogicalResource subtype.",
    "NetworkSlice":            "A 3GPP network slice instance with S-NSSAI identifiers, SLA targets, and lifecycle state.",
    "Service":                 "A customer-facing or resource-facing service instance from the TMF638 service inventory.",
    "Product":                 "A product subscription held by a customer, realised by one or more services (TMF637).",
    "Party":                   "A legal entity (Individual or Organization) that participates in business relationships (TMF632).",
    "Individual":              "A natural person party with given/family name and contact attributes.",
    "Organization":            "A legal organisation party — operator, vendor, regulator, or partner.",
    "RelatedParty":            "A party playing a typed role in relation to another entity (e.g. owner, contact, sponsor).",
    "Alarm":                   "A network fault event with perceived severity, alarm type, and state (TMF642).",
    "TroubleTicket":           "A trouble ticket tracking the lifecycle of a network or customer problem (TMF621).",
    "PerformanceIndicator":    "A KPI measurement or derived metric with confidence score and derivation method.",
    "ObservationRecord":       "A PROV-O annotated data observation — measured, inferred, imported, or synthesised.",
    "ConflictEvent":           "A detected conflict between two ontology assertions, with 3-tier resolution metadata.",
    "CustomerBill":            "A billing document issued to a customer account for a billing period (TMF678).",
    "BillingAccount":          "A customer account holding billing, credit, and payment configuration (TMF666).",
    "Agreement":               "A contractual agreement or SLA between two parties (TMF651).",
    "Policy":                  "An operational, compliance, security, or SLA policy governing entity behaviour.",
    "ServiceQualityReport":    "A QoS/SLA compliance measurement report for a service and agreement (TMF657).",
    "GeographicSite":          "A physical infrastructure site (data centre, cell tower, exchange) with location attributes.",
    "EventSubscription":       "A TMF630 event hub subscription linking an event type to a callback URL.",
}

# Output format instruction templates
_FORMAT_INSTRUCTIONS: dict[str, str] = {
    "json": (
        "Return a single JSON object conforming to the ontology context provided above. "
        "Top-level keys must be valid ontology terms (camelCase). "
        "Include an '@type' field for each entity in the response. "
        "Do not include explanatory prose — JSON only."
    ),
    "jsonld": (
        "Return a valid JSON-LD document with '@context', '@graph', and entity nodes. "
        "Use the context terms defined in the grounded data above. "
        "Each node must have '@id', '@type', and relevant property fields."
    ),
    "text": (
        "Return a clear, concise prose response. "
        "Reference ontology class names in CamelCase when mentioning entity types. "
        "Cite confidence scores and derivation methods where relevant."
    ),
    "table": (
        "Return a markdown table summarising the answer. "
        "Column headers must use ontology term names. "
        "Include a 'Source' column referencing the grounded data."
    ),
}


class PayloadAssembler:
    """Assembles the complete LLM input payload for an ontology-augmented query.

    Combines the system prompt, ontology flavor section, grounded data,
    PROV-O provenance summary, and user question into a single payload dict
    that any LLM adapter can consume without further transformation.
    """

    def __init__(
        self,
        flavor_registry: FlavorRegistry,
        grounder: Optional[Grounder] = None,
    ):
        """Initialise the assembler.

        Args:
            flavor_registry: A :class:`FlavorRegistry` instance used to load
                flavor definitions and generate context and system prompts.
            grounder: An optional :class:`Grounder` instance.  Not required for
                assembly if ``grounded_data`` is passed directly to
                :meth:`assemble`.
        """
        self._registry = flavor_registry
        self._grounder = grounder

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def assemble(
        self,
        question: str,
        flavor_name: str,
        grounded_data: Optional[dict] = None,
        output_format: str = "json",
        max_tokens: int = 4000,
    ) -> dict:
        """Build the full LLM input payload.

        If ``grounded_data`` is not supplied and a grounder is attached, the
        grounder will be called automatically.

        Args:
            question: The natural-language question to answer.
            flavor_name: The flavor to scope this payload to.
            grounded_data: Pre-grounded JSON-LD data dict (from Grounder).
                If ``None`` and a grounder is available, auto-grounds.
            output_format: One of ``"json"``, ``"jsonld"``, ``"text"``, ``"table"``.
            max_tokens: Token budget for the assembled payload.

        Returns:
            A dict with keys: ``system``, ``messages``, ``flavor``,
            ``payload_id``, ``assembled_at``, ``token_budget``, ``meta``.
        """
        if grounded_data is None and self._grounder is not None:
            grounded_data = self._grounder.ground(question, flavor_name)

        flavor = self._registry.load(flavor_name)

        system_prompt = self._build_system_prompt(flavor)
        ontology_section = self._build_ontology_section(flavor)
        prov_section = self._build_provenance_section(grounded_data or {})
        user_message = self._build_user_message(question, grounded_data or {}, output_format)

        full_system = "\n\n".join(filter(None, [system_prompt, ontology_section, prov_section]))

        payload_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        estimated_tokens = self._estimate_tokens(full_system + user_message)

        meta = {
            "flavor": flavor_name,
            "question": question,
            "output_format": output_format,
            "record_count": len((grounded_data or {}).get("@graph", [])),
            "tables_queried": (grounded_data or {}).get("meta", {}).get("tables_queried", []),
            "grounded_at": (grounded_data or {}).get("meta", {}).get("grounded_at"),
            "estimated_tokens": estimated_tokens,
        }

        return {
            "system": full_system,
            "messages": [{"role": "user", "content": user_message}],
            "flavor": flavor_name,
            "payload_id": payload_id,
            "assembled_at": now,
            "token_budget": max_tokens,
            "meta": meta,
        }

    def save(self, payload: dict, out_path: str) -> None:
        """Write the payload dict to a JSON file.

        Args:
            payload: The assembled payload dict (from :meth:`assemble`).
            out_path: Destination file path.
        """
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, default=str)
        print(f"  ✓ Payload saved → {out_path}")

    # ------------------------------------------------------------------
    # Internal builders
    # ------------------------------------------------------------------

    def _build_system_prompt(self, flavor: dict) -> str:
        """Build the system prompt for this flavor.

        Args:
            flavor: The loaded flavor dict.

        Returns:
            A multi-paragraph system prompt string.
        """
        name = flavor.get("name", "unknown")
        desc = flavor.get("description", "")
        tier = flavor.get("sensitivity_tier", "Internal")
        hint = flavor.get("system_prompt_hint", "")
        classes = flavor.get("owl_classes", [])

        classes_list = "\n".join(
            f"  - **{cls}**: {CLASS_DESCRIPTIONS.get(cls, 'A TM Forum ontology class.')}"
            for cls in classes
        )

        return f"""## Agent Role

You are an ontology-augmented AI assistant operating within the **{name}** domain of a TM Forum SID-aligned enterprise knowledge graph.

## Domain Scope

{desc}

## Active Ontology Classes

The following OWL 2 classes are in scope for this query:
{classes_list}

## Data Sensitivity

All data returned in this session is classified as **{tier}**.
- Do not expose raw database row IDs or internal system references.
- Minimise disclosure to only what is needed to answer the question.
- If the grounded data does not contain enough information, state that clearly.

## Operational Guidance

{hint}

## Base IRI

All ontology entities use the IRI prefix: `https://ontology.example.com/tmf/`
PROV-O annotations use prefix: `http://www.w3.org/ns/prov#`"""

    def _build_ontology_section(self, flavor: dict) -> str:
        """Build natural-language class + property descriptions for the flavor.

        Args:
            flavor: The loaded flavor dict.

        Returns:
            A formatted string describing each OWL class in the flavor.
        """
        classes = flavor.get("owl_classes", [])
        context_terms = flavor.get("context_terms", {})

        lines = ["## Ontology Class Definitions\n"]
        for cls in classes:
            desc = CLASS_DESCRIPTIONS.get(cls, "A TM Forum SID ontology class.")
            lines.append(f"### {cls}")
            lines.append(desc)
            # List context terms that apply to this class (heuristic: term name starts with lowercase class-derived prefix)
            cls_lower = cls.lower()
            relevant_terms = {
                k: v for k, v in context_terms.items()
                if k not in ("@vocab", "prov", "xsd", "rdfs")
                and not k[0].isupper()  # property terms (lowerCamelCase)
            }
            if relevant_terms:
                term_lines = [f"  - `{k}` → `{v}`" for k, v in list(relevant_terms.items())[:6]]
                lines.append("Key properties: " + ", ".join(f"`{k}`" for k in list(relevant_terms.keys())[:6]))
            lines.append("")

        return "\n".join(lines)

    def _build_provenance_section(self, grounded_data: dict) -> str:
        """Summarise provenance metadata from the grounded data.

        Args:
            grounded_data: The JSON-LD grounding result dict.

        Returns:
            A formatted PROV-O summary string.
        """
        if not grounded_data:
            return ""

        meta = grounded_data.get("meta", {})
        graph = grounded_data.get("@graph", [])

        # Collect derivation methods seen in the data
        derivation_methods: set[str] = set()
        for node in graph:
            dm = node.get("derivationMethod") or node.get("derivation_method")
            if dm:
                derivation_methods.add(dm)

        tables = meta.get("tables_queried", [])
        record_count = meta.get("record_count", len(graph))
        grounded_at = meta.get("grounded_at", "unknown")

        lines = [
            "## Data Provenance (PROV-O)\n",
            f"- **Grounded at**: {grounded_at}",
            f"- **Tables queried**: {', '.join(tables) if tables else 'none'}",
            f"- **Record count**: {record_count}",
        ]
        if derivation_methods:
            lines.append(f"- **Derivation methods present**: {', '.join(sorted(derivation_methods))}")

        lines += [
            "",
            "Records annotated with `prov:generatedAtTime` indicate when data was created in the system.",
            "Records with `derivationMethod: SYNTHESIZED` were produced by an automated agent and should be",
            "weighted lower than `MEASURED` values when making decisions.",
        ]

        return "\n".join(lines)

    def _build_user_message(
        self, question: str, grounded_data: dict, output_format: str
    ) -> str:
        """Build the user message combining grounded data, question, and format instructions.

        Args:
            question: The natural-language question.
            grounded_data: The JSON-LD grounding result dict.
            output_format: Desired output format key.

        Returns:
            The formatted user message string.
        """
        format_instruction = _FORMAT_INSTRUCTIONS.get(
            output_format,
            _FORMAT_INSTRUCTIONS["text"]
        )

        parts = []

        if grounded_data and grounded_data.get("@graph"):
            # Render grounded data as indented JSON-LD
            data_str = json.dumps(
                {
                    "@context": grounded_data.get("@context", {}),
                    "@graph": grounded_data.get("@graph", []),
                },
                indent=2,
                default=str,
            )
            parts.append("## Grounded Data (JSON-LD)\n\n```json\n" + data_str + "\n```")
        else:
            parts.append(
                "## Grounded Data\n\nNo records were retrieved from the database for this query. "
                "Answer from the ontology definitions provided in the system prompt."
            )

        parts.append(f"## Question\n\n{question}")
        parts.append(f"## Output Instructions\n\n{format_instruction}")

        return "\n\n".join(parts)

    def _estimate_tokens(self, text: str) -> int:
        """Estimate the token count of a string using a naive heuristic.

        Args:
            text: The string to estimate tokens for.

        Returns:
            An integer token estimate (``len(text) // 4``).
        """
        return len(text) // 4
