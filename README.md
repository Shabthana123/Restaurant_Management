# RestoDesk (phase 1)

Restaurant management: waiter orders, kitchen queue, menu admin. Python + Flask, MySQL, Bootstrap 5.

## Setup
```bash
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
python setup_db.py
export DB_USER=root DB_PASSWORD=yourpassword      # Windows: set instead of export
cd scripts
python seed.py
python app.py                                      # http://127.0.0.1:5000
```
Dev logins: admin/admin123, waiter1/waiter123, kitchen1/kitchen123, cashier1/cashier123

## Flow to try
1. Log in as waiter1, open a table, add items
2. Log in as kitchen1 (another browser/private window), start and finish items
3. Back as waiter1, mark ready items as served
