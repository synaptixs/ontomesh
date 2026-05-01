-- Postgres-flavoured DDL exercising every comment form the importer
-- understands, plus a soft-FK column (no declared FOREIGN KEY).

CREATE TABLE tenants (
    id           INTEGER PRIMARY KEY,    -- Surrogate identifier.
    name         VARCHAR(120) NOT NULL,
    /* Single-tenant flag — true if this row owns its own database. */
    is_isolated  BOOLEAN
);

CREATE TABLE users (
    id           INTEGER PRIMARY KEY,
    -- Tenant the user belongs to.
    tenant_id    INTEGER NOT NULL REFERENCES tenants(id),
    email        VARCHAR(255) NOT NULL,
    full_name    VARCHAR(120),
    created_at   TIMESTAMPTZ
);

-- Soft-FK target: orders.customer_id will name-match users via the
-- singular-of-table heuristic when there's no real FK declared.
CREATE TABLE orders (
    id           INTEGER PRIMARY KEY,
    user_id      INTEGER NOT NULL,        -- references users (no FK declared)
    placed_at    TIMESTAMPTZ
);

COMMENT ON TABLE tenants IS 'A customer organisation that uses the platform.';
COMMENT ON COLUMN users.email IS 'Primary contact address — must be unique.';
COMMENT ON COLUMN orders.placed_at IS 'When the customer submitted the order.';
