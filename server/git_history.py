"""Read actual Git parents; commit exactly one approved note path."""
import subprocess
import threading
from .storage import WorkbenchError

git_lock = threading.Lock()


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, encoding="utf-8", errors="replace", timeout=30)
    if result.returncode:
        raise WorkbenchError("Git 操作失败：请检查仓库、用户身份或冲突；未自动 push")
    return result.stdout


def history(root):
    try:
        git(root, "rev-parse", "--show-toplevel")
        output = git(root, "log", "--all", "--date-order", "-60", "--format=%H%x1f%P%x1f%aI%x1f%s")
    except (WorkbenchError, FileNotFoundError):
        return {"available": False, "commits": []}
    commits = []
    for line in output.splitlines():
        parts = line.split("\x1f", 3)
        if len(parts) == 4:
            sha, parents, date, subject = parts
            commits.append({"sha": sha, "parents": parents.split(), "date": date, "subject": subject})
    return {"available": True, "commits": commits}


def commit_note(root, path, lesson_id):
    relative = path.relative_to(root).as_posix()
    with git_lock:
        git(root, "rev-parse", "--show-toplevel")
        # Refuse an occupied index; never clear, reset or stage unrelated files.
        if git(root, "diff", "--cached", "--name-only"):
            raise WorkbenchError("笔记已保存，但暂存区有其他改动；请先处理它们，再单独提交本笔记")
        if git(root, "ls-files", "-u"):
            raise WorkbenchError("仓库存在未解决冲突；笔记已保存，暂不提交")
        if not git(root, "status", "--porcelain", "--", relative):
            return {"sha": git(root, "rev-parse", "HEAD").strip(), "unchanged": True}
        tracked = bool(git(root, "ls-files", "--", relative))
        git(root, "add", "--", relative)
        try:
            git(root, "commit", "-m", f"notes: lesson [{lesson_id}]", "--", relative)
        except WorkbenchError:
            # The index was empty; remove only the entry this operation staged.
            if tracked:
                git(root, "reset", "HEAD", "--", relative)
            else:
                git(root, "rm", "--cached", "--ignore-unmatch", "--", relative)
            raise
        return {"sha": git(root, "rev-parse", "HEAD").strip(), "unchanged": False}
