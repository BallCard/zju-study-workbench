"""One local worker: simple ordering, bounded results, no overlapping writes."""
from concurrent.futures import ThreadPoolExecutor
import threading
import uuid
from .storage import WorkbenchError


class Jobs:
    def __init__(self):
        self.worker = ThreadPoolExecutor(max_workers=1)
        self.lock = threading.Lock()
        self.items = {}

    def submit(self, title, fn):
        with self.lock:
            active = sum(j["status"] in {"queued", "running"} for j in self.items.values())
            if active >= 8:
                raise WorkbenchError("已有 8 个任务，请等待完成后再添加")
            if len(self.items) >= 60:
                done = [k for k, v in self.items.items() if v["status"] in {"done", "error"}]
                for key in done[:20]:
                    self.items.pop(key)
            jid = uuid.uuid4().hex
            self.items[jid] = {"id": jid, "title": title, "status": "queued"}

        def execute():
            with self.lock:
                self.items[jid]["status"] = "running"
            try:
                result = fn()
                update = {"status": "done", "result": result}
            except WorkbenchError as exc:
                update = {"status": "error", "error": str(exc)}
            except Exception:
                update = {"status": "error", "error": "操作失败，请检查输入、依赖或终端环境；原始错误不包含在界面中"}
            with self.lock:
                self.items[jid].update(update)
        self.worker.submit(execute)
        return {"job_id": jid}

    def snapshot(self):
        with self.lock:
            return [dict(j) for j in self.items.values()][-60:]
