-- Macmillan Company - Hospital Sales Management System (MySQL / MariaDB, XAMPP)
-- phpMyAdmin: open http://localhost/phpmyadmin -> Import -> choose this file -> Go.
-- Creates the database, tables, safety triggers and the first login admin / admin123.

CREATE DATABASE IF NOT EXISTS `macmillan_hms` CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
USE `macmillan_hms`;
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS users (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    username      VARCHAR(64)  NOT NULL,
    full_name     VARCHAR(120) NOT NULL,
    role          VARCHAR(20)  NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    active        TINYINT      NOT NULL DEFAULT 1,
    created_at    VARCHAR(19)  NOT NULL,
    UNIQUE KEY uq_users_username (username),
    CONSTRAINT chk_users_role CHECK (role IN ('administrator','pharmacist','cashier'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS products (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    code          VARCHAR(64)  NOT NULL,
    name          VARCHAR(200) NOT NULL,
    unit          VARCHAR(32)  NOT NULL DEFAULT 'unit',
    price         DOUBLE       NOT NULL,
    reorder_level INT          NOT NULL DEFAULT 0,
    active        TINYINT      NOT NULL DEFAULT 1,
    UNIQUE KEY uq_products_code (code),
    CONSTRAINT chk_products_price CHECK (price >= 0),
    CONSTRAINT chk_products_reorder CHECK (reorder_level >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS batches (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    product_id  INT         NOT NULL,
    batch_no    VARCHAR(64) NOT NULL,
    expiry_date VARCHAR(10) NOT NULL,
    quantity    INT         NOT NULL,
    cost_price  DOUBLE      NOT NULL DEFAULT 0,
    received_at VARCHAR(19) NOT NULL,
    UNIQUE KEY uq_batches_product_batch (product_id, batch_no),
    KEY idx_batches_fefo (product_id, expiry_date),
    CONSTRAINT fk_batches_product FOREIGN KEY (product_id) REFERENCES products(id),
    CONSTRAINT chk_batches_qty CHECK (quantity >= 0),
    CONSTRAINT chk_batches_cost CHECK (cost_price >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS sales (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    receipt_no  VARCHAR(64)  NOT NULL,
    sold_at     VARCHAR(19)  NOT NULL,
    cashier_id  INT          NOT NULL,
    customer    VARCHAR(200) NOT NULL DEFAULT '',
    total       DOUBLE       NOT NULL,
    status      VARCHAR(12)  NOT NULL DEFAULT 'COMPLETED',
    void_reason TEXT NULL,
    voided_by   INT NULL,
    voided_at   VARCHAR(19) NULL,
    UNIQUE KEY uq_sales_receipt (receipt_no),
    KEY idx_sales_date (sold_at),
    CONSTRAINT fk_sales_cashier FOREIGN KEY (cashier_id) REFERENCES users(id),
    CONSTRAINT fk_sales_voider FOREIGN KEY (voided_by) REFERENCES users(id),
    CONSTRAINT chk_sales_status CHECK (status IN ('COMPLETED','VOIDED'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS sale_items (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    sale_id    INT    NOT NULL,
    product_id INT    NOT NULL,
    batch_id   INT    NOT NULL,
    quantity   INT    NOT NULL,
    unit_price DOUBLE NOT NULL,
    line_total DOUBLE NOT NULL,
    CONSTRAINT fk_items_sale FOREIGN KEY (sale_id) REFERENCES sales(id),
    CONSTRAINT fk_items_product FOREIGN KEY (product_id) REFERENCES products(id),
    CONSTRAINT fk_items_batch FOREIGN KEY (batch_id) REFERENCES batches(id),
    CONSTRAINT chk_items_qty CHECK (quantity > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS `returns` (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    sale_item_id  INT         NOT NULL,
    quantity      INT         NOT NULL,
    refund        DOUBLE      NOT NULL,
    reason        TEXT        NOT NULL,
    authorised_by INT         NOT NULL,
    returned_at   VARCHAR(19) NOT NULL,
    CONSTRAINT fk_returns_item FOREIGN KEY (sale_item_id) REFERENCES sale_items(id),
    CONSTRAINT fk_returns_auth FOREIGN KEY (authorised_by) REFERENCES users(id),
    CONSTRAINT chk_returns_qty CHECK (quantity > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS audit_log (
    id       INT AUTO_INCREMENT PRIMARY KEY,
    ts       VARCHAR(19) NOT NULL,
    user_id  INT NULL,
    username VARCHAR(64) NOT NULL,
    action   VARCHAR(64) NOT NULL,
    details  TEXT        NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS expiry_alerts (
    id        INT AUTO_INCREMENT PRIMARY KEY,
    batch_id  INT         NOT NULL,
    threshold INT         NOT NULL,
    raised_on VARCHAR(10) NOT NULL,
    UNIQUE KEY uq_alert (batch_id, threshold),
    CONSTRAINT fk_alert_batch FOREIGN KEY (batch_id) REFERENCES batches(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE IF NOT EXISTS settings (
    setting_key   VARCHAR(64) NOT NULL PRIMARY KEY,
    setting_value TEXT        NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

DELIMITER $$
DROP TRIGGER IF EXISTS audit_no_update $$
CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_log FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'The audit log is append-only' $$
DROP TRIGGER IF EXISTS audit_no_delete $$
CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_log FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'The audit log is append-only' $$
DROP TRIGGER IF EXISTS block_expired_sale $$
CREATE TRIGGER block_expired_sale BEFORE INSERT ON sale_items FOR EACH ROW
BEGIN
  IF (SELECT expiry_date FROM batches WHERE id = NEW.batch_id) < DATE_FORMAT(CURDATE(), '%Y-%m-%d') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Expired batch cannot be sold';
  END IF;
END $$
DELIMITER ;

INSERT IGNORE INTO settings(setting_key, setting_value) VALUES ('alert_thresholds', '90,60,30');
INSERT INTO users(username, full_name, role, password_hash, created_at)
  SELECT 'admin', 'System Administrator', 'administrator', 'pbkdf2_sha256$200000$1b585193a662e9f0e2e57b4350508350$2498bce2ce5f4bebc20fc9061ab2a190ca8a0aacfcb490e6b7d3701c3cfc55d4', NOW() FROM DUAL
  WHERE NOT EXISTS (SELECT 1 FROM users);
