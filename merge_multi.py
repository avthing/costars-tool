"""多女優合併：把各女優的 wiki_works CSV 併成關聯圖用的 graph_data.json。
男優 = 「出演男優文字」與 wiki tag 的聯集；文字（藝名）與 tag（wiki 正式名）在同一作品逐一對照出別名，
同一人以 tag 為準合併。已發佈的河北彩花資料沿用現有 graph_data.json（含 javdb 日期），新女優只用 wiki。
用法：python merge_multi.py [--out graph_data_multi.json] [名字…]；不給名字就讀 data\\resolved_names.json
"""
import argparse
import base64
import csv
import datetime
import io
import json
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
NOISE = {"主観", "完全主観", "素人", "ASMR", "覆面", "ハメ撮り"}
# 人工確認過的別名（text → wiki 正式名），與 costars-merged\build.py 一致
ALIASES = {"清水健": "しみけん", "タイ": "ダイ", "優生": "優生×", "ムールかいせ": "ムールかいせ×", "羽田": "羽田貴史",
           "ニック": "にっく", "えりぐち": "舘つよし", "平ボンド": "中平くん", "くりぼ": "村田謙", "小梅": "千歳小梅",
           "エンツ": "成上奏", "タラオ": "トイボーイ相沢", "じゅうもんじ": "十文字隼人", "ハカー": "コグレハルト"}
# 顯示成「wiki 正式名（藝名）」。key 一律是 wiki 正式名
DISPLAY = {"にっく": "にっく（ニック）", "舘つよし": "舘つよし（えりぐち）", "中平くん": "中平くん（平ボンド）", "村田謙": "村田謙（くりぼ）",
           "千歳小梅": "千歳小梅（小梅）", "成上奏": "成上奏（エンツ）", "トイボーイ相沢": "トイボーイ相沢（タラオ）",
           "十文字隼人": "十文字隼人（じゅうもんじ）", "コグレハルト": "コグレハルト（ハカー）"}
_POV = re.compile(r"^主観[（(](.+)[）)]$")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_VARIANT = str.maketrans({"遙": "遥", "亞": "亜", "澤": "沢", "濱": "浜", "齋": "斎", "齊": "斉", "瀨": "瀬", "櫻": "桜", "戶": "戸", "國": "国", "實": "実", "惠": "恵", "德": "徳", "兒": "児", "學": "学", "廣": "広", "彌": "弥", "會": "会", "藝": "芸", "龍": "竜"})


def fz(s):
    """將人名統一為可比對的寫法。"""
    s = unicodedata.normalize("NFKC", str(s)).lower()
    s = "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)
    return re.sub(r"[\s・･·.\-_ー]", "", s).translate(_VARIANT)


def match_javdb(actresses, works, resolved, actors, overrides):
    """回傳標籤代碼、未配對資料與歧義；手動標籤覆寫優先。"""
    female = {a["name"] for a in actresses}
    male = {m for w in works for m in w["males"]}
    labels = female | male
    index = defaultdict(dict)

    def add(name, label, priority=1):
        key = fz(name)
        if key:
            index[key][label] = max(priority, index[key].get(label, 0))

    for a in actresses:
        add(a["name"], a["name"], 2)
        for alias in a.get("aka", []):
            add(alias, a["name"])
    for key, item in resolved.items():
        label = item.get("wiki_name") or key
        if label in female:
            add(key, label)
            add(item.get("wiki_name") or key, label, 2)
    for label in male:
        add(label, label, 2)
        match = re.search(r"[（(]([^）)]*)[）)]$", label)
        if match:
            add(label[:match.start()], label, 2)
            add(match.group(1), label)

    chosen, missed, ambiguous = {}, [], []
    for actor in actors:
        hits = {}
        for name in [*actor.get("names", []), actor.get("label", "")]:
            for label, priority in index.get(fz(name), {}).items():
                hits[label] = max(priority, hits.get(label, 0))
        if len(hits) > 1:
            ambiguous.append((actor["label"], sorted(hits)))
        elif hits:
            label = next(iter(hits))
            chosen.setdefault(label, []).append((hits[label], actor))
        else:
            missed.append(actor["label"])
    id_hits = defaultdict(set)
    for label, options in chosen.items():
        for _, actor in options:
            id_hits[actor["id"]].add(label)
    for code, labels_for_id in id_hits.items():
        if len(labels_for_id) > 1:
            ambiguous.append((code, sorted(labels_for_id)))
            for label in labels_for_id:
                chosen[label] = [(priority, actor) for priority, actor in chosen[label] if actor["id"] != code]
    ids = {}
    for label, options in chosen.items():
        if not options:
            continue
        best = max(priority for priority, _ in options)
        winners = [actor for priority, actor in options if priority == best]
        if len(winners) == 1:
            ids[label] = winners[0]["id"]
        else:
            ambiguous.extend((actor["label"], [label]) for actor in winners)
    ids.update({label: code for label, code in overrides.items() if label in labels})
    return ids, missed, ambiguous, female, male - female


