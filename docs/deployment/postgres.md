# Postgres backend

Set one env var to switch from SQLite to Postgres:

```bash
docker run -d --name ontomesh \
  -p 5051:5051 \
  -e ONTOMESH_DB_URL=postgresql://user:pass@host:5432/ontomesh \
  ghcr.io/synaptixs/ontomesh:3.7.0
```

The wizard's saved-ontologies store, preferences, and session state all migrate transparently.  Both backends share the same wire schema.

## When you'd want Postgres

- Multi-replica deployment (SQLite is single-writer)
- Centralised persistence across worker processes
- You already operate a Postgres
- You want point-in-time recovery / WAL archiving

## Schema

The wizard creates its tables on first connect.  Schema is documented in [`wizard/ontologies_store.py`](https://github.com/synaptixs/ontomesh/blob/main/wizard/ontologies_store.py).
