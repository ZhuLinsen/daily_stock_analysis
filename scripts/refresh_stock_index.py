#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Refresh local stock autocomplete index assets.

Default flow:
1. Fetch Tushare stock lists into ``data/`` with ``--a-rk`` for A-share name correction.
2. Generate ``apps/dsa-web/public/stocks.index.json`` from CSV plus JP/KR seed rows.
3. Copy the generated index to ``static/stocks.index.json`` for backend use.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_INDEX_PATH = REPO_ROOT / "apps" / "dsa-web" / "public" / "stocks.index.json"
STATIC_INDEX_PATH = REPO_ROOT / "static" / "stocks.index.json"


def _run(command: Sequence[str]) -> None:
    print(f"[refresh_stock_index] $ {' '.join(command)}", flush=True)
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    subprocess.run(command, cwd=REPO_ROOT, check=True, env=env)


def _has_tushare_token() -> bool:
    env_path = REPO_ROOT / ".env"
    try:
        from dotenv import load_dotenv  # type: ignore
    except ImportError:
        if env_path.is_file():
            for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                key, sep, value = line.partition("=")
                if sep and key.strip() == "TUSHARE_TOKEN" and value.strip().strip("'\""):
                    return True
        return bool(os.getenv("TUSHARE_TOKEN", "").strip())

    load_dotenv(env_path)
    return bool(os.getenv("TUSHARE_TOKEN", "").strip())


def _sync_static_index() -> None:
    if not WEB_INDEX_PATH.is_file():
        raise FileNotFoundError(f"generated Web index not found: {WEB_INDEX_PATH}")
    STATIC_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(WEB_INDEX_PATH, STATIC_INDEX_PATH)
    print(f"[refresh_stock_index] synced {WEB_INDEX_PATH} -> {STATIC_INDEX_PATH}", flush=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="刷新股票自动补全索引")
    parser.add_argument(
        "--skip-fetch",
        action="store_true",
        help="跳过 Tushare 抓取，仅用现有 data/stock_list_*.csv 重新生成索引",
    )
    args = parser.parse_args(argv)

    try:
        if args.skip_fetch:
            print("[refresh_stock_index] skip Tushare fetch; using existing CSV files")
        else:
            if not _has_tushare_token():
                print(
                    "[refresh_stock_index] ERROR: missing TUSHARE_TOKEN. "
                    "Set it in .env or environment, or rerun with --skip-fetch.",
                    file=sys.stderr,
                )
                return 2
            _run([sys.executable, "scripts/fetch_tushare_stock_list.py", "--a-rk"])

        _run([sys.executable, "scripts/generate_index_from_csv.py", "--source", "tushare"])
        _sync_static_index()

    except subprocess.CalledProcessError as exc:
        print(
            f"[refresh_stock_index] ERROR: command failed with exit code {exc.returncode}",
            file=sys.stderr,
        )
        return exc.returncode or 1
    except (OSError, RuntimeError) as exc:
        print(f"[refresh_stock_index] ERROR: {exc}", file=sys.stderr)
        return 1

    print("[refresh_stock_index] done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
