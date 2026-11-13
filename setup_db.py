"""Makes the database match schema.sql:  python setup_db.py   (add --yes to skip the confirmation)

Edit schema.sql whenever you want a new table, column or index, then run this again.
How it works: it builds schema.sql into a temporary "shadow" database, compares it with your real
database, and applies only the differences:
  - new tables are created
  - new columns are added; changed column definitions are modified
  - new indexes and foreign keys are added
It never drops tables, columns or data. Anything that is in the database but no longer in
schema.sql is reported as a warning and left alone (so renames and removals are done by hand).
"""
import re
import sys
import pymysql
from pymysql.constants import CLIENT
from config import DB

REAL = DB["database"]
SHADOW = REAL + "_shadow"
conn = pymysql.connect(**{k: v for k, v in DB.items() if k != "database"}, client_flag=CLIENT.MULTI_STATEMENTS)
cur = conn.cursor()


def run_script(sql):
    cur.execute(sql)
    while cur.nextset():   # drain results so an error in any statement is raised
        pass


def parse(db, table):
    """Read a table's definition: ({column: definition}, {normalised key: definition})."""
    cur.execute(f"SHOW CREATE TABLE `{db}`.`{table}`")
    cols, keys = {}, {}
    for line in cur.fetchone()[1].splitlines()[1:-1]:
        line = line.strip().rstrip(",")
        if line.startswith("`"):
            cols[line.split("`")[1]] = line
        elif not line.startswith("PRIMARY KEY"):
            line = re.sub(r"^CONSTRAINT `[^`]+` ", "", line)    # ignore auto-generated names
            line = re.sub(r"KEY `[^`]+` ", "KEY ", line)
            keys[line] = line
    return cols, keys


schema = open("schema.sql", encoding="utf-8").read()
schema = re.sub(r"(?im)^\s*(CREATE DATABASE|USE)\b[^;]*;", "", schema)   # we choose the database ourselves
tables = list(dict.fromkeys(re.findall(r"(?i)CREATE TABLE\s+(?:IF NOT EXISTS\s+)?`?(\w+)`?", schema)))

try:
    run_script(f"DROP DATABASE IF EXISTS `{SHADOW}`; "
               f"CREATE DATABASE `{SHADOW}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; USE `{SHADOW}`;" + schema)
    run_script(f"CREATE DATABASE IF NOT EXISTS `{REAL}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")

    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=%s", (REAL,))
    existing = {r[0] for r in cur.fetchall()}
    creates, alters, warnings = [], [], []

    for t in tables:
        if t not in existing:
            cur.execute(f"SHOW CREATE TABLE `{SHADOW}`.`{t}`")
            ddl = cur.fetchone()[1].replace(f"CREATE TABLE `{t}`", f"CREATE TABLE `{REAL}`.`{t}`", 1)
            creates.append((f"create table {t}", ddl))
            continue
        sc, sk = parse(SHADOW, t)
        rc, rk = parse(REAL, t)
        prev = None
        for name, d in sc.items():
            if name not in rc:
                where = f"AFTER `{prev}`" if prev else "FIRST"
                alters.append((f"{t}: add column {name}", f"ALTER TABLE `{REAL}`.`{t}` ADD COLUMN {d} {where}"))
            elif rc[name] != d:
                alters.append((f"{t}: change column {name}\n        from: {rc[name]}\n        to:   {d}",
                               f"ALTER TABLE `{REAL}`.`{t}` MODIFY COLUMN {d}"))
            prev = name
        for k in sk.keys() - rk.keys():
            alters.append((f"{t}: add {k}", f"ALTER TABLE `{REAL}`.`{t}` ADD {k}"))
        warnings += [f"{t}.{c} is in the database but not in schema.sql (left untouched)" for c in rc.keys() - sc.keys()]
        warnings += [f"{t} has an index/constraint not in schema.sql (left untouched): {k}" for k in rk.keys() - sk.keys()]
    warnings += [f"table {t} is in the database but not in schema.sql (left untouched)" for t in existing - set(tables)]

    for w in warnings:
        print("WARNING:", w)
    changes = creates + alters
    if not changes:
        print("Database already matches schema.sql.")
    else:
        print("Changes to apply:")
        for desc, _ in changes:
            print("  -", desc)
        if alters and "--yes" not in sys.argv and input("Apply these changes? [y/N] ").lower() != "y":
            sys.exit("Cancelled. Nothing was changed.")
        for desc, sql in creates + alters:   # create tables first so new foreign keys can point at them
            cur.execute(sql)
        print("Done.")
finally:
    cur.execute(f"DROP DATABASE IF EXISTS `{SHADOW}`")
    conn.close()