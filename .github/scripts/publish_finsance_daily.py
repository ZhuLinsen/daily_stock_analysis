#!/usr/bin/env python3
"""Copy the validated public daily artifact into a Finsance checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "finsance-quanttrade-daily-v1"
FORBIDDEN_KEYS = {
    "battle_plan",
    "current_price",
    "market_snapshot",
    "raw_response",
    "sniper_points",
    "stop_loss",
    "take_profit",
    "entry_low",
    "entry_high",
    "target_price",
}


def _contains_forbidden(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in FORBIDDEN_KEYS:
                return str(key)
            found = _contains_forbidden(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _contains_forbidden(child)
            if found:
                return found
    return None


def _read_payload(source_dir: Path) -> tuple[dict[str, Any], bytes]:
    latest = source_dir / "daily_latest.json"
    if not latest.is_file():
        raise ValueError(f"missing public export: {latest}")
    data = latest.read_bytes()
    checksum = source_dir / "daily_latest.json.sha256"
    if not checksum.is_file():
        raise ValueError("daily_latest.json checksum is missing")
    expected = checksum.read_text(encoding="utf-8").split()[0]
    actual = hashlib.sha256(data).hexdigest()
    if expected != actual:
        raise ValueError("daily_latest.json checksum mismatch")
    payload = json.loads(data.decode("utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported public export schema")
    if not isinstance(payload.get("date"), str) or not payload["date"]:
        raise ValueError("public export date is missing")
    stocks = payload.get("stocks")
    if not isinstance(stocks, list) or not stocks:
        raise ValueError("public export contains no stocks")
    forbidden = _contains_forbidden(payload)
    if forbidden:
        raise ValueError(f"private field is not publishable: {forbidden}")
    return payload, data


def _copy_with_checksum(source: Path, destination: Path) -> None:
    data = source.read_bytes()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    destination.with_name(f"{destination.name}.sha256").write_text(
        f"{digest}  {destination.name}\n",
        encoding="utf-8",
    )

def _read_checked(path: Path) -> bytes:
    data = path.read_bytes()
    checksum_path = path.with_name(f"{path.name}.sha256")
    if not checksum_path.is_file():
        raise ValueError(f"{path.name} checksum is missing")
    expected = checksum_path.read_text(encoding="utf-8").split()[0]
    if expected != hashlib.sha256(data).hexdigest():
        raise ValueError(f"{path.name} checksum mismatch")
    return data


def publish(
    source_dir: Path,
    destination_dir: Path,
    *,
    render_trigger: Path | None = None,
) -> list[Path]:
    payload, latest_data = _read_payload(source_dir)
    date_name = f"daily_{payload['date']}.json"
    versioned_source = source_dir / date_name
    if not versioned_source.is_file():
        raise ValueError(f"missing immutable public export: {versioned_source}")
    _read_checked(versioned_source)
    _copy_with_checksum(versioned_source, destination_dir / date_name)
    latest_path = destination_dir / "daily_latest.json"
    destination_dir.mkdir(parents=True, exist_ok=True)
    latest_path.write_bytes(latest_data)
    latest_digest = hashlib.sha256(latest_data).hexdigest()
    latest_path.with_name(f"{latest_path.name}.sha256").write_text(
        f"{latest_digest}  {latest_path.name}\n",
        encoding="utf-8",
    )
    paths = [destination_dir / date_name, latest_path]
    if render_trigger:
        render_trigger.parent.mkdir(parents=True, exist_ok=True)
        render_trigger.write_text(
            f"date={payload['date']}\nsha256={latest_digest}\n",
            encoding="utf-8",
        )
        paths.append(render_trigger)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--render-trigger", type=Path)
    args = parser.parse_args()
    paths = publish(
        args.source,
        args.destination,
        render_trigger=args.render_trigger,
    )
    print("Published Finsance daily artifact:")
    for path in paths:
        print(f"- {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
