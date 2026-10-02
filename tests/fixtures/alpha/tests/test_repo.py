from app.repo import normalize_rows


def test_normalize_rows_skips_blank_ids():
    assert normalize_rows([{"id": " ", "total": 1}, {"id": "a", "customer": "ACME", "total": "2.5"}]) == [("a", "acme", 2.5, "EUR")]
