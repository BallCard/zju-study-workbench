import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest.mock import patch

from server.storage import Store, safe_path, WorkbenchError
from server.library import Library, seed_demo, parse_pages
from server.git_history import git, history, commit_note
from server.__main__ import create_server
from server import ai, scholar, tex


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name, demo=True)
        seed_demo(self.store)
        self.library = Library(self.store)
        self.lessons = self.library.scan()["lessons"]

    def tearDown(self):
        self.temp.cleanup()

    def test_private_state_and_sources_do_not_enter_git(self):
        root = self.store.root()
        tracked = git(root, "ls-files")
        self.assertNotIn("materials", tracked)
        self.assertNotIn("state.json", tracked)
        self.assertTrue(history(root)["available"])

    def test_page_ranges_are_bounded_and_not_silently_truncated(self):
        self.assertEqual(parse_pages("1-3,5", 6), [0, 1, 2, 4])
        for value in ("0", "3-1", "1-999999", "hello", "1-2-3"):
            with self.assertRaises(WorkbenchError):
                parse_pages(value, 6)

    def test_traversal_and_outside_paths_fail(self):
        for relative in ("../secret", str(Path(self.temp.name).absolute())):
            with self.assertRaises(WorkbenchError):
                safe_path(self.store.root(), relative)

    def test_selection_rejects_other_lesson_files(self):
        a, b = self.lessons[:2]
        with self.assertRaises(WorkbenchError):
            self.library.select(a["id"], b["files"], {})

    def test_two_storage_roots_remain_visible_and_resolve_correctly(self):
        download = Path(self.temp.name) / "separate-downloads"
        target = download / self.lessons[0]["relative"] / "materials/separate.txt"
        target.parent.mkdir(parents=True)
        target.write_text("独立下载目录", encoding="utf-8")
        self.store.update(lambda s: s["settings"].update(downloads_root=str(download)))
        found = next(f for f in self.library.scan()["files"] if f["name"] == "separate.txt")
        self.assertEqual(self.library.extract(found["id"]), "独立下载目录")
        self.assertEqual(self.library.file(found["id"])[0], target)

    def test_copy_keeps_original_and_rejects_overwrite(self):
        course_lessons = next([l for l in self.lessons if l["course_id"] == c["id"]] for c in self.library.scan()["courses"] if sum(l["course_id"] == c["id"] for l in self.lessons) >= 2)
        a, b = course_lessons[:2]
        fid = a["files"][0]
        with self.assertRaises(WorkbenchError):
            self.library.import_reference(fid, b["id"])
        file = self.library.file(b["files"][0])[0]
        file.unlink()
        self.library.import_reference(fid, b["id"])
        self.assertTrue(self.library.file(fid)[0].is_file())
        self.assertTrue(file.is_file())

    def test_note_save_has_recovery_backup(self):
        l = self.lessons[0]
        self.library.save(l["id"], "old", "md")
        self.library.save(l["id"], "new", "md")
        self.assertEqual(self.library.note(l["id"]), "new")
        backups = list((self.store.directory / "backups").glob("*"))
        self.assertTrue(any(p.read_text(encoding="utf-8") == "old" for p in backups))

    def test_commit_does_not_include_preexisting_staged_changes(self):
        root = self.store.root()
        other = root / "unrelated.txt"
        other.write_text("user edit")
        git(root, "add", "--", "unrelated.txt")
        l = self.lessons[0]
        note = self.library.save(l["id"], "new", "md")
        before = git(root, "rev-parse", "HEAD")
        with self.assertRaises(WorkbenchError):
            commit_note(root, note, l["id"])
        self.assertEqual(git(root, "rev-parse", "HEAD"), before)
        self.assertEqual(git(root, "diff", "--cached", "--name-only").strip(), "unrelated.txt")

    def test_demo_generation_preserves_selected_sources(self):
        l = self.lessons[0]
        result = ai.generate(self.store, self.library, l["id"], "api", "保留推导", "md")
        self.assertTrue(result["demo"])
        self.assertIn("合成演示", self.library.draft(l["id"]))
        result = ai.generate(self.store, self.library, l["id"], "api", "保留推导", "tex")
        self.assertEqual(result["format"], "tex")
        self.assertIn(r"\begin{document}", self.library.draft(l["id"]))

    def test_assignments_adapter_keeps_unknown_and_partial(self):
        self.store.demo = False
        l = self.lessons[0]
        fake = Path(self.temp.name) / "scholar/scripts"
        fake.mkdir(parents=True)
        (fake / "zju_courses.py").write_text("")
        self.store.update(lambda s: (s["settings"].update(scholar_root=str(fake.parent), scholar_python="python"), s["courses"].update({l["course_id"]: {"course_id": "123"}})))
        payload = {"ok": True, "data": {"complete": False, "data": {"assignments": [{"id": 1, "submission_status": None, "score": None}]}}}
        with patch('server.scholar.subprocess.run', return_value=subprocess.CompletedProcess([], 0, json.dumps(payload), "")):
            result = scholar.run(self.store, self.library, "assignments", l["id"])
        self.assertTrue(result["partial"])
        self.assertIsNone(next(a for a in self.store.snapshot()["assignments"][l["course_id"]] if a["id"] == "1")["submission_status"])

    def fake_scholar(self):
        self.store.demo = False
        lesson = self.lessons[0]
        fake = Path(self.temp.name) / "fake-scholar/scripts"
        fake.mkdir(parents=True)
        (fake / "zju_courses.py").write_text("")
        self.store.update(lambda s: (s["settings"].update(scholar_root=str(fake.parent), scholar_python="python"), s["courses"].update({lesson["course_id"]: {"course_id": "123", "zhiyun_id": "456"}}), s["lessons"].setdefault(lesson["id"], {}).update(sub_id="789")))
        return lesson

    def test_partial_assignment_refresh_preserves_cached_records(self):
        lesson = self.fake_scholar()
        payload = {"ok": True, "data": {"meta": {"complete": False}, "data": {"assignments": [{"id": "demo-1", "submission_status": None}]}}}
        with patch('server.scholar.subprocess.run', return_value=subprocess.CompletedProcess([], 0, json.dumps(payload), "")):
            scholar.run(self.store, self.library, "assignments", lesson["id"])
        records = self.store.snapshot()["assignments"][lesson["course_id"]]
        self.assertEqual(len(records), 2)
        self.assertTrue(next(a for a in records if a["id"] == "demo-2")["cached"])
        self.assertTrue(self.store.snapshot()["assignment_sync"][lesson["course_id"]]["partial"])

    def test_failed_ppt_is_not_reported_completed(self):
        lesson = self.fake_scholar()
        payload = {"ok": True, "data": [{"sub_id": "789", "status": "download_failed", "slides": 0}]}
        with patch('server.scholar.subprocess.run', return_value=subprocess.CompletedProcess([], 0, json.dumps(payload), "")):
            with self.assertRaises(WorkbenchError):
                scholar.run(self.store, self.library, "ppt", lesson["id"])
        for empty in ({}, [], [{"sub_id": "789", "status": "no_slides"}]):
            payload = {"ok": True, "data": empty}
            with patch('server.scholar.subprocess.run', return_value=subprocess.CompletedProcess([], 0, json.dumps(payload), "")):
                self.assertFalse(scholar.run(self.store, self.library, "ppt", lesson["id"])["completed"])

    def test_note_formats_can_coexist_without_wrong_readback(self):
        lid = self.lessons[0]["id"]
        self.library.save(lid, "old latex", "tex")
        self.library.save(lid, "new markdown", "md")
        self.assertEqual(self.library.note(lid), "new markdown")
        self.library.put_draft(lid, "unsaved latex", "tex")
        self.assertEqual(self.library.note(lid), "new markdown")

    def test_pptx_slides_are_in_numeric_order(self):
        from zipfile import ZipFile
        lesson = self.lessons[0]
        file = self.store.root() / lesson["relative"] / "materials/sample.pptx"
        with ZipFile(file, 'w') as archive:
            for number in (1, 10, 2):
                archive.writestr(f"ppt/slides/slide{number}.xml", f"<slide><text>page{number}</text></slide>")
        fid = next(f["id"] for f in self.library.scan()["files"] if f["name"] == "sample.pptx")
        self.assertEqual(self.library.extract(fid).splitlines(), ["page1", "page2", "page10"])
        with ZipFile(file, 'a') as archive:
            archive.writestr('ppt/presentation.xml', '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldIdLst><p:sldId r:id="r2"/><p:sldId r:id="r1"/></p:sldIdLst></p:presentation>')
            archive.writestr('ppt/_rels/presentation.xml.rels', '<Relationships><Relationship Id="r1" Target="slides/slide1.xml"/><Relationship Id="r2" Target="slides/slide2.xml"/></Relationships>')
        self.assertEqual(self.library.extract(fid).splitlines(), ['page2', 'page1'])

    def test_ai_draft_overwrite_has_recovery_copy(self):
        lid = self.lessons[0]["id"]
        self.library.put_draft(lid, "my edited draft", "md")
        ai.generate(self.store, self.library, lid, "api", "", "md")
        self.assertTrue(any(p.read_text(encoding="utf-8") == "my edited draft" for p in (self.store.directory / 'backups').glob('*.draft')))

    def test_compile_failure_preserves_pdf(self):
        lid = self.lessons[0]["id"]
        source = self.library.save(lid, "invalid latex", "tex")
        pdf = source.with_suffix('.pdf')
        pdf.write_bytes(b'old PDF')
        with patch('server.tex.shutil.which', return_value='xelatex'), patch('server.tex.subprocess.run', return_value=subprocess.CompletedProcess([], 1)):
            with self.assertRaises(WorkbenchError):
                tex.compile_note(self.store, self.library, lid)
        self.assertEqual(pdf.read_bytes(), b'old PDF')

    def test_failed_commit_unstages_only_the_saved_note(self):
        lid = self.lessons[0]["id"]
        note = self.library.save(lid, "edited", "md")
        root = self.store.root()
        original = git
        def failed(root, *args):
            if args[0] == 'commit':
                raise WorkbenchError('failed hook')
            return original(root, *args)
        with patch('server.git_history.git', side_effect=failed):
            with self.assertRaises(WorkbenchError):
                commit_note(root, note, lid)
        self.assertEqual(git(root, 'diff', '--cached', '--name-only'), '')
        self.assertEqual(note.read_text(encoding='utf-8'), 'edited')


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name, demo=True)
        seed_demo(self.store)
        self.server = create_server(self.store, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.server.jobs.worker.shutdown(wait=True)
        self.temp.cleanup()

    def test_api_requires_local_session(self):
        for path in ('/api/state', '/api%2Fstate'):
            with self.assertRaises(HTTPError) as result:
                urlopen(self.base + path)
            self.assertEqual(result.exception.code, 400)

    def test_foreign_host_and_cross_site_write_are_rejected(self):
        with self.assertRaises(HTTPError):
            urlopen(Request(self.base, headers={"Host": "attacker.invalid"}))
        with self.assertRaises(HTTPError):
            urlopen(Request(self.base + "/api/settings", data=b'{}', headers={"Origin": "https://attacker.invalid", "Content-Type": "application/json"}))

    def test_index_sets_session_and_api_never_returns_a_key(self):
        with urlopen(self.base) as response:
            html = response.read().decode()
            cookie = response.headers.get("Set-Cookie").split(";", 1)[0]
        self.assertNotIn("__WORKBENCH_TOKEN__", html)
        with urlopen(Request(self.base + "/api/state", headers={"Cookie": cookie})) as response:
            data = json.load(response)
        self.assertNotIn("api_key", data["settings"])
        self.assertTrue(data["library"]["lessons"])


if __name__ == '__main__':
    unittest.main()
