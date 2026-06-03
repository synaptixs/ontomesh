--
-- Example file for the wizard's Import-from-file feature (#16).
--
-- A trimmed retail-orders schema in pg_dump style. Designed to exercise
-- every importer feature in one file:
--
--   • Postgres dialect detected from `SET search_path` + `nextval(...)`.
--   • Inline column comments using all four supported forms:
--       -- trailing comment on the column line
--       /* block comment on the line above */
--       MySQL-style `COMMENT 'text'` (not used here; see mysql fixture)
--       Postgres COMMENT ON TABLE / COLUMN at the bottom of the file
--   • PII-shaped column names that trigger SUGGEST_PROPERTY_SENSITIVITY:
--       customer.email           (Confidential — common contact field)
--       customer.dob             (Confidential — date of birth)
--       customer.password_hash   (Restricted   — auth credential)
--   • An event-shaped table name (`order_event_log`) — auto-routed to
--     the events list at parse time because of the `_log` suffix, so
--     no SUGGEST_EVENT row appears (it's already correctly classified).
--   • A soft FK that triggers SUGGEST_SOFT_FK:
--       order_event_log.order_id has no FOREIGN KEY declared but the name
--       matches the orders table — confidence 0.75, plural-form match.
--   • A real ALTER TABLE FK (orders.customer_id → customer.id) declared
--     after every CREATE TABLE — typical pg_dump output. The importer's
--     ALTER walker picks it up and turns it into a relationship.
--
-- Drop this file on the wizard's Step 1 'Import from file' card. Open
-- the Suggestions tab in the review modal — Accept the 3 sensitivity
-- bumps and the soft FK, then click 'Accept & replace session'. Then
-- run the pipeline on Step 6 to generate the OWL ontology + SHACL
-- shapes.
--

SET statement_timeout = 0;
SET search_path = public, pg_catalog;

CREATE SEQUENCE public.customer_id_seq;
CREATE SEQUENCE public.orders_id_seq;
CREATE SEQUENCE public.order_event_log_id_seq;

CREATE TABLE public.customer (
    id              integer NOT NULL DEFAULT nextval('public.customer_id_seq'::regclass),
    email           varchar(255) NOT NULL,                     -- Login + primary contact.
    /* Date of birth — required for age-restricted product purchases. */
    dob             date,
    full_name       varchar(120),                              -- Customer-facing display name.
    password_hash   varchar(255) NOT NULL,                     -- Bcrypt hash; never logged.
    created_at      timestamp with time zone DEFAULT now()
);

CREATE TABLE public.orders (
    id              integer NOT NULL DEFAULT nextval('public.orders_id_seq'::regclass),
    customer_id     integer NOT NULL,                          -- Buyer; FK declared via ALTER TABLE below.
    total_amount    numeric(10,2) NOT NULL,
    placed_at       timestamp with time zone DEFAULT now()
);

CREATE TABLE public.order_event_log (
    id              integer NOT NULL DEFAULT nextval('public.order_event_log_id_seq'::regclass),
    order_id        integer NOT NULL,                          -- Soft FK — name matches the orders table.
    event_type      varchar(40) NOT NULL,                      -- PLACED, CONFIRMED, SHIPPED, …
    occurred_at     timestamp with time zone NOT NULL
);

ALTER TABLE ONLY public.customer
    ADD CONSTRAINT customer_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.order_event_log
    ADD CONSTRAINT order_event_log_pkey PRIMARY KEY (id);

-- The "real" FK — typical pg_dump style is to declare it in a separate
-- ALTER block after every CREATE TABLE rather than inside the CREATE.
ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_customer_id_fkey
    FOREIGN KEY (customer_id) REFERENCES public.customer(id);

COMMENT ON TABLE  public.customer            IS 'Registered customers — one row per natural person or business with an active account.';
COMMENT ON TABLE  public.orders              IS 'Purchase orders. One row per checkout submission, regardless of fulfilment status.';
COMMENT ON TABLE  public.order_event_log     IS 'Lifecycle events for an order — placed, confirmed, shipped, delivered, refunded.';
COMMENT ON COLUMN public.customer.email      IS 'Used for both authentication and transactional email; indexed case-insensitively.';
COMMENT ON COLUMN public.orders.placed_at    IS 'When the customer submitted the order, recorded in UTC.';
COMMENT ON COLUMN public.order_event_log.event_type IS 'Discriminator — value drives which OWL subclass each event becomes.';
