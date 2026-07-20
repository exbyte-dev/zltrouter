from zlt import ussd_store
from zlt.config import ussd_store_path


def _use_tmp(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))


def test_load_missing_file_is_empty(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    assert ussd_store.load_codes() == []


def test_save_then_load_roundtrip(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    ussd_store.save_code("Check balance", "*310#")
    assert ussd_store.load_codes() == [{"label": "Check balance", "code": "*310#"}]
    assert oct(ussd_store_path().stat().st_mode)[-3:] == "600"


def test_save_upserts_by_case_insensitive_label(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    ussd_store.save_code("Balance", "*310#")
    ussd_store.save_code("balance", "*311#")
    assert ussd_store.load_codes() == [{"label": "balance", "code": "*311#"}]


def test_save_upsert_preserves_order(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    ussd_store.save_code("A", "x")
    ussd_store.save_code("B", "y")
    ussd_store.save_code("a", "z")
    assert ussd_store.load_codes() == [
        {"label": "a", "code": "z"},
        {"label": "B", "code": "y"},
    ]


def test_remove_returns_whether_removed(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    ussd_store.save_code("Balance", "*310#")
    assert ussd_store.remove_code("balance") is True
    assert ussd_store.remove_code("nope") is False
    assert ussd_store.load_codes() == []


def test_corrupt_file_is_empty(monkeypatch, tmp_path):
    _use_tmp(monkeypatch, tmp_path)
    path = ussd_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json")
    assert ussd_store.load_codes() == []
