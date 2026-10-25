# 合作關聯圖（costars-tool）

把女優與男優的合作作品畫成可互動的關聯圖：單一 HTML 檔、完全離線，用 Three.js（WebGL）與 anime.js 繪製。

- 2D／3D／4D：選一個人當原點，距離代表合作次數（對數刻度）；4D 的垂直軸是時間
- 時間軸可播放、拖曳、點年份跳轉
- 統計面板：逐月累計的長條圖競賽與四張統計卡
- 互動導覽（工具列「？」）

## 這個 repo 只有程式碼

**不含任何爬回來的資料、快取或頭像。** 資料請自行蒐集，並請遵守來源網站的使用條款與著作權。

## 使用方式

需求：Python 3、Node.js、一個以遠端偵錯埠啟動的 Chrome（預設 `127.0.0.1:9333`）。

1. 蒐集作品資料：`node wiki_collect.mjs --file names/<名單檔>`（每行一位，格式 `顯示名<TAB>候選寫法1|候選寫法2`）。程式內建節流，遇到驗證頁只會等你自己通過，不會繞過。
2. 合併並建置：`python -X utf8 build_local.py`
   - 產生 `graph.html`，並複製到桌面；`--no-desktop` 不複製，`--no-merge` 不重新合併資料
3. 測試：`python -X utf8 -m unittest`

## 授權

[GNU AGPL-3.0](LICENSE)，Copyright (C) 2026 AVthing。
`vendor/` 內的 three.js、anime.js 為 MIT 授權，授權聲明隨檔附上（`three.LICENSE.txt`、`anime.LICENSE.txt`）。
