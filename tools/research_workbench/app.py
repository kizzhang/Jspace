"""HTTP server for the local JSpace research workbench."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import threading
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from workbench import ResearchIndex


HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"


class WorkbenchServer(HTTPServer):
    def __init__(self, address: tuple[str, int], index: ResearchIndex):
        super().__init__(address, WorkbenchHandler)
        self.index = index


class WorkbenchHandler(BaseHTTPRequestHandler):
    server: WorkbenchServer

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message: str, status: int = 400) -> None:
        self._json({"ok": False, "error": message}, status)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("请求内容不是有效 JSON。") from error

    def _static(self, path: Path) -> None:
        try:
            resolved = path.resolve()
            if STATIC not in resolved.parents and resolved != STATIC:
                raise FileNotFoundError
            body = resolved.read_bytes()
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        path = parsed.path
        try:
            if path == "/":
                return self._static(STATIC / "index.html")
            if path.startswith("/static/"):
                return self._static(STATIC / path.removeprefix("/static/"))
            if path == "/api/dashboard":
                return self._json(self.server.index.dashboard(self._one(query, "day")))
            if path == "/api/sessions":
                return self._json(
                    self.server.index.list_sessions(
                        self._one(query, "q") or "", self._one(query, "provider") or ""
                    )
                )
            if path.startswith("/api/sessions/"):
                session_id = urllib.parse.unquote(path.removeprefix("/api/sessions/"))
                item = self.server.index.get_session(session_id)
                return self._json(item) if item else self._error("找不到该对话。", 404)
            if path == "/api/experiments":
                return self._json(
                    self.server.index.list_experiments(
                        self._one(query, "q") or "", self._one(query, "status") or ""
                    )
                )
            if path == "/api/papers":
                return self._json(
                    self.server.index.list_papers(
                        self._one(query, "q") or "", self._one(query, "status") or ""
                    )
                )
            match = re.fullmatch(r"/api/papers/(\d+)", path)
            if match:
                return self._json(self.server.index.get_paper(int(match.group(1))))
            if re.fullmatch(r"/api/pdf/\d+", path):
                return self._pdf(int(path.rsplit("/", 1)[1]))
            return self.send_error(HTTPStatus.NOT_FOUND)
        except (ValueError, KeyError) as error:
            self._error(str(error), 404 if isinstance(error, KeyError) else 400)
        except Exception as error:  # local app: return an actionable error
            self._error(f"工作台读取失败：{error}", 500)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        try:
            body = self._body()
            if parsed.path == "/api/sync":
                return self._json(self.server.index.sync_all(refresh_papers=True))
            if parsed.path == "/api/papers":
                item = self.server.index.register_paper(
                    title=str(body.get("title") or ""),
                    doi=str(body.get("doi") or ""),
                    arxiv_id=str(body.get("arxiv_id") or ""),
                    pdf_path=str(body.get("pdf_path") or ""),
                    source_url=str(body.get("source_url") or ""),
                    note=str(body.get("note") or ""),
                    status=str(body.get("status") or "inbox"),
                    refresh=bool(body.get("refresh", True)),
                )
                self.server.index.build_digest(__import__("datetime").date.today().isoformat())
                return self._json({"ok": True, "paper": item}, 201)
            match = re.fullmatch(r"/api/papers/(\d+)/refresh", parsed.path)
            if match:
                row = self.server.index.get_paper(int(match.group(1)))
                item = self.server.index.register_paper(
                    title=row["title"], doi=row["doi"], arxiv_id=row["arxiv_id"],
                    pdf_path=row["pdf_path"], source_url=row["source_url"],
                    authors=row["authors"], year=row["year"], abstract=row["abstract"],
                    status=row["status"], note=row["note"], refresh=True,
                )
                return self._json({"ok": True, "paper": item})
            return self.send_error(HTTPStatus.NOT_FOUND)
        except (ValueError, KeyError) as error:
            self._error(str(error), 400)
        except Exception as error:
            self._error(f"工作台更新失败：{error}", 500)

    def do_PATCH(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        try:
            body = self._body()
            match = re.fullmatch(r"/api/(papers|experiments|sessions)/(.+)", parsed.path)
            if match:
                table, raw_id = match.groups()
                identifier: Any = int(raw_id) if table == "papers" else urllib.parse.unquote(raw_id)
                self.server.index.update_note(
                    table, identifier, str(body.get("note") or ""), body.get("status")
                )
                return self._json({"ok": True})
            match = re.fullmatch(r"/api/digests/(\d{4}-\d{2}-\d{2})", parsed.path)
            if match:
                item = self.server.index.update_digest_note(
                    match.group(1), str(body.get("manual_note") or "")
                )
                return self._json({"ok": True, "digest": item})
            return self.send_error(HTTPStatus.NOT_FOUND)
        except (ValueError, KeyError) as error:
            self._error(str(error), 400)
        except Exception as error:
            self._error(f"保存失败：{error}", 500)

    @staticmethod
    def _one(query: dict[str, list[str]], key: str) -> str | None:
        values = query.get(key)
        return values[0] if values else None

    def _pdf(self, paper_id: int) -> None:
        paper = self.server.index.get_paper(paper_id)
        path = Path(paper["pdf_path"])
        if not path.exists() or path.suffix.lower() != ".pdf":
            return self._error("这条记录还没有可预览的本地 PDF。", 404)
        size = path.stat().st_size
        start, end = 0, size - 1
        status = 200
        range_header = self.headers.get("Range")
        if range_header:
            match = re.match(r"bytes=(\d*)-(\d*)", range_header)
            if match:
                if match.group(1):
                    start = int(match.group(1))
                if match.group(2):
                    end = min(int(match.group(2)), size - 1)
                status = 206
        length = max(0, end - start + 1)
        self.send_response(status)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining:
                block = handle.read(min(1024 * 1024, remaining))
                if not block:
                    break
                self.wfile.write(block)
                remaining -= len(block)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="JSpace local research workbench")
    parser.add_argument("--workspace", type=Path, default=HERE.parents[1])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7331)
    parser.add_argument("--sync-only", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    index = ResearchIndex(args.workspace)
    print("正在整理研究记录…")
    result = index.sync_all(refresh_papers=True)
    print(json.dumps(result, ensure_ascii=False))
    if args.sync_only:
        index.close()
        return 0
    server = WorkbenchServer((args.host, args.port), index)
    url = f"http://{args.host}:{args.port}"
    print(f"科研工作台已启动：{url}")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        index.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
