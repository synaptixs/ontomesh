-- ============================================================
-- Retail Demo Seed — ~60 rows across 8 tables, plus full
-- ontology_metadata annotations so the toolkit can generate
-- OWL classes, SHACL shapes, and the JSON-LD context.
--
-- Deliberate edge cases (these drive the demo talking points):
--   • status="Active" is valid on customers, orders (Active-ish),
--     and payments (Cleared) — exposes field-name ambiguity
--   • invoice 103 is Disputed with a Reversed payment
--   • order 9 is Cancelled and has no shipment row
--   • order_events row 23 is INFERRED, not MEASURED
-- ============================================================

-- ── CUSTOMERS (10) ────────────────────────────────────────────
INSERT INTO customers VALUES
 (1,'Ada Lovelace','ada@example.com','Active','2025-11-02'),
 (2,'Alan Turing','alan@example.com','Active','2025-11-05'),
 (3,'Grace Hopper','grace@example.com','Active','2025-11-09'),
 (4,'Linus Torvalds','linus@example.com','Suspended','2025-12-14'),
 (5,'Margaret Hamilton','margaret@example.com','Active','2026-01-02'),
 (6,'Edsger Dijkstra','edsger@example.com','Closed','2025-09-30'),
 (7,'Barbara Liskov','barbara@example.com','Active','2026-02-11'),
 (8,'Ken Thompson','ken@example.com','Active','2026-02-20'),
 (9,'Tim Berners-Lee','tim@example.com','Suspended','2026-03-03'),
 (10,'Donald Knuth','donald@example.com','Active','2026-03-18');

-- ── PRODUCTS (12) ─────────────────────────────────────────────
INSERT INTO products VALUES
 (1,'SKU-001','Mechanical Keyboard',149.00,'Peripherals'),
 (2,'SKU-002','27" 4K Monitor',539.00,'Displays'),
 (3,'SKU-003','Wireless Mouse',65.00,'Peripherals'),
 (4,'SKU-004','USB-C Hub',89.00,'Peripherals'),
 (5,'SKU-005','Noise-cancelling Headphones',329.00,'Audio'),
 (6,'SKU-006','HDMI Cable 2m',19.00,'Accessories'),
 (7,'SKU-007','Standing Desk',489.00,'Furniture'),
 (8,'SKU-008','Ergonomic Chair',599.00,'Furniture'),
 (9,'SKU-009','Webcam 1080p',99.00,'Peripherals'),
 (10,'SKU-010','External SSD 1TB',129.00,'Storage'),
 (11,'SKU-011','Desk Lamp',49.00,'Accessories'),
 (12,'SKU-012','Laptop Stand',39.00,'Accessories');

-- ── ORDERS (15) — mix of statuses, one Cancelled, two Pending ─
INSERT INTO orders VALUES
 (1, 1,'2026-03-01 10:05','Delivered', 214.00),
 (2, 2,'2026-03-03 09:14','Delivered', 539.00),
 (3, 3,'2026-03-06 15:22','Shipped',   418.00),
 (4, 1,'2026-03-10 11:01','Delivered', 129.00),
 (5, 5,'2026-03-12 13:45','Confirmed', 598.00),
 (6, 7,'2026-03-15 16:30','Delivered', 148.00),
 (7, 2,'2026-03-18 08:50','Delivered', 688.00),
 (8, 8,'2026-03-21 12:12','Pending',   329.00),
 (9, 4,'2026-03-23 09:25','Cancelled', 539.00),   -- cancelled, no shipment
 (10,10,'2026-03-25 14:04','Shipped',  588.00),
 (11, 3,'2026-03-27 10:40','Pending',   89.00),
 (12, 7,'2026-03-30 11:17','Delivered',  68.00),
 (13, 5,'2026-04-03 09:02','Confirmed',1088.00),
 (14, 1,'2026-04-08 17:22','Delivered', 198.00),
 (15,10,'2026-04-15 10:10','Shipped',   148.00);

-- ── ORDER ITEMS (30) ──────────────────────────────────────────
INSERT INTO order_items VALUES
 (1, 1, 1, 149.00),(1, 6, 1,  19.00),(1,12, 1,  39.00),(1,11, 1,  49.00),
 (2, 2, 1, 539.00),
 (3, 5, 1, 329.00),(3, 9, 1,  99.00),
 (4,10, 1, 129.00),
 (5, 8, 1, 599.00),
 (6, 3, 1,  65.00),(6,11, 1,  49.00),(6, 4, 1,  89.00),
 (7, 7, 1, 489.00),(7, 2, 0,   0.00),(7, 5, 1, 329.00),
 (8, 5, 1, 329.00),
 (9, 2, 1, 539.00),
 (10,7, 1, 489.00),(10,9, 1,  99.00),
 (11,4, 1,  89.00),
 (12,1, 0,   0.00),(12,3, 1,  65.00),
 (13,8, 1, 599.00),(13,7, 1, 489.00),
 (14,5, 1, 329.00),
 (15,1, 1, 149.00);

