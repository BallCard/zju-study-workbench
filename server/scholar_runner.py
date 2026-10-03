"""Run existing Scholar download functions in its own interpreter and namespace."""
import asyncio
import json
from pathlib import Path
import sys


async def main():
    scholar, action, course, sub, root, destination = sys.argv[1:]
    sys.path.insert(0, str(Path(scholar) / "scripts"))
    from zju_zhiyun import _get_api
    api = _get_api()
    if action == "video":
        from zju_video_download import download_video
        result = await download_video(api, course_id=course, sub_id=sub, root=root)
    elif action == "subtitle":
        content = await api.get_subtitle_text(sub, timestamps=True)
        if not content:
            raise RuntimeError("字幕不可用")
        folder = Path(destination)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"subtitle_{sub}.txt"
        with target.open("x", encoding="utf-8") as handle:
            handle.write(content)
        result = {"path": str(target)}
    else:
        raise RuntimeError("未知操作")
    print(json.dumps({"ok": True, "data": result}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        print(json.dumps({"ok": False, "error": "SCHOLAR_OPERATION_FAILED"}))
        sys.exit(1)