def pack_avatars(ids, folder, name=lambda code: f"{code}.jpg"):
    """將現有原圖裁成偏上的正方形，壞檔僅回報。"""
    packed, skipped = {}, []
    for label, code in ids.items():
        path = folder / name(code)
        try:
            with Image.open(path) as source:
                source = source.convert("RGB")
                width, height = source.size
                side = min(width, height)
                left = (width - side) // 2
                top = min(height - side, int(height * 0.15))
                cropped = source.crop((left, top, left + side, top + side))
                out = io.BytesIO()
                cropped.resize((96, 96), Image.Resampling.LANCZOS).save(out, format="JPEG", quality=75)
                packed[label] = "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode("ascii")
        except (OSError, ValueError):
            skipped.append(label)
    return packed, skipped


def read_resolved(path):
    """爬蟲可能正在寫檔；讀到不完整 JSON 時稍後重試。"""
    for attempt in range(5):
        try:
            return json.loads(path.read_text(encoding="utf-8")).get("resolved", {})
        except json.JSONDecodeError:
            if attempt == 4:
                raise
            time.sleep(0.2)


def norm(s):
    """比對用：全形半形、片假名平假名、結尾的 ×、括號註記視為相同。"""
    s = unicodedata.normalize("NFKC", s).lower()
    s = re.sub(r"\(.*?\)$", "", s).rstrip("×x✕ ")
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)


def clean(name):
    """去掉 wiki 文字裡的雜訊寫法：『主観(某人)』→ 某人；只有符號（???、.）的丟掉。"""
    name = name.strip()
    m = _POV.match(name)
    if m:
        name = m.group(1).strip()
    if not name or re.fullmatch(r"[\W_]+", name):
        return ""
    return name


def tokens(text):
    return [c for c in (clean(x) for x in re.split(r"[\s,、，/／]+", text.strip())) if c]


def norm_code(code):
    """品番正規化：1STARS00736 → STARS-736；已是 XXX-123 的維持。"""
    code = code.strip().upper()
    if re.fullmatch(r"[A-Z0-9]+-\d+[A-Z]?", code):
        return code
    m = re.fullmatch(r"\d?([A-Z]+?)0*(\d+)([A-Z]*)", code)
    return f"{m.group(1)}-{m.group(2)}{m.group(3)}" if m else code


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    head = rows[0]
    return [dict(zip(head, r)) for r in rows[1:]]


def pick_date(*cands):
    """第一個真的是日期的欄位（商品発売日 不明時 wiki 填「—-」）。"""
    for c in cands:
        c = (c or "").strip().replace("/", "-")
        if _DATE.fullmatch(c):
            return c
    return ""


def load_actress(name, path=None):
    """回傳 ([{code,date,title,text,tags}], 無日期品番清單)。"""
    rows = read_csv(path or ROOT / "data" / f"wiki_works_{name}.csv")
    upd = ROOT / "data" / "updates" / f"wiki_works_{name}.csv"  # --update 增量模式另存的新作
    if path is None and upd.exists():
        seen = {norm_code(r.get("メーカー品番") or r.get("配信品番") or "") for r in rows}
        for r in read_csv(upd):
            code = norm_code(r.get("メーカー品番") or r.get("配信品番") or "")
            if code not in seen:  # 日後主 CSV 若已收進同一部就不重複計
                seen.add(code)
                rows.append(r)
    out, nodate = [], []
    for r in rows:
        code = norm_code(r.get("メーカー品番") or r.get("配信品番") or "")
        if not code:
            continue
        date = pick_date(r.get("商品発売日"), r.get("配信開始日"))
        if not date:
            nodate.append(code)
            continue
        tags = [c for c in (clean(x) for x in (r.get("男優 tag 清單") or "").split(",")) if c]
        out.append({"code": code, "date": date, "title": r.get("標題", ""), "text": tokens(r.get("出演男優文字", "")), "tags": tags})
    return out, nodate


