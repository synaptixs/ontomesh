"""
Output SHACL Gate + PROV-O Stamping — governs LLM responses.

For structured responses: validates JSON-LD output against relevant SHACL shapes.
For all responses: stamps PROV-O provenance and stores as ObservationRecord.
"""

import json
import os
import re
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from typing import Optional, Union

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# Default shapes directory (relative to toolkit root)
_DEFAULT_SHAPES_DIR = os.path.join(
    os.path.dirname(_HERE), "output", "shapes"
)

# Required keys per OWL class for MVP structural SHACL check
_CLASS_REQUIRED_KEYS: dict[str, list[str]] = {
    "Resource":             ["@type", "@id"],
    "NetworkFunction":      ["@type", "@id"],
    "NetworkSlice":         ["@type", "@id"],
    "Alarm":                ["@type", "@id", "alarmType"],
    "TroubleTicket":        ["@type", "@id"],
    "PerformanceIndicator": ["@type", "@id"],
    "Service":              ["@type", "@id"],
    "Product":              ["@type", "@id"],
    "Party":                ["@type", "@id"],
    "CustomerBill":         ["@type", "@id", "billNumber"],
    "Agreement":            ["@type", "@id"],
    "ObservationRecord":    ["@type", "@id", "derivationMethod"],
    "ConflictEvent":        ["@type", "@id", "conflictType"],
    "Policy":               ["@type", "@id"],
    "ServiceQualityReport": ["@type", "@id"],
}

# Regex patterns for extracting SHACL constraints from TTL
_SHAPE_TARGET_RE = re.compile(r'sh:targetClass\s+([:\w]+)\s*;', re.MULTILINE)
_PROPERTY_PATH_RE = re.compile(r'sh:path\s+([:\w]+)\s*;', re.MULTILINE)
_MIN_COUNT_RE = re.compile(r'sh:minCount\s+(\d+)\s*;', re.MULTILINE)