-- ── INVOICES (15) ─────────────────────────────────────────────
INSERT INTO invoices VALUES
 (101,  1,'2026-03-01','2026-03-31', 214.00,'Paid'),
 (102,  2,'2026-03-03','2026-04-02', 539.00,'Paid'),
 (103,  3,'2026-03-06','2026-04-05', 418.00,'Disputed'),    -- disputed
 (104,  4,'2026-03-10','2026-04-09', 129.00,'Paid'),
 (105,  5,'2026-03-12','2026-04-11', 598.00,'Open'),
 (106,  6,'2026-03-15','2026-04-14', 148.00,'Paid'),
 (107,  7,'2026-03-18','2026-04-17', 688.00,'Paid'),
 (108,  8,'2026-03-21','2026-04-20', 329.00,'Open'),
 (109,  9,'2026-03-23','2026-04-22', 539.00,'Disputed'),    -- cancelled order, disputed invoice
 (110, 10,'2026-03-25','2026-04-24', 588.00,'Paid'),
 (111, 11,'2026-03-27','2026-04-26',  89.00,'Overdue'),
 (112, 12,'2026-03-30','2026-04-29',  68.00,'Paid'),
 (113, 13,'2026-04-03','2026-05-03',1088.00,'Open'),
 (114, 14,'2026-04-08','2026-05-08', 198.00,'Paid'),
 (115, 15,'2026-04-15','2026-05-15', 148.00,'Open');

-- ── PAYMENTS (12) ─────────────────────────────────────────────
INSERT INTO payments VALUES
 (201,101,'2026-03-02', 214.00,'CARD','Cleared'),
 (202,102,'2026-03-15', 539.00,'BANK','Cleared'),
 (203,103,'2026-03-09', 418.00,'CARD','Reversed'),   -- reversed on disputed invoice
 (204,104,'2026-03-17', 129.00,'WALLET','Cleared'),
 (205,106,'2026-03-22', 148.00,'CARD','Cleared'),
 (206,107,'2026-04-01', 688.00,'BANK','Cleared'),
 (207,110,'2026-04-06', 588.00,'CARD','Cleared'),
 (208,112,'2026-04-11',  68.00,'WALLET','Cleared'),
 (209,114,'2026-04-20', 198.00,'CARD','Cleared'),
 (210,111,'2026-04-27',  89.00,'CARD','Pending'),     -- pending on overdue invoice
 (211,109,'2026-04-02', 100.00,'CARD','Reversed'),    -- second reversed (partial)
 (212,105,'2026-04-18', 300.00,'BANK','Pending');     -- partial pending on Open invoice

-- ── SHIPMENTS (9) — note: no row for order 9 (cancelled) ──────
INSERT INTO shipments VALUES
 (301, 1,'2026-03-02 08:00','2026-03-04 15:20','DHL','DHL-11001'),
 (302, 2,'2026-03-04 10:10','2026-03-06 11:04','UPS','UPS-22001'),
 (303, 3,'2026-03-07 09:50',NULL,              'FedEx','FDX-33001'),  -- in-flight
 (304, 4,'2026-03-11 13:00','2026-03-13 16:40','DHL','DHL-11002'),
 (305, 6,'2026-03-16 11:20','2026-03-18 10:15','UPS','UPS-22002'),
 (306, 7,'2026-03-19 08:35','2026-03-22 14:02','FedEx','FDX-33002'),
 (307,10,'2026-03-26 10:00',NULL,              'UPS','UPS-22003'),    -- in-flight
 (308,12,'2026-03-31 09:15','2026-04-02 13:20','DHL','DHL-11003'),
 (309,14,'2026-04-09 12:05','2026-04-11 17:45','FedEx','FDX-33003'),
 (310,15,'2026-04-16 08:40',NULL,              'DHL','DHL-11004');    -- in-flight

