"""build_local 的離線測試；所有檔案均放在暫存目錄。"""

import json
import os
import subprocess
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from io import BytesIO, StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import build_local
import fetch_avatars
import fetch_male_thumbs
import merge_multi
from build_local import BuildError, build
from PIL import Image


class BuildLocalTests(unittest.TestCase):
    def setUp(self):
        # 此 Windows 沙箱無法存取 tempfile 預設以 mode=0o700 建立的目錄。
        if os.name == "nt":
            mkdir = os.mkdir
            with patch.object(os, "mkdir", side_effect=lambda path, mode=0o777: mkdir(path, 0o777)):
                self.temp_dir = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        else:
            self.temp_dir = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.template = self.root / "graph_template.html"
        self.data = self.root / "graph_data_multi.json"
        self.out = self.root / "graph.html"
        self.template.write_text(
            "<script>const DATA = /*__DATA__*/null;</script>", encoding="utf-8"
        )
        self.data.write_text(json.dumps({
            "actresses": [{"name": "河北彩花"}],
            "works": [
                {"title": "日本語與中文 </script>", "note": "/*__DATA__*/null", "males": ["男優甲", "男優乙"]},
                {"title": "第二部", "males": ["男優甲"]},
            ],
        }, ensure_ascii=False), encoding="utf-8")

    def run_build(self, desktop=None):
        output = StringIO()
        with redirect_stdout(output):
            result = build(self.template, self.data, self.out, desktop)
        return result, output.getvalue()

    def test_embeds_json_with_unicode_and_safe_script_end(self):
        (out_size, desktop_size), summary = self.run_build()
        html = self.out.read_text(encoding="utf-8")
        self.assertNotIn("/*__DATA__*/null", html)
        self.assertIn('"河北彩花"', html)
        self.assertIn('"日本語與中文 <\\/script>"', html)
        self.assertNotIn("\\u6cb3", html)
        self.assertTrue(html.endswith("</script>"))
        self.assertEqual(out_size, self.out.stat().st_size)
        self.assertIsNone(desktop_size)
        self.assertIn("女優 1 人、作品 2 部、男優 2 人", summary)

    def test_missing_placeholder_does_not_create_output(self):
        self.template.write_text("<script>const DATA = null;</script>", encoding="utf-8")
        with self.assertRaisesRegex(BuildError, "實際為 0 次"):
            self.run_build()
        self.assertFalse(self.out.exists())

    def test_duplicate_placeholder_does_not_create_output(self):
        self.template.write_text("/*__DATA__*/null /*__DATA__*/null", encoding="utf-8")
        with self.assertRaisesRegex(BuildError, "實際為 2 次"):
            self.run_build()
        self.assertFalse(self.out.exists())

    def test_missing_template_does_not_create_output(self):
        self.template.unlink()
        with self.assertRaisesRegex(BuildError, "範本檔不存在"):
            self.run_build()
        self.assertFalse(self.out.exists())

    def test_missing_data_does_not_create_output(self):
        self.data.unlink()
        with self.assertRaisesRegex(BuildError, "資料檔不存在"):
            self.run_build()
        self.assertFalse(self.out.exists())

    def test_invalid_json_does_not_create_output(self):
        self.data.write_text("{broken", encoding="utf-8")
        with self.assertRaisesRegex(BuildError, "不是合法 JSON"):
            self.run_build()
        self.assertFalse(self.out.exists())

    def test_copies_to_requested_desktop_directory(self):
        desktop = self.root / "Desktop"
        desktop.mkdir()
        (out_size, desktop_size), summary = self.run_build(desktop)
        copied = desktop / "合作關聯圖.html"
        self.assertEqual(copied.read_bytes(), self.out.read_bytes())
        self.assertEqual(out_size, desktop_size)
        self.assertIn(str(copied), summary)

    def test_missing_desktop_directory_only_warns(self):
        desktop = self.root / "missing-desktop"
        (_, desktop_size), summary = self.run_build(desktop)
        self.assertTrue(self.out.exists())
        self.assertFalse(desktop.exists())
        self.assertIsNone(desktop_size)
        self.assertIn("警告：桌面資料夾不存在", summary)

    def test_atomic_write_leaves_no_temporary_file(self):
        self.out.write_text("old", encoding="utf-8")
        with patch("build_local.os.replace", wraps=os.replace) as replace:
            self.run_build()
        replace.assert_called_once()
        self.assertNotEqual(self.out.read_text(encoding="utf-8"), "old")
        self.assertEqual(list(self.root.glob(".graph.html.*.tmp")), [])

    def test_merge_failure_preserves_output_and_exit_code(self):
        merge_result = subprocess.CompletedProcess([], 7, b"merge stdout\n", b"merge stderr\n")
        stdout = SimpleNamespace(buffer=BytesIO())
        stderr = SimpleNamespace(buffer=BytesIO())
        with patch("build_local.subprocess.run", return_value=merge_result) as run, \
                patch("build_local.sys.stdout", stdout), patch("build_local.sys.stderr", stderr):
            status = build_local.main(["--data", str(self.data), "--out", str(self.out), "--no-desktop"])
        self.assertEqual(status, 7)
        self.assertEqual(stdout.buffer.getvalue(), b"merge stdout\n")
        self.assertEqual(stderr.buffer.getvalue(), b"merge stderr\n")
        self.assertEqual(run.call_args.args[0], [
            build_local.sys.executable, "-X", "utf8", str(build_local.ROOT / "merge_multi.py"),
            "--out", str(self.data),
        ])
        self.assertFalse(self.out.exists())


