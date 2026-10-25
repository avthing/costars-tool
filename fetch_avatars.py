"""只從指定圖床依演員代碼下載大頭貼原圖，可重複執行。"""

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """拒絕任何轉址，確保請求只落在指定圖床網址。"""

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def fetch(actors_path, overrides_path, folder, opener=None, pause=time.sleep):
    if opener is None:
        built = urllib.request.build_opener(NoRedirect)
        built.addheaders = [("User-Agent", "costars-tool/1.0 (personal use)")]  # 圖床會擋 Python 預設 UA；不偽裝瀏覽器
        opener = built.open
    actors = json.loads(Path(actors_path).read_text(encoding="utf-8"))
    overrides = json.loads(Path(overrides_path).read_text(encoding="utf-8")) if Path(overrides_path).exists() else {}
    # JavDB 沒頭像的人 img 會是 images/actor_unknow.jpg，依代碼組的網址不存在（403），直接略過
    codes = {item["id"] for item in actors if "/avatars/" in item.get("img", "")} | set(overrides.values())
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    downloaded, existing, failed = 0, 0, []
    last_request_end = None
    for code in sorted(codes):
        if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9]+", code):
            failed.append((str(code), "代碼格式錯誤"))
            continue
        path = folder / f"{code}.jpg"
        if path.exists():
            existing += 1
            continue
        url = f"https://c0.jdbstatic.com/avatars/{code[:2].lower()}/{code}.jpg"
        for attempt in range(2):
            if last_request_end is not None:
                pause(max(0, 0.4 - (time.monotonic() - last_request_end)))
            try:
                with opener(url, timeout=15) as response:
                    content = response.read()
                path.write_bytes(content)
                downloaded += 1
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 403:
                    print(f"圖床回傳 403，已立即停止：{code}")
                    return downloaded, existing, failed, True
                if attempt == 1:
                    failed.append((code, f"HTTP {exc.code}"))
            except (OSError, urllib.error.URLError) as exc:
                reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
                if getattr(reason, "winerror", None) == 10061:
                    print(f"圖床連線遭拒，已立即停止：{code}")
                    return downloaded, existing, failed, True
                if attempt == 1:
                    failed.append((code, str(exc)))
            finally:
                last_request_end = time.monotonic()
    return downloaded, existing, failed, False


def main():
    downloaded, existing, failed, blocked = fetch(
        ROOT / "data" / "javdb_actors.json", ROOT / "data" / "javdb_ids.json", ROOT / "data" / "avatars"
    )
    print(f"大頭貼：新增 {downloaded}、既有 {existing}、失敗 {len(failed)}")
    for code, reason in failed:
        print(f"  {code}：{reason}")
    return 2 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
