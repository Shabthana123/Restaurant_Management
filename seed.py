"""Run once after schema.sql:  python seed.py   (dev data only)"""
import pymysql
from werkzeug.security import generate_password_hash
from config import DB

conn = pymysql.connect(**DB)
cur = conn.cursor()

users = [("admin", "admin123", "Admin", "admin"),
         ("waiter1", "waiter123", "Nimal (Waiter)", "waiter"),
         ("kitchen1", "kitchen123", "Kitchen", "kitchen"),
         ("cashier1", "cashier123", "Cashier", "cashier")]
for u, p, n, r in users:
    cur.execute("INSERT IGNORE INTO users (username,password_hash,full_name,role) VALUES (%s,%s,%s,%s)",
                (u, generate_password_hash(p), n, r))

for i in range(1, 9):
    cur.execute("INSERT IGNORE INTO dining_tables (label,seats) VALUES (%s,%s)", (f"T{i}", 2 if i <= 3 else 4))

menu = {
    "Starters": [("Vegetable Spring Rolls", 650), ("Chicken Wings", 950), ("Tomato Soup", 550)],
    "Mains": [("Chicken Fried Rice", 1100), ("Kottu Roti", 1250), ("Grilled Fish & Chips", 1650), ("Veg Curry Plate", 900)],
    "Drinks": [("Fresh Lime Juice", 400), ("Iced Tea", 350), ("Ceylon Tea", 250)],
    "Desserts": [("Watalappan", 500), ("Ice Cream Scoop", 400)],
}
for order, (cat, items) in enumerate(menu.items()):
    cur.execute("INSERT IGNORE INTO menu_categories (name,sort_order) VALUES (%s,%s)", (cat, order))
    cur.execute("SELECT id FROM menu_categories WHERE name=%s", (cat,))
    cid = cur.fetchone()[0]
    for name, price in items:
        cur.execute("SELECT 1 FROM menu_items WHERE name=%s", (name,))
        if not cur.fetchone():
            cur.execute("INSERT INTO menu_items (category_id,name,price) VALUES (%s,%s,%s)", (cid, name, price))
conn.commit()
print("Seeded. Logins: admin/admin123, waiter1/waiter123, kitchen1/kitchen123, cashier1/cashier123")
