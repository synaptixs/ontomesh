-- MySQL-flavoured DDL using the inline COMMENT 'text' form.

CREATE TABLE products (
    id          INT AUTO_INCREMENT,
    sku         VARCHAR(40)   NOT NULL COMMENT 'Stock-keeping unit, unique per catalog',
    title       VARCHAR(200)  NOT NULL COMMENT 'Customer-facing product name',
    price_cents INT           NOT NULL COMMENT 'Price in minor currency units (e.g. cents)',
    PRIMARY KEY (id)
) ENGINE=InnoDB COMMENT='Master product catalog — one row per SKU';

CREATE TABLE inventory (
    id           INT AUTO_INCREMENT,
    product_id   INT NOT NULL COMMENT 'FK to products.id',
    warehouse_id INT NOT NULL COMMENT 'Soft FK — no warehouses table here, kept for the legacy join',
    qty_on_hand  INT NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY (product_id) REFERENCES products(id)
) ENGINE=InnoDB;
