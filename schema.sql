CREATE DATABASE IF NOT EXISTS tableflow CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE tableflow;

CREATE TABLE users (
  id INT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(50) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  full_name VARCHAR(100) NOT NULL,
  role ENUM('admin','waiter','kitchen','cashier') NOT NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 1
);

CREATE TABLE dining_tables (
  id INT AUTO_INCREMENT PRIMARY KEY,
  label VARCHAR(20) NOT NULL UNIQUE,
  seats TINYINT NOT NULL DEFAULT 4
);

CREATE TABLE menu_categories (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(60) NOT NULL UNIQUE,
  sort_order INT NOT NULL DEFAULT 0
);

CREATE TABLE menu_items (
  id INT AUTO_INCREMENT PRIMARY KEY,
  category_id INT NOT NULL,
  name VARCHAR(100) NOT NULL,
  price DECIMAL(10,2) NOT NULL,
  is_available TINYINT(1) NOT NULL DEFAULT 1,
  FOREIGN KEY (category_id) REFERENCES menu_categories(id)
);

-- One open order per table at a time; 'paid' is set by the cashier (next phase)
CREATE TABLE orders (
  id INT AUTO_INCREMENT PRIMARY KEY,
  table_id INT NOT NULL,
  waiter_id INT NOT NULL,
  status ENUM('open','paid','cancelled') NOT NULL DEFAULT 'open',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  closed_at DATETIME NULL,
  FOREIGN KEY (table_id) REFERENCES dining_tables(id),
  FOREIGN KEY (waiter_id) REFERENCES users(id),
  INDEX idx_table_status (table_id, status)
);

-- unit_price is copied at order time so later price changes don't rewrite history
CREATE TABLE order_items (
  id INT AUTO_INCREMENT PRIMARY KEY,
  order_id INT NOT NULL,
  menu_item_id INT NOT NULL,
  quantity SMALLINT NOT NULL DEFAULT 1,
  unit_price DECIMAL(10,2) NOT NULL,
  note VARCHAR(200) NULL,
  status ENUM('new','preparing','ready','served','cancelled') NOT NULL DEFAULT 'new',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (order_id) REFERENCES orders(id),
  FOREIGN KEY (menu_item_id) REFERENCES menu_items(id),
  INDEX idx_status (status)
);

-- Payment is recorded by the cashier when the order is closed. One payment per order.
CREATE TABLE payments (
  id INT AUTO_INCREMENT PRIMARY KEY,
  order_id INT NOT NULL UNIQUE,            -- one payment closes one order
  cashier_id INT NOT NULL,
  subtotal DECIMAL(10,2) NOT NULL,
  discount DECIMAL(10,2) NOT NULL DEFAULT 0,
  service_charge DECIMAL(10,2) NOT NULL DEFAULT 0,
  tax DECIMAL(10,2) NOT NULL DEFAULT 0,
  total DECIMAL(10,2) NOT NULL,
  method ENUM('cash','card') NOT NULL,
  amount_tendered DECIMAL(10,2) NOT NULL,
  change_given DECIMAL(10,2) NOT NULL DEFAULT 0,
  paid_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (order_id) REFERENCES orders(id),
  FOREIGN KEY (cashier_id) REFERENCES users(id)
);