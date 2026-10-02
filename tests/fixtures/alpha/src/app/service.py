"""Fetch orders from the upstream API with retries and cache them on disk."""
import json
import logging
import os
import time

import requests

LOG = logging.getLogger(__name__)
DEFAULT_TIMEOUT = 5


def load_settings():
    """Settings come from the environment; the token is required."""
    return {
        "port": int(os.environ.get("APP_PORT", "8080")),
        "api_url": os.environ.get("ORDERS_API_URL", "https://api.example.com/v1"),
        "token": os.environ["ORDERS_API_TOKEN"],
        "cache_dir": os.environ.get("ORDERS_CACHE_DIR", "/var/cache/alpha"),
    }


def fetch_orders(settings, status, retries, include_items, customer_ids):
    """Fetch orders, optionally per customer, with naive retries and a disk cache."""
    results = []
    headers = {"Authorization": "Bearer " + settings["token"]}
    targets = customer_ids if customer_ids else [None]
    for customer_id in targets:
        attempt = 0
        while attempt <= retries:
            attempt += 1
            url = settings["api_url"] + "/orders"
            if customer_id is not None:
                url = url + "?customer=" + str(customer_id)
                if status:
                    url = url + "&status=" + status
            elif status:
                url = url + "?status=" + status
            try:
                response = requests.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)
            except requests.RequestException as e:
                LOG.warning("attempt %s failed: %s", attempt, e)
                time.sleep(0.5 * attempt)
                continue
            if response.status_code == 429:
                time.sleep(2)
                continue
            elif response.status_code == 404:
                break
            elif response.status_code >= 500:
                if attempt > retries:
                    raise RuntimeError("upstream unavailable")
                continue
            elif response.status_code != 200:
                raise RuntimeError("unexpected status " + str(response.status_code))
            payload = response.json()
            for order in payload.get("orders", []):
                if not include_items and "items" in order:
                    del order["items"]
                if order.get("total", 0) < 0:
                    LOG.error("negative total for order %s", order.get("id"))
                    continue
                elif order.get("currency") not in ("EUR", "USD"):
                    order["currency"] = "EUR"
                results.append(order)
            # TODO: handle pagination (the API returns at most 100 orders per call)
            break
    try:
        _write_cache(settings["cache_dir"], results)
    except Exception:
        pass
    return results


def _write_cache(cache_dir, orders):
    path = os.path.join(cache_dir, "orders.json")
    with open(path, "w") as handle:
        json.dump(orders, handle)