-- ── ORDER EVENTS (25) — PROV-O-rich, some INFERRED ────────────
-- One per major lifecycle transition.
INSERT INTO order_events VALUES
 (1,  1,'PLACED',   '2026-03-01 10:05','customer',  0.99,'MEASURED'),
 (2,  1,'CONFIRMED','2026-03-01 10:08','system',    0.99,'MEASURED'),
 (3,  1,'SHIPPED',  '2026-03-02 08:00','carrier',   0.99,'MEASURED'),
 (4,  1,'DELIVERED','2026-03-04 15:20','carrier',   0.99,'MEASURED'),
 (5,  2,'PLACED',   '2026-03-03 09:14','customer',  0.99,'MEASURED'),
 (6,  2,'DELIVERED','2026-03-06 11:04','carrier',   0.99,'MEASURED'),
 (7,  3,'PLACED',   '2026-03-06 15:22','customer',  0.99,'MEASURED'),
 (8,  3,'SHIPPED',  '2026-03-07 09:50','carrier',   0.99,'MEASURED'),
 (9,  4,'DELIVERED','2026-03-13 16:40','carrier',   0.99,'MEASURED'),
 (10, 5,'CONFIRMED','2026-03-12 13:55','system',    0.95,'MEASURED'),
 (11, 6,'DELIVERED','2026-03-18 10:15','carrier',   0.99,'MEASURED'),
 (12, 7,'PLACED',   '2026-03-18 08:50','customer',  0.99,'MEASURED'),
 (13, 7,'DELIVERED','2026-03-22 14:02','carrier',   0.99,'MEASURED'),
 (14, 8,'PLACED',   '2026-03-21 12:12','customer',  0.99,'MEASURED'),
 (15, 9,'PLACED',   '2026-03-23 09:25','customer',  0.99,'MEASURED'),
 (16, 9,'CANCELLED','2026-03-23 14:02','customer',  0.95,'MEASURED'),
 (17, 9,'REFUNDED', '2026-03-30 11:10','system',    0.90,'MEASURED'),
 (18,10,'SHIPPED',  '2026-03-26 10:00','carrier',   0.99,'MEASURED'),
 (19,11,'PLACED',   '2026-03-27 10:40','customer',  0.99,'MEASURED'),
 (20,12,'DELIVERED','2026-04-02 13:20','carrier',   0.99,'MEASURED'),
 (21,13,'CONFIRMED','2026-04-03 09:10','system',    0.95,'MEASURED'),
 (22,14,'DELIVERED','2026-04-11 17:45','carrier',   0.99,'MEASURED'),
 (23, 9,'CANCELLED','2026-03-24 02:00','fraud-rule',0.72,'INFERRED'),  -- inferred, not measured
 (24, 3,'DELIVERED','2026-03-10 12:00','heuristic', 0.60,'INFERRED'),  -- inferred delivery
 (25,15,'SHIPPED',  '2026-04-16 08:40','carrier',   0.99,'MEASURED');

-- ============================================================
-- ONTOLOGY METADATA — drives the ontology/shape/JSON-LD
-- generation. Table-level and column-level annotations.
-- ============================================================

-- TABLE-level
INSERT INTO ontology_metadata
 (target_type,table_name,semantic_type,label,description,sensitivity_tier,is_event_class,skos_pref_label,skos_alt_labels,cq_coverage)
VALUES
 ('TABLE','customers',  'Customer', 'Customer',  'A person or organisation that places retail orders.',                     'Confidential',0,'Customer','Client,Account Holder','CQ-001,CQ-002'),
 ('TABLE','products',   'Product',  'Product',   'A catalog item available for sale.',                                       'Public',      0,'Product','Item,SKU',             'CQ-003'),
 ('TABLE','orders',     'Order',    'Order',     'A customer-initiated request to purchase one or more products.',            'Internal',    0,'Order','Purchase Order',        'CQ-001,CQ-004'),
 ('TABLE','order_items','OrderLine','Order Line','A single line of an Order, binding a Product to a quantity and a line total.','Internal',  0,'Order Line','Line Item',            'CQ-004'),
 ('TABLE','invoices',   'Invoice',  'Invoice',   'A demand for payment issued against an Order.',                             'Confidential',0,'Invoice','Bill',                'CQ-005'),
 ('TABLE','payments',   'Payment',  'Payment',   'A monetary settlement made against an Invoice.',                            'Restricted',  0,'Payment','Settlement,Remittance','CQ-006'),
 ('TABLE','shipments',  'Shipment', 'Shipment',  'A physical delivery of an Order to a Customer.',                            'Internal',    0,'Shipment','Delivery,Parcel',      'CQ-007'),
 ('TABLE','order_events','OrderEvent','Order Event','A lifecycle transition of an Order (placed, shipped, delivered, cancelled, refunded).','Internal',1,'Order Event','Order Transition,Lifecycle Event','CQ-008,CQ-009');

-- COLUMN-level (status/state-machine columns and key PROV-O fields)
INSERT INTO ontology_metadata
 (target_type,table_name,column_name,semantic_type,label,description,sensitivity_tier)
VALUES
 ('COLUMN','customers','status','xsd:string','Customer Status','Lifecycle state of the customer account (Active / Suspended / Closed).','Internal'),
 ('COLUMN','orders','status','xsd:string','Order Status','Lifecycle state of the order (Pending / Confirmed / Shipped / Delivered / Cancelled).','Internal'),
 ('COLUMN','invoices','status','xsd:string','Invoice Status','Lifecycle state of the invoice (Open / Paid / Overdue / Disputed).','Confidential'),
 ('COLUMN','payments','status','xsd:string','Payment Status','Lifecycle state of the payment (Cleared / Pending / Reversed).','Restricted'),
 ('COLUMN','payments','amount','xsd:decimal','Payment Amount','Monetary amount of the payment.','Restricted'),
 ('COLUMN','order_events','event_type','xsd:string','Event Type','Discriminator column driving OrderEvent OWL subclass generation (PLACED, CONFIRMED, SHIPPED, DELIVERED, CANCELLED, REFUNDED).','Internal'),
 ('COLUMN','order_events','confidence','xsd:decimal','Confidence','PROV-O confidence score (0.0 to 1.0).','Internal'),
 ('COLUMN','order_events','derivation','xsd:string','Derivation Method','PROV-O derivation method (MEASURED / INFERRED / IMPORTED / SYNTHESIZED).','Internal'),
 ('COLUMN','order_events','actor_party','xsd:string','Actor','Party that triggered the event (customer / carrier / system / fraud-rule).','Internal');
