"""A narrow process bridge; no imported school credentials in the web service."""
import json
from pathlib import Path
import subprocess
from datetime import datetime, timezone
from .storage import WorkbenchError, safe_path


def unwrap(payload):
    for _ in range(5):
        if not isinstance(payload, dict) or "data" not in payload:
            break
        payload = payload["data"]
    return payload


def records(value):
    """Schema wrappers vary between Scholar features; retain completion markers."""
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from records(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from records(nested)


def run(store, library, action, lid):
    lesson = library.lesson(lid)
    state = store.snapshot()
    mapping = state["courses"].get(lesson["course_id"], {})
    course_id, zhiyun_id = mapping.get("course_id", ""), mapping.get("zhiyun_id", "")
    sub_id = state["lessons"].get(lid, {}).get("sub_id", "")
    if store.demo:
        raise WorkbenchError("演示库不连接学校；请切换正式配置后操作")
    settings = state["settings"]
    scholar = Path(settings["scholar_root"])
    python = settings["scholar_python"]
    if not python or not scholar.is_dir() or not (scholar / "scripts/zju_courses.py").is_file():
        raise WorkbenchError("请配置 zju-scholar 路径和该项目的 Python，并先在终端登录")
    root = settings["downloads_root"] or settings["notes_root"]
    safe_path(root)
    if action in {"assignments", "courseware"}:
        if not str(course_id).isdigit():
            raise WorkbenchError("请在本课程设置中填写学在浙大课程 ID")
        command = [python, str(scholar / "scripts/zju_courses.py"), "assignments" if action == "assignments" else "courseware-download", "--course-id", str(course_id)]
        command += ["--refresh"] if action == "assignments" else ["--materials-root", root]
    elif action in {"ppt", "subtitle", "video"}:
        if not str(zhiyun_id).isdigit() or not str(sub_id).isdigit():
            raise WorkbenchError("请明确填写智云课程 ID 与本课次录像 ID")
        if action == "ppt":
            course_name = next(c["title"] for c in library.scan()["courses"] if c["id"] == lesson["course_id"])
            output = safe_path(root, f"courses/{course_name}")
            command = [python, str(scholar / "scripts/zju_zhiyun.py"), "courseware-pdf", "--course-id", str(zhiyun_id), "--sub-id", str(sub_id), "--output", str(output)]
        else:
            destination = safe_path(root, f"{lesson['relative']}/materials")
            command = [python, str(Path(__file__).with_name("scholar_runner.py")), str(scholar), action, str(zhiyun_id), str(sub_id), str(root), str(destination)]
    else:
        raise WorkbenchError("不支持的学校操作")
    completed = subprocess.run(command, cwd=scholar, capture_output=True, encoding="utf-8", errors="replace", timeout=1800)
    if completed.returncode:
        raise WorkbenchError("学校操作失败，请在 zju-scholar 终端检查会话、权限或下载错误；不会绕过平台拒绝")
    try:
        payload = json.loads(completed.stdout)
    except ValueError:
        raise WorkbenchError("zju-scholar 返回格式不兼容，请检查增强版版本") from None
    if payload.get("ok") is False:
        raise WorkbenchError("学校接口报告失败，请在 zju-scholar 中检查")
    data = unwrap(payload)
    markers = list(records(payload))
    partial = any(v.get("complete") is False or v.get("status") == "partial" for v in markers)
    if action == "assignments":
        if not isinstance(data, dict) or not isinstance(data.get("assignments"), list):
            raise WorkbenchError("没有获取到有效个人作业集合；旧状态保留")
        if any(not isinstance(a, dict) or a.get("id") in {None, ""} for a in data["assignments"]):
            raise WorkbenchError("作业记录缺少有效 ID；旧状态保留")
        partial |= not any(v.get("complete") is True for v in markers)
        assignments = [{"id": str(a["id"]), "title": str(a.get("title") or "未命名作业"), "deadline": a.get("deadline"), "submission_status": a.get("submission_status"), "source": "platform", "cached": False} for a in data["assignments"]]
        def update(s):
            old = s["assignments"].get(lesson["course_id"], [])
            merged = {a["id"]: {**a, "cached": True} for a in old} if partial else {}
            merged.update({a["id"]: a for a in assignments})
            s["assignments"][lesson["course_id"]] = list(merged.values())
            s.setdefault("assignment_sync", {})[lesson["course_id"]] = {"partial": partial, "checked_at": datetime.now(timezone.utc).isoformat()}
        store.update(update)
        return {"count": len(assignments), "partial": partial, "message": "本次返回不完整，未返回的旧作业保留为缓存。" if partial else "个人作业记录已完整刷新。"}
    failed = sum(v.get("status") in {"download_failed", "download_denied_by_server", "error", "failed"} for v in markers)
    successful = sum((v.get("status") in {"ok", "downloaded", "skipped_existing_file"} and any(key in v for key in ("slides", "pdf_path", "path", "upload_id", "sub_id"))) or (action == "subtitle" and bool(v.get("path"))) for v in markers)
    if failed and not successful:
        raise WorkbenchError("本次资料未下载成功，平台拒绝或下载失败；旧文件保留")
    partial |= bool(failed) or any(v.get("original_slides", 0) > v.get("slides", v.get("original_slides", 0)) for v in markers)
    empty = not successful
    return {"action": action, "completed": not partial and not empty, "partial": partial, "message": "部分资料未成功下载，请核对已保存文件。" if partial else "平台未返回可用资料；可能未提供，或课程/录像关联未找到，请核对。" if empty else "请求已结束，资料按平台返回目录保存，请刷新核对课次。"}
