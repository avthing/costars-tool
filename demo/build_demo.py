"""用 Wikidata（CC0）的電影演員資料，建出公開可放的示範頁（007／不可能任務／漫威）。

流程：Wikidata SPARQL（一次查詢）→ demo/wikidata_cache.json → 依知名度篩選並轉成與正式資料相同的格式
→ 把介面用語換成「女演員／男演員」→ 以 build_local.build 打包成單一 HTML（site/index.html）。

知名度＝該演員在維基百科有幾種語言版本（Wikidata 的 sitelinks）；路人小角色通常幾乎沒有。
"""

import argparse
import collections
import datetime
import json
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build_local  # noqa: E402

CACHE = ROOT / "demo" / "wikidata_cache.json"
DATA = ROOT / "demo" / "graph_data_demo.json"
OUT = ROOT / "site" / "index.html"
ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = "costars-demo/1.0 (open-source demo data; single polite query)"
SERIES = ["James Bond", "Mission: Impossible", "Marvel Cinematic Universe"]
FEMALE, MALE = "Q6581072", "Q6581097"
TERMS = (("女優", "女演員"), ("男優", "男演員"))
TITLE = "女演員 × 男演員 合作關聯圖（示範：007／不可能任務／漫威）"

QUERY = """
SELECT ?seriesLabel ?film ?filmLabel ?date ?actor ?actorLabel ?gender ?links WHERE {
  VALUES ?name { %s }
  ?series rdfs:label ?name .
  ?film wdt:P179 ?series ; wdt:P577 ?date ; wdt:P161 ?actor .
  ?actor wdt:P21 ?gender ; wikibase:sitelinks ?links .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
""" % " ".join(f'"{s}"@en' for s in SERIES)


def qid(uri):
    return uri.rsplit("/", 1)[-1]


def fetch():
    url = ENDPOINT + "?" + urllib.parse.urlencode({"query": QUERY, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            bindings = json.load(resp)["results"]["bindings"]
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise SystemExit(f"Wikidata 限流（每分鐘 1 次查詢），請 {exc.headers.get('Retry-After', '60')} 秒後再試。")
        raise
    rows = {}
    for b in bindings:
        v = {k: x["value"] for k, x in b.items()}
        # 同一部片同一位演員只留一列、取最早上映日；只存需要的欄位
        key = (qid(v["film"]), qid(v["actor"]))
        row = {"s": v["seriesLabel"], "f": key[0], "ft": v["filmLabel"], "d": v["date"][:10],
               "a": key[1], "an": v["actorLabel"], "g": qid(v["gender"]), "l": int(v["links"])}
        if key not in rows or rank(row["d"]) < rank(rows[key]["d"]):
            rows[key] = row
    out = list(rows.values())
    CACHE.write_text(json.dumps({"fetched": datetime.date.today().isoformat(), "rows": out}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return out


def rank(date):
    # 只有年份的日期在 Wikidata 會變成 1 月 1 日；有完整月日的日期優先，其次取最早
    return (date.endswith("-01-01"), date)


def has_label(name):
    # 沒有英文標籤時 Wikidata 會回傳 Q 開頭的代號，這種人略過
    return not (name[:1] == "Q" and name[1:].isdigit())


def convert(rows, min_links):
    films = {}  # film qid -> {title, date, female:set, male:set}
    today = datetime.date.today().isoformat()
    for r in rows:
        if r["l"] < min_links or r["g"] not in (FEMALE, MALE) or not has_label(r["an"]) or not has_label(r["ft"]):
            continue
        d = r["d"]
        if len(d) != 10 or d[0] == "-" or d > today:  # 日期不合法或尚未上映
            continue
        f = films.setdefault(r["f"], {"title": r["ft"], "date": d, "female": set(), "male": set()})
        f["date"] = min(f["date"], d, key=rank)
        f["female" if r["g"] == FEMALE else "male"].add(r["an"])

    works = []
    for k, f in sorted(films.items(), key=lambda kv: (kv[1]["date"], kv[0])):
        if f["female"] and f["male"]:
            works.append({"code": f"{f['title']} ({f['date'][:4]})", "date": f["date"], "title": f["title"], "actresses": sorted(f["female"]), "males": sorted(f["male"])})

    count = collections.Counter(a for w in works for a in w["actresses"])
    return {
        "generated": datetime.date.today().isoformat(),
        "actresses": [{"name": a, "works": n, "total_works": n} for a, n in count.most_common()],
        "works": works,
        "total_works": len(works),
        "with_males": len(works),
        "javdb": {}, "avatars": {}, "wiki": {},
    }


def build_page(data_path, out_path):
    template = (ROOT / "graph_template.html").read_text(encoding="utf-8")
    for old, new in TERMS:
        template = template.replace(old, new)
    old_note = "部查得到男演員資料；次數是下限。`"
    assert template.count(old_note) == 1
    template = template.replace(old_note, "部查得到男演員資料；次數是下限。資料來源：Wikidata（CC0）。`")
    old_title = "<title>女演員 × 男演員 合作關聯圖</title>"
    assert template.count(old_title) == 1
    template = template.replace(old_title, f"<title>{TITLE}</title>")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tpl = Path(tmp) / "template.html"
        tpl.write_text(template, encoding="utf-8")
        return build_local.build(tpl, data_path, out_path, None, vendor_dir=ROOT / "vendor")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh", action="store_true", help="重新向 Wikidata 查詢（預設用快取）")
    ap.add_argument("--min-links", type=int, default=40, help="演員至少要有幾種維基百科語言版本才收錄（預設 40）")
    args = ap.parse_args(argv)

    rows = fetch() if args.refresh or not CACHE.exists() else json.loads(CACHE.read_text(encoding="utf-8"))["rows"]
    data = convert(rows, args.min_links)
    DATA.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    males = {m for w in data["works"] for m in w["males"]}
    print(f"快取列數 {len(rows)}；女演員 {len(data['actresses'])}、電影 {len(data['works'])}、男演員 {len(males)}")
    build_page(DATA, OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
