-- MySQL-flavoured DDL fixture (AUTO_INCREMENT, ENGINE=, TINYINT).

CREATE TABLE accounts (
    id           INT NOT NULL AUTO_INCREMENT,
    holder_email VARCHAR(255) NOT NULL,
    is_active    TINYINT(1)   NOT NULL,
    PRIMARY KEY (id)
) ENGINE=InnoDB;

CREATE TABLE transactions (
    id          BIGINT      NOT NULL AUTO_INCREMENT,
    account_id  INT         NOT NULL,
    amount      DECIMAL(12,2) NOT NULL,
    occurred_at DATETIME,
    PRIMARY KEY (id),
    FOREIGN KEY (account_id) REFERENCES accounts(id)
) ENGINE=InnoDB;