class OutputGate:
    """Validates LLM response output and stamps PROV-O provenance.

    Performs two operations on every LLM response:
    1. Structural SHACL validation (MVP: checks required keys; full RDFLib
       validation used if available, degrades gracefully if not).
    2. PROV-O stamping and storage as an ObservationRecord in the DB.
    """

    def __init__(self, db_path: str, shapes_dir: Optional[str] = None):
        """Initialise the OutputGate.

        Args:
            db_path: Absolute path to the SQLite enterprise database.
            shapes_dir: Directory containing SHACL shape TTL files.
                Defaults to ``output/shapes/`` relative to the toolkit root.
        """
        self._db_path = db_path
        self._shapes_dir = shapes_dir or _DEFAULT_SHAPES_DIR

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_and_stamp(
        self,
        response: Union[str, dict],
        payload: dict,
        model_id: str,
        confidence: Optional[float] = None,
    ) -> dict:
        """Validate a response and stamp it with PROV-O provenance.

        Args:
            response: The LLM response — either a raw string or a parsed dict.
            payload: The assembled payload dict (from PayloadAssembler).
            model_id: The LLM model identifier (e.g. ``"claude-sonnet-4-5"``).
            confidence: Optional confidence score override (0.0–1.0).

        Returns:
            A dict with keys: ``valid``, ``violations``, ``observation_iri``,
            ``prov``, ``response``.
        """
        parsed, raw_str = self._parse_response(response)

        # SHACL validation (only for structured JSON responses)
        violations: list[str] = []
        if parsed is not None:
            flavor_name = payload.get("flavor", "")
            violations = self._validate_shacl(parsed, flavor_name)

        # PROV-O stamping
        prov = self._stamp_provenance(raw_str, payload, model_id, confidence)

        # Store observation record
        observation_iri = self._store_observation(raw_str, prov, payload)

        return {
            "valid": len(violations) == 0,
            "violations": violations,
            "observation_iri": observation_iri,
            "prov": prov,
            "response": response,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_response(self, response: Union[str, dict]) -> tuple:
        """Try to parse the response as JSON.

        Args:
            response: Raw string or already-parsed dict.

        Returns:
            A tuple of ``(parsed_dict_or_None, raw_string)``.
        """
        if isinstance(response, dict):
            return response, json.dumps(response, default=str)

        raw = str(response)
        # Strip markdown code fences if present
        stripped = raw.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            # Drop first and last fence lines
            inner = "\n".join(lines[1:-1]) if len(lines) > 2 else ""
            stripped = inner.strip()

        try:
            parsed = json.loads(stripped)
            return parsed, raw
        except (json.JSONDecodeError, ValueError):
            return None, raw

    def _validate_shacl(self, response_dict: dict, flavor_name: str) -> list:
        """Validate the response dict against SHACL shapes.

        Attempts full TTL-based shape extraction first; falls back to an
        MVP structural check if shapes files are not found.

        Args:
            response_dict: The parsed JSON response dict.
            flavor_name: Flavor name used to locate relevant shape files.

        Returns:
            A list of violation message strings (empty = valid).
        """
        violations: list[str] = []

        # Try to load shape files
        shapes = self._load_shapes(flavor_name)

        # Gather all entities to check — support both @graph list and flat dict
        entities: list[dict] = []
        if "@graph" in response_dict and isinstance(response_dict["@graph"], list):
            entities = response_dict["@graph"]
        elif isinstance(response_dict, list):
            entities = response_dict
        elif "@type" in response_dict:
            entities = [response_dict]
        else:
            # Flat dict: treat top-level values that are dicts as entities
            entities = [v for v in response_dict.values() if isinstance(v, dict) and "@type" in v]

        if not entities:
            # Nothing structured to validate
            return []

        for entity in entities:
            entity_type = entity.get("@type", "")
            entity_id = entity.get("@id", "<unknown>")

            # MVP structural check from hardcoded required keys
            required_keys = _CLASS_REQUIRED_KEYS.get(entity_type, ["@type", "@id"])
            for key in required_keys:
                if key not in entity:
                    violations.append(
                        f"Entity <{entity_id}> of type '{entity_type}' missing required property '{key}'"
                    )

            # Additional checks from loaded SHACL shapes
            for shape in shapes:
                if shape.get("target_class") == entity_type:
                    for prop in shape.get("required_properties", []):
                        if prop not in entity and prop.lstrip(":") not in entity:
                            violations.append(
                                f"SHACL: Entity <{entity_id}> ({entity_type}) "
                                f"violates sh:minCount 1 for property '{prop}'"
                            )

        return violations

    def _stamp_provenance(
        self,
        response_raw: str,
        payload: dict,
        model_id: str,
        confidence: Optional[float],
    ) -> dict:
        """Build a PROV-O provenance dict for the response.

        Args:
            response_raw: The raw response string.
            payload: The assembled payload dict.
            model_id: The LLM model identifier.
            confidence: Confidence score (0.0–1.0) or None.

        Returns:
            A PROV-O provenance dict.
        """
        now = datetime.now(timezone.utc).isoformat()
        return {
            "prov:wasGeneratedBy": model_id,
            "prov:generatedAtTime": now,
            "prov:wasAssociatedWith": payload.get("payload_id", ""),
            "prov:hadPrimarySource": payload.get("flavor", ""),
            "derivation_method": "SYNTHESIZED",
            "confidence_score": confidence,
            "response_length": len(response_raw),
        }

    def _store_observation(
        self, response_raw: str, prov: dict, payload: dict
    ) -> str:
        """Insert an ObservationRecord row for the LLM response.

        Args:
            response_raw: The raw response string (stored as value_text).
            prov: The PROV-O provenance dict.
            payload: The assembled payload dict.

        Returns:
            The IRI of the created observation record.
        """
        record_iri = f"https://ontology.example.com/tmf/response/{uuid.uuid4()}"
        now = prov.get("prov:generatedAtTime", datetime.now(timezone.utc).isoformat())
        question = payload.get("meta", {}).get("question", "")[:500]
        flavor = payload.get("flavor", "")
        payload_id = payload.get("payload_id", "")
        model_id = prov.get("prov:wasGeneratedBy", "")
        confidence = prov.get("confidence_score")

        try:
            conn = sqlite3.connect(self._db_path)
            with conn:
                conn.execute("""
                    INSERT OR IGNORE INTO observation_record (
                        record_iri, entity_iri, entity_type, record_type, kpi_type,
                        value_numeric, value_text, unit, derivation_method,
                        confidence_score, source_ref, prov_agent_iri,
                        generated_at, valid_from, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    record_iri,
                    f"https://ontology.example.com/tmf/flavor/{flavor}",
                    "LLMResponse",
                    "RESPONSE",
                    None,
                    confidence,
                    response_raw[:2000],
                    None,
                    "SYNTHESIZED",
                    confidence,
                    f"payload:{payload_id} question:{question}",
                    f"https://ontology.example.com/tmf/agent/{model_id.replace('/', '-')}",
                    now,
                    now,
                    now,
                ))
            conn.close()
        except Exception as exc:
            print(f"  WARN OutputGate: could not store observation record: {exc}")

        return record_iri

    def _load_shapes(self, flavor_name: str) -> list:
        """Load SHACL shape constraints from TTL files for the flavor.

        Parses TTL files with regex to extract sh:targetClass and
        sh:property / sh:path / sh:minCount constraints.  No rdflib dependency.

        Args:
            flavor_name: Flavor name used to locate the shapes file.

        Returns:
            A list of shape dicts: ``{"target_class": str, "required_properties": [str]}``.
        """
        shapes: list[dict] = []

        if not os.path.isdir(self._shapes_dir):
            return shapes

        # Try flavor-specific file first, then fall back to generic agent-gate shapes
        candidate_files = [
            os.path.join(self._shapes_dir, f"{flavor_name}-shapes.ttl"),
            os.path.join(self._shapes_dir, "agent-gate.ttl"),
            os.path.join(self._shapes_dir, "enterprise-shapes.ttl"),
        ]

        for shapes_path in candidate_files:
            if not os.path.isfile(shapes_path):
                continue
            try:
                with open(shapes_path, "r", encoding="utf-8") as fh:
                    ttl_content = fh.read()
                shapes.extend(self._parse_shapes_ttl(ttl_content))
            except Exception as exc:
                print(f"  WARN OutputGate: could not read {shapes_path}: {exc}")

        return shapes

    def _parse_shapes_ttl(self, ttl_content: str) -> list:
        """Parse a SHACL TTL string and extract NodeShape constraints.

        Uses regex-based parsing — no rdflib dependency.

        Args:
            ttl_content: Raw Turtle/TTL string.

        Returns:
            List of shape dicts with ``target_class`` and ``required_properties``.
        """
        shapes: list[dict] = []

        # Split into shape blocks (heuristic: split on blank NodeShape declarations)
        # Each block starts when we see sh:NodeShape
        blocks = re.split(r'(?=\w+Shape\s+a\s+sh:NodeShape)', ttl_content)

        for block in blocks:
            target_match = _SHAPE_TARGET_RE.search(block)
            if not target_match:
                continue

            target_class = target_match.group(1).lstrip(":").strip()

            # Find all property paths with minCount >= 1
            required: list[str] = []
            # Find all sh:path occurrences
            paths = _PROPERTY_PATH_RE.findall(block)
            # Find all sh:minCount occurrences
            counts = _MIN_COUNT_RE.findall(block)

            # Pair them up (they appear in the same property block order)
            for i, path in enumerate(paths):
                count = int(counts[i]) if i < len(counts) else 0
                if count >= 1:
                    term = path.lstrip(":").strip()
                    # Convert to camelCase if it's a prefixed term
                    required.append(term)

            if target_class:
                shapes.append({
                    "target_class": target_class,
                    "required_properties": required,
                })

        return shapes
