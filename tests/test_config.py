from pathlib import Path

from zlt import config as cfg


def test_defaults_when_nothing_set(monkeypatch, tmp_path):
    monkeypatch.delenv("ZLT_HOST", raising=False)
    monkeypatch.delenv("ZLT_USERNAME", raising=False)
    monkeypatch.delenv("ZLT_PASSWORD", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.chdir(tmp_path)  # no ./.env
    c = cfg.load_config()
    assert c.host == "http://192.168.0.1"
    assert c.username == "admin"
    assert c.password is None


def test_config_file_read_and_env_overrides(monkeypatch, tmp_path):
    cfgdir = tmp_path / "cfg" / "zlt"
    cfgdir.mkdir(parents=True)
    (cfgdir / "config").write_text(
        'ZLT_HOST=http://10.0.0.1/\nZLT_PASSWORD="secret"\n# comment\n'
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ZLT_HOST", raising=False)
    monkeypatch.delenv("ZLT_PASSWORD", raising=False)
    c = cfg.load_config()
    assert c.host == "http://10.0.0.1"  # trailing slash stripped
    assert c.password == "secret"       # quotes stripped

    monkeypatch.setenv("ZLT_HOST", "http://192.168.8.1")
    assert cfg.load_config().host == "http://192.168.8.1"  # env wins


def test_paths_use_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "c"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "s"))
    assert cfg.config_path() == tmp_path / "c" / "zlt" / "config"
    assert cfg.session_path() == tmp_path / "s" / "zlt" / "session.json"
