"""
runtime — Ontology-Augmented AI Runtime Layer
=============================================

Provides the complete runtime pipeline for grounding natural-language questions
against a TM Forum SID-aligned enterprise knowledge graph and routing them
through configurable LLM adapters with SHACL validation and PROV-O stamping.

Exported symbols
----------------
FlavorRegistry   — loads and validates domain flavor configuration files
Grounder         — bridges DB records to JSON-LD grounded data
PayloadAssembler — constructs the full LLM input payload
OutputGate       — validates LLM responses and stamps PROV-O provenance
InputGate        — screens enterprise data before payload entry
RuntimeClient    — high-level SDK tying the full pipeline together

Version
-------
__version__ = "1.0.0"
"""

__version__ = "1.0.0"

import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
if _HERE not in _sys.path:
    _sys.path.insert(0, _HERE)

from flavor_registry import FlavorRegistry
from grounder import Grounder
from assembler import PayloadAssembler
from output_gate import OutputGate
from input_gate import InputGate
from client import RuntimeClient

__all__ = [
    "FlavorRegistry",
    "Grounder",
    "PayloadAssembler",
    "OutputGate",
    "InputGate",
    "RuntimeClient",
    "__version__",
]
