"""MySQL / MariaDB schema (works with the MariaDB that ships with XAMPP)."""

_TAIL = "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci"

TABLES = [
    ("users", """CREATE TABLE IF NOT EXISTS users (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    username      VARCHAR(64)  NOT NULL,
    full_name     VARCHAR(120) NOT NULL,
    role          VARCHAR(20)  NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    active        TINYINT      NOT NULL DEFAULT 1,
    created_at    VARCHAR(19)  NOT NULL,
    UNIQUE KEY uq_users_username (username),
    CONSTRAINT chk_users_role CHECK (role IN ('administrator','pharmacist','cashier'))
) """ + _TAIL),

    ("products", """CREATE TABLE IF NOT EXISTS products (
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
) """ + _TAIL),

    ("batches", """CREATE TABLE IF NOT EXISTS batches (
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
) """ + _TAIL),

    ("sales", """CREATE TABLE IF NOT EXISTS sales (
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
) """ + _TAIL),

    ("sale_items", """CREATE TABLE IF NOT EXISTS sale_items (
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
) """ + _TAIL),

    ("returns", """CREATE TABLE IF NOT EXISTS `returns` (
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
) """ + _TAIL),

    ("audit_log", """CREATE TABLE IF NOT EXISTS audit_log (
    id       INT AUTO_INCREMENT PRIMARY KEY,
    ts       VARCHAR(19) NOT NULL,
    user_id  INT NULL,
    username VARCHAR(64) NOT NULL,
    action   VARCHAR(64) NOT NULL,
    details  TEXT        NOT NULL
) """ + _TAIL),

    ("expiry_alerts", """CREATE TABLE IF NOT EXISTS expiry_alerts (
    id        INT AUTO_INCREMENT PRIMARY KEY,
    batch_id  INT         NOT NULL,
    threshold INT         NOT NULL,
    raised_on VARCHAR(10) NOT NULL,
    UNIQUE KEY uq_alert (batch_id, threshold),
    CONSTRAINT fk_alert_batch FOREIGN KEY (batch_id) REFERENCES batches(id)
) """ + _TAIL),

    ("settings", """CREATE TABLE IF NOT EXISTS settings (
    setting_key   VARCHAR(64) NOT NULL PRIMARY KEY,
    setting_value TEXT        NOT NULL
) """ + _TAIL),
]

# The application cannot edit or delete audit entries, and an expired batch can never be sold.
TRIGGERS = [
    ("audit_no_update",
     "CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_log FOR EACH ROW "
     "SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'The audit log is append-only'"),
    ("audit_no_delete",
     "CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit_log FOR EACH ROW "
     "SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'The audit log is append-only'"),
    ("block_expired_sale",
     "CREATE TRIGGER block_expired_sale BEFORE INSERT ON sale_items FOR EACH ROW\n"
     "BEGIN\n"
     "  IF (SELECT expiry_date FROM batches WHERE id = NEW.batch_id) < DATE_FORMAT(CURDATE(), '%Y-%m-%d') THEN\n"
     "    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Expired batch cannot be sold';\n"
     "  END IF;\n"
     "END"),
]

TABLE_NAMES = [name for name, _ in TABLES]
