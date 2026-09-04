/* onboarding.js — 新手导览 spotlight tour
   依赖 shell.js 的 switchView / renderChatModeButtons / updateSidebarViewMode；
   由 index.html 在 shell 之后加载。 */

const WEBUI_ONBOARDING_KEY = "amazingdraw_webui_onboarding_v3";

const _tour = {
  open: false,
  stepIndex: 0,
  prevView: null,
  prevMode: null,
  modeTouched: false,
  resizeBound: false,
  overlay: null,
};

async function _tourScrollSettingsAnchor(anchorId) {
  const el = document.getElementById(anchorId);
  if (!el) return;
  // 同步左侧快速跳转高亮
  document.querySelectorAll(".sidebar-anchor-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.getAttribute("data-anchor") === anchorId);
  });
  try {
    el.scrollIntoView({ behavior: "smooth", block: "center" });
  } catch (_) {
    el.scrollIntoView(true);
  }
  // 等布局稳定后再量 spotlight
  await new Promise((r) => setTimeout(r, 320));
}

const WEBUI_ONBOARDING_STEPS = [
  {
    id: "welcome",
    title: "欢迎使用 Amazing Draw",
    html: `<ul>
      <li>主界面分为三块：<strong>左侧</strong>历史列表与快捷操作、<strong>中间</strong>对话与结果区、<strong>右侧</strong>模式栏 + 参数看板。</li>
      <li>左上角品牌区的<strong>魔法棒图标</strong>可切换<strong>深色 / 浅色</strong>主题。</li>
      <li>首次打开会自动走完本导览；之后顶栏右侧有一个<strong>?</strong> 图标，可随时重看。</li>
      <li>可点「跳过」提前结束；结束后会恢复进入前的视图与模式。</li>
    </ul>`,
    view: "chat",
    mode: "cards",
    target: ".sidebar-brand",
    placement: "right",
  },
  {
    id: "mode-rail",
    title: "右侧模式栏",
    html: `<ul>
      <li><strong>卡片</strong>：浏览、筛选、预览历史卡片与参数；适合整理与复盘。</li>
      <li><strong>抽卡</strong>：AI 对话驱动建卡 / 连抽 / 常规流程（通常需要 OpenClaw）。</li>
      <li><strong>配置</strong>与<strong>文档</strong>：环境设置与完整说明。导览会在后续步骤自动跳转，无需手动点。</li>
    </ul>`,
    view: "chat",
    mode: "cards",
    target: "#chat-mode-selector",
    placement: "left",
  },
  {
    id: "cards-sidebar",
    title: "卡片模式 · 左侧列表",
    html: `<ul>
      <li>点「新建卡片骨架」可先搭结构再填内容。</li>
      <li>下方是历史卡片列表，可用状态筛选（草稿 / 定稿 / 失败 / 完成）与月份过滤。</li>
      <li>选中卡片后，右侧参数看板会展示对应配置。</li>
    </ul>`,
    view: "chat",
    mode: "cards",
    target: ".sidebar-actions",
    placement: "right",
  },
  {
    id: "chat-center",
    title: "中间 · 对话与结果",
    html: `<ul>
      <li>对话流、助手回复、出图结果都在中间主区展示。</li>
      <li>卡片模式下可结合左侧选中卡理解上下文；抽卡模式下以会话历史为主。</li>
      <li>滚动区域即当前对话正文，导览高亮的是消息列表主体。</li>
    </ul>`,
    view: "chat",
    mode: "cards",
    target: "#chat-body",
    placement: "left",
  },
  {
    id: "input-tools",
    title: "输入区 · 直投与精选",
    html: `<ul>
      <li><strong>直投</strong>（闪电）：输入完整英文 prompt，可直接建卡并提交渲染，<em>不依赖 OpenClaw</em>。</li>
      <li><strong>精选</strong>（骰子）：从 Obsidian 灵感库随机取笔记建卡并入队；需在配置里填好 Obsidian 保管箱路径。</li>
      <li>发送 / 停止按钮在同一行；抽卡模式下还可配合右侧快捷入口走常规 / 连抽对话流程。</li>
    </ul>`,
    view: "chat",
    mode: "cards",
    target: ".chat-input-row",
    placement: "top",
  },
  {
    id: "draw-mode",
    title: "抽卡模式 · 会话列表",
    html: `<ul>
      <li>切换到抽卡后，左侧变为会话 / 抽卡历史列表（同一侧栏区域）。</li>
      <li><strong>AI 连抽 / 常规</strong>需要已安装并可用的 OpenClaw；未安装时，配置页「AI 对话模型」会显示「请先安装 OpenClaw」。</li>
      <li>直投、精选仍可在输入区旁使用，不装 OpenClaw 也能建卡出图。</li>
    </ul>`,
    view: "chat",
    mode: "draw",
    target: "#sidebar-chat-sub",
    placement: "right",
  },
  {
    id: "param-queue",
    title: "参数看板与渲染队列",
    html: `<ul>
      <li>右侧参数看板：在卡片模式下选中一张卡，可查看 / 核对出图相关参数。</li>
      <li>下方是<strong>渲染队列</strong>：可查看排队与运行中任务，并使用「终止队列」「清空队列」。</li>
      <li>进入配置 / 文档页时看板会自动收起；回到对话视图会再展开。</li>
    </ul>`,
    view: "chat",
    mode: "cards",
    target: "#param-panel",
    placement: "left",
    prepare: async () => {
      if (typeof setParamPanelCollapsed === "function") setParamPanelCollapsed(false);
      await new Promise((r) => setTimeout(r, 200));
    },
  },
  {
    id: "settings-nav",
    title: "配置页 · 左侧快速跳转",
    html: `<ul>
      <li>左侧「快速跳转」对应右侧每一块配置；点一项会滚到对应分区。</li>
      <li>上方分组：<strong>环境与服务</strong>（核心 / 服务参数 / 工作流 / 路径）、<strong>生图与输出</strong>（分发 / 分辨率 / 算法 / 场景权重）。</li>
      <li>接下来会按块带你过右侧表单；改完记得顶栏「保存配置」。</li>
    </ul>`,
    view: "settings",
    mode: null,
    target: "#settings-anchor-nav",
    placement: "right",
  },
  {
    id: "settings-core",
    title: "配置 · 核心服务",
    html: `<ul>
      <li>出图依赖 <strong>ComfyUI</strong>：填写服务地址与本机安装根目录（本区分块靠下也有相关项）。</li>
      <li><strong>AI 对话模型</strong>：未装 OpenClaw 时这里会提示「请先安装 OpenClaw」；装好后即可选择模型。</li>
      <li>没装 OpenClaw 也能直投、精选、建卡出图；只有 AI 连抽 / 常规对话需要它。</li>
    </ul>`,
    view: "settings",
    mode: null,
    target: "#settings-anchor-core",
    placement: "left",
    prepare: async () => {
      await _tourScrollSettingsAnchor("settings-anchor-core");
    },
  },
  {
    id: "settings-server",
    title: "配置 · WebUI 服务参数",
    html: `<ul>
      <li>本 WebUI 的监听 IP / 端口（默认常见为 8318），以及相关本地运行开关。</li>
      <li>一般安装脚本已经写好；只有换端口、局域网访问或排查冲突时才需要改。</li>
      <li>改端口后要用新地址打开页面，并确认没有被防火墙拦住。</li>
    </ul>`,
    view: "settings",
    mode: null,
    target: "#settings-anchor-server",
    placement: "left",
    prepare: async () => {
      await _tourScrollSettingsAnchor("settings-anchor-server");
    },
  },
  {
    id: "settings-workflow",
    title: "配置 · 工作流管理",
    html: `<ul>
      <li>选择抽卡 / 常规渲染时默认使用的 ComfyUI 工作流。</li>
      <li>列表来自本机已同步的工作流文件；换模型或换配方时在这里切换默认项。</li>
      <li>若下拉为空，先检查工作流目录与 Comfy 侧是否已放入对应 JSON。</li>
    </ul>`,
    view: "settings",
    mode: null,
    target: "#settings-anchor-workflow",
    placement: "left",
    prepare: async () => {
      await _tourScrollSettingsAnchor("settings-anchor-workflow");
    },
  },
  {
    id: "settings-paths",
    title: "配置 · 物理路径",
    html: `<ul>
      <li>Comfy 本地输出、外置归档、临时目录、卡片目录等物理路径都在这里。</li>
      <li><strong>Obsidian 保管箱</strong>路径给「精选」用：填库根目录（其下应有「灵感库」文件夹）。</li>
      <li>请用本机可访问的绝对路径；外置盘不稳定时系统可能回落到本地输出。</li>
    </ul>`,
    view: "settings",
    mode: null,
    target: "#settings-anchor-paths",
    placement: "left",
    prepare: async () => {
      await _tourScrollSettingsAnchor("settings-anchor-paths");
    },
  },
  {
    id: "settings-delivery",
    title: "配置 · 分发通知",
    html: `<ul>
      <li>控制渲染成功后的图片投递到哪里：Telegram、WebUI 等渠道可分别开关。</li>
      <li>同区还有与通知机器人 / 目标相关的参数（若你启用了 TG 投递）。</li>
      <li>只想在网页里看图：保留 WebUI、关闭 Telegram 即可。</li>
    </ul>`,
    view: "settings",
    mode: null,
    target: "#settings-anchor-delivery",
    placement: "left",
    prepare: async () => {
      await _tourScrollSettingsAnchor("settings-anchor-delivery");
    },
  },
  {
    id: "settings-resolution",
    title: "配置 · 分辨率预设",
    html: `<ul>
      <li>竖版 / 横版 / 方图 / 宽屏等预设尺寸，以及是否锁定工作流内置尺寸。</li>
      <li>关闭「锁定工作流内置尺寸」后，完全采用下方自定义宽高。</li>
      <li>多人同框等逻辑可能再配合算法区的「自动横屏」一起生效。</li>
    </ul>`,
    view: "settings",
    mode: null,
    target: "#settings-anchor-resolution",
    placement: "left",
    prepare: async () => {
      await _tourScrollSettingsAnchor("settings-anchor-resolution");
    },
  },
  {
    id: "settings-algorithm",
    title: "配置 · 智能算法参数",
    html: `<ul>
      <li><strong>画面裸露范围</strong>：勾选允许抽中的级别（可多选，至少留一项）。</li>
      <li><strong>防重复冷却</strong>：最近出现过的场景会暂时少抽，减少连着撞车。</li>
      <li><strong>多人同框自动横屏</strong>：检测到多人描述时自动切横版构图。</li>
    </ul>`,
    view: "settings",
    mode: null,
    target: "#settings-anchor-algorithm",
    placement: "left",
    prepare: async () => {
      await _tourScrollSettingsAnchor("settings-anchor-algorithm");
    },
  },
  {
    id: "settings-scene",
    title: "配置 · 场景权重",
    html: `<ul>
      <li>控制随机抽卡时，各场景库的相对抽样比重。</li>
      <li>想多出某一类场景：调高对应权重；想少见则调低。</li>
      <li>这是兜底混合随机用的权重，指定场景 / 主题时仍以你的指令优先。</li>
    </ul>`,
    view: "settings",
    mode: null,
    target: "#settings-anchor-scene",
    placement: "left",
    prepare: async () => {
      await _tourScrollSettingsAnchor("settings-anchor-scene");
    },
  },
  {
    id: "docs",
    title: "文档页",
    html: `<ul>
      <li>这里是完整操作说明、依赖与安装相关文档的阅读区。</li>
      <li>遇到 OpenClaw、工作流、路径等问题可先查文档再改配置。</li>
      <li>以后想重看导览：点顶栏右侧<strong>?</strong> 图标即可。</li>
    </ul>`,
    view: "docs",
    mode: null,
    target: "#docs-reader-content-page",
    placement: "left",
  },
  {
    id: "done",
    title: "导览结束",
    html: `<ul>
      <li>你已经走完主界面、抽卡、参数队列、配置与文档的关键路径。</li>
      <li>重看入口：顶栏右侧这个<strong>?</strong>（鼠标悬停会显示「新手导览」）。</li>
      <li>点「完成」后，会恢复进入导览前的视图与聊天模式。</li>
    </ul>`,
    view: "chat",
    mode: "cards",
    target: ".chat-header-actions .btn-onboarding-launch",
    placement: "bottom",
  },
];

