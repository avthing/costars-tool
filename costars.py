"""蒐集女優與男優合作資料，並產生關聯圖所需的 CSV、JSON 與 HTML。"""

import argparse
import csv
from datetime import date, datetime, timezone
import html
import json
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import time
import unicodedata
from urllib import error, parse, request


ROOT = Path(__file__).resolve().parent
WIKI = "https://avdanyuwiki.com/"
JAVDB = "https://javdb.com"
MIN_NAV_INTERVAL = 5.0
JAVDB_INTERVAL = 5.1
MAX_PAGES = 30
DEFAULT_ALIASES = {"清水健": "しみけん", "タイ": "ダイ", "優生": "優生×",
                   "ムールかいせ": "ムールかいせ×", "羽田": "羽田貴史"}
DEFAULT_NOISE = ["主観", "完全主観", "素人"]
BLOCKED_TITLES = ("Just a moment", "請稍候", "请稍候", "Attention Required")
CARD = re.compile(r'<article\b[^>]*class="[^"]*\bentry-card\b[^"]*"[^>]*>(.*?)</article>', re.S | re.I)
TITLE = re.compile(r'<title\b[^>]*>(.*?)</title>', re.S | re.I)
DATE_JAVDB = re.compile(r'<strong>日期:</strong>\s*(?:&nbsp;)?\s*<span class="value">(\d{4}-\d{2}-\d{2})</span>')
JAVDB_BOX = re.compile(r'<a href="(/v/[A-Za-z0-9]+)" class="box" title="[^"]*">.*?<strong>([^<]+)</strong>', re.S)
JAVDB_PANEL = re.compile(r'<div class="panel-block[^"]*">\s*<strong>([^<:：]+)[:：]</strong>\s*(?:&nbsp;)?\s*<span class="value">(.*?)</span>', re.S)
JAVDB_LINK = re.compile(r'<a\b([^>]*)>([^<]*)</a>(\s*<strong\b[^>]*>.*?</strong>)?', re.S | re.I)


class StopScraping(Exception):
    """遇到阻擋、逾時或不安全的頁面時停止整批蒐集。"""


def clean(value):
    return html.unescape(re.sub(r'<[^>]+>', '', value or '')).strip()


def normalize(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value or '')).casefold()


def derive_code(value):
    value = value.strip()
    match = re.fullmatch(r'([a-zA-Z]+)0*(\d{3,})', value)
    return f'{match[1].upper()}-{match[2]}' if match else value.upper()


def split_males(value):
    return list(dict.fromkeys(part for part in re.split(r'[,，、\s\u3000]+', value.strip()) if part))


def page_title(body):
    match = TITLE.search(body)
    return clean(match[1]) if match else ''


def is_blocked(title, card_count, search_name):
    if title.startswith(BLOCKED_TITLES):
        return True
    return card_count == 0 and normalize(search_name) not in normalize(title)


def has_next(body):
    return bool(re.search(r'<a\b[^>]*class="[^"]*\bnext\b[^\"]*\bpage-numbers\b', body, re.I)
                or re.search(r'<a\b[^>]*>\s*次へ\s*</a>', body, re.I))


def parse_card(card):
    heading = re.search(r'<h2\b[^>]*>(.*?)</h2>', card, re.S | re.I)
    title = clean(heading[1]) if heading else ''
    link = re.search(r'<a\b[^>]*href="([^"]*#comment-area)"', card, re.I)
    url = html.unescape(link[1]).removesuffix('#comment-area') if link else ''
    body = card[heading.end():] if heading else card
    body = body.split('リンク先削除報告', 1)[0]
    lines = [clean(line) for line in re.sub(r'<br\s*/?>', '\n', body, flags=re.I).split('\n')]

    def field(name):
        for line in lines:
            if re.match(r'^\s*' + re.escape(name) + r'\s*[：:]', line):
                return re.split(r'[：:]', line, maxsplit=1)[1].strip()
        return ''

    delivery = field('配信品番') or field('品番')
    maker = field('メーカー品番')
    code = maker or derive_code(delivery)
    return {
        'code': code, 'code_inferred': not bool(maker), 'title': title,
        'date': field('配信開始日').replace('/', '-'), 'url': url,
        'males_wiki': split_males(field('出演男優')), 'males_javdb': None,
    }, field('出演者'), delivery


