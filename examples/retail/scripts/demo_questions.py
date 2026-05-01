"""Question bank for the first-contact demo.

Each question is chosen so that the ontology-grounded answer materially differs
from the baseline (raw-rows) answer. See tests/test-plan.md §5 Phase 3 for rationale.
"""

QUESTIONS = [
    {
        "id": "Q1",
        "text": "Which customers are Active?",
        "why": "status=\"Active\" exists on 3 tables (customers, orders, payments). Baseline often conflates them; grounded answer names Customer OWL class explicitly.",
        "tables_for_baseline": ["customers", "orders", "payments"],
    },
    {
        "id": "Q2",
        "text": "Show me overdue invoices and the customers who owe them.",
        "why": "Two-hop join invoice → order → customer. Baseline sometimes omits the customer entity.",
        "tables_for_baseline": ["invoices", "orders", "customers"],
    },
    {
        "id": "Q3",
        "text": "Which orders never reached the Delivered state?",
        "why": "Needs order_events (lifecycle), not orders.status (snapshot). Baseline typically uses the snapshot column.",
        "tables_for_baseline": ["orders", "order_events"],
    },
    {
        "id": "Q4",
        "text": "Are there any disputed invoices with reversed payments?",
        "why": "State-machine intersection across two tables — Invoice.status='Disputed' AND Payment.status='Reversed'.",
        "tables_for_baseline": ["invoices", "payments"],
    },
    {
        "id": "Q5",
        "text": "What is the full customer-to-payment traceability chain for order 7?",
        "why": "FK→object-property chaining. Grounded answer carries stable IRIs; baseline returns a prose summary.",
        "tables_for_baseline": ["customers", "orders", "invoices", "payments"],
    },
    {
        "id": "Q6",
        "text": "Which cancellation events were inferred rather than measured?",
        "why": "Requires PROV-O derivation vocabulary. Baseline has no column-name vocabulary for this distinction.",
        "tables_for_baseline": ["order_events"],
    },
    {
        "id": "Q7",
        "text": "List active orders whose shipment is missing.",
        "why": "Ambiguity between order status and shipment presence. Grounded answer disambiguates Order vs Shipment classes.",
        "tables_for_baseline": ["orders", "shipments"],
    },
    {
        "id": "Q8",
        "text": "Summarise customer 1's standing in one sentence.",
        "why": "Free-form summary. Tests whether grounded output remains structurally valid under SHACL while still reading naturally.",
        "tables_for_baseline": ["customers", "orders", "invoices", "payments"],
    },
]
