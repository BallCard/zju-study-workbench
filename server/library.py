"""Course/lesson discovery, selected-source extraction, drafts and note saves."""
import hashlib
from pathlib import Path
import shutil
import re
from datetime import datetime, timezone
from .storage import WorkbenchError, safe_path, atomic_text

SUPPORTED = {".pdf", ".txt", ".md", ".tex", ".ppt", ".pptx", ".docx", ".mp4", ".srt", ".vtt", ".png", ".jpg", ".jpeg"}


def identifier(relative):
    return hashlib.sha256(relative.encode("utf-8")).hexdigest()[:20]


class Library:
    def __init__(self, store):
        self.store = store

    def scan(self):
        settings = self.store.settings()
        collections = [self._scan_root(self.store.root(), "notes")]
        downloads = settings.get("downloads_root", "")
        if downloads and Path(downloads).is_dir() and Path(downloads).resolve() != self.store.root().resolve():
            collections.append(self._scan_root(safe_path(downloads), "downloads"))
        courses, lessons, files = {}, {}, {}
        state = self.store.snapshot()
        for collection in collections:
            courses.update({c["id"]: c for c in collection["courses"]})
            files.update({f["id"]: f for f in collection["files"]})
            for lesson in collection["lessons"]:
                if lesson["id"] in lessons:
                    previous = lessons[lesson["id"]]
                    previous["files"] += lesson["files"]
                    previous["has_note"] |= lesson["has_note"]
                    previous["has_pdf"] |= lesson["has_pdf"]
                else:
                    lessons[lesson["id"]] = lesson
        for lesson in lessons.values():
            lesson["selected"] = [fid for fid in state["lessons"].get(lesson["id"], {}).get("selected", []) if fid in lesson["files"]]
        return {"courses": list(courses.values()), "lessons": list(lessons.values()), "files": list(files.values())}

    def _scan_root(self, root, alias):
        state = self.store.snapshot()
        base = safe_path(root, "courses")
        courses, lessons, files = [], [], {}
        if not base.is_dir():
            return {"courses": [], "lessons": [], "files": []}
        for course in sorted(base.iterdir()):
            if not course.is_dir() or course.name.startswith("."):
                continue
            safe_path(root, course.relative_to(root))
            cid = identifier(course.relative_to(root).as_posix())
            courses.append({"id": cid, "title": course.name, **state["courses"].get(cid, {})})
            dirs = [course]
            dirs += [p for p in sorted(course.iterdir()) if p.is_dir() and p.name not in {"materials", "assignments", "topics"} and not p.name.startswith(".")]
            for group in ("assignments", "topics"):
                folder = safe_path(root, course.relative_to(root) / group)
                if folder.is_dir():
                    dirs += [p for p in sorted(folder.iterdir()) if p.is_dir() and not p.name.startswith(".")]
            for folder in dirs:
                rel = folder.relative_to(root).as_posix()
                safe_path(root, rel)
                lid = identifier(rel)
                meta = state["lessons"].get(lid, {})
                tex, md, pdf = (safe_path(root, f"{rel}/notes{suffix}") for suffix in (".tex", ".md", ".pdf"))
                preferred = meta.get("note_format")
                filename = f"notes.{preferred}" if preferred in {"md", "tex"} and safe_path(root, f"{rel}/notes.{preferred}").is_file() else "notes.tex" if tex.is_file() else "notes.md"
                lesson_files = []
                materials = safe_path(root, f"{rel}/materials")
                if materials.is_dir():
                    for file in sorted(materials.rglob("*")):
                        if len(files) >= 3000:
                            raise WorkbenchError("资料超过 3000 件，请分库管理")
                        relative = file.relative_to(root).as_posix()
                        safe_path(root, relative)
                        if file.is_file() and file.suffix.lower() in SUPPORTED:
                            fid = identifier(f"{alias}:{relative}")
                            item = {"id": fid, "root": alias, "lesson_id": lid, "course_id": cid, "relative": relative, "name": file.name, "suffix": file.suffix.lower(), "size": file.stat().st_size, "range": meta.get("ranges", {}).get(fid, ""), "status": "available"}
                            files[fid] = item
                            lesson_files.append(fid)
                if folder == course and not lesson_files and not tex.is_file() and not md.is_file():
                    continue
                lessons.append({"id": lid, "course_id": cid, "relative": rel, "title": "课程通用资料" if folder == course else folder.name, "note_file": filename, "has_note": tex.is_file() or md.is_file(), "has_pdf": pdf.is_file(), "status": meta.get("status", "review" if tex.is_file() or md.is_file() else "empty"), "selected": [fid for fid in meta.get("selected", []) if fid in files], "missing": meta.get("missing", {}), "files": lesson_files, "sub_id": meta.get("sub_id", "")})
        return {"courses": courses, "lessons": lessons, "files": list(files.values())}

    def lesson(self, lid):
        found = next((l for l in self.scan()["lessons"] if l["id"] == lid), None)
        if not found:
            raise WorkbenchError("课次不存在，请刷新资料库")
        return found

    def create_lesson(self, cid, title):
        course = next((c for c in self.scan()["courses"] if c["id"] == cid), None)
        if not course or not isinstance(title, str) or not 1 <= len(title) <= 100 or re.search(r'[<>:"/\\|?*\x00-\x1f]', title) or title.rstrip(' .') != title or title in {".", "..", "materials", "topics", "assignments"} or re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM\d|LPT\d)(\..*)?', title):
            raise WorkbenchError("课次名称无效，请使用一个有效目录名")
        relative = f"courses/{course['title']}/{title}"
        target = safe_path(self.store.root(), relative)
        if target.exists():
            raise WorkbenchError("课次目录已经存在")
        target.mkdir(parents=True, exist_ok=False)
        return {"lesson_id": identifier(relative)}

    def import_reference(self, fid, lid):
        source, info = self.file(fid)
        lesson = self.lesson(lid)
        if info["size"] > 50*1024*1024:
            raise WorkbenchError("大型文件请在本地归档，界面复制上限为 50 MiB")
        if info["course_id"] != lesson["course_id"]:
            raise WorkbenchError("不能自动将其他课程的资料归入本课次")
        folder = safe_path(self.store.root(), f"{lesson['relative']}/materials")
        folder.mkdir(parents=True, exist_ok=True)
        target = safe_path(self.store.root(), f"{lesson['relative']}/materials/{source.name}")
        if source.resolve() == target.resolve():
            raise WorkbenchError("资料已经位于本课次")
        if target.exists():
            raise WorkbenchError("本课次已存在同名文件，未覆盖；请先区分版本")
        created = False
        try:
            with source.open("rb") as incoming, target.open("xb") as outgoing:
                created = True
                shutil.copyfileobj(incoming, outgoing)
        except Exception:
            if created:
                target.unlink(missing_ok=True)
            raise
        return {"copied": True, "original_preserved": True}

    def file(self, fid):
        found = next((f for f in self.scan()["files"] if f["id"] == fid), None)
        if not found:
            raise WorkbenchError("资料不存在或已移动")
        root = self.store.settings()[f"{found['root']}_root"]
        return safe_path(root, found["relative"]), found

    def select(self, lid, selected, ranges):
        lesson = self.lesson(lid)
        if not isinstance(selected, list) or any(fid not in lesson["files"] for fid in selected):
            raise WorkbenchError("只能选择当前课次的资料；课程级资料请先明确归档到课次")
        if not isinstance(ranges, dict) or any(fid not in lesson["files"] for fid in ranges):
            raise WorkbenchError("页码范围不属于当前课次")
        self.store.update(lambda s: s["lessons"].setdefault(lid, {}).update(selected=list(dict.fromkeys(selected)), ranges={k: str(v)[:40] for k, v in ranges.items()}))

    def extract(self, fid, page_range=""):
        path, info = self.file(fid)
        if info["size"] > 50 * 1024 * 1024:
            raise WorkbenchError("单份资料超过 50 MiB，请先另存必要页码")
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            from pypdf import PdfReader
            pdf = PdfReader(path)
            pages = parse_pages(page_range, len(pdf.pages))
            content = "\n".join(f"[第 {p+1} 页]\n{pdf.pages[p].extract_text() or ''}" for p in pages)
        elif suffix in {".txt", ".md", ".tex", ".srt", ".vtt"}:
            content = path.read_text(encoding="utf-8-sig", errors="replace")
        elif suffix in {".pptx", ".docx"}:
            from zipfile import ZipFile
            from xml.etree import ElementTree
            with ZipFile(path) as archive:
                names = [n for n in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n) or n == "word/document.xml"]
                names.sort(key=lambda n: int(re.search(r"slide(\d+)", n).group(1)) if n.startswith("ppt/") else 0)
                if suffix == ".pptx" and "ppt/presentation.xml" in archive.namelist() and "ppt/_rels/presentation.xml.rels" in archive.namelist():
                    import posixpath
                    links = {rel.get("Id"): posixpath.normpath(posixpath.join("ppt", rel.get("Target", ""))) for rel in ElementTree.fromstring(archive.read("ppt/_rels/presentation.xml.rels"))}
                    order = [links.get(node.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")) for node in ElementTree.fromstring(archive.read("ppt/presentation.xml")).iter() if node.tag.endswith("}sldId")]
                    if not order or any(n not in names for n in order):
                        raise WorkbenchError("PPTX 的页序关联无效，请另存 PDF 后选择")
                    names = order
                if sum(archive.getinfo(n).file_size for n in names) > 30 * 1024 * 1024:
                    raise WorkbenchError("文档展开后过大")
                content = "\n".join(" ".join(ElementTree.fromstring(archive.read(n)).itertext()) for n in names)
        else:
            raise WorkbenchError("这类文件暂不做文字提取；视频请选择字幕，图片/扫描 PDF 请先 OCR")
        if not content.strip():
            raise WorkbenchError("没有提取到文字，可能是扫描件；请先 OCR，不会用空内容生成笔记")
        if len(content) > 60000:
            raise WorkbenchError("参考内容过长，请缩小 PDF 页码或另存文字节选")
        return content

    def draft(self, lid):
        self.lesson(lid)
        path = self.store.directory / "drafts" / f"{lid}.txt"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def put_draft(self, lid, text, fmt):
        self.lesson(lid)
        if fmt not in {"md", "tex"} or not isinstance(text, str) or len(text) > 500000:
            raise WorkbenchError("草稿格式或长度无效")
        path = self.store.directory / "drafts" / f"{lid}.txt"
        if path.is_file() and path.read_text(encoding="utf-8") != text:
            self.backup(path, lid, "draft")
        atomic_text(path, text)
        self.store.update(lambda s: s["lessons"].setdefault(lid, {}).update(status="draft", format=fmt))

    def note(self, lid):
        lesson = self.lesson(lid)
        path = safe_path(self.store.root(), f"{lesson['relative']}/{lesson['note_file']}")
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    def backup(self, path, lid, suffix):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        target = self.store.directory / "backups" / f"{lid}-{stamp}.{suffix}"
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(path, target)

    def save(self, lid, text, fmt):
        self.put_draft(lid, text, fmt)
        lesson = self.lesson(lid)
        path = safe_path(self.store.root(), f"{lesson['relative']}/notes.{fmt}")
        if fmt == "tex" and r"\input{note-style.tex}" in text:
            style = safe_path(self.store.root(), f"{lesson['relative']}/note-style.tex")
            template = safe_path(self.store.root(), "templates/note-style.tex")
            if not style.exists() and template.is_file():
                with template.open("rb") as incoming, style.open("xb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing)
        if path.exists():
            self.backup(path, lid, fmt)
        atomic_text(path, text)
        self.store.update(lambda s: s["lessons"].setdefault(lid, {}).update(status="review", note_format=fmt))
        return path


def parse_pages(value, total):
    if total > 200 and not value:
        raise WorkbenchError("PDF 超过 200 页，请填写本次使用范围")
    if not value:
        return list(range(total))
    pages = set()
    try:
        for part in str(value).replace("，", ",").split(","):
            ends = part.strip().split("-")
            if len(ends) not in {1, 2}:
                raise ValueError()
            start, end = int(ends[0]), int(ends[-1])
            if not 1 <= start <= end <= total or end-start > 199:
                raise ValueError()
            pages.update(range(start-1, end))
        if len(pages) > 200:
            raise ValueError()
    except ValueError:
        raise WorkbenchError("页码无效；请填写有效范围，例如 1-3,5，最多 200 页") from None
    return sorted(pages)


def seed_demo(store):
    root = store.directory / "demo-library"
    examples = {"矩阵论": {"lecture-01": "线性空间与基", "lecture-02": "相似变换"}, "信号与系统": {"lecture-01": "线性时不变系统"}}
    for course, lessons in examples.items():
        for folder, title in lessons.items():
            dest = root / "courses" / course / folder / "materials"
            dest.mkdir(parents=True, exist_ok=True)
            file = dest / "课堂字幕.txt"
            if not file.exists():
                file.write_text(f"合成演示资料：{title}。\n先明确概念及适用条件，再推导关键公式。\n矩阵相似变换：B = P⁻¹ A P，旧坐标 = P × 新坐标。", encoding="utf-8")
    store.update(lambda s: s["settings"].update(notes_root=str(root), downloads_root=str(root)))
    if not (root / ".git").exists():
        from .git_history import git
        git(root, "init", "-b", "main")
        git(root, "config", "user.name", "Workbench Demo")
        git(root, "config", "user.email", "demo@example.invalid")
        (root / ".gitignore").write_text("**/materials/\n.local/\n", encoding="utf-8")
        git(root, "add", "--", ".gitignore")
        git(root, "commit", "-m", "demo: initialize private sample library")
        for index, (course, lesson_map) in enumerate(examples.items()):
            title = next(iter(lesson_map.values()))
            file = root / "courses" / course / "lecture-01/notes.md"
            file.write_text(f"# {title}\n\n合成示例笔记，用于展示版本记录。\n", encoding="utf-8")
            relative = file.relative_to(root).as_posix()
            git(root, "add", "--", relative)
            git(root, "commit", "-m", f"demo: note revision {index+1}")
    library = Library(store)
    for lesson in library.scan()["lessons"]:
        store.update(lambda s, l=lesson: s["lessons"].setdefault(l["id"], {}).update(selected=l["files"]))
    for course in library.scan()["courses"]:
        store.update(lambda s, c=course: s["assignments"].setdefault(c["id"], [{"id": "demo-1", "title": "作业一 · 概念与推导", "deadline": "演示日期", "submission_status": True, "source": "demo"}, {"id": "demo-2", "title": "作业二 · 综合练习", "deadline": None, "submission_status": None, "source": "demo"}]))
    return root
