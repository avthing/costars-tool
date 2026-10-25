"""costars 的離線解析、資料合併與停手規則測試。"""

import csv
from contextlib import contextmanager
import json
from pathlib import Path
import shutil
import unittest
from unittest import mock
from uuid import uuid4

import costars


@contextmanager
def test_dir():
    # Windows 受限環境對 tempfile 的 0700 目錄可能無法再開啟。
    path = costars.ROOT / ('_test_' + uuid4().hex)
    path.mkdir()
    try:
        yield str(path)
    finally:
        shutil.rmtree(path)


def card(title, performer, males, delivery, maker='', tag='p'):
    maker_line = f'<br>メーカー品番 ： {maker}' if maker else ''
    return (f'<article class="entry-card"><h2>{title}</h2><{tag}>'
            f'配信開始日 ： 2026/10/23<br>出演者 ： {performer}<br>'
            f'出演男優： {males}<br>配信品番 ： {delivery}{maker_line}'
            f'</{tag}><a href="https://avdanyuwiki.com/work/#comment-area">リンク先削除報告</a></article>')


class ParseTests(unittest.TestCase):
    def test_new_and_old_cards_and_male_separators(self):
        body = (card('新作品', '河北彩花（河北彩伽）', '鮫島、貞松大輔，鮫島', 'snos00449', 'SNOS-449')
                + card('舊作品', '河北彩花', '小田切ジュン 武田大樹', 'sone00853', tag='div'))
        works, skipped = costars.parse_page(body, '河北彩花')
        self.assertEqual(skipped, 0)
        self.assertEqual([work['code'] for work in works], ['SNOS-449', 'SONE-853'])
        self.assertEqual([work['code_inferred'] for work in works], [False, True])
        self.assertEqual(works[0]['males_wiki'], ['鮫島', '貞松大輔'])
        self.assertEqual(works[1]['males_wiki'], ['小田切ジュン', '武田大樹'])
        self.assertEqual(works[0]['url'], 'https://avdanyuwiki.com/work/')

    def test_relevance_uses_performer_and_parenthesized_alias(self):
        body = (card('標題提到河北彩花', '其他人', '鮫島', 'sone00101')
                + card('別名作品', '別的姓名（河北彩伽）', '鮫島', 'sone00102'))
        works, skipped = costars.parse_page(body, '河北彩花', ['河北彩伽'])
        self.assertEqual(([work['code'] for work in works], skipped), (['SONE-102'], 1))

    def test_blocked_titles_and_empty_search_result(self):
        for title in costars.BLOCKED_TITLES:
            self.assertTrue(costars.is_blocked(title + '...', 0, '河北彩花'))
        self.assertTrue(costars.is_blocked('Unknown page', 0, '河北彩花'))
        self.assertFalse(costars.is_blocked('河北彩花の検索結果', 0, '河北彩花'))