function maybeStartWebuiOnboarding() {
  try {
    if (localStorage.getItem(WEBUI_ONBOARDING_KEY)) return;
  } catch (_) {
    // localStorage 不可用时仍尝试强制首启导览
  }
  // 等首屏布局 / 视图恢复完成后再强制开导览，避免高亮错位
  setTimeout(() => {
    try {
      if (localStorage.getItem(WEBUI_ONBOARDING_KEY)) return;
    } catch (_) {}
    startWebuiOnboarding({ force: true, firstRun: true });
  }, 450);
}

function startWebuiOnboarding(opts = {}) {
  const force = !!(opts && opts.force);
  const firstRun = !!(opts && opts.firstRun);
  if (force && !firstRun) {
    // 手动重看：清标记并从头播放
    try {
      localStorage.removeItem(WEBUI_ONBOARDING_KEY);
    } catch (_) {}
  } else if (!force) {
    try {
      if (localStorage.getItem(WEBUI_ONBOARDING_KEY)) return;
    } catch (_) {}
  }

  // 强制重播：即使已打开也从第 0 步重启
  if (_tour.open) {
    _tourTeardownOverlayOnly();
  }

  _tour.open = true;
  _tour.stepIndex = 0;
  _tour.prevView = (typeof state !== "undefined" && state.activeView) || "chat";
  try {
    _tour.prevMode =
      typeof normalizeChatMode === "function"
        ? normalizeChatMode(state.settings && state.settings.chat_mode)
        : (state.settings && state.settings.chat_mode) || "cards";
  } catch (_) {
    _tour.prevMode = "cards";
  }
  _tour.modeTouched = false;

  _tourEnsureOverlay();
  _tourBindResize();
  showWebuiOnboardingStep(0);
}

