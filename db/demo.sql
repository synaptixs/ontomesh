-- ============================================================
-- Retail Demo Schema — "First Contact" demo
-- Self-contained: includes the two toolkit system tables so this
-- file can be loaded into a fresh SQLite DB with one command.
-- ============================================================

PRAGMA foreign_keys = ON;

-- ── TOOLKIT SYSTEM TABLES ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS ontology_metadata (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    target_type       TEXT NOT NULL CHECK(target_type IN ('TABLE','COLUMN')),
    table_name        TEXT NOT NULL,
    column_name       TEXT,
    semantic_type     TEXT,
    label             TEXT,
    description       TEXT,
    sensitivity_tier  TEXT DEFAULT 'Internal'
                      CHECK(sensitivity_tier IN ('Public','Internal','Confidential','Restricted')),
    is_event_class    INTEGER DEFAULT 0,
    skos_pref_label   TEXT,
    skos_alt_labels   TEXT,
    cq_coverage       TEXT,
    created_at        TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS semantic_loss_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name        TEXT NOT NULL,
    column_name       TEXT,
    loss_type         TEXT NOT NULL,
    description       TEXT NOT NULL,
    severity          TEXT CHECK(severity IN ('CRITICAL','HIGH','MEDIUM','LOW')),
    remediation       TEXT,
    detected_at       TEXT DEFAULT (datetime('now')),
    resolved          INTEGER DEFAULT 0
);

-- ── DOMAIN TABLES ─────────────────────────────────────────────
CREATE TABLE customers (
    id             INTEGER PRIMARY KEY,
    full_name      TEXT NOT NULL,
    email          TEXT NOT NULL UNIQUE,
    status         TEXT NOT NULL CHECK (status IN ('Active','Suspended','Closed')),
    created_at     TEXT NOT NULL
);

CREATE TABLE products (
    id             INTEGER PRIMARY KEY,
    sku            TEXT NOT NULL UNIQUE,
    name           TEXT NOT NULL,
    unit_price     REAL NOT NULL,
    category       TEXT NOT NULL
);

CREATE TABLE orders (
    id             INTEGER PRIMARY KEY,
    customer_id    INTEGER NOT NULL REFERENCES customers(id),
    placed_at      TEXT NOT NULL,
    status         TEXT NOT NULL
                   CHECK (status IN ('Pending','Confirmed','Shipped','Delivered','Cancelled')),
    total_amount   REAL NOT NULL
);

CREATE TABLE order_items (
    order_id       INTEGER NOT NULL REFERENCES orders(id),
    product_id     INTEGER NOT NULL REFERENCES products(id),
    quantity       INTEGER NOT NULL,
    line_total     REAL NOT NULL,
    PRIMARY KEY (order_id, product_id)
);

CREATE TABLE invoices (
    id             INTEGER PRIMARY KEY,
    order_id       INTEGER NOT NULL REFERENCES orders(id),
    issued_at      TEXT NOT NULL,
    due_at         TEXT NOT NULL,
    amount_due     REAL NOT NULL,
    status         TEXT NOT NULL
                   CHECK (status IN ('Open','Paid','Overdue','Disputed'))
);

CREATE TABLE payments (
    id             INTEGER PRIMARY KEY,
    invoice_id     INTEGER NOT NULL REFERENCES invoices(id),
    paid_at        TEXT NOT NULL,
    amount         REAL NOT NULL,
    method         TEXT NOT NULL CHECK (method IN ('CARD','BANK','WALLET')),
    status         TEXT NOT NULL CHECK (status IN ('Cleared','Pending','Reversed'))
);

CREATE TABLE shipments (
    id             INTEGER PRIMARY KEY,
    order_id       INTEGER NOT NULL REFERENCES orders(id),
    shipped_at     TEXT,
    delivered_at   TEXT,
    carrier        TEXT NOT NULL,
    tracking_ref   TEXT NOT NULL UNIQUE
);

-- Event table — captures order lifecycle transitions.
-- Carries PROV-O-aligned confidence + derivation for each event,
-- so the toolkit can generate event subclasses + provenance properties.
CREATE TABLE order_events (
    id             INTEGER PRIMARY KEY,
    order_id       INTEGER NOT NULL REFERENCES orders(id),
    event_type     TEXT NOT NULL
                   CHECK (event_type IN ('PLACED','CONFIRMED','SHIPPED','DELIVERED','CANCELLED','REFUNDED')),
    occurred_at    TEXT NOT NULL,
    actor_party    TEXT,
    confidence     REAL CHECK (confidence BETWEEN 0.0 AND 1.0),
    derivation     TEXT CHECK (derivation IN ('MEASURED','INFERRED','IMPORTED','SYNTHESIZED'))
);
