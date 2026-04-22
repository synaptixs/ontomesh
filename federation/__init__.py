"""
federation — Workstream 3 (Gen2): Cross-Enterprise Federated Ontology Network
==============================================================================

Extends the toolkit from single-enterprise to multi-enterprise semantic
interoperability.  Each organisation maintains full sovereignty —
partners publish cryptographically signed capability manifests declaring
what they expose, to whom, and at what sensitivity tier.

Public entry points:

  * :mod:`federation.partner_registry`   — register / list / lookup partners
  * :mod:`federation.manifest`           — build + sign + verify capability manifests
  * :mod:`federation.router`             — cross-enterprise SPARQL routing
  * :mod:`federation.boundary`           — SHACL validation at the ingress boundary
  * :mod:`federation.trust`              — bilateral trust-bootstrap handshake

CLI:
    python3 toolkit.py --phase federate --register-partner <url>
    python3 toolkit.py --phase federate --generate-keys
    python3 toolkit.py --phase federate --handshake <url>
    python3 toolkit.py --phase federate --list-partners
"""

from __future__ import annotations

from .partner_registry import (  # noqa: F401
    register_partner,
    list_partners,
    get_partner,
    revoke_partner,
    REGISTRY_PATH,
)
from .manifest import (  # noqa: F401
    generate_keypair,
    build_manifest,
    sign_manifest,
    verify_manifest,
)
from .router import route_federated_query  # noqa: F401
from .boundary import validate_federated_results  # noqa: F401
from .trust import handshake, countersign, activate  # noqa: F401

__all__ = [
    "register_partner", "list_partners", "get_partner", "revoke_partner",
    "REGISTRY_PATH", "generate_keypair", "build_manifest", "sign_manifest",
    "verify_manifest", "route_federated_query", "validate_federated_results",
    "handshake", "countersign", "activate",
]
