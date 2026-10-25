"""將多女優合併資料打包成可離線開啟的單一 HTML 檔。"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PLACEHOLDER = "/*__DATA__*/null"
DESKTOP_NAME = "合作關聯圖.html"
# 範本裡的函式庫佔位符 → vendor\ 下對應檔案（嵌進單一 HTML，離線可用）；範本沒有該佔位符就略過
VENDOR = {"/*__VENDOR_THREE__*/": "three.min.js", "/*__VENDOR_ANIME__*/": "anime.min.js"}


class BuildError(Exception):
    """輸入或輸出無法完成時顯示給使用者的錯誤。"""


def build(template_path, data_path, out_path, desktop_dir, vendor_dir=None):
    """驗證輸入、原子寫入 HTML，並視需要複製至桌面。"""
    template_path = Path(template_path)
    data_path = Path(data_path)
    out_path = Path(out_path)

    try:
        template = template_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise BuildError(f"範本檔不存在：{template_path}") from exc
    except (OSError, UnicodeError) as exc:
        raise BuildError(f"無法讀取範本檔：{template_path}：{exc}") from exc

    count = template.count(PLACEHOLDER)
    if count != 1:
        raise BuildError(f"範本佔位符必須恰好出現一次，實際為 {count} 次：{template_path}")

    try:
        data = json.loads(data_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BuildError(f"資料檔不存在：{data_path}") from exc
    except json.JSONDecodeError as exc:
        raise BuildError(f"資料檔不是合法 JSON：{data_path}：{exc}") from exc
    except (OSError, UnicodeError) as exc:
        raise BuildError(f"無法讀取資料檔：{data_path}：{exc}") from exc

    try:
        actresses = data["actresses"]
        works = data["works"]
        male_names = {male for work in works for male in work["males"]}
        if not isinstance(actresses, list) or not isinstance(works, list):
            raise TypeError
    except (TypeError, KeyError) as exc:
        raise BuildError(f"資料格式錯誤，需包含 actresses、works 與 works[].males：{data_path}") from exc

    vendor_dir = Path(vendor_dir) if vendor_dir is not None else ROOT / "vendor"
    for marker, name in VENDOR.items():
        if marker not in template:
            continue
        try:
            code = (vendor_dir / name).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise BuildError(f"範本需要函式庫但無法讀取：{vendor_dir / name}：{exc}") from exc
        if "</script" in code.lower():
            raise BuildError(f"函式庫含有 </script，無法安全嵌入：{name}")
        template = template.replace(marker, code)

    embedded_data = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    embedded_data = embedded_data.replace(PLACEHOLDER, "/*__DATA__*\\/null")
    html = template.replace(PLACEHOLDER, embedded_data)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", delete=False,
            dir=out_path.parent, prefix=f".{out_path.name}.", suffix=".tmp",
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(html)
        os.replace(temp_path, out_path)
    except OSError as exc:
        raise BuildError(f"無法寫入輸出檔：{out_path}：{exc}") from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    desktop_path = None
    if desktop_dir is not None:
        desktop_dir = Path(desktop_dir)
        if not desktop_dir.is_dir():
            print(f"警告：桌面資料夾不存在，略過複製：{desktop_dir}")
        else:
            desktop_path = desktop_dir / DESKTOP_NAME
            try:
                if desktop_path.resolve() != out_path.resolve():
                    shutil.copyfile(out_path, desktop_path)
            except OSError as exc:
                raise BuildError(f"無法複製桌面檔：{desktop_path}：{exc}") from exc

    out_size = out_path.stat().st_size
    desktop_size = desktop_path.stat().st_size if desktop_path else None
    print(
        f"完成：女優 {len(actresses)} 人、作品 {len(works)} 部、男優 {len(male_names)} 人；"
        f"{out_path} {out_size} 位元組；"
        + (f"{desktop_path} {desktop_size} 位元組" if desktop_path else "桌面檔未建立（0 位元組）")
    )
    return out_size, desktop_size


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "graph_data_multi.json")
    parser.add_argument("--out", type=Path, default=ROOT / "graph.html")
    parser.add_argument("--desktop", type=Path, default=Path.home() / "Desktop")
    parser.add_argument("--no-merge", action="store_true")
    parser.add_argument("--no-desktop", action="store_true")
    args = parser.parse_args(argv)

    if not args.no_merge:
        try:
            result = subprocess.run(
                [sys.executable, "-X", "utf8", str(ROOT / "merge_multi.py"), "--out", str(args.data)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
        except OSError as exc:
            print(f"執行合併程式失敗：{exc}", file=sys.stderr)
            return 1
        if result.returncode != 0:
            sys.stdout.buffer.write(result.stdout)
            sys.stdout.buffer.flush()
            sys.stderr.buffer.write(result.stderr)
            sys.stderr.buffer.flush()
            return result.returncode

    try:
        build(ROOT / "graph_template.html", args.data, args.out,
              None if args.no_desktop else args.desktop)
    except BuildError as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
