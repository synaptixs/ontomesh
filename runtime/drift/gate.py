"""Phase 3 — SHACL gate over production DataFrames.

Validates incoming production data against the toolkit-generated SHACL
NodeShapes (``output/shapes/enterprise-shapes.ttl``) before it ever
reaches a drift monitor. The same gate is reusable for raw enterprise
records that flow through :class:`runtime.input_gate.InputGate` — the
only difference is the input format (DataFrame here, JSON-LD there).

The DataFrame → RDF mapper is intentionally minimal: each row becomes a
blank-node anchored under a per-entity IRI, and every non-null cell
becomes one ``<entity> <ns:column> <literal-or-iri>`` triple. Bring
your own mapper via ``df_to_rdf=`` if you need richer modelling
(e.g. typed datatypes, nested objects).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pandas as pd
from rdflib import Graph, Literal, Namespace, URIRef
from pyshacl import validate


DEFAULT_SHAPES_PATH = Path("output/shapes/enterprise-shapes.ttl")
DEFAULT_NAMESPACE = "https://ontology.example.com/retail#"


def default_df_to_rdf(
    df: pd.DataFrame,
    entity_key: str,
    namespace: str,
) -> Graph:
    """Project a DataFrame onto an RDF graph the SHACL validator can read.

    Each row → a fresh subject IRI ``<ns>{entity_key}_{row_index}``.
    Each non-null cell → one triple with predicate ``<ns>{column_name}``.
    Strings / numbers become rdflib Literals; if a value already looks
    like a full IRI it is materialised as a URIRef instead.
    """
    g = Graph()
    ns = Namespace(namespace)
    g.bind("ns", ns)
    key_clean = entity_key.replace("::", "_")
    for i, row in df.iterrows():
        subj = ns[f"{key_clean}_{i}"]
        for col, val in row.items():
            if val is None or (isinstance(val, float) and pd.isna(val)):
                continue
            pred = ns[str(col)]
            if isinstance(val, str) and (val.startswith("http://") or val.startswith("https://")):
                obj = URIRef(val)
            else:
                obj = Literal(val)
            g.add((subj, pred, obj))
    return g


class SHACLValidationError(ValueError):
    """Raised when SHACL validation fails. Carries the raw report graph."""

    def __init__(self, message: str, report_graph: Graph | None = None,
                 report_text: str | None = None) -> None:
        super().__init__(message)
        self.report_graph = report_graph
        self.report_text = report_text


class SHACLGate:
    """Pre-flight SHACL validator for any production DataFrame.

    Parameters
    ----------
    shapes_path:
        Toolkit-generated NodeShape graph. Defaults to
        ``output/shapes/enterprise-shapes.ttl``.
    namespace:
        IRI prefix to anchor synthetic data under. Should match the
        prefix used by the SHACL shapes (the toolkit emits one prefix
        per flavor).
    df_to_rdf:
        Optional override of the DataFrame → RDF mapper. Receives
        ``(df, entity_key, namespace)``, returns a populated
        :class:`rdflib.Graph`.
    """

    def __init__(
        self,
        shapes_path: str | Path = DEFAULT_SHAPES_PATH,
        namespace: str = DEFAULT_NAMESPACE,
        df_to_rdf: Callable[[pd.DataFrame, str, str], Graph] | None = None,
    ) -> None:
        self._shapes_path = Path(shapes_path)
        self._shapes = Graph()
        if self._shapes_path.exists():
            self._shapes.parse(self._shapes_path, format="turtle")
        self._namespace = namespace
        self._mapper = df_to_rdf or default_df_to_rdf

    # ── Public API ───────────────────────────────────────────────────────
    def validate(
        self,
        df: pd.DataFrame,
        entity_key: str,
        *,
        abort_on_first: bool = False,
    ) -> pd.DataFrame:
        """Return *df* unchanged if it conforms; raise on violation.

        If the shapes file is empty (or doesn't exist), the gate is a
        no-op — useful when running outside the toolkit pipeline.
        """
        if len(self._shapes) == 0:
            return df

        data_g = self._mapper(df, entity_key, self._namespace)
        conforms, report_g, report_text = validate(
            data_g,
            shacl_graph=self._shapes,
            abort_on_first=abort_on_first,
            allow_warnings=True,
        )
        if not conforms:
            raise SHACLValidationError(
                f"[SHACLGate] {entity_key} failed validation",
                report_graph=report_g,
                report_text=report_text,
            )
        return df

    def is_active(self) -> bool:
        """``True`` if the shapes graph has any constraints loaded."""
        return len(self._shapes) > 0

    @property
    def shapes_path(self) -> Path:
        return self._shapes_path
