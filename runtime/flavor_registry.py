"""
FlavorRegistry — loads and validates flavor JSON files.

Provides: load(name), list_flavors(), validate(flavor_dict),
          get_context(name), get_system_prompt(name).
Auto-discovers flavor JSON files from runtime/flavors/ directory.
"""

import json
import os
from typing import Optional

# Required keys every flavor dict must contain
_REQUIRED_KEYS = ("name", "description", "sensitivity_tier", "owl_classes", "db_tables")

# Valid sensitivity tier values
_VALID_TIERS = ("Public", "Internal", "Confidential", "Restricted")


class FlavorRegistry:
    """Registry for ontology flavor configuration files.

    Flavors define the scope, OWL classes, SHACL shapes, context terms, and
    sensitivity tier for a particular domain slice of the ontology (e.g.
    network-ops, billing, compliance).  The registry auto-discovers JSON files
    from the flavors directory and provides validated access to them.
    """

    def __init__(self, flavors_dir: Optional[str] = None):
        """Initialise the registry.

        Args:
            flavors_dir: Absolute path to the directory containing flavor JSON
                files.  Defaults to ``runtime/flavors/`` relative to this file.
        """
        if flavors_dir is None:
            flavors_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "flavors")
        self._flavors_dir: str = flavors_dir
        # In-memory cache: name -> dict
        self._cache: dict[str, dict] = {}
        self._discover()

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def _discover(self) -> None:
        """Scan the flavors directory and cache all valid JSON files."""
        if not os.path.isdir(self._flavors_dir):
            return
        for fname in os.listdir(self._flavors_dir):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(self._flavors_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                name = data.get("name") or fname[:-5]
                self._cache[name] = data
            except Exception as exc:
                print(f"  WARN FlavorRegistry: could not load {fname}: {exc}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self, name: str) -> dict:
        """Load a flavor by name.

        Args:
            name: The flavor name, e.g. ``"network-ops"``.

        Returns:
            The flavor configuration dict.

        Raises:
            ValueError: If no flavor with the given name is registered.
        """
        if name not in self._cache:
            raise ValueError(
                f"Flavor '{name}' not found. Available: {self.list_flavors()}"
            )
        return dict(self._cache[name])

    def list_flavors(self) -> list:
        """Return a sorted list of all registered flavor names."""
        return sorted(self._cache.keys())

    def validate(self, flavor: dict) -> list:
        """Validate a flavor dict and return a list of error strings.

        An empty list means the flavor is valid.

        Args:
            flavor: A flavor configuration dict (as returned by :meth:`load`).

        Returns:
            A list of human-readable validation error strings.  Empty if valid.
        """
        errors: list[str] = []

        # Required keys
        for key in _REQUIRED_KEYS:
            if key not in flavor:
                errors.append(f"Missing required key: '{key}'")

        # Sensitivity tier must be from the allowed set
        tier = flavor.get("sensitivity_tier")
        if tier and tier not in _VALID_TIERS:
            errors.append(
                f"Invalid sensitivity_tier '{tier}'. Must be one of: {_VALID_TIERS}"
            )

        # owl_classes must be a non-empty list of strings
        owl_classes = flavor.get("owl_classes")
        if owl_classes is not None:
            if not isinstance(owl_classes, list) or len(owl_classes) == 0:
                errors.append("'owl_classes' must be a non-empty list")
            elif not all(isinstance(c, str) for c in owl_classes):
                errors.append("All items in 'owl_classes' must be strings")

        # db_tables must be a non-empty list of strings
        db_tables = flavor.get("db_tables")
        if db_tables is not None:
            if not isinstance(db_tables, list) or len(db_tables) == 0:
                errors.append("'db_tables' must be a non-empty list")
            elif not all(isinstance(t, str) for t in db_tables):
                errors.append("All items in 'db_tables' must be strings")

        # description must be a non-empty string
        description = flavor.get("description")
        if description is not None and (not isinstance(description, str) or not description.strip()):
            errors.append("'description' must be a non-empty string")

        return errors

    def get_context(self, name: str) -> dict:
        """Return a scoped JSON-LD ``@context`` dict for the named flavor.

        The context includes ``@vocab`` set to the base TMF IRI plus all
        ``context_terms`` defined in the flavor.

        Args:
            name: Flavor name.

        Returns:
            A JSON-LD ``@context`` dict ready for embedding in a payload.
        """
        flavor = self.load(name)
        ctx: dict = {
            "@vocab": "https://ontology.example.com/tmf/",
            "prov": "http://www.w3.org/ns/prov#",
            "xsd": "http://www.w3.org/2001/XMLSchema#",
            "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
        }
        ctx.update(flavor.get("context_terms", {}))
        return {"@context": ctx}

    def get_system_prompt(self, name: str) -> str:
        """Return a system prompt preamble for the named flavor.

        The prompt summarises the flavor name, active OWL classes, sensitivity
        tier, and the flavor's ``system_prompt_hint``.

        Args:
            name: Flavor name.

        Returns:
            A multi-line string suitable for use as an LLM system prompt prefix.
        """
        flavor = self.load(name)
        classes_str = ", ".join(flavor.get("owl_classes", []))
        hint = flavor.get("system_prompt_hint", "")
        tier = flavor.get("sensitivity_tier", "Internal")
        desc = flavor.get("description", "")

        lines = [
            f"## Ontology Runtime — Flavor: {name}",
            "",
            f"**Domain**: {desc}",
            f"**Sensitivity tier**: {tier}",
            f"**Active OWL classes**: {classes_str}",
            "",
            "### Operational guidance",
            hint,
            "",
            "### Data handling constraints",
            f"All data in this session is classified as **{tier}**. ",
            "Do not reveal raw database identifiers or internal IRIs in user-facing responses. ",
            "Respond only in the requested output format. ",
            "If the grounded data is insufficient to answer the question, say so explicitly.",
        ]
        return "\n".join(lines)

    def register(self, flavor_dict: dict, save: bool = False) -> None:
        """Register a flavor in-memory and optionally persist it to disk.

        Args:
            flavor_dict: A valid flavor configuration dict.  Must contain at
                least the ``name`` key.
            save: If ``True``, write the flavor to
                ``{flavors_dir}/{name}.json``.

        Raises:
            ValueError: If ``flavor_dict`` is missing a ``name`` key.
        """
        name = flavor_dict.get("name")
        if not name:
            raise ValueError("flavor_dict must contain a 'name' key")
        self._cache[name] = dict(flavor_dict)
        if save:
            os.makedirs(self._flavors_dir, exist_ok=True)
            fpath = os.path.join(self._flavors_dir, f"{name}.json")
            with open(fpath, "w", encoding="utf-8") as fh:
                json.dump(flavor_dict, fh, indent=2)
            print(f"  ✓ Flavor '{name}' saved → {fpath}")
