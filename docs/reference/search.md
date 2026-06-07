# Reasoning search

Ontology-grounded **reasoning search** turns a natural-language question into a
**cited, reasoned answer** over your connected database. Instead of guessing your
schema, it plans over the generated **ontology**, executes **safe, read-only**
queries, and (from Phase 2) applies OWL-RL/Datalog **inference** — returning an
answer with provenance for every claim. It runs **locally (Ollama)** or in the
**cloud (OpenAI)**.

!!! note "Status"
    Single-hop search is available behind the `ONTOMESH_SEARCH` flag. Multi-hop
    traversal and rule-based inference land in a later release.

## SDK

```python
from runtime.reasoning_search import search

ans = search(
    "Which customers are Platinum?",
    flavor="network-ops",
    db_path="db/demo.db",
    providers="ollama",        # or "openai", or {"planner": "openai", ...}
    max_tier="Internal",       # sensitivity ceiling
)

print(ans.answer)              # synthesized, grounded answer
print(ans.executed_query)      # the read-only SQL that ran (transparency)
for c in ans.citations:        # every claim is traceable
    print(c.iri, c.source_table, "(inferred)" if c.inferred else "")
print(ans.confidence, ans.status)   # status: ok | empty | blocked | ungrounded
```

Or via the runtime client (reuses its adapter + database):

```python
from runtime.client import RuntimeClient
client = RuntimeClient(db_path="db/demo.db", adapter="ollama")
ans = client.search("Which customers are Platinum?", "network-ops")
```

### `ReasonedAnswer`

| Field | Meaning |
|---|---|
| `answer` | the synthesized natural-language answer |
| `plan` | the ontology-validated query plan |
| `results` | the retrieved records |
| `citations` | `Citation(iri, label, source_table, inferred)` per source |
| `inferred` | derived facts + `prov:wasDerivedFrom` lineage (Phase 2) |
| `confidence` | 0.0–1.0 |
| `executed_query` | the read-only SQL actually run |
| `trace` | stage-by-stage reasoning trace |
| `status` | `ok` · `empty` · `blocked` (tier) · `ungrounded` |

## CLI

```bash
ontomesh search "which customers are platinum?" --flavor network-ops --db db/demo.db
ontomesh search "…" --flavor clinical-research --provider openai --max-tier Confidential --json
```

## Safety

Generated queries are safe by construction:

- **Read-only** — single `SELECT` only; DDL/DML rejected; SQLite opened `mode=ro`
  with `PRAGMA query_only` and a statement timeout.
- **Allow-listed** — only the flavor's mapped tables/columns can be queried.
- **Sensitivity tiers** — columns/classes above your `max_tier` are withheld
  (`blocked`); unknown tiers fail closed.
- **De-identification** — flagged columns can be masked before results leave the host.

## How it works

`understand → plan → execute → reason → synthesize → verify`. The ontology is the
planner's controlled vocabulary, so it cannot reference entities that don't exist —
the core guardrail against hallucinated columns. See the architecture overview in
the project design notes.
