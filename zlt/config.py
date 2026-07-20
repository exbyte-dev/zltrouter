import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_HOST = "http://192.168.0.1"
DEFAULT_USERNAME = "admin"


@dataclass
class Config:
    host: str
    username: str
    password: str | None


def config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))


def _state_home() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))


def config_path() -> Path:
    return config_home() / "zlt" / "config"


def session_path() -> Path:
    return _state_home() / "zlt" / "session.json"


def ussd_store_path() -> Path:
    return config_home() / "zlt" / "ussd.json"


def _parse_env_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    try:
        text = path.read_text()
    except OSError:
        return data
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def load_config() -> Config:
    # Precedence: environment > ~/.config/zlt/config > ./.env
    file_data = _parse_env_file(Path(".env"))
    file_data.update(_parse_env_file(config_path()))

    def resolve(key: str, default: str | None = None) -> str | None:
        return os.environ.get(key) or file_data.get(key) or default

    host = resolve("ZLT_HOST", DEFAULT_HOST) or DEFAULT_HOST
    return Config(
        host=host.rstrip("/"),
        username=resolve("ZLT_USERNAME", DEFAULT_USERNAME) or DEFAULT_USERNAME,
        password=resolve("ZLT_PASSWORD"),
    )