def infer_aliases(all_works):
    """同一作品內，文字獨有的名字與 tag 獨有的名字逐一對照。回傳 (pairs{text:tag}, 證據作品數, 衝突, 未配對)。"""
    def one_pass(known):
        votes = defaultdict(Counter)
        unmatched = Counter()
        for w in all_works:
            text = [known.get(t, ALIASES.get(t, t)) for t in w["text"] if t not in NOISE]
            tags = [t for t in w["tags"] if t not in NOISE]
            t_only = [t for t in text if t not in tags]
            g_only = [t for t in tags if t not in text]
            # 文字寫法與 tag 只差在假名／全半形／結尾 ×：直接視為同一人
            for t in list(t_only):
                hit = [g for g in g_only if norm(g) == norm(t)]
                if hit:
                    votes[t][hit[0]] += 1
                    t_only.remove(t)
                    g_only.remove(hit[0])
            if len(t_only) == 1 and len(g_only) == 1:
                votes[t_only[0]][g_only[0]] += 1
            else:
                for x in t_only + g_only:
                    unmatched[x] += 1
        return votes, unmatched

    # 多輪：先收下一對一的確定配對，再用它們縮小「多人對不上」作品的範圍，直到沒有新配對
    pairs = {}
    for _ in range(6):
        votes, unmatched = one_pass(pairs)
        new = {t: next(iter(c)) for t, c in votes.items() if len(c) == 1 and t not in pairs}
        if not new:
            break
        pairs.update(new)
    votes, unmatched = one_pass(pairs)
    conflicts = [(t, dict(c)) for t, c in votes.items() if len(c) > 1]
    evidence = {t: sum(1 for w in all_works if t in w["text"] and g in w["tags"]) for t, g in pairs.items()}
    return pairs, evidence, conflicts, unmatched


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("actresses", nargs="*", help="不給就讀 data\\resolved_names.json 裡已完成的女優")
    ap.add_argument("--out", default=str(ROOT / "graph_data_multi.json"))
    ap.add_argument("--base", default=str(ROOT / "graph_data.json"), help="已發佈的河北彩花資料（new schema）")
    ap.add_argument("--apply-single", action="store_true", help="連只有單一證據、名字也不相似的配對一併套用（預設只列出）")
    a = ap.parse_args()

    # (檔名用的顯示名, 圖上標籤)：標籤用 wiki 的日文名，與男優以 wiki 為準一致
    resolved = read_resolved(ROOT / "data" / "resolved_names.json")
    if a.actresses:
        targets = [(n, n) for n in a.actresses]
    else:
        targets = [(k, v.get("wiki_name") or k) for k, v in resolved.items()
                   if v.get("done", True) and (ROOT / "data" / f"wiki_works_{k}.csv").exists()]
    per, nodate = {}, {}
    for key, label in targets:
        ws, nd = load_actress(key)
        per.setdefault(label, []).extend(ws)
        nodate.setdefault(label, []).extend(nd)
    base = json.loads(Path(a.base).read_text(encoding="utf-8")) if Path(a.base).exists() else {"works": [], "actresses": []}

    pairs, evidence, conflicts, unmatched = infer_aliases([w for ws in per.values() for w in ws])
    applied, held = {}, {}
    for t, g in pairs.items():
        if t in ALIASES or t == g:
            continue
        (applied if evidence[t] >= 2 or norm(t) == norm(g) or a.apply_single else held)[t] = g
    for t, g in applied.items():
        ALIASES[t] = g
        if norm(t) != norm(g) and g not in DISPLAY:
            DISPLAY[g] = f"{g}（{t}）"

    def key(n):  # 同一人的唯一 key = wiki 正式名；已發佈資料裡的「正式名（藝名）」也還原成 key
        n = re.sub(r"（[^）]*）$", "", n)
        return ALIASES.get(n, n)

    works = {}
    for w in base["works"]:  # 河北彩花：名稱先還原成 key，最後再統一加顯示名
        works[w["code"]] = {"code": w["code"], "date": w["date"], "title": w.get("title", ""),
                            "actresses": list(w["actresses"]), "males": {key(m) for m in w["males"]}}
    summary = {}
    for name, ws in per.items():
        with_males = 0
        for w in ws:
            males = {key(n) for n in set(w["text"]) | set(w["tags"])} - NOISE
            if not males:
                continue
            with_males += 1
            cur = works.setdefault(w["code"], {"code": w["code"], "date": w["date"], "title": w["title"], "actresses": [], "males": set()})
            if name not in cur["actresses"]:
                cur["actresses"].append(name)
            cur["males"] |= males
        summary[name] = (len(ws), with_males)

    out_works = [dict(w, males=sorted(DISPLAY.get(m, m) for m in w["males"]))
                 for w in sorted(works.values(), key=lambda x: (x["date"], x["code"]))]
    # 搜尋別名：名單檔裡使用者慣用的寫法（如 高崎聖子 → 高橋しょう子），給圖上的模糊搜尋用
    aka = {}
    for k, label in targets:
        if k != label:
            aka.setdefault(label, []).append(k)
    jp = ROOT / "data" / "javdb_ids.json"  # {圖上標籤: javdb 演員代碼}，手動覆寫優先
    raw_ids = json.loads(jp.read_text(encoding="utf-8")) if jp.exists() else {}
    actor_path = ROOT / "data" / "javdb_actors.json"
    actors = json.loads(actor_path.read_text(encoding="utf-8")) if actor_path.exists() else []
    actresses = [dict(x) for x in base.get("actresses", [])]
    for name, (total, wm) in summary.items():
        actresses.append({"name": name, "works": wm, "total_works": total})
    for x in actresses:
        if aka.get(x["name"]):
            x["aka"] = aka[x["name"]]
    javdb_ids, missed, ambiguous, female, male = match_javdb(actresses, out_works, resolved, actors, raw_ids)
    javdb_ids = {k: v for k, v in javdb_ids.items() if k in female}  # 男優不連 JavDB，改連 avdanyuwiki 標籤頁
    avatars, skipped = pack_avatars(javdb_ids, ROOT / "data" / "avatars")
    # 男優連結：data\wiki_male_tags.json（使用者提供的 avdanyuwiki 男優標籤清單 {name,url,count}）
    mp = ROOT / "data" / "wiki_male_tags.json"
    tags = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else []
    wiki_ids, wiki_missed, wiki_amb, _, _ = match_javdb([], out_works, {}, [{"id": t["url"], "names": [t["name"]], "label": t["name"]} for t in tags], {})
    # 男優縮圖：fetch_male_thumbs.py 下載到 data\avatars_male，male_thumbs.json 為 {標籤頁網址: 檔名}；沒有檔就維持無頭像
    tp = ROOT / "data" / "male_thumbs.json"
    thumbs = json.loads(tp.read_text(encoding="utf-8")) if tp.exists() else {}
    male_ids = {label: thumbs[url] for label, url in wiki_ids.items() if url in thumbs}
    male_avatars, male_skipped = pack_avatars(male_ids, ROOT / "data" / "avatars_male", name=lambda f: f)
    avatars.update(male_avatars)
    data = {"generated": datetime.date.today().isoformat(), "actresses": actresses, "works": out_works,
            "total_works": sum(x["total_works"] for x in actresses), "with_males": len(out_works),
            "javdb": javdb_ids, "avatars": avatars, "wiki": wiki_ids}
    Path(a.out).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    cnt = Counter(m for w in out_works for m in w["males"])
    print(f"輸出 {a.out}：作品 {len(out_works)}、男優 {len(cnt)}、女優 {len(actresses)}")
    print(f"男優 wiki 連結：{len(wiki_ids)} / {len(male)} 位；標籤清單 {len(tags)} 筆中未配對 {len(wiki_missed)}：{wiki_missed[:40]}；歧義：{wiki_amb}")
    print(f"JavDB 配對：女優 {len(female & javdb_ids.keys())}、未配對 {len(missed)} 筆")
    print("JavDB 未配對：", missed)
    print("JavDB 歧義（未配對）：", ambiguous)
    print(f"大頭貼：{len(avatars)} 張（含男優 {len(male_avatars)}）；缺檔或壞檔：{skipped + male_skipped}")
    for name, (total, wm) in summary.items():
        print(f"  {name}: wiki 作品 {total}、有男優 {wm}、無日期略過 {nodate[name]}")
    print("本次套用的新別名（text→tag, 證據作品數）：", {t: (g, evidence[t]) for t, g in applied.items()})
    if held:
        print("【未套用】單一證據且名字不相似，請複核（確認後可加入 ALIASES，或用 --apply-single）：")
        for t, g in held.items():
            print(f"  {t} → {g}")
    if conflicts:
        print("別名衝突（未套用）：", conflicts)
    left = [(n, c) for n, c in unmatched.items() if n not in NOISE]
    if left:
        print("文字與 tag 對不上、未能配對的名字（可能是漏人、雜訊或多對多）：", sorted(left, key=lambda x: -x[1])[:30])
    print("前 15：", cnt.most_common(15))


if __name__ == "__main__":
    sys.exit(main())