function markWebuiOnboardingSeen() {
  try {
    localStorage.setItem(WEBUI_ONBOARDING_KEY, "1");
  } catch (_) {}
}

function _tourSetMode(mode) {
  if (!mode) return;
  if (typeof state === "undefined") return;
  if (!state.settings) state.settings = {};
  const next =
    typeof normalizeChatMode === "function" ? normalizeChatMode(mode) : mode === "draw" ? "draw" : "cards";
  const cur =
    typeof normalizeChatMode === "function"
      ? normalizeChatMode(state.settings.chat_mode)
      : state.settings.chat_mode || "cards";
  if (cur !== next) {
    _tour.modeTouched = true;
    state.settings.chat_mode = next;
    try {
      localStorage.setItem("chat_mode", next);
    } catch (_) {}
  }
  if (typeof renderChatModeButtons === "function") {
    renderChatModeButtons();
  } else if (typeof updateSidebarViewMode === "function") {
    updateSidebarViewMode();
  }
}

async function _tourRestoreContext() {
  const view = _tour.prevView || "chat";
  const mode = _tour.prevMode || "cards";
  try {
    if (typeof switchView === "function") {
      await switchView(view, true);
    }
  } catch (_) {}
  if (_tour.modeTouched || (state.settings && state.settings.chat_mode !== mode)) {
    if (!state.settings) state.settings = {};
    state.settings.chat_mode = mode;
    try {
      localStorage.setItem("chat_mode", mode);
    } catch (_) {}
    if (typeof renderChatModeButtons === "function") {
      renderChatModeButtons();
    }
  }
}

