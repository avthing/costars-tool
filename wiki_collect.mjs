import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { csvToCards, cardKey, judgePage } from "./wiki_update.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const CDP_HTTP = "http://127.0.0.1:9333";
const MIN_NAV_INTERVAL_MS = 6000;
const MAX_PAGES_PER_ACTRESS = 40;
const ADOPTION_THRESHOLD = 3;
const MAX_CANDIDATES_PER_ACTRESS = 5;
const MAX_FALLBACK_CANDIDATES = 3;
const REST_EVERY_N_NAVIGATIONS = 100;
const LONG_REST_MS = 90000;
const UPDATE_DEFAULT_MAX_PAGES = 8;

// 女優候選寫法預設對照表（相容既有單獨指令呼叫）
const CANDIDATE_SPELLINGS = {
  "三上悠亞": ["三上悠亜", "三上悠亞"],
  "三上悠亜": ["三上悠亜", "三上悠亞"],
  "鈴村あいり": ["鈴村あいり", "鈴村愛里"],
  "鈴村愛里": ["鈴村あいり", "鈴村愛里"],
  "本庄鈴": ["本庄鈴"],
};

// 繁中漢字轉日文常用漢字/新字體對照表
const KANJI_MAP = {
  "亞": "亜", "戶": "戸", "遙": "遥", "戀": "恋", "濱": "浜",
  "澤": "沢", "齋": "斎", "櫻": "桜", "廣": "広", "邊": "辺",
  "條": "条", "繪": "絵", "龍": "竜", "實": "実", "壽": "寿",
  "惠": "恵", "豐": "豊", "禮": "礼", "彌": "弥", "澀": "渋",
  "關": "関", "莊": "庄", "蓳": "菫", "裏": "里", "裡": "里",
  "凛": "凜", "凜": "凛"
};

// 常見藝名日文讀音假名/異體補充表
const KNOWN_READINGS = {
  "東凛": ["東凜", "東りん"],
  "立花瑠莉": ["立花るり", "立花瑠璃", "立花ルリ"],
  "流川夕": ["流川ゆう", "流川ユウ"],
  "西田那津": ["西田なつ", "西田ナツ"],
  "友田彩也香": ["友田さやか", "友田彩香"],
  "高崎聖子": ["高崎しょうこ", "高崎せいこ"],
  "水野朝陽": ["水野あさひ"],
  "山岸逢花": ["山岸あいは", "山岸あいか"],
  "宮下玲奈": ["宮下れな"],
  "伊藤舞雪": ["伊藤まゆき"],
  "浜崎真緒": ["浜崎まお", "濱崎真緒"],
  "鈴村あいり": ["鈴村愛梨", "すずむらあいり"],
  "麻里梨夏": ["麻里りか", "麻里リカ"],
  "神咲詩織": ["神咲しおり"],
  "佐藤遙希": ["佐藤遥", "佐藤はるき"],
  "松下紗栄子": ["松下さえこ"],
  "石川澪": ["石川みお"],
  "瀬戸環奈": ["瀬戸かんな"],
  "辻本杏": ["辻本あん"],
  "大橋未久": ["大橋みく"],
  "吉高寧寧": ["吉高ねね"],
  "新有菜": ["新ありな"],
  "星奈愛": ["星奈あい"],
  "朝日奈花戀": ["朝日奈花恋", "朝日奈かれん"],
  "北川瞳": ["北川ひとみ"],
  "八掛海": ["八掛うみ"],
  "橘瑪麗": ["橘メアリー", "橘マリー"],
  "齋藤亞美里": ["斎藤あみり", "斉藤あみり"],
  "夢乃愛華": ["夢乃あいか"],
  "白峰美羽": ["白峰ミウ", "白峰みう"],
  "初川南": ["初川みなみ"],
  "坂道美琉": ["坂道みる"],
  "桃乃木香奈": ["桃乃木かな"],
  "水川蓳": ["水川スミレ", "水川菫", "水川すみれ"],
  "明裏紬": ["明里つむぎ", "明里紬"],
  "柚木蒂娜": ["柚木ティナ"],
  "七森莉莉": ["七森りり"],
  "夏希栗": ["夏希まろん"],
  "彩美旬果": ["あやみ旬果"],
  "吉沢明歩": ["吉澤明歩", "吉沢あきほ"],
  "神宮寺奈緒": ["神宮寺なお"],
  "星宮一花": ["星宮いちか"],
  "小野夕子": ["小野ゆうこ"],
  "星野娜美": ["星野なみ"],
  "逢見梨花": ["逢見りか"],
  "本田岬": ["本田みさき"],
  "美谷朱里": ["美谷しゅり"],
  "波多野結衣": ["波多野ゆい"]
};

// 候選寫法自動補齊（轉新字體、假名、疊字符號，最多補 3 個，總數 <= 5）
function generateFallbackCandidates(displayName, existingCandidates) {
  const existingSet = new Set(existingCandidates);
  const fallbacks = [];

  if (KNOWN_READINGS[displayName]) {
    for (const cand of KNOWN_READINGS[displayName]) {
      if (!existingSet.has(cand) && !fallbacks.includes(cand)) {
        fallbacks.push(cand);
      }
    }
  }

  let converted = displayName;
  for (const [tc, sc] of Object.entries(KANJI_MAP)) {
    converted = converted.replaceAll(tc, sc);
  }
  if (!existingSet.has(converted) && !fallbacks.includes(converted)) {
    fallbacks.push(converted);
  }

  const repeated = displayName.replace(/(.)\1/g, "$1々");
  if (!existingSet.has(repeated) && !fallbacks.includes(repeated)) {
    fallbacks.push(repeated);
  }

  const maxAllowed = Math.min(MAX_FALLBACK_CANDIDATES, Math.max(0, MAX_CANDIDATES_PER_ACTRESS - existingCandidates.length));
  return fallbacks.slice(0, maxAllowed);
}

// CDP WebSocket 客戶端
class CdpClient {
  constructor(wsUrl) {
    this.wsUrl = wsUrl;
    this.ws = null;
    this.id = 1;
    this.pending = new Map();
    this.eventListeners = new Map();
  }

  async connect() {
    this.ws = new WebSocket(this.wsUrl);
    await new Promise((resolve, reject) => {
      this.ws.onopen = resolve;
      this.ws.onerror = reject;
      this.ws.onmessage = (m) => {
        const data = JSON.parse(m.data);
        if (data.id && this.pending.has(data.id)) {
          const { resolve, reject } = this.pending.get(data.id);
          this.pending.delete(data.id);
          if (data.error) reject(new Error(JSON.stringify(data.error)));
          else resolve(data.result);
        } else if (data.method) {
          const listeners = this.eventListeners.get(data.method) || [];
          for (const fn of listeners) fn(data.params);
        }
      };
    });
  }

  on(event, fn) {
    if (!this.eventListeners.has(event)) {
      this.eventListeners.set(event, []);
    }
    this.eventListeners.get(event).push(fn);
  }

  off(event, fn) {
    const list = this.eventListeners.get(event);
    if (!list) return;
    const idx = list.indexOf(fn);
    if (idx !== -1) list.splice(idx, 1);
  }

  send(method, params = {}) {
    return new Promise((resolve, reject) => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
        return reject(new Error("WebSocket 尚未連線"));
      }
      const curId = this.id++;
      this.pending.set(curId, { resolve, reject });
      this.ws.send(JSON.stringify({ id: curId, method, params }));
    });
  }

  close() {
    if (this.ws) {
      try {
        this.ws.close();
      } catch (_) {}
    }
  }
}

