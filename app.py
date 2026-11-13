import re
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from functools import wraps
import pymysql
from flask import Flask, g, render_template, request, redirect, url_for, session, flash, abort
from werkzeug.security import check_password_hash, generate_password_hash
import config

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

HOME = {"admin": "tables", "waiter": "tables", "kitchen": "kitchen", "cashier": "tables"}


# ---------- database ----------
def db():
    if "db" not in g:
        g.db = pymysql.connect(**config.DB, cursorclass=config.DICT_CURSOR, autocommit=False)
    return g.db


@app.teardown_appcontext
def close_db(_):
    conn = g.pop("db", None)
    if conn:
        conn.close()


def query(sql, args=(), one=False):
    with db().cursor() as cur:
        cur.execute(sql, args)
        rows = cur.fetchall()
    return (rows[0] if rows else None) if one else rows


def execute(sql, args=()):
    with db().cursor() as cur:
        cur.execute(sql, args)
        last = cur.lastrowid
    db().commit()
    return last


# ---------- auth ----------
def login_required(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if "user" not in session:
                return redirect(url_for("login"))
            if roles and session["user"]["role"] not in roles and session["user"]["role"] != "admin":
                abort(403)
            return fn(*a, **kw)
        return wrapper
    return deco


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = query("SELECT * FROM users WHERE username=%s",
                     (request.form["username"].strip(),), one=True)
        if user and check_password_hash(user["password_hash"], request.form["password"]):
            if not user["is_active"]:
                flash("Your account is waiting for admin approval.", "warning")
            else:
                session["user"] = {"id": user["id"], "name": user["full_name"], "role": user["role"]}
                return redirect(url_for(HOME[user["role"]]))
        else:
            flash("Wrong username or password.", "danger")
    return render_template("login.html")


# Admin accounts are never self-service: they can only be created by seed.py or directly in the database.
SIGNUP_ROLES = ["waiter", "kitchen", "cashier"]


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"].strip().lower()
        full_name = request.form["full_name"].strip()
        password = request.form["password"]
        role = request.form["role"]
        error = None
        if not re.fullmatch(r"[a-z0-9_]{3,30}", username):
            error = "Username must be 3-30 characters: letters, numbers or underscores."
        elif not full_name:
            error = "Enter your full name."
        elif role not in SIGNUP_ROLES:
            error = "Choose a valid role."
        elif len(password) < 8:
            error = "Password must be at least 8 characters."
        elif password != request.form["confirm"]:
            error = "Passwords don't match."
        elif query("SELECT 1 FROM users WHERE username=%s", (username,), one=True):
            error = "That username is taken."
        if error:
            flash(error, "danger")
            return render_template("signup.html", roles=SIGNUP_ROLES, form=request.form)
        # is_active=0: the account can't log in until an admin approves it
        execute("INSERT INTO users (username,password_hash,full_name,role,is_active) VALUES (%s,%s,%s,%s,0)",
                (username, generate_password_hash(password), full_name, role))
        flash("Account created. An admin needs to approve it before you can log in.", "success")
        return redirect(url_for("login"))
    return render_template("signup.html", roles=SIGNUP_ROLES, form={})


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def index():
    if "user" in session:
        return redirect(url_for(HOME[session["user"]["role"]]))
    return redirect(url_for("login"))


# ---------- waiter: floor + orders ----------
@app.route("/tables")
@login_required("waiter", "cashier")
def tables():
    rows = query("""
        SELECT t.id, t.label, t.seats, o.id AS order_id,
               COALESCE(SUM(CASE WHEN oi.status<>'cancelled' THEN oi.quantity*oi.unit_price END),0) AS total,
               SUM(oi.status='ready') AS ready_count
        FROM dining_tables t
        LEFT JOIN orders o ON o.table_id=t.id AND o.status='open'
        LEFT JOIN order_items oi ON oi.order_id=o.id
        GROUP BY t.id, t.label, t.seats, o.id
        ORDER BY t.id""")
    return render_template("tables.html", tables=rows)


@app.route("/tables/<int:table_id>/order")
@login_required("waiter", "cashier")
def order_page(table_id):
    table = query("SELECT * FROM dining_tables WHERE id=%s", (table_id,), one=True) or abort(404)
    order = query("SELECT * FROM orders WHERE table_id=%s AND status='open'", (table_id,), one=True)
    items = []
    if order:
        items = query("""SELECT oi.*, m.name FROM order_items oi
                         JOIN menu_items m ON m.id=oi.menu_item_id
                         WHERE oi.order_id=%s ORDER BY oi.id""", (order["id"],))
    menu = query("""SELECT m.*, c.name AS category FROM menu_items m
                    JOIN menu_categories c ON c.id=m.category_id
                    WHERE m.is_available=1 ORDER BY c.sort_order, m.name""")
    total = sum(i["quantity"] * i["unit_price"] for i in items if i["status"] != "cancelled")
    return render_template("order.html", table=table, order=order, items=items, menu=menu, total=total)


@app.post("/tables/<int:table_id>/add")
@login_required("waiter")
def add_item(table_id):
    item_id = int(request.form["menu_item_id"])
    qty = max(1, min(int(request.form.get("quantity", 1)), 50))
    conn = db()
    try:
        with conn.cursor() as cur:
            # lock the table row so two waiters can't create two open orders for one table
            cur.execute("SELECT id FROM dining_tables WHERE id=%s FOR UPDATE", (table_id,))
            if not cur.fetchone():
                abort(404)
            cur.execute("SELECT id FROM orders WHERE table_id=%s AND status='open'", (table_id,))
            row = cur.fetchone()
            if row:
                order_id = row["id"]
            else:
                cur.execute("INSERT INTO orders (table_id, waiter_id) VALUES (%s,%s)",
                            (table_id, session["user"]["id"]))
                order_id = cur.lastrowid
            cur.execute("SELECT price FROM menu_items WHERE id=%s AND is_available=1", (item_id,))
            menu_item = cur.fetchone()
            if not menu_item:
                flash("That item is no longer available.", "warning")
            else:
                cur.execute("""INSERT INTO order_items (order_id, menu_item_id, quantity, unit_price, note)
                               VALUES (%s,%s,%s,%s,%s)""",
                            (order_id, item_id, qty, menu_item["price"], request.form.get("note", "").strip()[:200] or None))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return redirect(url_for("order_page", table_id=table_id))


@app.post("/order-items/<int:item_id>/cancel")
@login_required("waiter")
def cancel_item(item_id):
    item = query("""SELECT oi.id, o.table_id FROM order_items oi JOIN orders o ON o.id=oi.order_id
                    WHERE oi.id=%s""", (item_id,), one=True) or abort(404)
    # only cancellable before the kitchen starts on it
    execute("UPDATE order_items SET status='cancelled' WHERE id=%s AND status='new'", (item_id,))
    return redirect(url_for("order_page", table_id=item["table_id"]))


@app.post("/order-items/<int:item_id>/served")
@login_required("waiter")
def mark_served(item_id):
    item = query("""SELECT o.table_id FROM order_items oi JOIN orders o ON o.id=oi.order_id
                    WHERE oi.id=%s""", (item_id,), one=True) or abort(404)
    execute("UPDATE order_items SET status='served' WHERE id=%s AND status='ready'", (item_id,))
    return redirect(url_for("order_page", table_id=item["table_id"]))


# ---------- kitchen ----------
NEXT_STATUS = {"new": "preparing", "preparing": "ready"}


@app.route("/kitchen")
@login_required("kitchen")
def kitchen():
    rows = query("""SELECT oi.id, oi.quantity, oi.note, oi.status, oi.created_at, m.name,
                           t.label AS table_label, o.id AS order_id
                    FROM order_items oi
                    JOIN orders o ON o.id=oi.order_id AND o.status='open'
                    JOIN dining_tables t ON t.id=o.table_id
                    JOIN menu_items m ON m.id=oi.menu_item_id
                    WHERE oi.status IN ('new','preparing')
                    ORDER BY oi.created_at""")
    return render_template("kitchen.html", items=rows)


@app.post("/kitchen/<int:item_id>/advance")
@login_required("kitchen")
def advance(item_id):
    item = query("SELECT status FROM order_items WHERE id=%s", (item_id,), one=True) or abort(404)
    if item["status"] in NEXT_STATUS:
        # status guard in WHERE prevents double-advancing on a double click
        execute("UPDATE order_items SET status=%s WHERE id=%s AND status=%s",
                (NEXT_STATUS[item["status"]], item_id, item["status"]))
    return redirect(url_for("kitchen"))


# ---------- admin: menu ----------
@app.route("/admin/menu", methods=["GET", "POST"])
@login_required()
def admin_menu():
    if session["user"]["role"] != "admin":
        abort(403)
    if request.method == "POST":
        execute("INSERT INTO menu_items (category_id,name,price) VALUES (%s,%s,%s)",
                (request.form["category_id"], request.form["name"].strip(), request.form["price"]))
        flash("Item added.", "success")
        return redirect(url_for("admin_menu"))
    cats = query("SELECT * FROM menu_categories ORDER BY sort_order")
    items = query("""SELECT m.*, c.name AS category FROM menu_items m
                     JOIN menu_categories c ON c.id=m.category_id ORDER BY c.sort_order, m.name""")
    return render_template("admin_menu.html", cats=cats, items=items)


@app.post("/admin/menu/<int:item_id>/toggle")
@login_required()
def toggle_item(item_id):
    if session["user"]["role"] != "admin":
        abort(403)
    execute("UPDATE menu_items SET is_available = 1 - is_available WHERE id=%s", (item_id,))
    return redirect(url_for("admin_menu"))


@app.route("/admin/users")
@login_required()
def admin_users():
    if session["user"]["role"] != "admin":
        abort(403)
    users = query("SELECT id, username, full_name, role, is_active FROM users ORDER BY is_active, role, username")
    return render_template("admin_users.html", users=users)


@app.post("/admin/users/<int:user_id>/toggle")
@login_required()
def toggle_user(user_id):
    if session["user"]["role"] != "admin":
        abort(403)
    if user_id == session["user"]["id"]:
        flash("You can't disable your own account.", "warning")
    else:
        execute("UPDATE users SET is_active = 1 - is_active WHERE id=%s", (user_id,))
    return redirect(url_for("admin_users"))

# ---------- cashier: billing ----------
def money(x):
    return Decimal(x).quantize(Decimal("0.01"), ROUND_HALF_UP)
 
 
def bill_totals(subtotal, discount):
    base = subtotal - discount
    service = money(base * config.SERVICE_CHARGE_PCT / 100)
    tax = money(base * config.TAX_PCT / 100)
    return service, tax, base + service + tax
 
 
def load_bill(order_id):
    order = query("""SELECT o.*, t.label AS table_label FROM orders o
                     JOIN dining_tables t ON t.id=o.table_id WHERE o.id=%s""", (order_id,), one=True) or abort(404)
    items = query("""SELECT oi.*, m.name FROM order_items oi JOIN menu_items m ON m.id=oi.menu_item_id
                     WHERE oi.order_id=%s AND oi.status<>'cancelled' ORDER BY oi.id""", (order_id,))
    subtotal = sum((i["quantity"] * i["unit_price"] for i in items), Decimal("0"))
    return order, items, subtotal
 
 
@app.route("/orders/<int:order_id>/bill")
@login_required("cashier")
def bill(order_id):
    order, items, subtotal = load_bill(order_id)
    if order["status"] == "paid":
        return redirect(url_for("receipt", order_id=order_id))
    if order["status"] != "open":
        abort(404)
    pending = [i for i in items if i["status"] in ("new", "preparing")]
    return render_template("bill.html", order=order, items=items, subtotal=subtotal, pending=pending,
                           svc_pct=config.SERVICE_CHARGE_PCT, tax_pct=config.TAX_PCT)
 
 
@app.post("/orders/<int:order_id>/pay")
@login_required("cashier")
def pay(order_id):
    method = request.form.get("method")
    try:
        discount = money(request.form.get("discount") or 0)
        tendered = money(request.form.get("tendered") or 0)
    except InvalidOperation:
        flash("Enter valid amounts.", "danger")
        return redirect(url_for("bill", order_id=order_id))
    conn = db()
    try:
        with conn.cursor() as cur:
            # lock the order so two cashiers can't take payment twice
            cur.execute("SELECT status FROM orders WHERE id=%s FOR UPDATE", (order_id,))
            row = cur.fetchone() or abort(404)
            if row["status"] != "open":
                conn.rollback()
                flash("This order is already closed.", "warning")
                return redirect(url_for("receipt", order_id=order_id))
            cur.execute("""SELECT status, quantity, unit_price FROM order_items
                           WHERE order_id=%s AND status<>'cancelled'""", (order_id,))
            items = cur.fetchall()
            subtotal = sum((i["quantity"] * i["unit_price"] for i in items), Decimal("0"))
            error = None
            if not items:
                error = "There are no items to bill."
            elif any(i["status"] in ("new", "preparing") for i in items):
                error = "Some items haven't left the kitchen yet. Wait until they're ready, or ask the waiter to cancel them."
            elif method not in ("cash", "card"):
                error = "Choose a payment method."
            elif discount < 0 or discount > subtotal:
                error = "Discount must be between 0 and the subtotal."
            service, tax, total = bill_totals(subtotal, discount) if not error else (0, 0, 0)
            if not error and method == "cash" and tendered < total:
                error = "The cash received is less than the total."
            if error:
                conn.rollback()
                flash(error, "danger")
                return redirect(url_for("bill", order_id=order_id))
            if method == "card":
                tendered = total
            cur.execute("""INSERT INTO payments (order_id,cashier_id,subtotal,discount,service_charge,tax,total,
                                                 method,amount_tendered,change_given)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (order_id, session["user"]["id"], subtotal, discount, service, tax, total,
                         method, tendered, tendered - total))
            cur.execute("UPDATE order_items SET status='served' WHERE order_id=%s AND status='ready'", (order_id,))
            cur.execute("UPDATE orders SET status='paid', closed_at=NOW() WHERE id=%s", (order_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    flash("Payment recorded. The table is free again.", "success")
    return redirect(url_for("receipt", order_id=order_id))
 
 
@app.post("/orders/<int:order_id>/void")
@login_required("cashier")
def void_empty(order_id):
    """Frees a table whose order has no billable items (everything was cancelled)."""
    order, items, _ = load_bill(order_id)
    if order["status"] == "open" and not items:
        execute("UPDATE orders SET status='cancelled', closed_at=NOW() WHERE id=%s", (order_id,))
        flash("Empty order closed. The table is free.", "success")
    return redirect(url_for("tables"))
 
 
@app.route("/orders/<int:order_id>/receipt")
@login_required("cashier", "waiter")
def receipt(order_id):
    order, items, _ = load_bill(order_id)
    pay_row = query("""SELECT p.*, u.full_name AS cashier FROM payments p
                       JOIN users u ON u.id=p.cashier_id WHERE p.order_id=%s""", (order_id,), one=True) or abort(404)
    return render_template("receipt.html", order=order, items=items, p=pay_row)

 
@app.errorhandler(403)
def forbidden(_):
    return render_template("base.html", content="You don't have access to that page."), 403


if __name__ == "__main__":
    app.run(debug=True)