class JavdbMatchTests(unittest.TestCase):
    def setUp(self):
        if os.name == "nt":
            mkdir = os.mkdir
            with patch.object(os, "mkdir", side_effect=lambda path, mode=0o777: mkdir(path, 0o777)):
                self.temp_dir = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        else:
            self.temp_dir = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

    def test_normalization_and_matches(self):
        self.assertEqual(merge_multi.fz(" 遙・カナ-亞_澤ー "), "遥かな亜沢")
        actresses = [{"name": "高橋しょう子", "aka": ["高崎聖子"]}, {"name": "浜崎遥"}]
        works = [{"males": ["舘つよし（えりぐち）"]}]
        resolved = {"濱崎遙": {"wiki_name": "浜崎遥"}}
        actors = [
            {"id": "A1", "names": ["高崎聖子"], "label": "高崎聖子"},
            {"id": "A2", "names": ["濱崎遙"], "label": "濱崎遙"},
            {"id": "M1", "names": ["えりぐち"], "label": "えりぐち"},
            {"id": "X1", "names": ["未知人物"], "label": "未知人物"},
        ]
        ids, missed, ambiguous, _, _ = merge_multi.match_javdb(actresses, works, resolved, actors, {})
        self.assertEqual(ids, {"高橋しょう子": "A1", "浜崎遥": "A2", "舘つよし（えりぐち）": "M1"})
        self.assertEqual(missed, ["未知人物"])
        self.assertEqual(ambiguous, [])

    def test_ambiguity_and_manual_override(self):
        actresses = [{"name": "甲"}, {"name": "乙"}]
        actors = [{"id": "X1", "names": ["甲", "乙"], "label": "共同名"}]
        ids, missed, ambiguous, _, _ = merge_multi.match_javdb(
            actresses, [], {}, actors, {"甲": "Manual"}
        )
        self.assertEqual(ids, {"甲": "Manual"})
        self.assertEqual(missed, [])
        self.assertEqual(ambiguous, [("共同名", ["乙", "甲"])])

    def test_male_formal_name_precedes_parenthetical_alias(self):
        actors = [
            {"id": "Alias", "names": ["タラオ"], "label": "タラオ"},
            {"id": "Formal", "names": ["トイボーイ相沢"], "label": "トイボーイ相沢"},
        ]
        ids, _, ambiguous, _, _ = merge_multi.match_javdb(
            [], [{"males": ["トイボーイ相沢（タラオ）"]}], {}, actors, {}
        )
        self.assertEqual(ids, {"トイボーイ相沢（タラオ）": "Formal"})
        self.assertEqual(ambiguous, [])

    def test_repeated_id_cannot_map_to_two_labels(self):
        actors = [
            {"id": "Same", "names": ["甲"], "label": "甲"},
            {"id": "Same", "names": ["乙"], "label": "乙"},
        ]
        ids, _, ambiguous, _, _ = merge_multi.match_javdb(
            [{"name": "甲"}, {"name": "乙"}], [], {}, actors, {}
        )
        self.assertEqual(ids, {})
        self.assertEqual(ambiguous, [("Same", ["乙", "甲"])])

    def test_missing_and_broken_avatar_are_skipped(self):
        Image.new("RGB", (80, 160), "red").save(self.root / "A1.jpg")
        (self.root / "Bad.jpg").write_text("不是圖片", encoding="utf-8")
        avatars, skipped = merge_multi.pack_avatars(
            {"甲": "A1", "乙": "Missing", "丙": "Bad"}, self.root
        )
        self.assertEqual(list(avatars), ["甲"])
        self.assertTrue(avatars["甲"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(skipped, ["乙", "丙"])

    def test_fetch_uses_only_image_host_and_retries_once(self):
        actors = self.root / "actors.json"
        overrides = self.root / "ids.json"
        actors.write_text(json.dumps([{"id": "J21m3", "img": "https://c0.jdbstatic.com/avatars/j2/J21m3.jpg"}]), encoding="utf-8")
        overrides.write_text("{}", encoding="utf-8")
        urls = []

        def opener(url, timeout):
            urls.append((url, timeout))
            if len(urls) == 1:
                raise urllib.error.URLError("暫時失敗")
            return BytesIO("圖片內容".encode("utf-8"))

        result = fetch_avatars.fetch(actors, overrides, self.root / "avatars", opener, lambda _: None)
        self.assertEqual(result, (1, 0, [], False))
        self.assertEqual(urls, [("https://c0.jdbstatic.com/avatars/j2/J21m3.jpg", 15)] * 2)
        self.assertEqual((self.root / "avatars" / "J21m3.jpg").read_bytes(), "圖片內容".encode("utf-8"))

    def test_fetch_skips_actors_without_real_avatar(self):
        actors = self.root / "actors.json"
        overrides = self.root / "ids.json"
        actors.write_text(json.dumps([{"id": "Nn1", "img": "https://c0.jdbstatic.com/images/actor_unknow.jpg"}]), encoding="utf-8")
        overrides.write_text("{}", encoding="utf-8")
        urls = []
        result = fetch_avatars.fetch(actors, overrides, self.root / "avatars", lambda url, timeout: urls.append(url), lambda _: None)
        self.assertEqual(result, (0, 0, [], False))
        self.assertEqual(urls, [])

    def test_fetch_stops_on_403(self):
        actors = self.root / "actors.json"
        overrides = self.root / "ids.json"
        actors.write_text(json.dumps([{"id": "Aa1", "img": "https://c0.jdbstatic.com/avatars/aa/Aa1.jpg"}, {"id": "Bb2", "img": "https://c0.jdbstatic.com/avatars/bb/Bb2.jpg"}]), encoding="utf-8")
        overrides.write_text("{}", encoding="utf-8")
        urls = []

        def opener(url, timeout):
            urls.append(url)
            raise urllib.error.HTTPError(url, 403, "禁止", {}, None)

        with redirect_stdout(StringIO()):
            result = fetch_avatars.fetch(actors, overrides, self.root / "avatars", opener, lambda _: None)
        self.assertEqual(result, (0, 0, [], True))
        self.assertEqual(len(urls), 1)
        self.assertIsNone(fetch_avatars.NoRedirect().redirect_request(None, None, 302, "", {}, "https://javdb.com"))

    def test_male_thumb_parse_keeps_only_wiki_uploads(self):
        html = (
            '<div class="image-tag-item"><a target="_self" href="https://avdanyuwiki.com/tag/a/"><img src="https://avdanyuwiki.com/wp-content/uploads/2026/05/a.jpg" alt="甲">'
            '<div class="tag-name">甲</div></a></div>'
            '<div class="image-tag-item"><a target="_self" href="https://avdanyuwiki.com/tag/b/"><img src="https://evil.example/b.jpg" alt="乙"></a></div>'
        )
        self.assertEqual(
            fetch_male_thumbs.parse(html),
            [("https://avdanyuwiki.com/tag/a/", "https://avdanyuwiki.com/wp-content/uploads/2026/05/a.jpg")],
        )

    def test_male_thumb_fetch_downloads_then_skips_existing(self):
        items = [("https://avdanyuwiki.com/tag/a/", "https://avdanyuwiki.com/wp-content/uploads/2026/05/a.png")]
        urls = []

        class Resp(BytesIO):
            headers = {"Content-Type": "image/png"}

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def opener(url, timeout):
            urls.append(url)
            return Resp(b"png")

        mapping, downloaded, existing, failed, blocked = fetch_male_thumbs.fetch(items, self.root / "m", opener, lambda _: None)
        self.assertEqual((mapping, downloaded, existing, failed, blocked), ({items[0][0]: "a.png"}, 1, 0, [], False))
        mapping, downloaded, existing, failed, blocked = fetch_male_thumbs.fetch(items, self.root / "m", opener, lambda _: None)
        self.assertEqual((downloaded, existing, blocked, len(urls)), (0, 1, False, 1))

    def test_male_thumb_fetch_stops_on_403_and_on_html_page(self):
        items = [
            ("https://avdanyuwiki.com/tag/a/", "https://avdanyuwiki.com/wp-content/uploads/a.jpg"),
            ("https://avdanyuwiki.com/tag/b/", "https://avdanyuwiki.com/wp-content/uploads/b.jpg"),
        ]
        urls = []

        def blocked_403(url, timeout):
            urls.append(url)
            raise urllib.error.HTTPError(url, 403, "禁止", {}, None)

        with redirect_stdout(StringIO()):
            result = fetch_male_thumbs.fetch(items, self.root / "m403", blocked_403, lambda _: None)
        self.assertEqual((result[1], result[4], len(urls)), (0, True, 1))

        class Html(BytesIO):
            headers = {"Content-Type": "text/html; charset=UTF-8"}

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        urls.clear()
        with redirect_stdout(StringIO()):
            result = fetch_male_thumbs.fetch(items, self.root / "mhtml", lambda url, timeout: (urls.append(url), Html(b"<html>challenge</html>"))[1], lambda _: None)
        self.assertEqual((result[1], result[4], len(urls)), (0, True, 1))
        self.assertFalse(list((self.root / "mhtml").glob("*")))
        self.assertIsNone(fetch_male_thumbs.NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.com"))

    def test_pack_avatars_accepts_filename_resolver(self):
        Image.new("RGB", (60, 90), "blue").save(self.root / "x.png")
        avatars, skipped = merge_multi.pack_avatars({"男": "x.png"}, self.root, name=lambda f: f)
        self.assertEqual((list(avatars), skipped), (["男"], []))


if __name__ == "__main__":
    unittest.main()
