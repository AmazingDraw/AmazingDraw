/* onboarding.js — 新手导览 spotlight tour
   依赖 shell.js 的 switchView / renderChatModeButtons / updateSidebarViewMode；
   由 index.html 在 shell 之后加载。 */

const WEBUI_ONBOARDING_KEY = "amazingdraw_webui_onboarding_v6";

const _tour = {
  open: false,
  stepIndex: 0,
  prevView: null,
  prevMode: null,
  modeTouched: false,
  resizeBound: false,
  overlay: null,
};

function _tourFrames(n) {
  const count = Math.max(1, n | 0);
  return new Promise((resolve) => {
    const tick = (left) => {
      if (left <= 0) return resolve();
      requestAnimationFrame(() => tick(left - 1));
    };
    tick(count);
  });
}

function _tourIsUsable(el) {
  if (!el || typeof el.getBoundingClientRect !== "function") return false;
  const r = el.getBoundingClientRect();
  if (r.width < 2 || r.height < 2) return false;
  const st = window.getComputedStyle(el);
  if (st.display === "none" || st.visibility === "hidden" || Number(st.opacity) === 0) return false;
  return true;
}

function _tourCollectTargets(selector) {
  if (!selector) return [];
  try {
    return Array.from(document.querySelectorAll(selector)).filter(_tourIsUsable);
  } catch (_) {
    return [];
  }
}

async function _tourWaitTargets(selector, timeoutMs) {
  const deadline = Date.now() + (timeoutMs || 900);
  let found = _tourCollectTargets(selector);
  while (!found.length && Date.now() < deadline) {
    await _tourFrames(1);
    found = _tourCollectTargets(selector);
  }
  return found;
}

function _tourScrollEl(el, block) {
  if (!el) return;
  try {
    el.scrollIntoView({ behavior: "auto", block: block || "nearest", inline: "nearest" });
  } catch (_) {
    el.scrollIntoView(true);
  }
}

async function _tourScrollSettingsAnchor(anchorId) {
  const el = document.getElementById(anchorId);
  if (!el) return;
  document.querySelectorAll(".sidebar-anchor-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.getAttribute("data-anchor") === anchorId);
  });
  _tourScrollEl(el, "start");
  await _tourFrames(2);
}

