import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_HOST = "http://192.168.0.1"
DEFAULT_USERNAME = "admin"

# Speed-test target. The browser measures against this directly, so it has to be
# a public host that sends CORS headers; Cloudflare's speed backend does.
DEFAULT_SPEEDTEST_DOWN_URL = "https://speed.cloudflare.com/__down"
DEFAULT_SPEEDTEST_UP_URL = "https://speed.cloudflare.com/__up"
DEFAULT_SPEEDTEST_DOWN_BYTES = 25_000_000
DEFAULT_SPEEDTEST_UP_BYTES = 8_000_000


@dataclass
class Config:
    host: str
    username: str
    password: str | None


@dataclass
class SpeedtestConfig:
    down_url: str
    up_url: str
    down_bytes: int
    up_bytes: int


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


def _resolver():
    """Key lookup with the standard precedence: environment > ~/.config/zlt/config > ./.env."""
    file_data = _parse_env_file(Path(".env"))
    file_data.update(_parse_env_file(config_path()))

    def resolve(key: str, default: str | None = None) -> str | None:
        return os.environ.get(key) or file_data.get(key) or default

    return resolve


def load_speedtest_config() -> SpeedtestConfig:
    resolve = _resolver()

    def as_int(key: str, default: int) -> int:
        # A typo in the config should not take the panel down, so fall back
        # rather than raise. Non-positive sizes would make the test divide by
        # an elapsed time it never spent, so they fall back too.
        try:
            value = int(resolve(key, "") or "")
        except ValueError:
            return default
        return value if value > 0 else default

    return SpeedtestConfig(
        down_url=resolve("ZLT_SPEEDTEST_DOWN_URL", DEFAULT_SPEEDTEST_DOWN_URL)
        or DEFAULT_SPEEDTEST_DOWN_URL,
        up_url=resolve("ZLT_SPEEDTEST_UP_URL", DEFAULT_SPEEDTEST_UP_URL)
        or DEFAULT_SPEEDTEST_UP_URL,
        down_bytes=as_int("ZLT_SPEEDTEST_DOWN_BYTES", DEFAULT_SPEEDTEST_DOWN_BYTES),
        up_bytes=as_int("ZLT_SPEEDTEST_UP_BYTES", DEFAULT_SPEEDTEST_UP_BYTES),
    )


def load_config() -> Config:
    resolve = _resolver()
    host = resolve("ZLT_HOST", DEFAULT_HOST) or DEFAULT_HOST
    return Config(
        host=host.rstrip("/"),
        username=resolve("ZLT_USERNAME", DEFAULT_USERNAME) or DEFAULT_USERNAME,
        password=resolve("ZLT_PASSWORD"),
    )
