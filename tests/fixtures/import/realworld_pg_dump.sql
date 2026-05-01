--
-- Real-world fixture: trimmed pg_dump output. Exercises the patterns
-- that show up in actual Postgres dumps but not in hand-written DDL:
--
--   • SET / SELECT statements at the top of the file
--   • CREATE TABLE public.<name>
--   • CREATE SEQUENCE + DEFAULT nextval() for surrogate keys
--   • ALTER TABLE ... OWNER TO (skip)
--   • ALTER TABLE ... ADD CONSTRAINT FOREIGN KEY (separate from CREATE)
--   • COMMENT ON TABLE / COMMENT ON COLUMN at the bottom
--
-- The importer should ignore non-CREATE-TABLE statements, pick up the
-- table-level FK constraints from the ALTER blocks, and attach the
-- comments back to the right columns.
--

SET statement_timeout = 0;
SET client_encoding = 'UTF8';
SET search_path = public, pg_catalog;

CREATE SEQUENCE public.customers_id_seq;
CREATE SEQUENCE public.orders_id_seq;

CREATE TABLE public.customers (
    id           integer NOT NULL DEFAULT nextval('public.customers_id_seq'::regclass),
    email        character varying(255) NOT NULL,
    full_name    character varying(120),
    created_at   timestamp with time zone DEFAULT now()
);

CREATE TABLE public.orders (
    id           integer NOT NULL DEFAULT nextval('public.orders_id_seq'::regclass),
    customer_id  integer NOT NULL,
    total_amount numeric(10,2) NOT NULL,
    placed_at    timestamp with time zone DEFAULT now()
);

ALTER TABLE ONLY public.customers
    ADD CONSTRAINT customers_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_customer_id_fkey
    FOREIGN KEY (customer_id) REFERENCES public.customers(id);

ALTER TABLE public.customers OWNER TO postgres;
ALTER TABLE public.orders    OWNER TO postgres;

COMMENT ON TABLE  public.customers IS 'Registered customers — one row per natural person or business.';
COMMENT ON COLUMN public.customers.email IS 'Login + primary contact address. Indexed for case-insensitive lookup.';
COMMENT ON COLUMN public.orders.placed_at IS 'When the customer submitted the order, in UTC.';
