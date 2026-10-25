// 增量更新（--update）的純函式：不碰網路與檔案，可離線測試。

// 最小 RFC-4180 解析（BOM、CRLF、雙引號跳脫）
export function parseCsv(text) {
  const src = text.replace(/^﻿/, "");
  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < src.length; i++) {
    const ch = src[i];
    if (quoted) {
      if (ch === '"' && src[i + 1] === '"') { cell += '"'; i++; }
      else if (ch === '"') quoted = false;
      else cell += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ",") { row.push(cell); cell = ""; }
    else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && src[i + 1] === "\n") i++;
      row.push(cell); cell = "";
      rows.push(row); row = [];
    } else cell += ch;
  }
  if (cell !== "" || row.length) { row.push(cell); rows.push(row); }
  return rows.filter((r) => r.length > 1 || r[0] !== "");
}

// CSV 一列 → 與 parseCardsFromHtml 相同形狀的作品物件（欄位順序見 buildCsvContent）
export function csvToCards(text) {
  return parseCsv(text).slice(1).map((r) => ({
    title: r[0] || "", makerCode: r[1] || "", deliveryCode: r[2] || "",
    releaseDate: r[3] || "", saleDate: r[4] || "", performerText: r[5] || "",
    danyuText: r[6] || "", tags: r[7] || "", url: r[8] || ""
  }));
}

// 一部作品的唯一鍵：優先用文章網址，沒有才用品番＋標題
export function cardKey(card) {
  return card.url || `${card.makerCode}|${card.deliveryCode}|${card.title}`;
}

// 單一搜尋頁的判定：newCards＝與該女優相關且尚未收錄；stop＝這頁已沒有新作，不必再往舊的翻
export function judgePage(cards, isRelevant, known) {
  const newCards = [];
  const seen = new Set();
  for (const c of cards) {
    if (!isRelevant(c)) continue;
    const k = cardKey(c);
    if (known.has(k) || seen.has(k)) continue;
    seen.add(k);
    newCards.push(c);
  }
  return { newCards, stop: newCards.length === 0 };
}
