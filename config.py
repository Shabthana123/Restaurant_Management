import os
import pymysql
from dotenv import load_dotenv

load_dotenv()

db_password = os.getenv("DB_Password")
print(db_password)

SECRET_KEY = os.getenv("TABLEFLOW_SECRET", "change-me-in-production")
DB = dict(
    host=os.getenv("DB_HOST", "localhost"),
    user=os.getenv("DB_USER", "root"),
    password=os.getenv("DB_PASSWORD", db_password),
    database=os.getenv("DB_NAME", "RestoDesk"),
    charset="utf8mb4",
)
DICT_CURSOR = pymysql.cursors.DictCursor

# Billing (percentage of charge as service tax)
from decimal import Decimal
SERVICE_CHARGE_PCT = Decimal("10")
TAX_PCT = Decimal("0")