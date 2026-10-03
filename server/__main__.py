"""A loopback-only HTTP service, built static UI and small explicit JSON routes."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import secrets
from urllib.parse import urlparse, unquote
from .storage import Store, WorkbenchError, safe_path
from .library import Library, seed_demo
from .jobs import Jobs
from . import ai, scholar, git_history, tex

PROJECT = Path(__file__).resolve().parents[1]


def create_server(store, port=8765):
    library, jobs = Library(store), Jobs()
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # Avoid URLs, filenames, school content and tokens in request logs.

        def send(self, status, content, mime="application/json; charset=utf-8", cookie=False):
            body = content if isinstance(content, bytes) else json.dumps(content, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            ancestors = "'self'" if mime == "application/pdf" else "'none'"
            self.send_header("Content-Security-Policy", f"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; frame-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors {ancestors}")
            if cookie:
                self.send_header("Set-Cookie", f"workbench={token}; HttpOnly; SameSite=Strict; Path=/")
            self.end_headers()
            self.wfile.write(body)

        def authorized(self, mutate=False):
            port = self.server.server_address[1]
            hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
            if self.headers.get("Host") not in hosts:
                raise WorkbenchError("拒绝非本机主机名")
            if mutate:
                if not secrets.compare_digest(self.headers.get("X-Workbench-Token", ""), token):
                    raise WorkbenchError("页面会话失效，请刷新")
                origin = self.headers.get("Origin")
                if origin and origin not in {f"http://{h}" for h in hosts}:
                    raise WorkbenchError("拒绝跨站写入")
            if unquote(urlparse(self.path).path).startswith("/api/") and f"workbench={token}" not in self.headers.get("Cookie", "").split("; "):
                raise WorkbenchError("请先打开本机工作台")

        def do_GET(self):
            try:
                self.authorized()
                path = unquote(urlparse(self.path).path)
                if path == "/api/state":
                    data = store.snapshot()
                    try:
                        data["library"] = library.scan()
                        data["git"] = git_history.history(store.root())
                    except WorkbenchError as exc:
                        data["library"] = {"courses": [], "lessons": [], "files": []}
                        data["git"] = {"available": False, "commits": []}
                        data["library_error"] = str(exc)
                    data.update(demo=store.demo, jobs=jobs.snapshot())
                    self.send(200, data)
                elif path == "/api/jobs":
                    self.send(200, jobs.snapshot())
                elif path.startswith("/api/note/"):
                    lid = path.rsplit("/", 1)[-1]
                    self.send(200, {"draft": library.draft(lid), "note": library.note(lid)})
                elif path.startswith("/api/text/"):
                    self.send(200, {"text": library.extract(path.rsplit("/", 1)[-1])})
                elif path.startswith("/api/pdf/"):
                    lesson = library.lesson(path.rsplit("/", 1)[-1])
                    file = safe_path(store.root(), f"{lesson['relative']}/notes.pdf")
                    if not file.is_file():
                        raise WorkbenchError("没有已编译的笔记 PDF")
                    self.send(200, file.read_bytes(), "application/pdf")
                elif path.startswith("/api/file/"):
                    file, info = library.file(path.rsplit("/", 1)[-1])
                    if info["size"] > 60*1024*1024:
                        raise WorkbenchError("文件较大，请使用界面显示的位置在本地查看")
                    mime = "application/pdf" if info["suffix"] == ".pdf" else "text/plain; charset=utf-8" if info["suffix"] in {".txt", ".md", ".tex", ".srt", ".vtt"} else "application/octet-stream"
                    self.send(200, file.read_bytes(), mime)
                else:
                    target = safe_path(PROJECT / "dist", path.lstrip("/") or "index.html")
                    if not target.is_file():
                        self.send(404, {"error": "界面尚未构建，请执行 npm run build"})
                        return
                    body = target.read_bytes()
                    if target.name == "index.html":
                        body = body.replace(b"__WORKBENCH_TOKEN__", token.encode())
                    self.send(200, body, mimetypes.guess_type(target.name)[0] or "application/octet-stream", cookie=target.name == "index.html")
            except WorkbenchError as exc:
                self.send(400, {"error": str(exc)})
            except Exception:
                self.send(500, {"error": "读取失败，请检查文件或依赖"})

        def do_POST(self):
            try:
                self.authorized(mutate=True)
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 2*1024*1024:
                    raise WorkbenchError("请求长度无效")
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict):
                    raise WorkbenchError("请求格式无效")
                action = urlparse(self.path).path
                if action not in {"/api/generate", "/api/scholar", "/api/compile"} and any(j["status"] in {"running", "queued"} for j in jobs.snapshot()):
                    raise WorkbenchError("后台任务进行中，请完成后再改变目录、参考资料或正文")
                lid = str(body.get("lesson_id", ""))
                if action == "/api/settings":
                    allowed = set(store.settings())
                    settings = {k: str(v) for k, v in body.items() if k in allowed}
                    if any(len(v) > 2000 for v in settings.values()):
                        raise WorkbenchError("设置内容过长")
                    if body.get("api_key"):
                        ai.save_api_key(store, str(body["api_key"]))
                    store.update(lambda s: s["settings"].update(settings))
                    result = {"saved": True}
                elif action == "/api/select":
                    library.select(lid, body.get("selected", []), body.get("ranges", {}))
                    result = {"saved": True}
                elif action == "/api/create-lesson":
                    result = library.create_lesson(str(body.get("course_id", "")), body.get("title", ""))
                elif action == "/api/import":
                    result = library.import_reference(str(body.get("file_id", "")), lid)
                elif action == "/api/lesson":
                    lesson = library.lesson(lid)
                    status = body.get("status", "")
                    if status and status not in {"empty", "draft", "review", "done"}:
                        raise WorkbenchError("笔记阶段无效")
                    changes = {k: body[k] for k in ("status", "sub_id", "missing") if k in body}
                    if "sub_id" in changes and (not isinstance(changes["sub_id"], str) or len(changes["sub_id"]) > 100):
                        raise WorkbenchError("录像 ID 无效")
                    if "missing" in changes and (not isinstance(changes["missing"], dict) or any(k not in {"教师课件", "智云 PPT", "手写笔记"} or v not in {"unknown", "none", "pending"} for k, v in changes["missing"].items())):
                        raise WorkbenchError("资料缺口记录无效")
                    store.update(lambda s: s["lessons"].setdefault(lid, {}).update(changes))
                    mapping = {k: str(body[k]) for k in ("course_id", "zhiyun_id") if k in body}
                    store.update(lambda s: s["courses"].setdefault(lesson["course_id"], {}).update(mapping))
                    result = {"saved": True}
                elif action == "/api/draft":
                    library.put_draft(lid, body.get("text", ""), body.get("format", "md"))
                    result = {"saved": True}
                elif action == "/api/save":
                    file = library.save(lid, body.get("text", ""), body.get("format", "md"))
                    result = {"saved": True}
                    if body.get("commit"):
                        result["git"] = git_history.commit_note(store.root(), file, lid)
                elif action == "/api/generate":
                    library.lesson(lid)
                    result = jobs.submit("整理电子笔记", lambda: ai.generate(store, library, lid, str(body.get("route", "api")), str(body.get("instruction", ""))[:8000], str(body.get("format", "md"))))
                elif action == "/api/compile":
                    library.lesson(lid)
                    result = jobs.submit("编译笔记 PDF", lambda: tex.compile_note(store, library, lid))
                elif action == "/api/scholar":
                    library.lesson(lid)
                    result = jobs.submit("学校资料与作业", lambda: scholar.run(store, library, str(body.get("action", "")), lid))
                else:
                    self.send(404, {"error": "接口不存在"})
                    return
                self.send(200, result)
            except (WorkbenchError, ValueError) as exc:
                self.send(400, {"error": str(exc) if isinstance(exc, WorkbenchError) else "请求格式无效"})
            except Exception:
                self.send(500, {"error": "操作失败，请检查本机环境；正文和凭据未输出"})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.jobs = jobs
    return server


def main():
    parser = argparse.ArgumentParser(description="ZJU Study Workbench · local server")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", type=Path, default=Path.home() / ".zju-study-workbench")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--open", action="store_true", help="open the local UI in your default browser")
    args = parser.parse_args()
    directory = args.data_dir / "demo" if args.demo else args.data_dir
    store = Store(directory, demo=args.demo)
    if args.demo:
        seed_demo(store)
    server = create_server(store, args.port)
    print(f"http://127.0.0.1:{server.server_address[1]}", flush=True)
    if args.open:
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{server.server_address[1]}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        server.jobs.worker.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    main()