def parse_page(body, name, known_aliases=()):
    """僅根據出演者欄判定相關性；搜尋結果標題中的名字不算。"""
    parsed = [parse_card(card) for card in CARD.findall(body)]
    names = {normalize(name), *(normalize(alias) for alias in known_aliases)}
    for _, performer, _ in parsed:
        if normalize(name) in normalize(performer):
            names.update(normalize(alias) for alias in re.findall(r'[（(]([^）)]+)[）)]', performer))
    works, skipped = [], 0
    for work, performer, _ in parsed:
        if any(alias and alias in normalize(performer) for alias in names):
            works.append(work)
        else:
            skipped += 1
    return works, skipped


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def load_store(data):
    path = data / 'store.json'
    if not path.exists():
        return {'version': 1, 'actresses': {}}
    store = json.loads(path.read_text(encoding='utf-8'))
    if store.get('version') != 1 or not isinstance(store.get('actresses'), dict):
        raise ValueError(f'不支援的 store 格式：{path}')
    return store


def ensure_settings(data):
    for name, value in [('aliases.json', DEFAULT_ALIASES), ('noise.json', DEFAULT_NOISE)]:
        path = data / name
        if not path.exists():
            atomic_json(path, value)


def local_json(port, endpoint):
    with request.urlopen(f'http://127.0.0.1:{port}{endpoint}', timeout=2) as response:
        return json.load(response)


