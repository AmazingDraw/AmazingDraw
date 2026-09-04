// =====================================================================
// ⚡ Global State
// =====================================================================

/* core.js — 共享状态、通用工具与启动引导
   由 app.js 拆分而来；加载顺序见 index.html，core.js 必须最先。 */

let state = {
  activeCardId: null,
  cards: [],
  profiles: {},
  celebrities: [],
  scenes: [],
  settings: {},
  lastSlots: {}, // 用于比对并触发闪烁效果
  openclawModels: [],
  cliproxyModels: [],
  activeFilter: "all",
  timeFilter: "all",     // all / today / 7d / 30d / YYYY-MM
  cardsLimit: 100,
  sessionsLimit: 100,
  sessionTotal: 0,
  // 抽卡会话
  sessions: [],
  activeSessionId: null,
  // 卡片→抽卡交接：锁定 UI，禁止 loadSessions 闪回旧会话
  sessionUiLock: false,
  pendingSessionId: null,
  handoffGen: 0,          // 交接代数，用于丢弃过期回调
  historyLoadToken: 0,    // 历史加载代数，防止旧请求晚到覆盖新会话
  isChatBusy: false,      // 发送/流式中，禁止 silent 历史重载抹掉气泡
  streamingSessionId: null, // 正在流式的那个会话；用于只保护它的气泡，不连累其它会话的切换
  streamingTurn: null,      // 在途这轮的 {userText, replyText, msgId}；切回该会话时补画（此时尚未落盘）
  streamingTurns: new Map(), // 每个会话各自的在途轮次，允许 S1/S2/S3 并发且不串 UI
  bootReady: false,       // settings 就绪前禁止 loadCards 画侧栏
  activeView: "chat",     // 当前 workspace 视图：chat / settings / docs (注: 对应 Cards/Draw/配置/文档 选项)
  dangerConfirmAction: null,
};


// =====================================================================
// 🚀 Page Bootstrapping
// =====================================================================
document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  initNavigation();
  initKeyboardNavigation();
  initResizers();
  initLightbox();
  initCardStatusFilters();
  initTimeFilter();
  initChat();
  initModals();
  initAutocomplete();
  initQueueCollapse();
  initPoetryWidget();
  
  // 渲染引导消息
  showWelcomeMessage();

  // 先等 settings 就绪再按 chat_mode 分支侧栏，避免抽卡页刷新先画成卡片布局
  loadPresets();
  loadSettings().then(() => {
    state.bootReady = true;
    // 完整同步 mode 按钮 + 指示条（loadSettings 在 boot 期只做了半套样式）
    renderChatModeButtons({ skipSidebar: true });
    const mode = normalizeChatMode(state.settings && state.settings.chat_mode);
    if (mode === "draw") {
      // 刷新恢复：boot 时先灌入 localStorage 会话 id，再拉列表+历史，避免内容空
      const savedSessionId = localStorage.getItem("active_session_id");
      if (savedSessionId) {
        state.activeSessionId = savedSessionId;
      }
      updateSidebarViewMode();
    } else {
      loadCards();
    }
    if (typeof maybeStartWebuiOnboarding === "function") maybeStartWebuiOnboarding();
  }).catch(() => {
    state.bootReady = true;
    renderChatModeButtons({ skipSidebar: true });
    loadCards();
    if (typeof maybeStartWebuiOnboarding === "function") maybeStartWebuiOnboarding();
  });

  // 开启卡片列表增量轮询（每 3 秒一次）
  initIncrementalPolling();

  // 开启队列轮询（每 4 秒一次）
  setInterval(loadQueueStatus, 4000);
  
  // 初始化直投模式（连抽已改为对话指令，无独立前端页）
  initDirectMode();
  
  // 初始化垂直对话模式选择器
  initChatModeSelector();

  // 绑定原生会话新建按钮事件
});

// =====================================================================
// 🔔 Toast Notifications
// =====================================================================
function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  if (!container) return;
  
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  
  let icon = "fa-circle-info";
  if (type === "success") icon = "fa-circle-check";
  if (type === "error") icon = "fa-triangle-exclamation";

  const iconEl = document.createElement("i");
  iconEl.className = `fa-solid ${icon}`;
  const textEl = document.createElement("span");
  textEl.textContent = String(message ?? "");
  toast.appendChild(iconEl);
  toast.appendChild(textEl);
  container.appendChild(toast);
  
  setTimeout(() => {
    toast.style.animation = "slideIn 0.3s reverse";
    setTimeout(() => {
      if (toast.parentNode) {
        container.removeChild(toast);
      }
    }, 300);
  }, 3200);
}

