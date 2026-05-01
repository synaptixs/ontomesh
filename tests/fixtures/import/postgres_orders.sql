-- Postgres-style retail DDL fixture for the import tests.
-- Exercises: PRIMARY KEY column constraint, inline REFERENCES,
-- table-level FOREIGN KEY, NOT NULL, NUMERIC(p,s), TIMESTAMPTZ.

CREATE TABLE customers (
    id           INTEGER PRIMARY KEY,
    email        VARCHAR(255) NOT NULL,
    full_name    VARCHAR(120),
    created_at   TIMESTAMPTZ
);

CREATE TABLE orders (
    id           INTEGER PRIMARY KEY,
    customer_id  INTEGER NOT NULL REFERENCES customers(id),
    total_amount NUMERIC(10,2),
    placed_at    TIMESTAMPTZ
);

CREATE TABLE order_event_log (
    id           BIGSERIAL PRIMARY KEY,
    order_id     INTEGER NOT NULL,
    event_type   TEXT NOT NULL,
    occurred_at  TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(id)
);
