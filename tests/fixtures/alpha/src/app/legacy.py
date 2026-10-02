"""Kept for the old CSV export; the normalizer is a copy of the repository's."""
import csv
import warnings


def export_csv(orders, path):
    warnings.warn("export_csv is deprecated, use the API", DeprecationWarning)
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        for row in normalize_rows(orders):
            writer.writerow(row)


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
