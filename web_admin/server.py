# -*- coding: utf-8 -*-
"""Minimal web admin server for config and report management."""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from web_admin.config_schema import CONFIG_SECTIONS, SENSITIVE_TYPES  # noqa: E402
ENV_FILE = ROOT_DIR / ".env"
ENV_EXAMPLE = ROOT_DIR / ".env.example"
REPORTS_DIRS = [ROOT_DIR / "reports"]
FRONTEND_DIST = ROOT_DIR / "web" / "dist"

DEFAULT_PORT = int(os.getenv("WEB_ADMIN_PORT", "8787"))
RUN_LOG_LIMIT = 2000
RUNS: Dict[str, Dict[str, Any]] = {}
RUN_LOCK = threading.Lock()

RUN_COMMANDS = {
    "full": ["python", "main.py"],
    "market-review": ["python", "main.py", "--market-review"],
    "schedule": ["python", "main.py", "--schedule"],
}


def _run_summary(run: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": run["id"],
        "mode": run["mode"],
        "command": run["command"],
        "pid": run["pid"],
        "startedAt": run["startedAt"],
        "status": run["status"],
        "exitCode": run.get("exitCode"),
        "logLines": len(run["logs"]),
        "lastLine": run["logs"][-1]["line"] if run["logs"] else "",
    }


def _append_log(run_id: str, line: str) -> None:
    timestamp = datetime.now().isoformat()
    with RUN_LOCK:
        run = RUNS.get(run_id)
        if not run:
            return
        run["logs"].append({"ts": timestamp, "line": line.rstrip("\n")})
        if len(run["logs"]) > RUN_LOG_LIMIT:
            overflow = len(run["logs"]) - RUN_LOG_LIMIT
            run["logs"] = run["logs"][overflow:]


def _reader_thread(run_id: str, process: subprocess.Popen) -> None:
    try:
        if process.stdout:
            for line in iter(process.stdout.readline, ""):
                if not line:
                    break
                _append_log(run_id, line)
    finally:
        process.wait()
        exit_code = process.returncode
        with RUN_LOCK:
            run = RUNS.get(run_id)
            if run:
                run["status"] = "finished" if exit_code == 0 else "failed"
                run["exitCode"] = exit_code


def _read_env_lines(path: Path) -> Tuple[List[str], Dict[str, str]]:
    if not path.exists():
        return [], {}
    lines = path.read_text(encoding="utf-8").splitlines()
    values: Dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    return lines, values