function _tourTeardownOverlayOnly() {
  const overlay = document.getElementById("webui-onboarding-overlay");
  if (overlay) overlay.remove();
  _tour.overlay = null;
  document.querySelectorAll(".onboarding-target-alive").forEach((el) => {
    el.classList.remove("onboarding-target-alive");
  });
}

function _tourUnbindResize() {
  if (!_tour.resizeBound) return;
  window.removeEventListener("resize", _tourOnResize);
  window.removeEventListener("scroll", _tourOnResize, true);
  _tour.resizeBound = false;
}

function _tourBindResize() {
  if (_tour.resizeBound) return;
  window.addEventListener("resize", _tourOnResize);
  window.addEventListener("scroll", _tourOnResize, true);
  _tour.resizeBound = true;
}

function _tourOnResize() {
  if (!_tour.open) return;
  _tourPositionUI(WEBUI_ONBOARDING_STEPS[_tour.stepIndex]);
}

async function closeWebuiOnboardingOverlay(markSeen) {
  if (!_tour.open && !document.getElementById("webui-onboarding-overlay")) {
    if (markSeen) markWebuiOnboardingSeen();
    return;
  }
  _tour.open = false;
  _tourUnbindResize();
  _tourTeardownOverlayOnly();
  if (markSeen) markWebuiOnboardingSeen();
  await _tourRestoreContext();
  _tour.prevView = null;
  _tour.prevMode = null;
  _tour.modeTouched = false;
  _tour.stepIndex = 0;
}

