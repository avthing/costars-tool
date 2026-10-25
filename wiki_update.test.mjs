import test from "node:test";
import assert from "node:assert/strict";
import { parseCsv, csvToCards, cardKey, judgePage } from "./wiki_update.mjs";

const HEAD = "標題,メーカー品番,配信品番,配信開始日,商品発売日,出演者文字,出演男優文字,男優 tag 清單,文章網址";

test("parseCsv：BOM、CRLF、引號內的逗號／換行／雙引號", () => {
  const text = `﻿${HEAD}\r\n"A, ""B""\nC",X-1,,2024-01-01,2024-01-02,甲,乙,"乙, 丙",https://x/1\r\n`;
  const rows = parseCsv(text);
  assert.equal(rows.length, 2);
  assert.equal(rows[1][0], 'A, "B"\nC');
  assert.equal(rows[1][7], "乙, 丙");
  assert.equal(rows[1].length, 9);
});

test("csvToCards：欄位對應", () => {
  const cards = csvToCards(`${HEAD}\r\nT,M-1,D-1,2024-01-01,2024-01-02,P,男,男,https://x/1\r\n`);
  assert.deepEqual(cards[0], {
    title: "T", makerCode: "M-1", deliveryCode: "D-1", releaseDate: "2024-01-01",
    saleDate: "2024-01-02", performerText: "P", danyuText: "男", tags: "男", url: "https://x/1"
  });
});

test("cardKey：有網址用網址，沒有才用品番＋標題", () => {
  assert.equal(cardKey({ url: "https://x/1", makerCode: "a", deliveryCode: "b", title: "t" }), "https://x/1");
  assert.equal(cardKey({ url: "", makerCode: "a", deliveryCode: "b", title: "t" }), "a|b|t");
});

const rel = (c) => c.performerText.includes("甲");
const card = (url, p = "甲") => ({ url, performerText: p, makerCode: "", deliveryCode: "", title: url });

test("judgePage：新作未收錄 → 收下、不停", () => {
  const r = judgePage([card("n1"), card("old1")], rel, new Set(["old1"]));
  assert.deepEqual(r.newCards.map((c) => c.url), ["n1"]);
  assert.equal(r.stop, false);
});

test("judgePage：整頁都已收錄 → 停", () => {
  const r = judgePage([card("old1"), card("old2")], rel, new Set(["old1", "old2"]));
  assert.equal(r.newCards.length, 0);
  assert.equal(r.stop, true);
});

test("judgePage：不相關的卡片不算新作（同名搜尋雜訊）", () => {
  const r = judgePage([card("x1", "乙"), card("old1")], rel, new Set(["old1"]));
  assert.equal(r.stop, true);
});

test("judgePage：同頁重複只算一次；空頁 → 停", () => {
  assert.equal(judgePage([card("n1"), card("n1")], rel, new Set()).newCards.length, 1);
  assert.equal(judgePage([], rel, new Set()).stop, true);
});
