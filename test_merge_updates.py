import tempfile
import unittest
from pathlib import Path

import merge_multi

HEAD = "標題,メーカー品番,配信品番,配信開始日,商品発売日,出演者文字,出演男優文字,男優 tag 清單,文章網址\r\n"


def line(code, date, males="男A"):
    return f"T {code},{code},,{date},{date},甲,{males},{males},https://x/{code}\r\n"


class LoadActressUpdatesTests(unittest.TestCase):
    def setUp(self):
        self._root = merge_multi.ROOT
        self.tmp = tempfile.TemporaryDirectory()
        merge_multi.ROOT = Path(self.tmp.name)
        (merge_multi.ROOT / "data" / "updates").mkdir(parents=True)

    def tearDown(self):
        merge_multi.ROOT = self._root
        self.tmp.cleanup()

    def write(self, rel, text):
        (merge_multi.ROOT / rel).write_text("﻿" + HEAD + text, encoding="utf-8")

    def test_without_updates_file_behaves_as_before(self):
        self.write("data/wiki_works_甲.csv", line("AAA-001", "2024-01-01"))
        works, nodate = merge_multi.load_actress("甲")
        self.assertEqual([w["code"] for w in works], ["AAA-001"])
        self.assertEqual(nodate, [])

    def test_updates_are_appended(self):
        self.write("data/wiki_works_甲.csv", line("AAA-001", "2024-01-01"))
        self.write("data/updates/wiki_works_甲.csv", line("AAA-002", "2025-02-02", "男B"))
        works, _ = merge_multi.load_actress("甲")
        self.assertEqual(sorted(w["code"] for w in works), ["AAA-001", "AAA-002"])

    def test_code_already_in_main_csv_is_not_counted_twice(self):
        self.write("data/wiki_works_甲.csv", line("AAA-001", "2024-01-01") + line("AAA-002", "2025-02-02"))
        self.write("data/updates/wiki_works_甲.csv", line("AAA-002", "2025-02-02") + line("AAA-003", "2025-03-03"))
        works, _ = merge_multi.load_actress("甲")
        self.assertEqual(sorted(w["code"] for w in works), ["AAA-001", "AAA-002", "AAA-003"])

    def test_explicit_path_ignores_updates(self):
        self.write("data/wiki_works_甲.csv", line("AAA-001", "2024-01-01"))
        self.write("data/updates/wiki_works_甲.csv", line("AAA-002", "2025-02-02"))
        works, _ = merge_multi.load_actress("甲", merge_multi.ROOT / "data" / "wiki_works_甲.csv")
        self.assertEqual([w["code"] for w in works], ["AAA-001"])


if __name__ == "__main__":
    unittest.main()