const WEBUI_ONBOARDING_STEPS = [
  {
    id: "welcome",
    title: "欢迎使用 Amazing Draw",
    html: `<ul>
      <li>主界面分为三块：<strong>左侧</strong>卡片列表与快捷说明、<strong>中间</strong>预览与出卡区、<strong>右侧</strong>模式栏 + 参数看板。</li>
      <li>左上角品牌区的<strong>魔法棒图标</strong>可切换<strong>深色 / 浅色</strong>主题。</li>
      <li>首次打开会自动走完本导览；之后顶栏右侧有一个<strong>?</strong> 图标，可随时重看。</li>
      <li>可点「跳过」提前结束；结束后会恢复进入前的视图与模式。</li>
    </ul>`,
    view: "chat",
    mode: "cards",
    target: ".sidebar-brand",
    placement: "right",
    pad: 4,
    scroll: "nearest",
  },
  {
    id: "mode-rail",
    title: "右侧模式栏",
    html: `<ul>
      <li><strong>卡片</strong>：浏览、筛选、预览历史卡片与参数；出卡只用直投 / 精选。</li>
      <li><strong>相册</strong>：成品库，可建专辑、拖卡片归档。</li>
      <li><strong>配置</strong>与<strong>文档</strong>：环境设置与完整说明。导览会在后续步骤自动跳转，无需手动点。</li>
    </ul>`,
    view: "chat",
    mode: "cards",
    target: "#chat-mode-selector .chat-mode-btn",
    placement: "left",
    pad: 6,
    scroll: "nearest",
  },
  {
    id: "cards-sidebar",
    title: "卡片模式 · 左侧列表",
    html: `<ul>
      <li>出卡请用中间输入区的<strong>直投</strong>或<strong>精选</strong>。</li>
      <li>左侧是历史卡片列表：状态筛选（草稿 / 定稿 / 失败 / 完成）与月份过滤。</li>
      <li>选中卡片后，右侧参数看板会展示对应配置。</li>
    </ul>`,
    view: "chat",
    mode: "cards",
    target: "#sidebar-card-filters",
    placement: "right",
    pad: 6,
    scroll: "nearest",
  },
  {
    id: "chat-center",
    title: "中间 · 预览与出卡",
    html: `<ul>
      <li>选中卡片后的预览、出图结果都在中间主区展示。</li>
      <li>WebUI 出卡只用下方直投 / 精选；连抽与常规请用 CLI。</li>
      <li>导览高亮的是中间内容区。</li>
    </ul>`,
    view: "chat",
    mode: "cards",
    target: "#chat-body",
    placement: "left",
    pad: 6,
    scroll: "nearest",
  },
  {
    id: "input-tools",
    title: "输入区 · 直投与精选",
    html: `<ul>
      <li><strong>直投</strong>（闪电）：在输入框写入完整英文 prompt 再点闪电，建卡并提交渲染。</li>
      <li><strong>精选</strong>（骰子）：从 Obsidian 灵感库随机取笔记建卡并入队；需在配置里填好保管箱路径。精选不必在输入框打字。</li>
    </ul>`,
    view: "chat",
    mode: "cards",
    target: ".chat-input-row",
    placement: "top",
    pad: 6,
    scroll: "nearest",
  },
  {
    id: "album-view",
    title: "相册 · 成品库",
    html: `<ul>
      <li>右侧模式栏的「相册」进入成品库：默认只显示已出图完成卡。</li>
      <li>点「新建专辑」弹出命名；也可按角色浏览（少见角色收在「其他」）。删专辑不会删卡。</li>
      <li>鼠标悬停卡片会出现收藏与删除。收藏进「我的收藏」，不用确认；删除要二次确认。</li>
      <li>点「工作台打开」回到卡片页查看原卡。直投 / 精选仍在工作台。</li>
    </ul>`,
    view: "album",
    mode: null,
    target: "#album-sidebar-tools",
    placement: "right",
    pad: 10,
    scroll: "nearest",
  },
  {
    id: "param-queue",
    title: "参数看板与渲染队列",
    html: `<ul>
      <li>右侧参数看板：在卡片模式下选中一张卡，可查看 / 核对出图相关参数。</li>
      <li>下方是<strong>渲染队列</strong>：可查看排队与运行中任务。「终止任务」只停当前渲染并退出 ComfyUI，队列保留；「清空队列」才移除等待任务。</li>
      <li>进入配置 / 文档页时看板会自动收起；回到工作台会再展开。</li>
    </ul>`,
    view: "chat",
    mode: "cards",
    target: "#param-panel",
    placement: "left",
    pad: 4,
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
    pad: 6,
    scroll: "nearest",
  },
  {
    id: "settings-core",
    title: "配置 · 核心服务",
    html: `<ul>
      <li>出图依赖 <strong>ComfyUI</strong>：填写服务地址与本机安装根目录（本区分块靠下也有相关项）。</li>
      <li><strong>LLM Base URL / 模型</strong>：填 OpenAI 兼容 <code>/v1</code> 端点；模型列表从该地址的 <code>/v1/models</code> 拉取，拉不到会提示无法列出模型。</li>
      <li>直投、精选出图走 ComfyUI；填槽 / 判定走上面的 LLM 端点，共用同一个模型。</li>
    </ul>`,
    view: "settings",
    mode: null,
    target: "#settings-anchor-core",
    placement: "left",
    pad: 8,
    scroll: "start",
    maxHeight: 420,
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
    pad: 8,
    scroll: "start",
    maxHeight: 420,
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
    pad: 8,
    scroll: "start",
    maxHeight: 420,
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
    pad: 8,
    scroll: "start",
    maxHeight: 420,
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
    pad: 8,
    scroll: "start",
    maxHeight: 420,
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
    pad: 8,
    scroll: "start",
    maxHeight: 420,
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
    pad: 8,
    scroll: "start",
    maxHeight: 420,
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
    pad: 8,
    scroll: "start",
    maxHeight: 420,
    prepare: async () => {
      await _tourScrollSettingsAnchor("settings-anchor-scene");
    },
  },
  {
    id: "docs",
    title: "文档页",
    html: `<ul>
      <li>左侧目录切换说明文档；右侧是正文阅读区。</li>
      <li>遇到工作流、路径等问题可先查文档再改配置。</li>
      <li>以后想重看导览：点顶栏右侧<strong>?</strong> 图标即可。</li>
    </ul>`,
    view: "docs",
    mode: null,
    target: "#docs-sidebar-tabs",
    placement: "right",
    pad: 6,
    scroll: "nearest",
  },
  {
    id: "done",
    title: "导览结束",
    html: `<ul>
      <li>你已经走完主界面、出卡、参数队列、配置与文档的关键路径。</li>
      <li>重看入口：顶栏右侧这个<strong>?</strong>（鼠标悬停会显示「新手导览」）。</li>
      <li>点「完成」后，会恢复进入导览前的视图与模式。</li>
    </ul>`,
    view: "chat",
    mode: "cards",
    target: "#view-chat .chat-header-actions .btn-onboarding-launch",
    placement: "bottom",
    pad: 6,
    scroll: "nearest",
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

function _tourUnionVisibleRect(els, pad) {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  let left = Infinity;
  let top = Infinity;
  let right = -Infinity;
  let bottom = -Infinity;
  for (const el of els) {
    const r = el.getBoundingClientRect();
    const visL = Math.max(0, r.left);
    const visT = Math.max(0, r.top);
    const visR = Math.min(vw, r.right);
    const visB = Math.min(vh, r.bottom);
    if (visR - visL < 1 || visB - visT < 1) continue;
    left = Math.min(left, visL);
    top = Math.min(top, visT);
    right = Math.max(right, visR);
    bottom = Math.max(bottom, visB);
  }
  if (!isFinite(left)) return null;
  const margin = 6;
  const p = Number.isFinite(pad) ? pad : 6;
  left = Math.max(margin, left - p);
  top = Math.max(margin, top - p);
  right = Math.min(vw - margin, right + p);
  bottom = Math.min(vh - margin, bottom + p);
  return {
    top,
    left,
    width: Math.max(20, right - left),
    height: Math.max(20, bottom - top),
  };
}

function _tourPositionUI(step) {
  const spotlight = document.getElementById("onboarding-spotlight");
  const card = document.getElementById("onboarding-card");
  if (!spotlight || !card) return;

  document.querySelectorAll(".onboarding-target-alive").forEach((el) => {
    el.classList.remove("onboarding-target-alive");
  });

  const targets = step && step.target ? _tourCollectTargets(step.target) : [];
  const hole = targets.length ? _tourUnionVisibleRect(targets, step.pad) : null;
  if (hole && step.maxHeight && hole.height > step.maxHeight) {
    hole.height = step.maxHeight;
  }

  if (hole) {
    targets.forEach((el) => el.classList.add("onboarding-target-alive"));
    const radius = Math.max(8, Math.min(14, Math.round(Math.min(hole.width, hole.height) * 0.08)));
    spotlight.classList.add("is-visible");
    spotlight.style.top = `${Math.round(hole.top)}px`;
    spotlight.style.left = `${Math.round(hole.left)}px`;
    spotlight.style.width = `${Math.round(hole.width)}px`;
    spotlight.style.height = `${Math.round(hole.height)}px`;
    spotlight.style.borderRadius = `${radius}px`;
    _tourPlaceCard(card, hole, (step && step.placement) || "auto");
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
  const gap = 12;
  const cw = card.offsetWidth || 420;
  const ch = Math.min(card.offsetHeight || 240, Math.min(window.innerHeight * 0.7, 560));
  const vw = window.innerWidth;
  const vh = window.innerHeight;

  const clamp = (top, left) => ({
    top: Math.min(Math.max(12, top), Math.max(12, vh - ch - 12)),
    left: Math.min(Math.max(12, left), Math.max(12, vw - cw - 12)),
  });
  const overlapArea = (top, left) => {
    const x = Math.max(0, Math.min(left + cw, hole.left + hole.width) - Math.max(left, hole.left));
    const y = Math.max(0, Math.min(top + ch, hole.top + hole.height) - Math.max(top, hole.top));
    return x * y;
  };

  const raw = {
    right: { top: hole.top, left: hole.left + hole.width + gap },
    left: { top: hole.top, left: hole.left - cw - gap },
    bottom: { top: hole.top + hole.height + gap, left: hole.left },
    top: { top: hole.top - ch - gap, left: hole.left },
  };
  let order = ["right", "left", "bottom", "top"];
  if (placement && placement !== "auto") {
    order = [placement].concat(order.filter((x) => x !== placement));
  }

  let best = null;
  for (const name of order) {
    const c = clamp(raw[name].top, raw[name].left);
    const ov = overlapArea(c.top, c.left);
    const fits =
      raw[name].left >= 8 &&
      raw[name].left + cw <= vw - 8 &&
      raw[name].top >= 8 &&
      raw[name].top + ch <= vh - 8;
    const score = (fits ? 1e7 : 0) - ov;
    if (!best || score > best.score) best = { name, top: c.top, left: c.left, score };
    if (fits && ov === 0) break;
  }
  if (!best) {
    card.style.top = "50%";
    card.style.left = "50%";
    card.style.transform = "translate(-50%, -50%)";
    card.dataset.placement = "center";
    return;
  }
  card.style.transform = "none";
  card.style.top = `${Math.round(best.top)}px`;
  card.style.left = `${Math.round(best.left)}px`;
  card.dataset.placement = best.name;
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

  await _tourFrames(2);
  if (step.target) {
    const els = await _tourWaitTargets(step.target, 1000);
    if (els[0]) _tourScrollEl(els[0], step.scroll || "nearest");
    await _tourFrames(2);
  }

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

  const spotlight = document.getElementById("onboarding-spotlight");
  if (spotlight) spotlight.classList.add("is-jump");
  _tourPositionUI(step);
  await _tourFrames(1);
  _tourPositionUI(step);
  if (spotlight) spotlight.classList.remove("is-jump");
  setTimeout(() => {
    if (_tour.open && _tour.stepIndex === idx) _tourPositionUI(step);
  }, 80);
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