def ensure_chrome(port):
    try:
        version = local_json(port, '/json/version')
        print(f'Chrome CDP 已就緒：127.0.0.1:{port}（{version.get("Browser", "未知版本")}）')
        return
    except (OSError, ValueError):
        pass
    chrome = Path(r'C:\Program Files\Google\Chrome\Application\chrome.exe')
    if not chrome.exists():
        raise StopScraping(f'找不到 Chrome：{chrome}')
    profile = Path.home() / '.costars-chrome'
    subprocess.Popen([str(chrome), f'--remote-debugging-port={port}',
                      f'--user-data-dir={profile}', '--no-first-run',
                      '--no-default-browser-check'],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            local_json(port, '/json/version')
            print(f'Chrome CDP 已啟動：127.0.0.1:{port}')
            return
        except (OSError, ValueError):
            time.sleep(0.5)
    raise StopScraping(f'Chrome 啟動後 20 秒內未開放 CDP 埠 {port}')


class Cdp:
    def __init__(self, port):
        from websockets.sync.client import connect
        ensure_chrome(port)
        pages = local_json(port, '/json/list')
        target = next((page for page in pages if page.get('type') == 'page' and page.get('webSocketDebuggerUrl')), None)
        if target is None:
            raise StopScraping('Chrome 沒有可用的 page target')
        self.socket = connect(target['webSocketDebuggerUrl'], open_timeout=10)
        self.next_id = 0
        self.call('Page.enable')

    def call(self, method, params=None):
        self.next_id += 1
        wanted = self.next_id
        self.socket.send(json.dumps({'id': wanted, 'method': method, 'params': params or {}}))
        while True:
            message = json.loads(self.socket.recv(timeout=30))
            if message.get('id') == wanted:
                if 'error' in message:
                    raise StopScraping(f'CDP {method} 失敗：{message["error"]}')
                return message.get('result', {})

    def evaluate(self, expression):
        result = self.call('Runtime.evaluate', {'expression': expression, 'returnByValue': True})
        if 'exceptionDetails' in result:
            raise StopScraping(f'CDP 評估失敗：{expression}')
        return result.get('result', {}).get('value')

    def navigate(self, url):
        previous_load = self.evaluate('performance.timeOrigin')
        self.call('Page.navigate', {'url': url})
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            # 等到新文件載入，避免舊分頁原本已是 complete 而過早讀取。
            if (self.evaluate('performance.timeOrigin') != previous_load
                    and self.evaluate('document.readyState') == 'complete'):
                return
            time.sleep(0.2)
        raise StopScraping(f'頁面載入超過 30 秒：{url}')

    def close(self):
        self.socket.close()


class WikiFetcher:
    def __init__(self, data, port, clock=time.monotonic, sleep=time.sleep, jitter=random.uniform, cdp_factory=Cdp):
        self.data, self.port = data, port
        self.clock, self.sleep, self.jitter = clock, sleep, jitter
        self.cdp_factory = cdp_factory
        self.cdp = None
        self.last_navigation = None
        self.navigations = 0

    def throttle(self):
        if self.last_navigation is not None:
            due = self.last_navigation + MIN_NAV_INTERVAL + self.jitter(0, 3)
            self.sleep(max(0, due - self.clock()))

    def wait_for_verification(self, name, page):
        print('請在已開啟的 Chrome 視窗自行通過驗證,完成後會自動繼續', flush=True)
        deadline = self.clock() + 300
        while self.clock() < deadline:
            self.sleep(min(3, max(0, deadline - self.clock())))
            title = self.cdp.evaluate('document.title') or ''
            count = self.cdp.evaluate("document.querySelectorAll('article.entry-card').length") or 0
            if not is_blocked(title, count, name):
                return
        raise StopScraping(f'{name} 第 {page} 頁 Cloudflare 驗證逾時，已保留已完成進度')

    def get(self, name, page):
        cache = self.data / 'cache' / 'wiki' / name / f'page_{page}.html'
        if cache.exists():
            return cache.read_text(encoding='utf-8')
        if self.cdp is None:
            self.cdp = self.cdp_factory(self.port)
        self.throttle()
        url = WIKI + '?s=' + parse.quote(name)
        if page > 1:
            url += f'&paged={page}'
        self.navigations += 1
        print(f'導航：{name} 第 {page} 頁 {url}', flush=True)
        self.cdp.navigate(url)
        title = self.cdp.evaluate('document.title') or ''
        count = self.cdp.evaluate("document.querySelectorAll('article.entry-card').length") or 0
        if is_blocked(title, count, name):
            self.wait_for_verification(name, page)
        body = self.cdp.evaluate('document.documentElement.outerHTML') or ''
        if is_blocked(page_title(body), len(CARD.findall(body)), name):
            raise StopScraping(f'{name} 第 {page} 頁仍是驗證頁，停止')
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(body, encoding='utf-8')
        self.last_navigation = self.clock()
        return body

    def close(self):
        if self.cdp is not None:
            self.cdp.close()


def javdb_block_reason(body):
    title = page_title(body)
    if '登入' in title:
        return 'javdb 要求登入'
    if title.startswith(BLOCKED_TITLES):
        return 'javdb Cloudflare 驗證頁'
    return None


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class JavdbFetcher:
    def __init__(self, data):
        self.cache = data / 'cache' / 'javdb'
        self.cache.mkdir(parents=True, exist_ok=True)
        cookie_file = os.environ.get('JAVDB_COOKIE_FILE')
        self.cookie = Path(cookie_file).read_text(encoding='utf-8').strip() if cookie_file else None
        if self.cookie and any(ord(char) < 32 or ord(char) == 127 for char in self.cookie):
            raise StopScraping('JAVDB_COOKIE_FILE 格式錯誤：只接受單行')
        self.last_request = None
        self.opener = request.build_opener(NoRedirect)

    def get(self, path, page=None):
        key = path.strip('/').replace('/', '_')
        cache = self.cache / f'{key}{"_page_" + str(page) if page else ""}.html'
        if cache.exists():
            body = cache.read_text(encoding='utf-8')
        else:
            if self.last_request is not None:
                time.sleep(max(0, JAVDB_INTERVAL - (time.monotonic() - self.last_request)))
            headers = {'User-Agent': 'Mozilla/5.0'}
            if self.cookie:
                headers['Cookie'] = self.cookie
            url = JAVDB + path + (f'?page={page}' if page else '?locale=zh')
            self.last_request = time.monotonic()
            try:
                with self.opener.open(request.Request(url, headers=headers), timeout=30) as response:
                    body = response.read().decode('utf-8', errors='replace')
            except (error.HTTPError, error.URLError) as exc:
                raise StopScraping(f'javdb 請求失敗：{path}：{exc}') from None
            reason = javdb_block_reason(body)
            if reason:
                raise StopScraping(f'{reason}：{path}')
            cache.write_text(body, encoding='utf-8')
        reason = javdb_block_reason(body)
        if reason:
            raise StopScraping(f'{reason}：{path}')
        return body


def parse_javdb_males(body, actress_id):
    panel = next((value for label, value in JAVDB_PANEL.findall(body) if clean(label) == '演員'), '')
    names = []
    for attrs, name, _ in JAVDB_LINK.findall(panel):
        actor = re.search(r'href=["\']/actors/([A-Za-z0-9]+)["\']', attrs, re.I)
        if not actor or actor[1] == actress_id:
            continue
        classes = re.search(r'class=["\']([^"\']*)["\']', attrs, re.I)
        if not classes or 'actor-female' not in classes[1].split():
            names.append(clean(name))
    return list(dict.fromkeys(names))


def collect_javdb(actress_id, data):
    fetcher = JavdbFetcher(data)
    found = {}
    for page in range(1, 301):
        boxes = JAVDB_BOX.findall(fetcher.get(f'/actors/{actress_id}', page))
        if not boxes:
            break
        for path, code in boxes:
            found.setdefault(path, clean(code))
    else:
        raise StopScraping(f'javdb 演員 {actress_id} 超過 300 頁，停止')
    works = []
    for path, code in found.items():
        body = fetcher.get(path)
        match = DATE_JAVDB.search(body)
        works.append({'code': code, 'title': '', 'date': '', 'date_javdb': match[1] if match else '',
                      'url': JAVDB + path, 'code_inferred': False,
                      'males_wiki': None, 'males_javdb': parse_javdb_males(body, actress_id)})
    return works


def collect_wiki(name, fetcher):
    works, skipped, pages = {}, 0, 0
    known_aliases = set()
    for page in range(1, MAX_PAGES + 1):
        try:
            body = fetcher.get(name, page)
        except StopScraping:
            raise
        except (OSError, ValueError) as exc:
            raise StopScraping(f'{name} 第 {page} 頁失敗：{exc}') from exc
        cards = CARD.findall(body)
        if not cards:
            break
        for card in cards:
            _, performer, _ = parse_card(card)
            if normalize(name) in normalize(performer):
                known_aliases.update(re.findall(r'[（(]([^）)]+)[）)]', performer))
        parsed, skipped_here = parse_page(body, name, known_aliases)
        skipped += skipped_here
        for work in parsed:
            works.setdefault(work['code'] or work['url'], work)
        pages = page
        if not has_next(body):
            break
    else:
        raise StopScraping(f'{name} 已達每位女優 {MAX_PAGES} 頁安全上限，停止')
    return list(works.values()), pages, skipped


def add(args):
    ensure_settings(args.data)
    store = load_store(args.data)
    names = list(args.names)
    if args.file:
        names.extend(line.strip() for line in args.file.read_text(encoding='utf-8-sig').splitlines()
                     if line.strip() and not line.lstrip().startswith('#'))
    names = list(dict.fromkeys(names))
    if not names:
        raise ValueError('請提供女優名稱或 --file 名單')
    if args.javdb and len(names) != 1:
        raise ValueError('--javdb 只能搭配一位女優')
    fetcher = WikiFetcher(args.data, args.cdp_port)
    processed, consecutive_empty = 0, 0
    try:
        for name in names:
            if args.max is not None and processed >= args.max:
                break
            if name in store['actresses'] and not args.refresh:
                print(f'跳過已完成：{name}')
                continue
            works, pages, skipped = collect_wiki(name, fetcher)
            if args.javdb:
                by_code = {w['code']: w for w in works if w['code']}
                for work in collect_javdb(args.javdb, args.data):
                    if work['code'] in by_code:
                        by_code[work['code']]['males_javdb'] = work['males_javdb']
                        by_code[work['code']]['date_javdb'] = work['date_javdb']
                    else:
                        works.append(work)
            store['actresses'][name] = {'collected_at': datetime.now(timezone.utc).isoformat(),
                                        'pages': pages, 'skipped_irrelevant': skipped,
                                        'works': works}
            atomic_json(args.data / 'store.json', store)
            processed += 1
            consecutive_empty = consecutive_empty + 1 if pages == 0 else 0
            print(f'{name}：{len(works)} 部，{pages} 頁；略過 {skipped} 部(出演者不含該名)')
            if consecutive_empty >= 3:
                print('警告：連續 3 位女優沒有搜尋結果，可能名稱格式有誤或遭阻擋；已停止')
                break
    finally:
        fetcher.close()
    print(f'本次處理 {processed} 位；Chrome 導航 {fetcher.navigations} 次')


def build(args):
    ensure_settings(args.data)
    store = load_store(args.data)
    aliases = json.loads((args.data / 'aliases.json').read_text(encoding='utf-8'))
    noise = set(json.loads((args.data / 'noise.json').read_text(encoding='utf-8')))
    merged = {}
    for actress, entry in store['actresses'].items():
        for work in entry['works']:
            code = work.get('code') or work.get('url')
            if not code:
                continue
            item = merged.setdefault(code, {'code': code, 'date': '', 'title': '',
                                            'actresses': set(), 'wiki': None, 'javdb': set()})
            item['actresses'].add(actress)
            item['date'] = work.get('date_javdb') or item['date'] or work.get('date') or ''
            item['title'] = item['title'] or work.get('title') or ''
            if work.get('males_wiki') is not None:
                item['wiki'] = (item['wiki'] or set()) | set(work['males_wiki'])
            item['javdb'].update(work.get('males_javdb') or [])
    graph_works = []
    for item in merged.values():
        source = item['wiki'] if item['wiki'] is not None else item['javdb']
        males = sorted({aliases.get(name, name) for name in source} - noise)
        if males:
            graph_works.append({'code': item['code'], 'date': item['date'],
                                'title': item['title'], 'actresses': sorted(item['actresses']),
                                'males': males})
    graph_works.sort(key=lambda work: (work['date'], work['code']))
    actresses = [{'name': name,
                  'works': sum(name in work['actresses'] for work in graph_works),
                  'total_works': len({work.get('code') or work.get('url') for work in entry['works']})}
                 for name, entry in sorted(store['actresses'].items())]
    data = {'generated': date.today().isoformat(), 'actresses': actresses,
            'works': graph_works, 'total_works': len(merged), 'with_males': len(graph_works)}
    atomic_json(ROOT / 'graph_data.json', data)
    actor_works = {}
    for work in graph_works:
        for male in work['males']:
            actor_works.setdefault(male, []).append(work)
    with (ROOT / 'costars.csv').open('w', newline='', encoding='utf-8-sig') as output:
        writer = csv.writer(output)
        writer.writerow(['男優名', '合作作品數', '合作女優', '首次合作日', '最近合作日', '作品番號'])
        for male, works in sorted(actor_works.items(), key=lambda pair: (-len(pair[1]), pair[0])):
            writer.writerow([male, len(works), ';'.join(sorted({a for w in works for a in w['actresses']})),
                             min((w['date'] for w in works if w['date']), default=''),
                             max((w['date'] for w in works if w['date']), default=''),
                             ';'.join(w['code'] for w in works)])
    template = ROOT / 'graph_template.html'
    if not template.exists():
        raise FileNotFoundError(f'缺少模板：{template}；已產生 graph_data.json 與 costars.csv')
    marker = '/*__DATA__*/null'
    source = template.read_text(encoding='utf-8')
    if marker not in source:
        raise ValueError(f'模板缺少資料標記 {marker}：{template}')
    payload = json.dumps(data, ensure_ascii=False).replace('</', '<\\/')
    args.out.write_text(source.replace(marker, payload), encoding='utf-8')
    print(f'已產生：{ROOT / "costars.csv"}、{ROOT / "graph_data.json"}、{args.out}')
    print(f'作品 {data["total_works"]} 部；有男優 {data["with_males"]} 部；男優 {len(actor_works)} 位')
    print('前 5：' + '、'.join(f'{name} {len(works)}' for name, works in
                         sorted(actor_works.items(), key=lambda pair: (-len(pair[1]), pair[0]))[:5]))


def status(args):
    store = load_store(args.data)
    noise_path = args.data / 'noise.json'
    noise = set(json.loads(noise_path.read_text(encoding='utf-8'))) if noise_path.exists() else set(DEFAULT_NOISE)
    if not store['actresses']:
        print('尚無已蒐集女優')
    for name, entry in sorted(store['actresses'].items()):
        works = entry['works']
        with_males = sum(bool(set(work['males_wiki'] if work.get('males_wiki') is not None
                                       else work.get('males_javdb') or []) - noise) for work in works)
        javdb = any(work.get('males_javdb') is not None for work in works)
        print(f'{name}：作品 {len(works)}；有男優資料 {with_males}；最後蒐集 {entry["collected_at"]}；javdb {"有" if javdb else "無"}')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=ROOT / 'data', help='資料目錄')
    parser.add_argument('--cdp-port', type=int, default=9333, help='Chrome CDP 埠')
    commands = parser.add_subparsers(dest='command', required=True)
    add_parser = commands.add_parser('add', help='蒐集一位或多位女優')
    add_parser.add_argument('names', nargs='*', metavar='名稱')
    add_parser.add_argument('--file', type=Path, help='每行一位女優的 UTF-8 名單')
    add_parser.add_argument('--refresh', action='store_true')
    add_parser.add_argument('--javdb', metavar='演員ID')
    add_parser.add_argument('--max', type=int, metavar='N')
    build_parser = commands.add_parser('build', help='產生 CSV、JSON、HTML')
    build_parser.add_argument('--out', type=Path, default=ROOT / 'graph.html')
    commands.add_parser('status', help='顯示蒐集狀態')
    commands.add_parser('chrome', help='確認或啟動 Chrome CDP')
    for command in commands.choices.values():
        command.add_argument('--data', type=Path, default=argparse.SUPPRESS, help='資料目錄')
        command.add_argument('--cdp-port', type=int, default=argparse.SUPPRESS, help='Chrome CDP 埠')
    args = parser.parse_args(argv)
    if args.cdp_port < 1 or args.cdp_port > 65535:
        parser.error('--cdp-port 必須在 1 到 65535 之間')
    if args.command == 'add' and (args.max is not None and args.max < 0 or
                                  args.javdb and not re.fullmatch(r'[A-Za-z0-9]+', args.javdb)):
        parser.error('--max 不可為負；--javdb 演員 ID 須為英數')
    try:
        if args.command == 'add':
            add(args)
        elif args.command == 'build':
            build(args)
        elif args.command == 'status':
            status(args)
        else:
            ensure_chrome(args.cdp_port)
    except (StopScraping, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f'停止：{exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    sys.exit(main())
