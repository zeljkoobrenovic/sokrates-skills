"""SQLite persistence for orders."""
import sqlite3

SCHEMA = "CREATE TABLE IF NOT EXISTS orders (id TEXT PRIMARY KEY, customer TEXT, total REAL, currency TEXT)"


class OrdersRepository:
    def __init__(self, path):
        self.connection = sqlite3.connect(path)
        self.connection.execute(SCHEMA)

    def save_all(self, orders):
        rows = normalize_rows(orders)
        with self.connection:
            self.connection.executemany("INSERT OR REPLACE INTO orders VALUES (?, ?, ?, ?)", rows)

    def find_by_customer(self, customer):
        cursor = self.connection.execute("SELECT id, customer, total, currency FROM orders WHERE customer = ?", (customer,))
        return [dict(zip(("id", "customer", "total", "currency"), row)) for row in cursor.fetchall()]


def normalize_rows(orders):
    rows = []
    for order in orders:
        identifier = str(order.get("id", "")).strip()
        if not identifier:
            continue
        customer = str(order.get("customer", "")).strip().lower()
        total = float(order.get("total", 0) or 0)
        currency = str(order.get("currency", "EUR")).upper()
        if currency not in ("EUR", "USD"):
            currency = "EUR"
        rows.append((identifier, customer, round(total, 2), currency))
    return rows