function _tourEnsureOverlay() {
  let overlay = document.getElementById("webui-onboarding-overlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "webui-onboarding-overlay";
    overlay.className = "onboarding-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.innerHTML = `
      <div class="onboarding-spotlight" id="onboarding-spotlight" aria-hidden="true"></div>
      <div class="onboarding-card" id="onboarding-card">
        <div class="onboarding-step-meta" id="onboarding-step-meta"></div>
        <h3 class="onboarding-title" id="onboarding-title" aria-live="polite"></h3>
        <div class="onboarding-body" id="onboarding-body"></div>
        <div class="onboarding-actions">
          <button type="button" class="guided-error-btn" data-onboarding-act="skip">跳过</button>
          <div class="onboarding-actions-right">
            <button type="button" class="guided-error-btn" data-onboarding-act="prev">上一步</button>
            <button type="button" class="guided-error-btn onboarding-primary" data-onboarding-act="next">下一步</button>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    overlay.addEventListener("click", (e) => {
      const actBtn = e.target.closest("[data-onboarding-act]");
      if (!actBtn) {
        // 点击遮罩不关闭，避免误触跳过
        e.preventDefault();
        return;
      }
      const act = actBtn.getAttribute("data-onboarding-act");
      if (act === "skip" || act === "done") {
        closeWebuiOnboardingOverlay(true);
        return;
      }
      if (act === "prev") showWebuiOnboardingStep(_tour.stepIndex - 1);
      if (act === "next") showWebuiOnboardingStep(_tour.stepIndex + 1);
    });
  }
  _tour.overlay = overlay;
  return overlay;
}

