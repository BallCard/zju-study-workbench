"""Optional local XeLaTeX: private intermediates, preserve the last working PDF."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid
from .storage import WorkbenchError, safe_path


def compile_note(store, library, lid):
    lesson = library.lesson(lid)
    if lesson["note_file"] != "notes.tex" or not lesson["has_note"]:
        raise WorkbenchError("请先保存 LaTeX 正式笔记，再编译")
    executable = shutil.which("xelatex")
    if not executable:
        raise WorkbenchError("未找到 XeLaTeX；请安装 TeX Live / MiKTeX 并加入 PATH")
    source = safe_path(store.root(), f"{lesson['relative']}/notes.tex")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="tex-", dir=store.directory) as directory:
        command = [executable, "-no-shell-escape", "-halt-on-error", "-interaction=nonstopmode", "-output-directory", directory, "notes.tex"]
        try:
            for _ in range(2):
                result = subprocess.run(command, cwd=source.parent, capture_output=True, timeout=120)
                if result.returncode:
                    # Logs may contain private source. Preserve locally, never put them in jobs/API.
                    log = Path(directory) / "notes.log"
                    if log.is_file():
                        shutil.copy2(log, store.directory / "last-compile.log")
                    raise WorkbenchError("编译失败，原 PDF 保留；诊断在私有状态目录 last-compile.log")
        except subprocess.TimeoutExpired:
            raise WorkbenchError("编译超时，原 PDF 保留") from None
        output = Path(directory) / "notes.pdf"
        if not output.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise WorkbenchError("未生成 PDF 或编译期间源稿改变，原 PDF 保留")
        target = safe_path(store.root(), f"{lesson['relative']}/notes.pdf")
        if target.exists():
            library.backup(target, lid, "pdf")
        staged = source.parent / f".notes.pdf.{uuid.uuid4().hex}.tmp"
        try:
            with staged.open("xb") as handle:
                handle.write(output.read_bytes())
            os.replace(staged, target)
        finally:
            staged.unlink(missing_ok=True)
    store.update(lambda s: s["lessons"].setdefault(lid, {}).update(pdf_source_hash=digest))
    return {"lesson_id": lid, "compiled": True, "message": "双遍编译完成，请打开 PDF 核对排版。"}
