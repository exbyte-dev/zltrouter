import json
import os

from zlt.config import ussd_store_path


def load_codes() -> list[dict]:
    try:
        data = json.loads(ussd_store_path().read_text())
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if isinstance(item, dict) and "label" in item and "code" in item:
            out.append({"label": str(item["label"]), "code": str(item["code"])})
    return out


def save_code(label: str, code: str) -> None:
    label, code = label.strip(), code.strip()
    codes = load_codes()
    for c in codes:
        if c["label"].lower() == label.lower():
            c["label"], c["code"] = label, code
            break
    else:
        codes.append({"label": label, "code": code})
    _write(codes)


def remove_code(label: str) -> bool:
    label = label.strip()
    codes = load_codes()
    kept = [c for c in codes if c["label"].lower() != label.lower()]
    if len(kept) == len(codes):
        return False
    _write(kept)
    return True


def _write(codes: list[dict]) -> None:
    path = ussd_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(codes, indent=2))