function _tourEscapeHtml(s) {
  return String(s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function _tourFindTarget(selector) {
  if (!selector) return null;
  try {
    return document.querySelector(selector);
  } catch (_) {
    return null;
  }
}

function _tourPositionUI(step) {
  const spotlight = document.getElementById("onboarding-spotlight");
  const card = document.getElementById("onboarding-card");
  if (!spotlight || !card) return;

  document.querySelectorAll(".onboarding-target-alive").forEach((el) => {
    el.classList.remove("onboarding-target-alive");
  });

  const target = step && step.target ? _tourFindTarget(step.target) : null;
  const pad = 8;
  const vw = window.innerWidth;
  const vh = window.innerHeight;

  if (target) {
    const r = target.getBoundingClientRect();
    const top = Math.max(8, r.top - pad);
    const left = Math.max(8, r.left - pad);
    const width = Math.min(vw - left - 8, r.width + pad * 2);
    const height = Math.min(vh - top - 8, r.height + pad * 2);
    spotlight.classList.add("is-visible");
    spotlight.style.top = `${top}px`;
    spotlight.style.left = `${left}px`;
    spotlight.style.width = `${Math.max(24, width)}px`;
    spotlight.style.height = `${Math.max(24, height)}px`;
    target.classList.add("onboarding-target-alive");

    const placement = (step && step.placement) || "auto";
    _tourPlaceCard(card, { top, left, width, height }, placement);
  } else {
    spotlight.classList.remove("is-visible");
    spotlight.style.width = "0px";
    spotlight.style.height = "0px";
    card.style.top = "50%";
    card.style.left = "50%";
    card.style.transform = "translate(-50%, -50%)";
    card.dataset.placement = "center";
  }
}

function _tourPlaceCard(card, hole, placement) {
  const gap = 14;
  const cw = card.offsetWidth || 420;
  const ch = card.offsetHeight || 240;
  const vw = window.innerWidth;
  const vh = window.innerHeight;

  const candidates = [];
  const push = (name, top, left) => candidates.push({ name, top, left });

  push("right", hole.top, hole.left + hole.width + gap);
  push("left", hole.top, hole.left - cw - gap);
  push("bottom", hole.top + hole.height + gap, hole.left);
  push("top", hole.top - ch - gap, hole.left);

  let order = ["right", "left", "bottom", "top"];
  if (placement && placement !== "auto") {
    order = [placement].concat(order.filter((x) => x !== placement));
  }

  let chosen = null;
  for (const name of order) {
    const c = candidates.find((x) => x.name === name);
    if (!c) continue;
    let top = c.top;
    let left = c.left;
    if (left < 12) left = 12;
    if (left + cw > vw - 12) left = Math.max(12, vw - cw - 12);
    if (top < 12) top = 12;
    if (top + ch > vh - 12) top = Math.max(12, vh - ch - 12);
    const fits =
      c.left >= 8 &&
      c.left + cw <= vw - 8 &&
      c.top >= 8 &&
      c.top + ch <= vh - 8;
    chosen = { name, top, left, fits };
    if (fits) break;
  }
  if (!chosen) {
    card.style.top = "50%";
    card.style.left = "50%";
    card.style.transform = "translate(-50%, -50%)";
    card.dataset.placement = "center";
    return;
  }
  card.style.transform = "none";
  card.style.top = `${chosen.top}px`;
  card.style.left = `${chosen.left}px`;
  card.dataset.placement = chosen.name;
}

async function showWebuiOnboardingStep(stepIndex) {
  const steps = WEBUI_ONBOARDING_STEPS;
  if (!_tour.open) return;
  const idx = Math.max(0, Math.min(stepIndex | 0, steps.length - 1));
  _tour.stepIndex = idx;
  const step = steps[idx];
  const overlay = _tourEnsureOverlay();

  // 强制导航到对应视图，避免停在配置/文档却讲聊天布局
  if (step.view && typeof switchView === "function") {
    try {
      await switchView(step.view, true);
    } catch (_) {}
  }
  if (step.view === "chat" && step.mode) {
    _tourSetMode(step.mode);
  }

  if (typeof step.prepare === "function") {
    try {
      await step.prepare(step);
    } catch (_) {}
  }

  // 再等一帧让视图 class / 侧栏切换完成
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));

  const isFirst = idx === 0;
  const isLast = idx === steps.length - 1;
  const meta = document.getElementById("onboarding-step-meta");
  const title = document.getElementById("onboarding-title");
  const body = document.getElementById("onboarding-body");
  const prevBtn = overlay.querySelector('[data-onboarding-act="prev"]');
  const nextBtn = overlay.querySelector('[data-onboarding-act="next"], [data-onboarding-act="done"]');

  if (meta) meta.textContent = `新手导览 · ${idx + 1}/${steps.length}`;
  if (title) title.textContent = step.title || "";
  if (body) body.innerHTML = step.html || (step.body ? `<p>${_tourEscapeHtml(step.body)}</p>` : "");
  if (prevBtn) prevBtn.disabled = isFirst;
  if (nextBtn) {
    nextBtn.setAttribute("data-onboarding-act", isLast ? "done" : "next");
    nextBtn.textContent = isLast ? "完成" : "下一步";
  }

  _tourPositionUI(step);
  // 部分目标（参数看板、设置滚动）稍后尺寸会变，再测一次
  setTimeout(() => {
    if (_tour.open && _tour.stepIndex === idx) _tourPositionUI(step);
  }, 120);
}

function bindWebuiOnboardingReplay() {
  if (document.documentElement.dataset.onboardingReplayDelegated === "1") return;
  document.documentElement.dataset.onboardingReplayDelegated = "1";
  document.addEventListener("click", (e) => {
    const t = e.target && e.target.closest && e.target.closest("[data-onboarding-replay]");
    if (!t) return;
    e.preventDefault();
    startWebuiOnboarding({ force: true });
  });
}

(function initWebuiOnboardingBindings() {
  const run = () => bindWebuiOnboardingReplay();
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", run);
  } else {
    run();
  }
})();