// =====================================================================
// 🌓 Theme Switching Manager (localStorage remembered)
// =====================================================================
/* 只拦危险协议，相对路径与锚点照常放行。
   先去掉控制字符再判协议，挡住 "java\tscript:" 这类夹缝写法。 */
function safeLinkHref(href) {
  const raw = String(href || "").trim();
  if (!raw) return "";
  const probe = raw.replace(/[\u0000-\u0020]/g, "");
  const m = /^([a-z][a-z0-9+.-]*):/i.exec(probe);
  if (m && !["http", "https", "mailto"].includes(m[1].toLowerCase())) return "";
  return raw;
}

/* 带安全钩子的 marked 实例。
   marked 默认原样放行原始 HTML，而 AI 输出常包含它读到的文件或网页内容，
   直接进 innerHTML 就是注入面；这里把「原始 HTML」这类 token 转义成字面量，
   markdown 语法与代码块不受影响。链接另外拦 javascript: 之类协议。
   用独立实例而不是全局 setOptions：聊天要 breaks，文档不要，互不干扰。 */
function createSafeMarked(options) {
  if (!window.marked || typeof marked.Marked !== "function") return null;
  const inst = new marked.Marked(options || {});
  inst.use({
    renderer: {
      html(tok) {
        return escapeHtml(tok && tok.text !== undefined ? tok.text : tok);
      },
      link(tokenOrHref, title, text) {
        const tok = (tokenOrHref && typeof tokenOrHref === "object")
          ? tokenOrHref
          : { href: tokenOrHref, title, text };
        // tok.text 是未经解析的 Markdown 源文本，可能含 <img onerror=...>。
        // 必须让嵌套 token 重新经过本 renderer；其中 html() 会转义原始标签。
        const label = Array.isArray(tok.tokens) && this.parser
          ? this.parser.parseInline(tok.tokens)
          : escapeHtml(tok.text != null ? tok.text : "");
        const href = safeLinkHref(tok.href);
        if (!href) return label;   // 危险协议退化成纯文字，不留可点入口
        const t = tok.title ? ` title="${escapeHtml(tok.title)}"` : "";
        return `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer"${t}>${label}</a>`;
      },
    },
  });
  return inst;
}

/* 中文对话里模型常写出 CommonMark 不认的加粗：
   1) `** 【标题】 **` 星号内侧空格
   2) `带**‘标题’**服务` 汉字贴着 **，内侧又是 Unicode 标点（侧翼规则失败）
   只改 Markdown 源码的空格，不插入 HTML。代码块/行内代码整段保护。
   半边 `**` 不配对，保持字面量。 */
function _mdIsPunct(ch) {
  return !!ch && /[\p{P}\p{S}]/u.test(ch);
}

function _mdNeedsOpenPad(prev, innerFirst) {
  if (!innerFirst || /\s/.test(innerFirst) || !_mdIsPunct(innerFirst)) return false;
  if (!prev || /\s/.test(prev) || _mdIsPunct(prev)) return false;
  return true;
}

function _mdNeedsClosePad(innerLast, next) {
  if (!innerLast || /\s/.test(innerLast) || !_mdIsPunct(innerLast)) return false;
  if (!next || /\s/.test(next) || _mdIsPunct(next)) return false;
  return true;
}