class StorageTests(unittest.TestCase):
    def test_atomic_json_replaces_file_without_temp_residue(self):
        with test_dir() as temp:
            path = Path(temp) / 'store.json'
            path.write_text('{"old": true}', encoding='utf-8')
            costars.atomic_json(path, {'version': 1, 'actresses': {'河北彩花': {}}})
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['version'], 1)
            self.assertFalse(path.with_name('store.json.tmp').exists())

    def test_build_alias_noise_and_wiki_priority(self):
        with test_dir() as temp:
            root = Path(temp)
            data = root / 'data'
            data.mkdir()
            (root / 'graph_template.html').write_text('<script>const DATA=/*__DATA__*/null;</script>', encoding='utf-8')
            store = {'version': 1, 'actresses': {
                '女優甲': {'collected_at': 'now', 'pages': 1, 'works': [
                    {'code': 'A-1', 'title': '甲作品', 'date': '2026-01-01', 'date_javdb': '2026-01-02',
                     'males_wiki': ['清水健', '素人'], 'males_javdb': ['不採用']}]},
                '女優乙': {'collected_at': 'now', 'pages': 1, 'works': [
                    {'code': 'A-1', 'title': '甲作品', 'date': '2026-01-01',
                     'males_wiki': ['しみけん'], 'males_javdb': None}]}}}
            costars.atomic_json(data / 'store.json', store)
            args = type('Args', (), {'data': data, 'out': root / 'graph.html'})()
            with mock.patch.object(costars, 'ROOT', root):
                costars.build(args)
            graph = json.loads((root / 'graph_data.json').read_text(encoding='utf-8'))
            self.assertEqual((graph['total_works'], graph['with_males']), (1, 1))
            self.assertEqual(graph['works'][0]['males'], ['しみけん'])
            self.assertEqual(graph['works'][0]['date'], '2026-01-02')
            self.assertEqual(set(graph['works'][0]['actresses']), {'女優甲', '女優乙'})
            self.assertEqual([a['works'] for a in graph['actresses']], [1, 1])
            with (root / 'costars.csv').open(encoding='utf-8-sig', newline='') as file:
                self.assertEqual(list(csv.DictReader(file))[0]['合作作品數'], '1')
            self.assertIn('しみけん', (root / 'graph.html').read_text(encoding='utf-8'))


class FetchTests(unittest.TestCase):
    def test_throttle_has_hard_five_second_floor(self):
        waited = []
        fetcher = costars.WikiFetcher(Path('.'), 9333, clock=lambda: 2.0,
                                      sleep=waited.append, jitter=lambda low, high: 0)
        fetcher.last_navigation = 0.0
        fetcher.throttle()
        self.assertGreaterEqual(waited[0], 3.0)
        self.assertEqual(costars.MIN_NAV_INTERVAL, 5.0)

    def test_verification_waits_without_navigating_again(self):
        with test_dir() as temp:
            now = [0.0]

            def sleep(seconds):
                now[0] += seconds

            class FakeCdp:
                navigations = 0

                def navigate(self, url):
                    self.navigations += 1

                def evaluate(self, expression):
                    if expression == 'document.title':
                        return 'Just a moment...' if now[0] < 6 else '河北彩花の検索結果'
                    if 'querySelectorAll' in expression:
                        return 0 if now[0] < 6 else 1
                    return ('<html><title>河北彩花の検索結果</title>'
                            + card('作品', '河北彩花', '鮫島', 'sone00101') + '</html>')

                def close(self):
                    pass

            fake = FakeCdp()
            fetcher = costars.WikiFetcher(Path(temp), 9333, clock=lambda: now[0],
                                          sleep=sleep, cdp_factory=lambda port: fake)
            body = fetcher.get('河北彩花', 1)
            self.assertIn('entry-card', body)
            self.assertEqual(fake.navigations, 1)
            self.assertEqual(fetcher.navigations, 1)
            self.assertEqual(now[0], 6.0)

    def test_verification_timeout_preserves_existing_store(self):
        with test_dir() as temp:
            root = Path(temp)
            existing = {'version': 1, 'actresses': {'已完成': {'works': []}}}
            costars.atomic_json(root / 'store.json', existing)
            now = [0.0]

            class BlockedCdp:
                navigations = 0

                def navigate(self, url):
                    self.navigations += 1

                def evaluate(self, expression):
                    return 'Just a moment...' if expression == 'document.title' else 0

                def close(self):
                    pass

            fake = BlockedCdp()
            fetcher = costars.WikiFetcher(root, 9333, clock=lambda: now[0],
                                          sleep=lambda seconds: now.__setitem__(0, now[0] + seconds),
                                          cdp_factory=lambda port: fake)
            with self.assertRaisesRegex(costars.StopScraping, '驗證逾時'):
                fetcher.get('河北彩花', 1)
            self.assertEqual(fake.navigations, 1)
            self.assertEqual(json.loads((root / 'store.json').read_text(encoding='utf-8')), existing)
            self.assertFalse((root / 'cache' / 'wiki' / '河北彩花' / 'page_1.html').exists())


if __name__ == '__main__':
    unittest.main()
