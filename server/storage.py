"""Atomic private state and strictly rooted file operations."""
import copy
import json
import os
from pathlib import Path
import threading
import uuid


class WorkbenchError(Exception):
    pass


def safe_path(root, relative=""):
    root = Path(root).absolute()
    path = root / relative
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise WorkbenchError("路径必须位于已配置的资料库内")
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        raise WorkbenchError("路径超出资料库") from None
    # Check every ancestor, including Windows junctions.
    for part in [path, *path.parents]:
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise WorkbenchError("资料路径不能使用符号链接或 junction")
    return path


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(text, encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


class Store:
    def __init__(self, directory, demo=False):
        self.directory = Path(directory).absolute()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.file = self.directory / "state.json"
        self.lock = threading.RLock()
        self.data = json.loads(self.file.read_text(encoding="utf-8")) if self.file.exists() else {
            "version": 1, "settings": {"notes_root": "", "downloads_root": "", "scholar_root": "", "scholar_python": "", "api_base": "http://127.0.0.1:8045/v1", "api_model": "gemini-3.8-flash", "pi_model": "", "codex_model": ""},
            "lessons": {}, "courses": {}, "assignments": {},
        }
        self.demo = demo

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.data)

    def update(self, fn):
        with self.lock:
            result = fn(self.data)
            atomic_text(self.file, json.dumps(self.data, ensure_ascii=False, indent=2))
            return result

    def settings(self):
        return self.snapshot()["settings"]

    def root(self):
        value = self.settings()["notes_root"]
        if not value or not Path(value).is_dir():
            raise WorkbenchError("请在设置中填写存在的笔记根目录")
        return safe_path(value)