def _write_env_file(path: Path, updates: Dict[str, str]) -> None:
    lines, _ = _read_env_lines(path)
    if not lines and ENV_EXAMPLE.exists():
        lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()

    updated_keys: set[str] = set()
    new_lines: List[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        key, _ = stripped.split("=", 1)
        key = key.strip()
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            updated_keys.add(key)
        else:
            new_lines.append(line)

    missing = [key for key in updates.keys() if key not in updated_keys]
    if missing:
        new_lines.append("")
        new_lines.append("# === Web Admin Updates ===")
        for key in missing:
            new_lines.append(f"{key}={updates[key]}")

    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def _flatten_schema() -> Dict[str, Dict[str, Any]]:
    lookup: Dict[str, Dict[str, Any]] = {}
    for section in CONFIG_SECTIONS:
        for item in section.get("items", []):
            lookup[item["key"]] = item
    return lookup


def _bool_value(value: str) -> Optional[bool]:
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in {"true", "1", "yes"}:
        return True
    if lowered in {"false", "0", "no"}:
        return False
    return None


def _report_type_from_title(title: str) -> str:
    if "决策仪表盘" in title:
        return "dashboard"
    if "复盘" in title or "大盘" in title:
        return "review"
    if "日报" in title or "分析报告" in title:
        return "daily"
    return "other"


def _extract_report_meta(path: Path) -> Dict[str, Any]:
    title = path.stem
    first_heading = ""
    try:
        with path.open("r", encoding="utf-8") as file:
            for _ in range(10):
                line = file.readline()
                if not line:
                    break
                if line.lstrip().startswith("#"):
                    first_heading = line.strip("# \n\t")
                    break
    except OSError:
        pass

    if first_heading:
        title = first_heading

    date_match = re.search(r"(20\d{2})[-_]?([01]\d)[-_]?([0-3]\d)", path.name)
    report_date = None
    if date_match:
        report_date = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"

    return {
        "path": str(path.relative_to(ROOT_DIR)),
        "title": title,
        "type": _report_type_from_title(first_heading or title),
        "date": report_date,
        "updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
        "size": path.stat().st_size,
    }


def _list_reports() -> List[Dict[str, Any]]:
    reports: List[Dict[str, Any]] = []
    for base in REPORTS_DIRS:
        if not base.exists():
            continue
        for report in base.rglob("*.md"):
            if report.is_file():
                reports.append(_extract_report_meta(report))
    reports.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    return reports


def _resolve_report_path(request_path: str) -> Optional[Path]:
    candidate = (ROOT_DIR / request_path).resolve()
    if not candidate.exists() or candidate.suffix.lower() != ".md":
        return None
    for base in REPORTS_DIRS:
        try:
            if candidate.is_relative_to(base.resolve()):
                return candidate
        except AttributeError:
            base_resolved = base.resolve()
            if str(candidate).startswith(str(base_resolved)):
                return candidate
    return None


class AdminHandler(BaseHTTPRequestHandler):
    server_version = "StockAdmin/0.1"

    def _send_json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, status: int = HTTPStatus.OK) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, path: str) -> None:
        if not FRONTEND_DIST.exists():
            self._send_text("Frontend not built. Run npm install && npm run build in /web.", HTTPStatus.NOT_FOUND)
            return
        requested = path.lstrip("/") or "index.html"
        file_path = (FRONTEND_DIST / requested).resolve()
        if not str(file_path).startswith(str(FRONTEND_DIST.resolve())):
            self._send_text("Invalid path", HTTPStatus.BAD_REQUEST)
            return
        if file_path.is_dir():
            file_path = file_path / "index.html"
        if not file_path.exists():
            # SPA fallback
            file_path = FRONTEND_DIST / "index.html"
        content_type = "text/html; charset=utf-8"
        if file_path.suffix == ".js":
            content_type = "text/javascript; charset=utf-8"
        elif file_path.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif file_path.suffix == ".svg":
            content_type = "image/svg+xml"

        data = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._send_json({"status": "ok"})
            return

        if parsed.path == "/api/reports":
            self._send_json({"reports": _list_reports()})
            return

        if parsed.path == "/api/report":
            query = parse_qs(parsed.query)
            request_path = query.get("path", [""])[0]
            if not request_path:
                self._send_json({"error": "path required"}, HTTPStatus.BAD_REQUEST)
                return
            report_path = _resolve_report_path(request_path)
            if not report_path:
                self._send_json({"error": "report not found"}, HTTPStatus.NOT_FOUND)
                return
            content = report_path.read_text(encoding="utf-8")
            self._send_json({
                "path": str(report_path.relative_to(ROOT_DIR)),
                "content": content,
            })
            return

        if parsed.path == "/api/run":
            with RUN_LOCK:
                runs = sorted(RUNS.values(), key=lambda item: item["startedAt"], reverse=True)
                payload = [_run_summary(run) for run in runs[:20]]
            self._send_json({"runs": payload})
            return

        if parsed.path == "/api/run/logs":
            query = parse_qs(parsed.query)
            run_id = query.get("id", [""])[0]
            cursor = int(query.get("cursor", ["0"])[0])
            if not run_id:
                self._send_json({"error": "id required"}, HTTPStatus.BAD_REQUEST)
                return
            with RUN_LOCK:
                run = RUNS.get(run_id)
                if not run:
                    self._send_json({"error": "run not found"}, HTTPStatus.NOT_FOUND)
                    return
                logs = run["logs"]
                if cursor < 0:
                    cursor = 0
                slice_logs = logs[cursor:]
                next_cursor = cursor + len(slice_logs)
                self._send_json({
                    "logs": slice_logs,
                    "nextCursor": next_cursor,
                    "status": run["status"],
                    "exitCode": run.get("exitCode"),
                })
            return

        if parsed.path == "/api/run/stream":
            query = parse_qs(parsed.query)
            run_id = query.get("id", [""])[0]
            cursor = int(query.get("cursor", ["0"])[0])
            if not run_id:
                self._send_json({"error": "id required"}, HTTPStatus.BAD_REQUEST)
                return

            with RUN_LOCK:
                run = RUNS.get(run_id)
                if not run:
                    self._send_json({"error": "run not found"}, HTTPStatus.NOT_FOUND)
                    return

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            last_status = None
            while True:
                with RUN_LOCK:
                    run = RUNS.get(run_id)
                    if not run:
                        break
                    logs = run["logs"]
                    status = run["status"]
                    exit_code = run.get("exitCode")
                    slice_logs = logs[cursor:]
                    next_cursor = cursor + len(slice_logs)

                payload = {
                    "logs": slice_logs,
                    "cursor": next_cursor,
                    "status": status,
                    "exitCode": exit_code,
                }
                if slice_logs or status != last_status:
                    data = json.dumps(payload, ensure_ascii=False)
                    try:
                        self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        break
                    last_status = status
                else:
                    try:
                        self.wfile.write(b": keep-alive\n\n")
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        break

                cursor = next_cursor
                if status != "running" and cursor >= len(logs):
                    break
                time.sleep(0.5)
            return

        if parsed.path == "/api/config":
            _, values = _read_env_lines(ENV_FILE)
            schema_lookup = _flatten_schema()
            response_values: Dict[str, Any] = {}
            for key, item in schema_lookup.items():
                value = values.get(key, "")
                if item.get("type") in SENSITIVE_TYPES:
                    response_values[key] = {"isSet": bool(value), "value": ""}
                elif item.get("type") == "bool":
                    response_values[key] = _bool_value(value) if value else False
                elif item.get("type") == "number":
                    response_values[key] = float(value) if value else None
                else:
                    response_values[key] = value
            env_updated_at = None
            if ENV_FILE.exists():
                env_updated_at = datetime.fromtimestamp(ENV_FILE.stat().st_mtime).isoformat()
            self._send_json({
                "sections": CONFIG_SECTIONS,
                "values": response_values,
                "envFileExists": ENV_FILE.exists(),
                "envUpdatedAt": env_updated_at,
            })
            return

        self._serve_static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/api/run":
            content_length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(content_length) if content_length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                self._send_json({"error": "invalid json"}, HTTPStatus.BAD_REQUEST)
                return

            mode = payload.get("mode")
            if mode not in RUN_COMMANDS:
                self._send_json({"error": "invalid mode"}, HTTPStatus.BAD_REQUEST)
                return

            command = RUN_COMMANDS[mode]
            run_id = f"run_{int(time.time() * 1000)}"
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            try:
                process = subprocess.Popen(
                    command,
                    cwd=str(ROOT_DIR),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    env=env,
                )
            except OSError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return

            record = {
                "id": run_id,
                "mode": mode,
                "command": " ".join(command),
                "pid": process.pid,
                "startedAt": datetime.now().isoformat(),
                "status": "running",
                "exitCode": None,
                "logs": [],
            }
            with RUN_LOCK:
                RUNS[run_id] = record
            thread = threading.Thread(target=_reader_thread, args=(run_id, process), daemon=True)
            thread.start()
            self._send_json({"run": _run_summary(record)})
            return

        if self.path != "/api/config":
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            self._send_json({"error": "empty body"}, HTTPStatus.BAD_REQUEST)
            return
        raw = self.rfile.read(content_length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json({"error": "invalid json"}, HTTPStatus.BAD_REQUEST)
            return

        incoming = payload.get("values", {})
        clear_secrets = set(payload.get("clearSecrets", []))
        _, existing_values = _read_env_lines(ENV_FILE)
        schema_lookup = _flatten_schema()
        updates: Dict[str, str] = {}

        for key, item in schema_lookup.items():
            if key not in incoming:
                continue
            raw_value = incoming.get(key)
            if item.get("type") in SENSITIVE_TYPES:
                if key in clear_secrets:
                    updates[key] = ""
                    continue
                if raw_value in (None, ""):
                    if key in existing_values:
                        continue
                    updates[key] = ""
                    continue
                updates[key] = str(raw_value)
                continue
            if item.get("type") == "bool":
                updates[key] = "true" if bool(raw_value) else "false"
                continue
            if raw_value is None:
                updates[key] = ""
            else:
                updates[key] = str(raw_value)

        _write_env_file(ENV_FILE, updates)
        self._send_json({"status": "ok"})


def run_server(port: int = DEFAULT_PORT) -> None:
    server_address = ("", port)
    httpd = ThreadingHTTPServer(server_address, AdminHandler)
    print(f"Web admin server running at http://localhost:{port}")
    httpd.serve_forever()


if __name__ == "__main__":
    run_server()