async function getPageWsUrl() {
  const res = await fetch(`${CDP_HTTP}/json/list`);
  const list = await res.json();
  const page = list.find((t) => t.type === "page");
  if (!page || !page.webSocketDebuggerUrl) {
    throw new Error("找不到可用的 Chrome page target");
  }
  return page.webSocketDebuggerUrl;
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function decodeHtmlEntities(str) {
  if (!str) return "";
  return str
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#039;/g, "'")
    .replace(/&nbsp;/g, " ")
    .replace(/&#8211;/g, "-")
    .replace(/&#8212;/g, "—")
    .replace(/&#8230;/g, "…")
    .replace(/&#(\d+);/g, (_, dec) => String.fromCharCode(parseInt(dec, 10)))
    .replace(/&#x([0-9a-fA-F]+);/g, (_, hex) => String.fromCharCode(parseInt(hex, 16)));
}

function stripHtml(s) {
  if (!s) return "";
  return decodeHtmlEntities(s.replace(/<[^>]+>/g, "").trim());
}

function escapeCsv(val) {
  if (val === null || val === undefined) return "";
  const str = String(val);
  if (str.includes(",") || str.includes('"') || str.includes("\n") || str.includes("\r")) {
    return `"${str.replace(/"/g, '""')}"`;
  }
  return str;
}

function deriveMakerCode(code) {
  if (!code) return "";
  const trimmed = code.trim();
  const m = trimmed.match(/^([a-zA-Z]+)0*(\d{3,})$/);
  if (m) {
    return `${m[1].toUpperCase()}-${m[2]}`;
  }
  return trimmed.toUpperCase();
}

// NFKC 正規化後比對候選寫法（含括號內別名）
function isPerformerMatchingCandidate(performerText, candidate) {
  if (!performerText || !candidate) return false;
  const cleanPerformer = performerText.normalize("NFKC").replace(/[\s\u3000]+/g, "");
  const cleanCand = candidate.normalize("NFKC").replace(/[\s\u3000]+/g, "");
  return cleanPerformer.includes(cleanCand);
}

function isPerformerRelevant(performerText, candidates) {
  if (!performerText || !candidates || candidates.length === 0) return false;
  return candidates.some((cand) => isPerformerMatchingCandidate(performerText, cand));
}

function countCards(html) {
  const matches = html.match(/<article[^>]*class="[^"]*entry-card[^"]*"[^>]*>/g);
  return matches ? matches.length : 0;
}

function hasNextPage(html) {
  return html.includes("next page-numbers") || html.includes("pagination-next-link");
}

function parseCardsFromHtml(html) {
  const works = [];
  const cardMatches = [...html.matchAll(/<article[^>]*class="[^"]*entry-card[^"]*"[^>]*>([\s\S]*?)<\/article>/g)];

  for (const m of cardMatches) {
    const card = m[1];

    const h2Match = card.match(/<h2>([\s\S]*?)<\/h2>/);
    const title = h2Match ? stripHtml(h2Match[1]) : "";

    const urlMatch = card.match(/<a[^>]+href="([^"]*#comment-area)"/);
    const url = urlMatch ? urlMatch[1].replace(/#comment-area$/, "") : "";

    const postTagsBlockMatch = card.match(/出演AV男優\s*[：:]\s*([\s\S]*?)(?:&nbsp;|<div)/);
    const tagBlock = postTagsBlockMatch ? postTagsBlockMatch[1] : "";
    const tagMatches = [...tagBlock.matchAll(/<a[^>]+href="[^"]*\/tag\/([^"/]+)\/?"[^>]*>([\s\S]*?)<\/a>/g)];
    const tags = tagMatches.map((t) => stripHtml(t[2]));

    const h2End = card.indexOf("</h2>");
    const reportLinkStart = card.indexOf("リンク先削除報告");
    const body = card.slice(h2End !== -1 ? h2End + 5 : 0, reportLinkStart !== -1 ? reportLinkStart : undefined);
    const textLines = stripHtml(body.replace(/<br\s*\/?>/gi, "\n"))
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean);

    const findLine = (prefix) => {
      const l = textLines.find((line) => line.startsWith(prefix) || line.replace(/\s+/g, "").startsWith(prefix));
      if (!l) return "";
      const colonIdx = l.indexOf("：") !== -1 ? l.indexOf("：") : l.indexOf(":");
      return colonIdx !== -1 ? l.slice(colonIdx + 1).trim() : l.trim();
    };

    // 部分片商（如プレステージ）的卡片欄位寫成「出演：」而非「出演者 ：」。只認「出演」後面直接接冒號，避免誤抓「出演男優」「出演AV男優」
    const findLabelLine = (re) => {
      const i = textLines.findIndex((line) => re.test(line));
      if (i === -1) return "";
      const rest = textLines[i].replace(re, "").trim();
      if (rest) return rest;
      const next = (textLines[i + 1] || "").trim();
      return /^[^\s：:]+\s*[：:]/.test(next) ? "" : next;
    };

    const danyuText = findLine("出演男優");
    const performerText = findLine("出演者") || findLabelLine(/^出演\s*[：:]/);
    const releaseDate = findLine("配信開始日");
    const saleDate = findLine("商品発売日");
    const deliveryCode = findLine("配信品番");
    const makerCode = findLine("メーカー品番");
    const generalCode = findLine("品番");

    const effectiveDeliveryCode = deliveryCode || generalCode || "";
    const effectiveMakerCode = makerCode || deriveMakerCode(generalCode || deliveryCode) || "";

    works.push({
      title,
      makerCode: effectiveMakerCode,
      deliveryCode: effectiveDeliveryCode,
      releaseDate,
      saleDate,
      performerText,
      danyuText,
      tags,
      url
    });
  }

  return works;
}

// 原子寫入檔案輔助函式
function atomicWriteFileSync(filePath, content) {
  const dir = path.dirname(filePath);
  const tmpPath = path.join(dir, `.${path.basename(filePath)}.${Date.now()}.${Math.random().toString(36).slice(2)}.tmp`);
  fs.writeFileSync(tmpPath, content, "utf-8");
  try {
    fs.renameSync(tmpPath, filePath);
  } catch (_) {
    fs.copyFileSync(tmpPath, filePath);
    try { fs.unlinkSync(tmpPath); } catch (_) {}
  }
}

// 原子寫入 JSON 輔助函式
function atomicWriteJsonSync(filePath, data) {
  atomicWriteFileSync(filePath, JSON.stringify(data, null, 2));
}

// 建立 CSV 內容
function buildCsvContent(relevantWorks) {
  const csvHeader = [
    "標題",
    "メーカー品番",
    "配信品番",
    "配信開始日",
    "商品発売日",
    "出演者文字",
    "出演男優文字",
    "男優 tag 清單",
    "文章網址"
  ];

  const csvRows = relevantWorks.map((w) => [
    escapeCsv(w.title),
    escapeCsv(w.makerCode),
    escapeCsv(w.deliveryCode),
    escapeCsv(w.releaseDate),
    escapeCsv(w.saleDate),
    escapeCsv(w.performerText),
    escapeCsv(w.danyuText),
    escapeCsv(Array.isArray(w.tags) ? w.tags.join(", ") : (w.tags || "")),
    escapeCsv(w.url)
  ]);

  return "\uFEFF" + [csvHeader.join(","), ...csvRows.map((r) => r.join(","))].join("\r\n");
}

function loadResolvedNames(dataDir) {
  const jsonPath = path.join(dataDir, "resolved_names.json");
  if (!fs.existsSync(jsonPath)) {
    return { resolved: {}, unresolved: {} };
  }
  try {
    const data = JSON.parse(fs.readFileSync(jsonPath, "utf-8"));
    if (!data.resolved) data.resolved = {};
    if (!data.unresolved) data.unresolved = {};
    return data;
  } catch (_) {
    return { resolved: {}, unresolved: {} };
  }
}

function updateResolvedNames(dataDir, updater) {
  const data = loadResolvedNames(dataDir);
  updater(data);
  const jsonPath = path.join(dataDir, "resolved_names.json");
  atomicWriteJsonSync(jsonPath, data);
  return data;
}

function updateCrawlState(dataDir, updates) {
  const statePath = path.join(dataDir, "crawl_state.json");
  let state = {};
  if (fs.existsSync(statePath)) {
    try {
      state = JSON.parse(fs.readFileSync(statePath, "utf-8"));
    } catch (_) {}
  }
  Object.assign(state, updates, { updatedAt: new Date().toISOString() });
  atomicWriteJsonSync(statePath, state);
}

// 離線補入前一批已完成的三位女優
function ensurePreviousBatchInResolvedNames(dataDir) {
  const resolvedData = loadResolvedNames(dataDir);
  let changed = false;

  const previousActresses = [
    { name: "三上悠亞", defaultWiki: "三上悠亜" },
    { name: "本庄鈴", defaultWiki: "本庄鈴" }
  ];

  for (const prev of previousActresses) {
    if (!resolvedData.resolved[prev.name]) {
      const cacheDir = path.join(dataDir, "cache", "wiki", prev.name);
      const csvPath = path.join(dataDir, `wiki_works_${prev.name}.csv`);
      if (fs.existsSync(cacheDir) && fs.existsSync(csvPath)) {
        const pageFiles = fs.readdirSync(cacheDir).filter((f) => f.startsWith("page_") && f.endsWith(".html"));
        let totalCards = 0;
        let relevant = 0;
        let skipped = 0;
        let withMales = 0;
        let wikiName = prev.defaultWiki;

        for (let i = 1; i <= pageFiles.length; i++) {
          const pagePath = path.join(cacheDir, `page_${i}.html`);
          if (fs.existsSync(pagePath)) {
            const html = fs.readFileSync(pagePath, "utf-8");
            if (i === 1) {
              const m = html.match(/<title>[“"]([^”"]+)[”"]\s*の検索結果/);
              if (m && m[1]) wikiName = m[1];
            }
            const cards = parseCardsFromHtml(html);
            totalCards += cards.length;
            for (const c of cards) {
              if (isPerformerMatchingCandidate(c.performerText, wikiName)) {
                relevant++;
                if (c.danyuText) withMales++;
              } else {
                skipped++;
              }
            }
          }
        }

        resolvedData.resolved[prev.name] = {
          wiki_name: wikiName,
          pages: pageFiles.length,
          relevant,
          skipped,
          with_males: withMales,
          truncated: false,
          done: true
        };
        changed = true;
        console.log(`[離線補入] 已將前一批女優「${prev.name}」寫入 resolved_names.json (wiki_name: ${wikiName})`);
      }
    }
  }

  // 鈴村あいり（前一批 skipped）
  if (!resolvedData.resolved["鈴村あいり"] && !resolvedData.unresolved["鈴村あいり"]) {
    resolvedData.unresolved["鈴村あいり"] = {
      "鈴村あいり": 0,
      "鈴村愛里": 0
    };
    changed = true;
    console.log(`[離線補入] 已將前一批未解析女優「鈴村あいり」記錄至 unresolved`);
  }

  if (changed) {
    const jsonPath = path.join(dataDir, "resolved_names.json");
    atomicWriteJsonSync(jsonPath, resolvedData);
  }
}

// 全域導航狀態追蹤（跨女優共享）
let cdpClient = null;
let lastNavEndTime = 0;
let minNavIntervalMs = Infinity;
const navIntervals = [];
let totalNavigations = 0;
let consecutiveErrors = 0;
let verificationTotalWaitMs = 0;
let verificationEncountered = false;
let verificationCount = 0;
let currentActressName = "";
let currentPageNum = 1;

async function getCdp() {
  if (!cdpClient) {
    const wsUrl = await getPageWsUrl();
    cdpClient = new CdpClient(wsUrl);
    await cdpClient.connect();
    await cdpClient.send("Page.enable");
  }
  return cdpClient;
}

async function throttleBeforeNav() {
  if (lastNavEndTime > 0) {
    const elapsed = Date.now() - lastNavEndTime;
    const jitter = Math.floor(Math.random() * 4001); // 0~4000 ms 隨機抖動
    const targetInterval = MIN_NAV_INTERVAL_MS + jitter; // 6000 ~ 10000 ms

    if (elapsed < targetInterval) {
      const waitMs = targetInterval - elapsed;
      console.log(`[節流等待] 導航間隔須 >= 6s (+抖動 ${(jitter / 1000).toFixed(2)}s)，等待 ${(waitMs / 1000).toFixed(2)} 秒...`);
      await sleep(waitMs);
    }

    // 嚴格下限保證：不可由參數調低，必須 >= 6000ms
    while (Date.now() - lastNavEndTime < MIN_NAV_INTERVAL_MS) {
      await sleep(50);
    }

    const actualInterval = Date.now() - lastNavEndTime;
    navIntervals.push(actualInterval);
    if (actualInterval < minNavIntervalMs) {
      minNavIntervalMs = actualInterval;
    }
    console.log(`[導航間隔] 與前次導航結束間隔: ${(actualInterval / 1000).toFixed(2)} 秒`);
  }
}

async function waitForDocumentComplete(cdp, timeoutMs = 30000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await cdp.send("Runtime.evaluate", {
        expression: "document.readyState",
        returnByValue: true
      });
      if (res?.result?.value === "complete") {
        return;
      }
    } catch (_) {}
    await sleep(250);
  }
}

function isVerificationOrBlocked(title, cardCount) {
  const blockedPrefixes = ["Just a moment", "請稍候", "Attention Required"];
  const cleanTitle = (title || "").trim();
  if (blockedPrefixes.some((p) => cleanTitle.startsWith(p))) return true;
  if (cardCount === 0 && !cleanTitle.includes("検索結果")) return true;
  return false;
}

async function navigateTo(targetUrl, dataDir) {
  await throttleBeforeNav();

  const cdp = await getCdp();
  totalNavigations++;
  const navStartTime = Date.now();

  let loadTimeoutId;
  const loadPromise = new Promise((resolve) => {
    const handler = () => {
      clearTimeout(loadTimeoutId);
      cdp.off("Page.loadEventFired", handler);
      resolve();
    };
    cdp.on("Page.loadEventFired", handler);
    loadTimeoutId = setTimeout(() => {
      cdp.off("Page.loadEventFired", handler);
      resolve();
    }, 20000);
  });

  try {
    console.log(`[導航開始] (${totalNavigations}) 前往: ${targetUrl}`);
    const navRes = await cdp.send("Page.navigate", { url: targetUrl });
    if (navRes?.errorText) {
      throw new Error(`Page.navigate 失敗: ${navRes.errorText}`);
    }

    await loadPromise;
    await waitForDocumentComplete(cdp, 20000);
    await sleep(500);

    const navDuration = Date.now() - navStartTime;
    lastNavEndTime = Date.now();

    const titleEval = await cdp.send("Runtime.evaluate", {
      expression: "document.title",
      returnByValue: true
    });
    let title = (titleEval?.result?.value || "").trim();

    const cardCountEval = await cdp.send("Runtime.evaluate", {
      expression: "document.querySelectorAll('article.entry-card').length",
      returnByValue: true
    });
    let cardCount = cardCountEval?.result?.value || 0;

    console.log(`[導航完成] 耗時: ${navDuration}ms | 標題: "${title}" | 卡片數: ${cardCount}`);

    // 檢查 HTTP 狀態或錯誤頁面
    const isHttpError = /403\s+Forbidden|500\s+Internal|502\s+Bad|503\s+Service|504\s+Gateway/i.test(title);
    if (isHttpError) {
      consecutiveErrors++;
      console.error(`[HTTP 異常] 頁面載入異常標題: "${title}" (連續第 ${consecutiveErrors} 次)`);
      if (consecutiveErrors >= 3) {
        console.error(`[重大錯誤] 連續 3 次 HTTP 錯誤或頁面異常，停手退出！停在: ${currentActressName} 第 ${currentPageNum} 頁`);
        if (dataDir) {
          updateCrawlState(dataDir, {
            status: "stopped_consecutive_errors",
            stoppedReason: `連續 3 次 HTTP 錯誤或頁面異常，停在: ${currentActressName} 第 ${currentPageNum} 頁`
          });
        }
        if (cdpClient) cdpClient.close();
        process.exit(1);
      }
      throw new Error(`HTTP 錯誤頁面: ${title}`);
    }

    // 檢查 Cloudflare 與停手條件
    if (isVerificationOrBlocked(title, cardCount)) {
      verificationEncountered = true;
      verificationCount++;
      console.warn(`[驗證中] 偵測到驗證頁面或非搜尋結果！標題: "${title}", 卡片數: ${cardCount}`);
      console.log("請在已開啟的 Chrome 視窗自行通過驗證,完成後會自動繼續");

      if (dataDir) {
        updateCrawlState(dataDir, {
          status: "waiting_verification",
          stoppedReason: `驗證中: ${title}`
        });
      }

      const verifyStart = Date.now();
      const maxWaitMs = 5 * 60 * 1000; // 最多等 5 分鐘
      let solved = false;

      while (Date.now() - verifyStart < maxWaitMs) {
        await sleep(3000);
        const curTitleEval = await cdp.send("Runtime.evaluate", {
          expression: "document.title",
          returnByValue: true
        });
        title = (curTitleEval?.result?.value || "").trim();

        const curCountEval = await cdp.send("Runtime.evaluate", {
          expression: "document.querySelectorAll('article.entry-card').length",
          returnByValue: true
        });
        cardCount = curCountEval?.result?.value || 0;

        if (!isVerificationOrBlocked(title, cardCount)) {
          solved = true;
          const waitSec = ((Date.now() - verifyStart) / 1000).toFixed(1);
          console.log(`[驗證通過] 已通過驗證（等待了 ${waitSec} 秒），標題: "${title}", 卡片數: ${cardCount}`);
          verificationTotalWaitMs += (Date.now() - verifyStart);
          if (dataDir) {
            updateCrawlState(dataDir, {
              status: "running",
              stoppedReason: null
            });
          }
          break;
        }
      }

      if (!solved) {
        console.error(`[驗證逾時] 5 分鐘內未通過驗證，停止整個流程，保留已寫入之檔案。未完成: 停在 ${currentActressName} 第 ${currentPageNum} 頁`);
        if (dataDir) {
          updateCrawlState(dataDir, {
            status: "stopped_verification_timeout",
            stoppedReason: `驗證逾時: 停在 ${currentActressName} 第 ${currentPageNum} 頁`
          });
        }
        if (cdpClient) cdpClient.close();
        process.exit(1);
      }
    }

    const htmlEval = await cdp.send("Runtime.evaluate", {
      expression: "document.documentElement.outerHTML",
      returnByValue: true
    });
    const html = htmlEval?.result?.value || "";

    consecutiveErrors = 0;

    // 每累計 100 次導航，額外休息 90 秒
    if (totalNavigations > 0 && totalNavigations % REST_EVERY_N_NAVIGATIONS === 0) {
      console.log(`[長休息] 累計達到 ${totalNavigations} 次導航，依節流規定額外休息 90 秒...`);
      await sleep(LONG_REST_MS);
      lastNavEndTime = Date.now();
    }

    return { html, title, cardCount, navDuration };
  } catch (err) {
    consecutiveErrors++;
    console.error(`[導航錯誤] 導航至 ${targetUrl} 失敗 (連續第 ${consecutiveErrors} 次):`, err.message);
    if (consecutiveErrors >= 3) {
      console.error(`[重大錯誤] 連續 3 次導航失敗或頁面異常，停手退出！停在: ${currentActressName} 第 ${currentPageNum} 頁`);
      if (dataDir) {
        updateCrawlState(dataDir, {
          status: "stopped_consecutive_errors",
          stoppedReason: `連續 3 次導航失敗或頁面異常，停在: ${currentActressName} 第 ${currentPageNum} 頁`
        });
      }
      if (cdpClient) cdpClient.close();
      process.exit(1);
    }
    throw err;
  }
}

async function processActress(target, dataDir) {
  const displayName = typeof target === "string" ? target : target.displayName;
  const initialCandidates = typeof target === "string" ? (CANDIDATE_SPELLINGS[displayName] || [displayName]) : target.candidates;

  currentActressName = displayName;
  currentPageNum = 1;

  const cacheDir = path.join(dataDir, "cache", "wiki", displayName);
  if (!fs.existsSync(cacheDir)) {
    fs.mkdirSync(cacheDir, { recursive: true });
  }

  const csvPath = path.join(dataDir, `wiki_works_${displayName}.csv`);
  const page1CacheFile = path.join(cacheDir, "page_1.html");
  const skippedCacheFile = path.join(cacheDir, "skipped.json");

  // 0. 續跑檢查：若已在 resolved_names.json 標記 done: true 且 CSV 存在，直接略過（不發請求）
  const resolvedState = loadResolvedNames(dataDir);
  if (resolvedState.resolved[displayName]?.done === true && fs.existsSync(csvPath)) {
    console.log(`[續跑略過] 女優「${displayName}」在 resolved_names.json 標記已完成 (done: true)，直接略過。`);
    const r = resolvedState.resolved[displayName];
    return {
      actress: displayName,
      adoptedCandidate: r.wiki_name,
      navigations: 0,
      pagesTurned: r.pages,
      relevantCount: r.relevant,
      skippedCount: r.skipped,
      withDanyuCount: r.with_males,
      isTruncated: r.truncated,
      done: true
    };
  }

  updateCrawlState(dataDir, { currentActress: displayName, currentPage: 1, status: "running" });

  let adoptedCandidate = null;
  let page1Html = "";
  const navCountBefore = totalNavigations;
  const candidateCounts = {};
  const candidateHtmls = {};

  // 1. 檢查是否已有 page_1.html，若無但有 probe_<候選>.html 則先行重判
  if (!fs.existsSync(page1CacheFile) && fs.existsSync(cacheDir)) {
    const probeFiles = fs.readdirSync(cacheDir).filter((f) => f.startsWith("probe_") && f.endsWith(".html"));
    for (const pf of probeFiles) {
      const cand = pf.slice(6, -5);
      const probePath = path.join(cacheDir, pf);
      const probeHtml = fs.readFileSync(probePath, "utf-8");
      const testCards = parseCardsFromHtml(probeHtml);
      const matchCount = testCards.filter((c) => isPerformerMatchingCandidate(c.performerText, cand)).length;
      const smallButClean = matchCount >= 1 && testCards.length < 20 && matchCount === testCards.length;
      if (matchCount >= ADOPTION_THRESHOLD || smallButClean) {
        console.log(`[探測頁重判通過] 女優「${displayName}」候選「${cand}」在探測頁相關作品 ${matchCount} 部 (>= ${ADOPTION_THRESHOLD} 或 smallButClean)！已複製為 page_1.html`);
        fs.copyFileSync(probePath, page1CacheFile);
        if (fs.existsSync(skippedCacheFile)) {
          try { fs.unlinkSync(skippedCacheFile); } catch (_) {}
        }
        updateResolvedNames(dataDir, (d) => {
          delete d.unresolved[displayName];
        });
        break;
      }
    }
  }

  if (fs.existsSync(page1CacheFile)) {
    console.log(`[快取命中] 女優「${displayName}」第 1 頁已存在快取: ${page1CacheFile}`);
    page1Html = fs.readFileSync(page1CacheFile, "utf-8");

    const m = page1Html.match(/<title>[“"]([^”"]+)[”"]\s*の検索結果/);
    if (m && m[1]) {
      adoptedCandidate = m[1];
    } else {
      adoptedCandidate = initialCandidates[0];
    }
    console.log(`[確認寫法] 由快取識別採用搜尋寫法: 「${adoptedCandidate}」`);
  } else {
    // 檢查 skipped.json
    let previouslyTestedSet = new Set();
    if (fs.existsSync(skippedCacheFile)) {
      try {
        const skippedData = JSON.parse(fs.readFileSync(skippedCacheFile, "utf-8"));
        if (skippedData.testedCandidates) {
          for (const [cand, cnt] of Object.entries(skippedData.testedCandidates)) {
            previouslyTestedSet.add(cand);
            candidateCounts[cand] = cnt;
          }
        } else {
          // 舊版 skipped.json 沒有 testedCandidates 屬性（如前一批的鈴村あいり）
          const oldList = CANDIDATE_SPELLINGS[displayName] || [displayName];
          for (const c of oldList) {
            previouslyTestedSet.add(c);
            candidateCounts[c] = 0;
          }
        }
      } catch (_) {}
    }

    // 篩選出尚未測試過的候選
    let candidatesToTest = initialCandidates.filter((c) => !previouslyTestedSet.has(c));
    console.log(`[候選清單] 女優「${displayName}」原始候選: ${JSON.stringify(initialCandidates)}，待測未測候選: ${JSON.stringify(candidatesToTest)}`);

    for (const cand of candidatesToTest) {
      currentPageNum = 1;
      const searchUrl = `https://avdanyuwiki.com/?s=${encodeURIComponent(cand)}`;
      console.log(`[嘗試候選] 正在載入寫法「${cand}」第 1 頁...`);
      const navRes = await navigateTo(searchUrl, dataDir);
      const testCards = parseCardsFromHtml(navRes.html);
      const matchCount = testCards.filter((c) => isPerformerMatchingCandidate(c.performerText, cand)).length;

      candidateCounts[cand] = matchCount;
      candidateHtmls[cand] = navRes.html;
      previouslyTestedSet.add(cand);

      console.log(`[候選評估] 寫法「${cand}」第 1 頁共 ${testCards.length} 張卡片，出演者含該寫法作品數: ${matchCount}`);

      // 作品很少的女優：搜尋結果不滿一頁且全部相符，也視為有效（例如 2 張全中）
      const smallButClean = matchCount >= 1 && testCards.length < 20 && matchCount === testCards.length;
      if (matchCount >= ADOPTION_THRESHOLD || smallButClean) {
        adoptedCandidate = cand;
        page1Html = navRes.html;
        fs.writeFileSync(page1CacheFile, page1Html, "utf-8");
        if (fs.existsSync(skippedCacheFile)) {
          try { fs.unlinkSync(skippedCacheFile); } catch (_) {}
        }
        console.log(`[採用寫法] 寫法「${cand}」相關卡片 ${matchCount} 張 (>= ${ADOPTION_THRESHOLD})，已採用並快取第 1 頁。`);
        break;
      } else {
        console.log(`[候選不符] 寫法「${cand}」相關卡片僅 ${matchCount} 張 (< ${ADOPTION_THRESHOLD})，嘗試下一個候選寫法...`);
      }
    }

    // 若原始候選皆失敗，嘗試自動補充最多 3 個候選（總數 <= 5）
    if (!adoptedCandidate) {
      const allTested = Array.from(previouslyTestedSet);
      const fallbacks = generateFallbackCandidates(displayName, allTested);

      if (fallbacks.length > 0) {
        console.log(`[補充候選] 女優「${displayName}」自動補充 ${fallbacks.length} 個候選寫法: ${JSON.stringify(fallbacks)}`);

        for (const cand of fallbacks) {
          currentPageNum = 1;
          const searchUrl = `https://avdanyuwiki.com/?s=${encodeURIComponent(cand)}`;
          console.log(`[嘗試補充候選] 正在載入補充寫法「${cand}」第 1 頁...`);
          const navRes = await navigateTo(searchUrl, dataDir);
          const testCards = parseCardsFromHtml(navRes.html);
          const matchCount = testCards.filter((c) => isPerformerMatchingCandidate(c.performerText, cand)).length;

          candidateCounts[cand] = matchCount;
          candidateHtmls[cand] = navRes.html;
          previouslyTestedSet.add(cand);

          console.log(`[補充候選評估] 寫法「${cand}」第 1 頁共 ${testCards.length} 張卡片，相關作品數: ${matchCount}`);

          if (matchCount >= ADOPTION_THRESHOLD) {
            adoptedCandidate = cand;
            page1Html = navRes.html;
            fs.writeFileSync(page1CacheFile, page1Html, "utf-8");
            if (fs.existsSync(skippedCacheFile)) {
              try { fs.unlinkSync(skippedCacheFile); } catch (_) {}
            }
            console.log(`[採用寫法] 補充寫法「${cand}」相關卡片 ${matchCount} 張 (>= ${ADOPTION_THRESHOLD})，已採用並快取第 1 頁。`);
            break;
          }
        }
      }
    }

    // 仍未解決：寫入 unresolved 與 probe 快取頁
    if (!adoptedCandidate) {
      console.warn(`[未解決女優] 女優「${displayName}」所有候選寫法皆無法取得足夠相關卡片 (>= ${ADOPTION_THRESHOLD})。`);

      // 找出相關張數最多的候選
      let bestCand = null;
      let maxCnt = -1;
      for (const [cand, cnt] of Object.entries(candidateCounts)) {
        if (cnt > maxCnt) {
          maxCnt = cnt;
          bestCand = cand;
        }
      }
      if (!bestCand) {
        bestCand = initialCandidates[0];
      }

      // 將相關張數最多的候選第 1 頁存成 probe_<候選>.html
      const probeCacheFile = path.join(cacheDir, `probe_${bestCand}.html`);
      if (candidateHtmls[bestCand]) {
        fs.writeFileSync(probeCacheFile, candidateHtmls[bestCand], "utf-8");
        console.log(`[探測快取] 已將候選「${bestCand}」第 1 頁儲存為: ${probeCacheFile}`);
      } else if (!fs.existsSync(probeCacheFile)) {
        console.log(`[額外導航] 重新載入候選「${bestCand}」第 1 頁以儲存 probe 檔案供人工複核...`);
        try {
          const navRes = await navigateTo(`https://avdanyuwiki.com/?s=${encodeURIComponent(bestCand)}`, dataDir);
          fs.writeFileSync(probeCacheFile, navRes.html, "utf-8");
          console.log(`[探測快取] 已將候選「${bestCand}」第 1 頁儲存為: ${probeCacheFile}`);
        } catch (e) {
          console.error(`[探測失敗] 無法載入 probe 頁面: ${e.message}`);
        }
      }

      // 儲存 skipped.json
      const skippedData = {
        actress: displayName,
        skipped: true,
        testedCandidates: candidateCounts,
        reason: `所有候選寫法皆未達第 1 頁相關卡片 >= ${ADOPTION_THRESHOLD} 門檻`,
        testedAt: new Date().toISOString()
      };
      fs.writeFileSync(skippedCacheFile, JSON.stringify(skippedData, null, 2), "utf-8");

      // 更新 resolved_names.json 的 unresolved
      updateResolvedNames(dataDir, (d) => {
        d.unresolved[displayName] = candidateCounts;
        delete d.resolved[displayName];
      });

      return {
        actress: displayName,
        adoptedCandidate: null,
        candidateCounts,
        navigations: totalNavigations - navCountBefore,
        pagesTurned: 0,
        relevantCount: 0,
        skippedCount: 0,
        withDanyuCount: 0,
        isTruncated: false,
        done: false
      };
    }
  }

  // 2. 依序翻頁（第 2 頁至第 40 頁）
  let totalPages = 1;
  let currentHtml = page1Html;
  let isTruncated = false;

  for (let page = 2; page <= MAX_PAGES_PER_ACTRESS; page++) {
    if (!hasNextPage(currentHtml)) {
      console.log(`[分頁結束] 第 ${page - 1} 頁無「次へ」連結，已達最後一頁。`);
      break;
    }

    currentPageNum = page;
    updateCrawlState(dataDir, { currentActress: displayName, currentPage: page });

    const pageCacheFile = path.join(cacheDir, `page_${page}.html`);
    if (fs.existsSync(pageCacheFile)) {
      console.log(`[快取命中] 第 ${page} 頁已存在快取: ${pageCacheFile}`);
      currentHtml = fs.readFileSync(pageCacheFile, "utf-8");
    } else {
      const pageUrl = `https://avdanyuwiki.com/?s=${encodeURIComponent(adoptedCandidate)}&paged=${page}`;
      const navRes = await navigateTo(pageUrl, dataDir);
      currentHtml = navRes.html;
      fs.writeFileSync(pageCacheFile, currentHtml, "utf-8");
      console.log(`[寫入快取] 已儲存第 ${page} 頁至: ${pageCacheFile}`);
    }

    const cardCount = countCards(currentHtml);
    if (cardCount === 0) {
      console.log(`[分頁結束] 第 ${page} 頁無任何 article 卡片，抓取結束。`);
      if (fs.existsSync(pageCacheFile)) {
        try { fs.unlinkSync(pageCacheFile); } catch (_) {}
      }
      break;
    }

    totalPages = page;

    if (page === MAX_PAGES_PER_ACTRESS) {
      if (hasNextPage(currentHtml)) {
        isTruncated = true;
        console.warn(`[截斷警告] 女優「${displayName}」達到第 40 頁上限仍有下一頁，標記 truncated: true！`);
      }
      break;
    }

    if (!hasNextPage(currentHtml)) {
      console.log(`[分頁結束] 第 ${page} 頁無「次へ」連結，已達最後一頁。`);
      break;
    }
  }

  // 3. 解析所有快取頁面並過濾相關作品（出演者含採用寫法）
  const allWorks = [];
  const relevantWorks = [];
  let skippedCount = 0;

  for (let page = 1; page <= totalPages; page++) {
    const pageCacheFile = path.join(cacheDir, `page_${page}.html`);
    if (!fs.existsSync(pageCacheFile)) break;
    const html = fs.readFileSync(pageCacheFile, "utf-8");
    const cards = parseCardsFromHtml(html);

    for (const card of cards) {
      allWorks.push(card);
      if (isPerformerMatchingCandidate(card.performerText, adoptedCandidate)) {
        relevantWorks.push(card);
      } else {
        skippedCount++;
      }
    }
  }

  const withDanyuCount = relevantWorks.filter((w) => !!w.danyuText).length;

  // 4. 立即輸出 CSV（原子寫入）
  const csvContent = buildCsvContent(relevantWorks);
  atomicWriteFileSync(csvPath, csvContent);
  console.log(`[寫入完成] 已輸出 CSV: ${csvPath} (共 ${relevantWorks.length} 部相關作品)`);

  // 5. 更新 resolved_names.json（原子寫入）
  updateResolvedNames(dataDir, (d) => {
    d.resolved[displayName] = {
      wiki_name: adoptedCandidate,
      pages: totalPages,
      relevant: relevantWorks.length,
      skipped: skippedCount,
      with_males: withDanyuCount,
      truncated: isTruncated,
      done: true
    };
    delete d.unresolved[displayName];
  });

  const actressNavigations = totalNavigations - navCountBefore;

  console.log(`\n--- 【${displayName}】統計摘要 ---`);
  console.log(`- 採用的搜尋寫法: ${adoptedCandidate}`);
  console.log(`- 實際發出導航數: ${actressNavigations}`);
  console.log(`- 翻頁總數: ${totalPages}`);
  console.log(`- 總卡片數: ${allWorks.length}`);
  console.log(`- 相關作品數: ${relevantWorks.length}`);
  console.log(`- 略過數: ${skippedCount}`);
  console.log(`- 有列出男優的作品數: ${withDanyuCount}`);
  console.log(`- 是否截斷 (truncated): ${isTruncated}`);
  console.log(`--------------------------------\n`);

  return {
    actress: displayName,
    adoptedCandidate,
    candidateCounts,
    navigations: actressNavigations,
    pagesTurned: totalPages,
    relevantCount: relevantWorks.length,
    skippedCount,
    withDanyuCount,
    isTruncated,
    done: true,
    csvPath
  };
}

function getDisplayWidth(str) {
  let width = 0;
  for (const ch of String(str)) {
    const code = ch.codePointAt(0);
    if (
      (code >= 0x1100 && code <= 0x115f) ||
      (code >= 0x2e80 && code <= 0xa4cf) ||
      (code >= 0xac00 && code <= 0xd7a3) ||
      (code >= 0xf900 && code <= 0xfaff) ||
      (code >= 0xfe10 && code <= 0xfe19) ||
      (code >= 0xfe30 && code <= 0xfe6f) ||
      (code >= 0xff00 && code <= 0xff60) ||
      (code >= 0xffe0 && code <= 0xffe6)
    ) {
      width += 2;
    } else {
      width += 1;
    }
  }
  return width;
}

function cjkPadEnd(str, targetWidth) {
  const s = String(str);
  const cur = getDisplayWidth(s);
  return cur >= targetWidth ? s : s + " ".repeat(targetWidth - cur);
}

function cjkPadStart(str, targetWidth) {
  const s = String(str);
  const cur = getDisplayWidth(s);
  return cur >= targetWidth ? s : " ".repeat(targetWidth - cur) + s;
}

async function reparseResolvedActresses(dataDir) {
  console.log("==================================================");
  console.log("avdanyuwiki 離線重算模式 (--reparse) 啟動");
  console.log(`資料目錄: ${dataDir}`);
  console.log("此模式為完全離線，不連線 CDP，不發送任何網路導航。");
  console.log("==================================================");

  const resolvedData = loadResolvedNames(dataDir);
  const resolvedList = Object.entries(resolvedData.resolved);
  console.log(`已解析女優總數: ${resolvedList.length} 位`);

  let oldRelTotal = 0;
  let newRelTotal = 0;
  let oldSkipTotal = 0;
  let newSkipTotal = 0;
  let oldMaleTotal = 0;
  let newMaleTotal = 0;

  const tableRows = [];
  let skippedDueToMissing = 0;

  for (const [displayName, info] of resolvedList) {
    const wikiName = info.wiki_name;
    const totalPages = info.pages;
    const cacheDir = path.join(dataDir, "cache", "wiki", displayName);
    const csvPath = path.join(dataDir, `wiki_works_${displayName}.csv`);

    let hasMissing = false;
    for (let p = 1; p <= totalPages; p++) {
      const pageFile = path.join(cacheDir, `page_${p}.html`);
      if (!fs.existsSync(pageFile)) {
        console.error(`[快取頁缺漏] 女優「${displayName}」缺少第 ${p} 頁快取: ${pageFile}，跳過此女優！`);
        hasMissing = true;
        break;
      }
    }
    if (hasMissing) {
      skippedDueToMissing++;
      continue;
    }

    const relevantWorks = [];
    let skippedCount = 0;
    let withMalesCount = 0;

    for (let p = 1; p <= totalPages; p++) {
      const pageFile = path.join(cacheDir, `page_${p}.html`);
      const html = fs.readFileSync(pageFile, "utf-8");
      const cards = parseCardsFromHtml(html);

      for (const card of cards) {
        if (isPerformerMatchingCandidate(card.performerText, wikiName)) {
          relevantWorks.push(card);
          if (card.danyuText) withMalesCount++;
        } else {
          skippedCount++;
        }
      }
    }

    const csvContent = buildCsvContent(relevantWorks);
    atomicWriteFileSync(csvPath, csvContent);

    const oldRel = info.relevant;
    const newRel = relevantWorks.length;
    const oldSkip = info.skipped;
    const newSkip = skippedCount;
    const oldMale = info.with_males;
    const newMale = withMalesCount;

    oldRelTotal += oldRel;
    newRelTotal += newRel;
    oldSkipTotal += oldSkip;
    newSkipTotal += newSkip;
    oldMaleTotal += oldMale;
    newMaleTotal += newMale;

    info.relevant = newRel;
    info.skipped = newSkip;
    info.with_males = newMale;

    tableRows.push({
      displayName,
      wikiName,
      pages: totalPages,
      oldRel,
      newRel,
      relDiff: newRel - oldRel,
      oldSkip,
      newSkip,
      skipDiff: newSkip - oldSkip,
      oldMale,
      newMale,
      maleDiff: newMale - oldMale
    });
  }

  const jsonPath = path.join(dataDir, "resolved_names.json");
  atomicWriteJsonSync(jsonPath, resolvedData);

  console.log("\n=========================================================================================================");
  console.log("【--reparse 重新解析前後對照表】");
  console.log("=========================================================================================================");
  console.log(
    cjkPadEnd("女優名", 16) +
    cjkPadEnd("搜尋寫法", 18) +
    cjkPadStart("頁數", 6) +
    cjkPadStart("相關作品 (舊 → 新)", 24) +
    cjkPadStart("略過作品 (舊 → 新)", 24) +
    cjkPadStart("有男優作品 (舊 → 新)", 24)
  );
  console.log("-".repeat(112));

  for (const r of tableRows) {
    const relStr = `${r.oldRel} → ${r.newRel}${r.relDiff !== 0 ? ` (+${r.relDiff})` : ""}`;
    const skipStr = `${r.oldSkip} → ${r.newSkip}${r.skipDiff !== 0 ? ` (${r.skipDiff})` : ""}`;
    const maleStr = `${r.oldMale} → ${r.newMale}${r.maleDiff !== 0 ? ` (+${r.maleDiff})` : ""}`;
    console.log(
      cjkPadEnd(r.displayName, 16) +
      cjkPadEnd(r.wikiName, 18) +
      cjkPadStart(String(r.pages), 6) +
      cjkPadStart(relStr, 24) +
      cjkPadStart(skipStr, 24) +
      cjkPadStart(maleStr, 24)
    );
  }

  console.log("=".repeat(112));
  const totalRelStr = `${oldRelTotal} → ${newRelTotal} (+${newRelTotal - oldRelTotal})`;
  const totalSkipStr = `${oldSkipTotal} → ${newSkipTotal} (${newSkipTotal - oldSkipTotal})`;
  const totalMaleStr = `${oldMaleTotal} → ${newMaleTotal} (+${newMaleTotal - oldMaleTotal})`;
  console.log(
    cjkPadEnd("合計", 16) +
    cjkPadEnd("-", 18) +
    cjkPadStart("-", 6) +
    cjkPadStart(totalRelStr, 24) +
    cjkPadStart(totalSkipStr, 24) +
    cjkPadStart(totalMaleStr, 24)
  );
  console.log("=========================================================================================================");
  console.log(`\n重新解析完成: 總處理 ${tableRows.length} 位女優，快取缺漏跳過 ${skippedDueToMissing} 位。`);
  console.log(`確認導航次數: 0 (完全離線重算)`);
}

async function recheckUnresolvedActresses(dataDir) {
  const startTime = Date.now();
  console.log("==================================================");
  console.log("avdanyuwiki 重判 unresolved 女優任務啟動");
  console.log(`資料目錄: ${dataDir}`);
  console.log("==================================================");

  const resolvedData = loadResolvedNames(dataDir);
  const unresolvedEntries = Object.entries(resolvedData.unresolved);
  console.log(`待重判 unresolved 女優人數: ${unresolvedEntries.length} 位`);

  const results = [];

  for (let i = 0; i < unresolvedEntries.length; i++) {
    const [displayName, candidateCounts] = unresolvedEntries[i];
    console.log(`\n==================================================`);
    console.log(`[${i + 1}/${unresolvedEntries.length}] 開始重判女優: ${displayName}`);
    console.log(`==================================================`);

    const cacheDir = path.join(dataDir, "cache", "wiki", displayName);
    const page1CacheFile = path.join(cacheDir, "page_1.html");
    const skippedCacheFile = path.join(cacheDir, "skipped.json");

    let adoptedCandidate = null;
    let adoptedProbeFile = null;
    const probeEvaluations = {};

    if (fs.existsSync(cacheDir)) {
      const probeFiles = fs.readdirSync(cacheDir).filter((f) => f.startsWith("probe_") && f.endsWith(".html"));
      for (const pf of probeFiles) {
        const cand = pf.slice(6, -5);
        const probePath = path.join(cacheDir, pf);
        const probeHtml = fs.readFileSync(probePath, "utf-8");
        const testCards = parseCardsFromHtml(probeHtml);
        const matchCount = testCards.filter((c) => isPerformerMatchingCandidate(c.performerText, cand)).length;
        const smallButClean = matchCount >= 1 && testCards.length < 20 && matchCount === testCards.length;
        probeEvaluations[cand] = { totalCards: testCards.length, matchCount, smallButClean };

        console.log(`[探測評估] 寫法「${cand}」探測頁共 ${testCards.length} 張卡片，相關作品: ${matchCount} (smallButClean: ${smallButClean})`);

        if (matchCount >= ADOPTION_THRESHOLD || smallButClean) {
          adoptedCandidate = cand;
          adoptedProbeFile = probePath;
          break;
        }
      }
    }

    if (adoptedCandidate && adoptedProbeFile) {
      console.log(`[重判通過] 女優「${displayName}」候選「${adoptedCandidate}」通過門檻！`);
      console.log(`[複製快取] 將探測頁複製為 ${page1CacheFile} (省一次第 1 頁導航)`);
      fs.copyFileSync(adoptedProbeFile, page1CacheFile);

      if (fs.existsSync(skippedCacheFile)) {
        try {
          fs.unlinkSync(skippedCacheFile);
          console.log(`[清除略過] 已刪除 ${skippedCacheFile}`);
        } catch (_) {}
      }

      updateResolvedNames(dataDir, (d) => {
        delete d.unresolved[displayName];
      });

      console.log(`[接續一般流程] 繼續翻查女優「${displayName}」第 2 頁起...`);
      const res = await processActress({ displayName, candidates: [adoptedCandidate] }, dataDir);
      results.push(res);
    } else {
      console.log(`[重判未通過] 女優「${displayName}」所有探測候選皆未達門檻，維持 unresolved，保留 probe 快取。`);
      results.push({
        actress: displayName,
        adoptedCandidate: null,
        candidateCounts,
        probeEvaluations,
        navigations: 0,
        pagesTurned: 0,
        relevantCount: 0,
        skippedCount: 0,
        withDanyuCount: 0,
        isTruncated: false,
        done: false
      });
    }
  }

  if (cdpClient) {
    try {
      cdpClient.close();
    } catch (_) {}
  }

  const totalDurationMs = Date.now() - startTime;
  const minIntervalSec = minNavIntervalMs === Infinity ? "N/A (無導航或僅 1 次導航)" : `${(minNavIntervalMs / 1000).toFixed(2)} 秒`;

  updateCrawlState(dataDir, {
    status: "completed_unresolved_batch",
    totalNavigations,
    minNavIntervalMs: minNavIntervalMs === Infinity ? null : minNavIntervalMs,
    finishedAt: new Date().toISOString()
  });

  console.log("\n==================================================");
  console.log("unresolved 女優重判與補爬完成，統計回報");
  console.log("==================================================");
  console.log(`總耗時: ${(totalDurationMs / 1000).toFixed(2)} 秒`);
  console.log(`總導航次數: ${totalNavigations}`);
  console.log(`實際導航最小間隔: ${minIntervalSec}`);
  console.log(`是否遇到驗證頁: ${verificationEncountered ? `是（共遇到 ${verificationCount} 次，累積等待 ${(verificationTotalWaitMs / 1000).toFixed(1)} 秒）` : "否"}`);

  console.log("\n重判個別結果清單:");
  for (const r of results) {
    if (r.done) {
      console.log(`- [通過 / RESOLVED] ${r.actress}: 採用「${r.adoptedCandidate}」 | 導航: ${r.navigations} 次 | 頁數: ${r.pagesTurned} | 相關: ${r.relevantCount} 部 | 略過: ${r.skippedCount} 部 | 有男優: ${r.withDanyuCount} 部 | 截斷: ${r.isTruncated ? "是" : "否"}`);
    } else {
      console.log(`- [未通過 / UNRESOLVED] ${r.actress}: 未達門檻 (維持 unresolved) | 各候選結果: ${JSON.stringify(r.candidateCounts)}`);
    }
  }
  console.log("==================================================");

  return results;
}

async function extendActress(displayName, maxPages = 120, dataDir) {
  const startTime = Date.now();
  console.log("==================================================");
  console.log("avdanyuwiki 女優搜尋結果擴展模式 (--extend) 啟動");
  console.log(`目標女優: ${displayName}`);
  console.log(`最大頁數: ${maxPages}`);
  console.log(`資料目錄: ${dataDir}`);
  console.log("==================================================");

  const resolvedData = loadResolvedNames(dataDir);
  const oldRecord = resolvedData.resolved[displayName];
  if (!oldRecord) {
    console.error(`[錯誤] 女優「${displayName}」尚未在 resolved_names.json 中，無法執行 --extend`);
    process.exit(1);
  }

  const wikiName = oldRecord.wiki_name || displayName;
  const cacheDir = path.join(dataDir, "cache", "wiki", displayName);
  if (!fs.existsSync(cacheDir)) {
    fs.mkdirSync(cacheDir, { recursive: true });
  }

  // 盤點既有連續快取頁數
  let lastCachedPage = 0;
  while (fs.existsSync(path.join(cacheDir, `page_${lastCachedPage + 1}.html`))) {
    lastCachedPage++;
  }
  console.log(`[快取盤點] 女優「${displayName}」(wiki_name: ${wikiName}) 連續快取至第 ${lastCachedPage} 頁 (resolved 記錄頁數: ${oldRecord.pages})`);

  if (lastCachedPage === 0) {
    console.error(`[錯誤] 快取中找不到第 1 頁，無法擴展`);
    process.exit(1);
  }

  const lastPageFile = path.join(cacheDir, `page_${lastCachedPage}.html`);
  const lastPageHtml = fs.readFileSync(lastPageFile, "utf-8");
  const hasNext = hasNextPage(lastPageHtml);

  let totalPages = lastCachedPage;
  let isTruncated = false;
  let currentHtml = lastPageHtml;

  if (!hasNext) {
    console.log(`[無需導航] 第 ${lastCachedPage} 頁已無「次へ」連結，已抓取完整，直接進行離線重算與更新。`);
  } else {
    console.log(`[接續導航] 第 ${lastCachedPage} 頁仍有下一頁，自第 ${lastCachedPage + 1} 頁起逐頁導航至最多第 ${maxPages} 頁...`);
    currentActressName = displayName;

    for (let page = lastCachedPage + 1; page <= maxPages; page++) {
      currentPageNum = page;
      updateCrawlState(dataDir, { currentActress: displayName, currentPage: page, status: "running" });

      const pageCacheFile = path.join(cacheDir, `page_${page}.html`);
      if (fs.existsSync(pageCacheFile)) {
        console.log(`[快取命中] 第 ${page} 頁已存在快取: ${pageCacheFile}`);
        currentHtml = fs.readFileSync(pageCacheFile, "utf-8");
      } else {
        const pageUrl = `https://avdanyuwiki.com/?s=${encodeURIComponent(wikiName)}&paged=${page}`;
        const navRes = await navigateTo(pageUrl, dataDir);
        currentHtml = navRes.html;
        fs.writeFileSync(pageCacheFile, currentHtml, "utf-8");
        console.log(`[寫入快取] 已儲存第 ${page} 頁至: ${pageCacheFile}`);
      }

      const cardCount = countCards(currentHtml);
      if (cardCount === 0) {
        console.log(`[分頁結束] 第 ${page} 頁無任何 article 卡片，抓取結束。`);
        if (fs.existsSync(pageCacheFile)) {
          try { fs.unlinkSync(pageCacheFile); } catch (_) {}
        }
        break;
      }

      totalPages = page;

      if (page === maxPages) {
        if (hasNextPage(currentHtml)) {
          isTruncated = true;
          console.warn(`[截斷警告] 女優「${displayName}」達到第 ${maxPages} 頁上限仍有下一頁，維持 truncated: true！`);
        } else {
          isTruncated = false;
        }
        break;
      }

      if (!hasNextPage(currentHtml)) {
        isTruncated = false;
        console.log(`[分頁結束] 第 ${page} 頁無「次へ」連結，已達最後一頁。`);
        break;
      }
    }
  }

  if (cdpClient) {
    try {
      cdpClient.close();
    } catch (_) {}
  }

  // 全部頁面重新解析
  console.log(`\n[開始解析] 正在重新解析第 1 ~ ${totalPages} 頁所有快取...`);
  const allWorks = [];
  const relevantWorks = [];
  let skippedCount = 0;

  for (let page = 1; page <= totalPages; page++) {
    const pageCacheFile = path.join(cacheDir, `page_${page}.html`);
    if (!fs.existsSync(pageCacheFile)) {
      console.error(`[快取頁缺漏] 缺少第 ${page} 頁快取: ${pageCacheFile}`);
      break;
    }
    const html = fs.readFileSync(pageCacheFile, "utf-8");
    const cards = parseCardsFromHtml(html);

    for (const card of cards) {
      allWorks.push(card);
      if (isPerformerMatchingCandidate(card.performerText, wikiName)) {
        relevantWorks.push(card);
      } else {
        skippedCount++;
      }
    }
  }

  const withDanyuCount = relevantWorks.filter((w) => !!w.danyuText).length;

  // 原子寫入 CSV
  const csvPath = path.join(dataDir, `wiki_works_${displayName}.csv`);
  const csvContent = buildCsvContent(relevantWorks);
  atomicWriteFileSync(csvPath, csvContent);
  console.log(`[寫入完成] 已輸出 CSV: ${csvPath} (共 ${relevantWorks.length} 部相關作品)`);

  // 原子更新 resolved_names.json
  updateResolvedNames(dataDir, (d) => {
    d.resolved[displayName] = {
      wiki_name: wikiName,
      pages: totalPages,
      relevant: relevantWorks.length,
      skipped: skippedCount,
      with_males: withDanyuCount,
      truncated: isTruncated,
      done: true
    };
    delete d.unresolved[displayName];
  });

  const totalDurationMs = Date.now() - startTime;
  const minIntervalSec = minNavIntervalMs === Infinity ? "N/A (無導航或僅 1 次導航)" : `${(minNavIntervalMs / 1000).toFixed(2)} 秒`;

  updateCrawlState(dataDir, {
    status: isTruncated ? "completed_extend_truncated" : "completed_extend",
    currentActress: displayName,
    currentPage: totalPages,
    totalNavigations,
    minNavIntervalMs: minNavIntervalMs === Infinity ? null : minNavIntervalMs,
    finishedAt: new Date().toISOString()
  });

  console.log("\n==================================================");
  console.log(`【${displayName}】--extend 執行結果統計`);
  console.log("==================================================");
  console.log(`- 頁數 (舊 → 新): ${oldRecord.pages} → ${totalPages}`);
  console.log(`- 相關作品數 (舊 → 新): ${oldRecord.relevant} → ${relevantWorks.length} (+${relevantWorks.length - oldRecord.relevant})`);
  console.log(`- 略過作品數 (舊 → 新): ${oldRecord.skipped} → ${skippedCount} (+${skippedCount - oldRecord.skipped})`);
  console.log(`- 有男優作品數 (舊 → 新): ${oldRecord.with_males} → ${withDanyuCount} (+${withDanyuCount - oldRecord.with_males})`);
  console.log(`- 是否截斷 (truncated) (舊 → 新): ${oldRecord.truncated} → ${isTruncated}`);
  console.log(`- 實際導航次數: ${totalNavigations}`);
  console.log(`- 實際導航最小間隔: ${minIntervalSec}`);
  console.log(`- 總耗時: ${(totalDurationMs / 1000).toFixed(2)} 秒`);
  console.log(`- 驗證頁遇到次數: ${verificationCount} 次`);
  console.log(`- 驗證頁等待總時間: ${(verificationTotalWaitMs / 1000).toFixed(1)} 秒`);
  console.log(`- 是否完成: ${isTruncated ? "否 (達到上限仍有下一頁)" : "是"}`);
  console.log("==================================================");
}

// 增量更新：只翻搜尋結果最前面幾頁（新到舊），遇到「整頁都已收錄」就停。
// 新作品另存 data/updates/wiki_works_<名>.csv，不動主 CSV 與頁面快取（--reparse 不受影響），merge_multi.py 會一併讀入。
async function updateActresses(dataDir, only, maxPages) {
  const startTime = Date.now();
  const resolved = loadResolvedNames(dataDir).resolved;
  const names = Object.keys(resolved).filter((n) => resolved[n].done && (only.length === 0 || only.includes(n)));
  const missing = only.filter((n) => !resolved[n] || !resolved[n].done);
  if (missing.length) console.warn(`[略過] 不在 resolved_names.json 或尚未完成: ${missing.join("、")}`);

  console.log("==================================================");
  console.log("avdanyuwiki 增量更新模式 (--update) 啟動");
  console.log(`目標人數: ${names.length}｜每人最多翻 ${maxPages} 頁｜資料目錄: ${dataDir}`);
  console.log("==================================================");

  const updatesDir = path.join(dataDir, "updates");
  const summary = [];
  for (let i = 0; i < names.length; i++) {
    const name = names[i];
    const wikiName = resolved[name].wiki_name || name;
    currentActressName = name;

    const readCards = (file) => (fs.existsSync(file) ? csvToCards(fs.readFileSync(file, "utf-8")) : []);
    const updatesCsv = path.join(updatesDir, `wiki_works_${name}.csv`);
    const prior = readCards(updatesCsv);
    const known = new Set([...readCards(path.join(dataDir, `wiki_works_${name}.csv`)), ...prior].map(cardKey));
    const isRelevant = (c) => isPerformerMatchingCandidate(c.performerText, wikiName);

    const added = [];
    let capped = false;
    for (let page = 1; page <= maxPages; page++) {
      currentPageNum = page;
      updateCrawlState(dataDir, { currentActress: name, currentPage: page, status: "running_update" });
      const url = `https://avdanyuwiki.com/?s=${encodeURIComponent(wikiName)}${page > 1 ? `&paged=${page}` : ""}`;
      const { html } = await navigateTo(url, dataDir);
      const { newCards, stop } = judgePage(parseCardsFromHtml(html), isRelevant, known);
      for (const c of newCards) {
        known.add(cardKey(c));
        added.push(c);
      }
      console.log(`[${i + 1}/${names.length}] ${name} 第 ${page} 頁：新增 ${newCards.length} 部${stop ? "（整頁已收錄，停止）" : ""}`);
      if (stop || !hasNextPage(html)) break;
      if (page === maxPages) capped = true;
    }
    if (capped) console.warn(`[上限] ${name} 翻滿 ${maxPages} 頁仍有新作，可能還有更多；請加大 --max-pages 或改用 --extend`);

    if (added.length) {
      fs.mkdirSync(updatesDir, { recursive: true });
      atomicWriteFileSync(updatesCsv, buildCsvContent([...prior, ...added]));
    }
    updateResolvedNames(dataDir, (d) => {
      d.resolved[name].last_update = { at: new Date().toISOString(), new: added.length, capped };
    });
    summary.push({ name, added: added.length, capped });
  }

  if (cdpClient) cdpClient.close();
  updateCrawlState(dataDir, { status: "completed_update", totalNavigations, finishedAt: new Date().toISOString() });

  console.log("\n==================================================");
  console.log("增量更新結果");
  console.log("==================================================");
  for (const s of summary) console.log(`- ${s.name}: 新增 ${s.added} 部${s.capped ? "（已達頁數上限）" : ""}`);
  console.log(`- 合計新增: ${summary.reduce((n, s) => n + s.added, 0)} 部｜導航 ${totalNavigations} 次｜耗時 ${((Date.now() - startTime) / 1000).toFixed(1)} 秒｜驗證頁 ${verificationCount} 次`);
}

async function main() {
  const startTime = Date.now();

  let dataDir = path.resolve(__dirname, "data");
  let listFilePath = null;
  let isReparse = false;
  let isUnresolved = false;
  let extendName = null;
  let maxPages = null;
  let isUpdate = false;
  let onlyNames = [];
  const names = [];

  for (let i = 2; i < process.argv.length; i++) {
    const arg = process.argv[i];
    if (arg === "--data" && i + 1 < process.argv.length) {
      dataDir = path.resolve(process.argv[++i]);
    } else if (arg.startsWith("--data=")) {
      dataDir = path.resolve(arg.slice(7));
    } else if (arg === "--file" && i + 1 < process.argv.length) {
      listFilePath = path.resolve(process.argv[++i]);
    } else if (arg.startsWith("--file=")) {
      listFilePath = path.resolve(arg.slice(7));
    } else if (arg === "--extend" && i + 1 < process.argv.length) {
      extendName = process.argv[++i];
    } else if (arg.startsWith("--extend=")) {
      extendName = arg.slice(9);
    } else if (arg === "--max-pages" && i + 1 < process.argv.length) {
      maxPages = parseInt(process.argv[++i], 10);
    } else if (arg.startsWith("--max-pages=")) {
      maxPages = parseInt(arg.slice(12), 10);
    } else if (arg === "--update") {
      isUpdate = true;
    } else if (arg === "--only" && i + 1 < process.argv.length) {
      onlyNames = process.argv[++i].split(",").map((s) => s.trim()).filter(Boolean);
    } else if (arg.startsWith("--only=")) {
      onlyNames = arg.slice(7).split(",").map((s) => s.trim()).filter(Boolean);
    } else if (arg === "--reparse") {
      isReparse = true;
    } else if (arg === "--unresolved" || arg === "--recheck-unresolved") {
      isUnresolved = true;
    } else if (arg === "--batchC") {
      isReparse = true;
      isUnresolved = true;
    } else if (!arg.startsWith("--")) {
      names.push(arg);
    }
  }

  if (isUpdate) {
    await updateActresses(dataDir, onlyNames, maxPages || UPDATE_DEFAULT_MAX_PAGES);
    return;
  }

  if (extendName) {
    await extendActress(extendName, maxPages || 120, dataDir);
    return;
  }

  if (isReparse && !isUnresolved) {
    await reparseResolvedActresses(dataDir);
    return;
  }

  if (isReparse && isUnresolved) {
    await reparseResolvedActresses(dataDir);
    console.log("\n");
    await recheckUnresolvedActresses(dataDir);
    return;
  }

  if (isUnresolved) {
    await recheckUnresolvedActresses(dataDir);
    return;
  }

  // 離線補入前一批女優資料至 resolved_names.json
  ensurePreviousBatchInResolvedNames(dataDir);

  const targets = [];
  if (listFilePath) {
    if (!fs.existsSync(listFilePath)) {
      throw new Error(`找不到名單檔案: ${listFilePath}`);
    }
    const lines = fs.readFileSync(listFilePath, "utf-8").split(/\r?\n/);
    for (const rawLine of lines) {
      const line = rawLine.trim();
      if (!line || line.startsWith("#")) continue;
      const parts = rawLine.split("\t");
      const displayName = parts[0].trim();
      let candidates = [displayName];
      if (parts.length > 1 && parts[1].trim()) {
        candidates = parts[1].split("|").map((c) => c.trim()).filter(Boolean);
      }
      targets.push({ displayName, candidates });
    }
  } else if (names.length > 0) {
    for (const name of names) {
      targets.push({
        displayName: name,
        candidates: CANDIDATE_SPELLINGS[name] || [name]
      });
    }
  } else {
    // 預設
    const defaults = ["三上悠亞", "鈴村あいり", "本庄鈴"];
    for (const name of defaults) {
      targets.push({
        displayName: name,
        candidates: CANDIDATE_SPELLINGS[name] || [name]
      });
    }
  }

  console.log("==================================================");
  console.log("avdanyuwiki 女優作品與出演男優批次蒐集工具啟動");
  console.log(`名單來源: ${listFilePath ? listFilePath : "命令列參數"}`);
  console.log(`目標人數: ${targets.length}`);
  console.log(`資料目錄: ${dataDir}`);
  console.log("==================================================");

  updateCrawlState(dataDir, {
    status: "running",
    totalTargets: targets.length,
    startedAt: new Date().toISOString()
  });

  const results = [];
  let consecutiveZeroActresses = 0;

  for (let i = 0; i < targets.length; i++) {
    const target = targets[i];
    console.log(`\n==================================================`);
    console.log(`[${i + 1}/${targets.length}] 開始處理女優: ${target.displayName}`);
    console.log(`==================================================`);

    const res = await processActress(target, dataDir);
    results.push(res);

    if (res.done) {
      consecutiveZeroActresses = 0;
    } else {
      const counts = Object.values(res.candidateCounts || {});
      const maxCards = counts.length > 0 ? Math.max(...counts) : 0;
      if (maxCards === 0) {
        consecutiveZeroActresses++;
        console.warn(`[連續零卡警告] 女優「${target.displayName}」所有候選第 1 頁相關張數皆為 0 (連續第 ${consecutiveZeroActresses} 位)`);
        if (consecutiveZeroActresses >= 3) {
          console.error(`[重大警報] 連續 3 位女優所有候選第 1 頁相關張數為 0，可能名單或連線有問題，停止流程！停在: ${target.displayName}`);
          updateCrawlState(dataDir, {
            status: "stopped_consecutive_zero_candidates",
            stoppedReason: `連續 3 位女優所有候選第 1 頁相關張數為 0，停在: ${target.displayName}`
          });
          if (cdpClient) cdpClient.close();
          process.exit(1);
        }
      } else {
        consecutiveZeroActresses = 0;
      }
    }
  }

  if (cdpClient) {
    cdpClient.close();
  }

  const totalDurationMs = Date.now() - startTime;
  const minIntervalSec = minNavIntervalMs === Infinity ? "N/A (無導航或僅 1 次導航)" : `${(minNavIntervalMs / 1000).toFixed(2)} 秒`;

  updateCrawlState(dataDir, {
    status: "completed",
    totalNavigations,
    minNavIntervalMs: minNavIntervalMs === Infinity ? null : minNavIntervalMs,
    finishedAt: new Date().toISOString()
  });

  console.log("\n==================================================");
  console.log("所有女優處理完成，總體統計回報");
  console.log("==================================================");
  console.log(`總耗時: ${(totalDurationMs / 1000).toFixed(2)} 秒`);
  console.log(`總導航次數: ${totalNavigations}`);
  console.log(`實際導航最小間隔: ${minIntervalSec}`);
  console.log(`是否遇到驗證頁: ${verificationEncountered ? `是（共遇到 ${verificationCount} 次，累積等待 ${(verificationTotalWaitMs / 1000).toFixed(1)} 秒）` : "否"}`);

  console.log("\n個別女優結果清單:");
  for (const r of results) {
    if (r.done) {
      console.log(`- [RESOLVED] ${r.actress}: 採用「${r.adoptedCandidate}」 | 導航: ${r.navigations} 次 | 頁數: ${r.pagesTurned} | 相關: ${r.relevantCount} 部 | 略過: ${r.skippedCount} 部 | 有男優: ${r.withDanyuCount} 部 | 截斷: ${r.isTruncated ? "是" : "否"}`);
    } else {
      console.log(`- [UNRESOLVED] ${r.actress}: 未通過門檻 | 導航: ${r.navigations} 次 | 各候選結果: ${JSON.stringify(r.candidateCounts)}`);
    }
  }
  console.log("==================================================");
}

main().catch((err) => {
  console.error("執行發生致命錯誤:", err);
  if (cdpClient) {
    try {
      cdpClient.close();
    } catch (_) {}
  }
  process.exit(1);
});
