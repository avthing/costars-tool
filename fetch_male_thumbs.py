"""從 男優資料.txt 解析男優縮圖網址並下載，可重複執行；遇到封鎖（403／429／HTML 驗證頁）立即停止，不繞過。"""

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ALLOWED = "https://avdanyuwiki.com/wp-content/uploads/"
ITEM = re.compile(r'<div class="image-tag-item"><a [^>]*href="([^"]+)"[^>]*><img [^>]*?src="([^"]+)"')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """拒絕任何轉址，確保請求只落在指定網址。"""

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def parse(html):
    """回傳 [(標籤頁網址, 縮圖網址)]，只收允許前綴下的縮圖。"""
    return [(tag, img) for tag, img in ITEM.findall(html) if img.startswith(ALLOWED)]


def slug(tag_url):
    return urllib.parse.unquote(tag_url.rstrip("/").rsplit("/", 1)[-1]).lower()


def fetch(items, folder, opener=None, pause=time.sleep, gap=1.5):
    if opener is None:
        built = urllib.request.build_opener(NoRedirect)
        built.addheaders = [("User-Agent", "costars-tool/1.0 (personal use)")]  # 誠實 UA，不偽裝瀏覽器
        opener = built.open
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    mapping, downloaded, existing, failed = {}, 0, 0, []
    last_end = None
    for tag, img in items:
        ext = img.rsplit(".", 1)[-1].lower()
        name = re.sub(r"[^a-z0-9_-]", "_", slug(tag)) + "." + ext
        path = folder / name
        if path.exists():
            mapping[tag] = name
            existing += 1
            continue
        if last_end is not None:
            pause(max(0, gap - (time.monotonic() - last_end)))
        try:
            with opener(img, timeout=20) as response:
                kind = response.headers.get("Content-Type", "")
                content = response.read()
            if not kind.startswith("image/"):
                print(f"回傳非圖片（{kind}），疑似驗證頁，已立即停止：{img}")
                return mapping, downloaded, existing, failed, True
            path.write_bytes(content)
            mapping[tag] = name
            downloaded += 1
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429):
                print(f"HTTP {exc.code}，已立即停止：{img}")
                return mapping, downloaded, existing, failed, True
            failed.append((img, f"HTTP {exc.code}"))
        except (OSError, urllib.error.URLError) as exc:
            failed.append((img, str(exc)))
        finally:
            last_end = time.monotonic()
    return mapping, downloaded, existing, failed, False


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "Desktop" / "男優資料.txt"
    items = parse(src.read_text(encoding="utf-8"))
    folder = ROOT / "data" / "avatars_male"
    mapping, downloaded, existing, failed, blocked = fetch(items, folder)
    out = ROOT / "data" / "male_thumbs.json"
    out.write_text(json.dumps(mapping, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"男優縮圖：解析 {len(items)}、新增 {downloaded}、既有 {existing}、失敗 {len(failed)}")
    for img, reason in failed:
        print(f"  {img}：{reason}")
    return 2 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
