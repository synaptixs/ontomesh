"""
src/adapters — T1.2 modality-specific adapters.

Each adapter implements the ``observability_adapter.Adapter``
Protocol and exposes a single modality (Prometheus metrics, OTel
spans, deploy / config events, log template rates) as a
``Dict[node_id, np.ndarray]`` ready for the PC algorithm.
"""

from .prometheus import PrometheusAdapter, PrometheusSample
from .otel import OtelAdapter, SpanEvent
from .deploys import DeploysAdapter, DeployEvent
from .logs import LogsAdapter

__all__ = [
    "PrometheusAdapter", "PrometheusSample",
    "OtelAdapter", "SpanEvent",
    "DeploysAdapter", "DeployEvent",
    "LogsAdapter",
]