function normalizeChatMarkdown(src) {
  const text = String(src ?? "");
  if (!text || text.indexOf("**") === -1) return text;
  const slots = [];
  const stash = (chunk) => {
    const i = slots.length;
    slots.push(chunk);
    return `\uE000MD${i}\uE001`;
  };
  let out = text.replace(/```[\s\S]*?(?:```|$)/g, stash);
  out = out.replace(/`[^`\n]+`/g, stash);
  out = out.replace(/\*\*[ \t]+([^*\n]+?)[ \t]+\*\*/g, "**$1**");
  out = out.replace(/\*\*([^*\n]+)\*\*/g, (m, inner, offset) => {
    if (!String(inner).trim()) return m;
    const prev = offset > 0 ? out[offset - 1] : " ";
    const next = out[offset + m.length] || " ";
    const open = _mdNeedsOpenPad(prev, inner[0]) ? " **" : "**";
    const close = _mdNeedsClosePad(inner[inner.length - 1], next) ? "** " : "**";
    return open + inner + close;
  });
  return out.replace(/\uE000MD(\d+)\uE001/g, (_, i) => slots[Number(i)] ?? "");
}

function wrapChatMarked(inst) {
  if (!inst || inst.__chatNormalized) return inst;
  const parse = inst.parse.bind(inst);
  const parseInline = inst.parseInline.bind(inst);
  inst.parse = (src, opt) => parse(normalizeChatMarkdown(src), opt);
  inst.parseInline = (src, opt) => parseInline(normalizeChatMarkdown(src), opt);
  inst.__chatNormalized = true;
  return inst;
}

let _mdChat = null;
let _mdDoc = null;
/** 聊天用：单换行即换行，符合对话观感 */
function markdownForChat() {
  if (!_mdChat) _mdChat = wrapChatMarked(createSafeMarked({ gfm: true, breaks: true }));
  return _mdChat;
}
/** 文档用：遵循标准 markdown，单换行不断行 */
function markdownForDoc() {
  if (!_mdDoc) _mdDoc = createSafeMarked({ gfm: true, breaks: false });
  return _mdDoc;
}

function escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/** 仅解码工具 JSON 属性会用到的 HTML 实体，不创建 DOM/不触发资源事件。 */
function decodeHtmlEntities(str) {
  const decodeCodePoint = (raw, radix) => {
    const value = Number.parseInt(raw, radix);
    if (!Number.isFinite(value) || value < 0 || value > 0x10ffff) return "";
    try {
      return String.fromCodePoint(value);
    } catch (_) {
      return "";
    }
  };
  return String(str ?? "")
    .replace(/&#x([0-9a-f]+);/gi, (_m, value) => decodeCodePoint(value, 16))
    .replace(/&#([0-9]+);/g, (_m, value) => decodeCodePoint(value, 10))
    .replace(/&quot;/gi, '"')
    .replace(/&apos;|&#39;/gi, "'")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&amp;/gi, "&");
}

function formatCardTime(mtime) {
  if (!mtime) return "";
  const date = new Date(mtime * 1000);
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${month}-${day} ${hours}:${minutes}`;
}

/**
 * 卡片筛选分类：状态集合与引擎 card_schema.json 的 status 枚举对齐。
 * 单一数据源，避免筛选逻辑在多处重复实现后各自漂移。
 * 未列入任何分类的状态（如 test_cleanup）只出现在「全部」。
 */
function normalizeChatMode(mode) {
  return String(mode || "").toLowerCase() === "draw" ? "draw" : "cards";
}

/** 同步右侧四入口高亮 + 滑动指示条（卡片/抽卡/配置/文档都会跟随） */
const CARD_FILTERS = {
  draft: { label: "草稿", statuses: ["draft", "filled"] },
  pending: { label: "定稿", statuses: ["validated", "submitted", "queued", "rendering"] },
  rendered: { label: "完成", statuses: ["rendered", "delivered", "success"] },
  failed: { label: "失败", statuses: ["failed"] },
};

function filterCardsByStatus(cards, filterKey) {
  const group = CARD_FILTERS[filterKey];
  if (!group) return cards;
  return cards.filter(c => group.statuses.includes(c.status));
}

/** 卡片用 mtime，会话用 updated_at，都是 unix 秒。 */
function itemUnixTime(item) {
  const raw = item && (item.mtime || item.updated_at);
  const value = Number(raw);
  return Number.isFinite(value) && value > 0 ? value : 0;
}

/** 按月份筛选，key 为 "all" 或 "YYYY-MM"；无时间戳的条目仅在「全部月份」下出现。 */
function filterItemsByTime(items, key) {
  if (!key || key === "all") return items;
  if (!/^\d{4}-\d{2}$/.test(key)) return items;
  return items.filter(item => {
    const ts = itemUnixTime(item);
    return ts && monthKeyOf(ts) === key;
  });
}

function filterCardsByTime(cards, key) {
  return filterItemsByTime(cards, key);
}

function monthKeyOf(mtime) {
  const d = new Date(mtime * 1000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

const RESOLUTION_FALLBACK = {
  vertical: { width: 512, height: 768 },
  horizontal: { width: 768, height: 512 },
  square: { width: 640, height: 640 },
  widescreen: { width: 1088, height: 464 },
};

function getPresetSize(key) {
  const fallback = RESOLUTION_FALLBACK[key] || RESOLUTION_FALLBACK.vertical;
  const preset = (state.settings.resolution_presets || {})[key] || {};
  return {
    width: parseInt(preset.width, 10) || fallback.width,
    height: parseInt(preset.height, 10) || fallback.height,
  };
}

function isCleanupEligibleCardId(cardId) {
  if (!cardId || typeof cardId !== "string") return false;
  const isTimestamp = cardId.length > 15 && /^\d/.test(cardId);
  const isFeatured = cardId.startsWith("featured_") && cardId.length > 15;
  return isTimestamp || isFeatured;
}

