/* shell.js — 主题、导航、视图切换、键盘与拖拽
   由 app.js 拆分而来；加载顺序见 index.html，core.js 必须最先。 */

function initTheme() {
  const toggleBtn = document.getElementById("theme-toggle");
  if (!toggleBtn) return;
  
  const savedTheme = localStorage.getItem("theme") || "dark";
  const updateBtnUI = (isLight) => {
    if (isLight) {
      document.documentElement.classList.add("light-mode");
    } else {
      document.documentElement.classList.remove("light-mode");
    }
  };
  
  updateBtnUI(savedTheme === "light");
  
  /**
   * 切换主题前后临时禁用全站过渡。
   * 各元素的 transition 时长不一（0.15s~0.3s），主题变量瞬间切换时它们会以不同速度渐变，
   * 分割线与相邻面板因此出现明显色差与闪烁。
   */
  const withoutTransitions = (mutate) => {
    const root = document.documentElement;
    root.classList.add("theme-switching");
    mutate();
    void root.offsetHeight; // 强制重排，让新配色在无过渡状态下一次性落定
    const restore = () => root.classList.remove("theme-switching");
    requestAnimationFrame(() => requestAnimationFrame(restore));
    // 兜底：标签页不在前台时 rAF 不会触发，缺了这行过渡会被永久禁用
    setTimeout(restore, 120);
  };

  toggleBtn.addEventListener("click", () => {
    const isLight = document.documentElement.classList.contains("light-mode");
    withoutTransitions(() => updateBtnUI(!isLight));
    if (isLight) {
      localStorage.setItem("theme", "dark");
      showToast("已切换至深色模式", "info");
    } else {
      localStorage.setItem("theme", "light");
      showToast("已切换至浅色模式", "info");
    }
  });
}

function getHelpText() {
  return `🎬 **Cards / Draw 控制台**

侧栏两态（内部键不变）：
*   **Cards · 卡片**：纯展示与管理；发送会交接进 Draw 并可选携带当前卡。
*   **Draw · 抽卡**：真 AI 对话（极简人设 + CLI help）；右侧快捷钮发「进入xxx模式」。

### 四模式入口
*   **常规**：快捷钮发送「进入常规模式」，再按 \`card_cli --help\` 走 create/fill/…
*   **连抽**：快捷钮发送「进入连抽模式」，由 AI 对话驱动批量出卡
*   **直投**：快捷钮发送「进入直投模式」；输入框旁闪电也可直投完整英文 prompt
*   **精选**：输入框旁骰子 → \`/api/featured\`

卡片页可先选卡再发消息交接；Draw 页直接聊即可。`;
}

function showWelcomeMessage() {
  const body = document.getElementById("chat-body");
  if (body) {
    body.innerHTML = "";
  }
}

// =====================================================================
// 🏢 Sidebar Card Status Filters Setup
// =====================================================================
function syncChatModeButtonUI() {
  const container = document.getElementById("chat-mode-selector");
  if (!container) return;
  if (state.settings) state.settings.chat_mode = normalizeChatMode(state.settings.chat_mode);
  const currentMode = (state.settings && state.settings.chat_mode) || "cards";
  const currentView = state.activeView || "chat";

  const indicator = document.getElementById("chat-mode-indicator");
  let activeBtn = null;

  container.querySelectorAll(".chat-mode-btn").forEach(btn => {
    const mode = btn.getAttribute("data-mode");
    const view = btn.getAttribute("data-view");
    let isActive = false;

    if (currentView === "settings" || currentView === "docs") {
      // 配置/文档：高亮对应 view 按钮，卡片/抽卡不再占指示条
      isActive = view === currentView;
    } else {
      // 聊天相关视图：高亮当前 chat_mode（cards/draw）
      isActive = !!mode && mode === currentMode;
    }

    btn.classList.toggle("active", isActive);
    btn.style.background = "transparent";
    btn.style.boxShadow = "none";
    if (isActive) {
      btn.style.color = "#ffffff";
      activeBtn = btn;
    } else {
      btn.style.color = "var(--text-muted)";
    }
  });

  if (indicator && activeBtn) {
    const updatePosition = () => {
      const top = activeBtn.offsetTop;
      const h = activeBtn.offsetHeight;
      if (h > 0) {
        indicator.style.opacity = "1";
        indicator.style.transform = `translateY(${top}px)`;
        indicator.style.height = `${h}px`;
        activeBtn.style.color = "#ffffff";
      } else {
        indicator.style.opacity = "0";
        activeBtn.style.color = "var(--color-primary)";
      }
    };
    updatePosition();
    if (activeBtn.offsetHeight === 0) {
      setTimeout(updatePosition, 50);
      setTimeout(updatePosition, 150);
    } else {
      requestAnimationFrame(updatePosition);
    }
  } else if (indicator) {
    indicator.style.opacity = "0";
  }
}

function renderChatModeButtons(opts = {}) {
  const skipSidebar = !!(opts && opts.skipSidebar);
  syncChatModeButtonUI();
  // boot 未完成或显式 skip 时不重载侧栏，避免竞态
  if (!skipSidebar && state.bootReady && typeof updateSidebarViewMode === "function") {
    updateSidebarViewMode();
  }
}

function initChatModeSelector() {
  const container = document.getElementById("chat-mode-selector");
  if (!container) return;

  // Recalculate on window resize to keep indicator aligned
  window.addEventListener("resize", renderChatModeButtons);

  container.querySelectorAll(".chat-mode-btn[data-mode]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const mode = btn.getAttribute("data-mode");
      // 右侧选择器现为全局常驻节点：若当前停留在配置/文档页，点击卡片/抽卡需先跳回对话视图
      const viewChat = document.getElementById("view-chat");
      if (viewChat && !viewChat.classList.contains("active")) {
        switchView("chat");
      }
      if (state.settings.chat_mode === mode) return;
      
      state.settings.chat_mode = mode;
      try { localStorage.setItem("chat_mode", mode); } catch (_) {}
      renderChatModeButtons();
      
      try {
        const res = await fetch("/api/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(state.settings)
        });
        const data = await res.json();
        state.settings = data.settings;
        if (state.settings) {
          state.settings.chat_mode = normalizeChatMode(state.settings.chat_mode);
          try { localStorage.setItem("chat_mode", state.settings.chat_mode); } catch (_) {}
        }
        // 模式已保存，无需额外弹窗提示
      } catch (err) {
        showToast("保存模式配置失败", "error");
      }
    });

    btn.addEventListener("mouseover", () => {
      const currentMode = state.settings.chat_mode || "cards";
      if (btn.getAttribute("data-mode") !== currentMode) {
        btn.style.background = "var(--bg-hover)";
        btn.style.color = "var(--text-bright)";
      }
    });
    btn.addEventListener("mouseout", () => {
      const currentMode = state.settings.chat_mode || "cards";
      if (btn.getAttribute("data-mode") !== currentMode) {
        btn.style.background = "transparent";
        btn.style.color = "var(--text-muted)";
      }
    });
  });
}

function showNavigationGuardModal(onSave, onDiscard, onCancel) {
  if (!document.getElementById("nav-guard-modal-style")) {
    const style = document.createElement("style");
    style.id = "nav-guard-modal-style";
    style.textContent = `
      @keyframes navGuardFadeIn {
        from { opacity: 0; }
        to { opacity: 1; }
      }
      @keyframes navGuardScaleIn {
        from { transform: scale(0.95); opacity: 0; }
        to { transform: scale(1); opacity: 1; }
      }
    `;
    document.head.appendChild(style);
  }

  const modalHtml = `
    <div id="nav-guard-modal" style="position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background: rgba(0,0,0,0.65); backdrop-filter: blur(4px); display: flex; align-items: center; justify-content: center; z-index: 9999; animation: navGuardFadeIn 0.2s ease;">
      <div style="background: var(--bg-panel); border: 1px solid var(--border-color); border-radius: 12px; padding: 24px; width: 420px; box-shadow: 0 12px 32px rgba(0,0,0,0.5); text-align: left; animation: navGuardScaleIn 0.2s ease;">
        <h3 style="margin-top: 0; margin-bottom: 12px; font-size: 1.05rem; color: var(--text-bright); display: flex; align-items: center; gap: 8px;">
          <i class="fa-solid fa-triangle-exclamation" style="color: var(--color-warning);"></i> 未保存的设置修改
        </h3>
        <p style="font-size: 0.8rem; color: var(--text-main); line-height: 1.6; margin-bottom: 24px;">
          您对系统环境配置进行了修改，但尚未保存。切换到其他页面可能会导致这些修改丢失。
        </p>
        <div style="display: flex; justify-content: flex-end; gap: 8px;">
          <button id="nav-guard-cancel" class="btn btn-secondary-minimal" style="padding: 6px 12px; font-size: 0.72rem; border-radius: 6px; box-shadow: none;">继续编辑</button>
          <button id="nav-guard-discard" class="btn" style="padding: 6px 12px; font-size: 0.72rem; border-radius: 6px; background: rgba(239, 68, 68, 0.15); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.3); box-shadow: none;">放弃修改</button>
          <button id="nav-guard-save" class="btn btn-primary-minimal" style="padding: 6px 16px; font-size: 0.72rem; border-radius: 6px; box-shadow: none;">保存并切换</button>
        </div>
      </div>
    </div>
  `;
  const tempDiv = document.createElement("div");
  tempDiv.innerHTML = modalHtml.trim();
  const modalElement = tempDiv.firstChild;
  document.body.appendChild(modalElement);
  
  modalElement.querySelector("#nav-guard-cancel").onclick = () => {
    modalElement.remove();
    onCancel();
  };
  modalElement.querySelector("#nav-guard-discard").onclick = () => {
    modalElement.remove();
    onDiscard();
  };
  modalElement.querySelector("#nav-guard-save").onclick = () => {
    modalElement.remove();
    onSave();
  };
}


const WORKSPACE_VIEWS = ["chat", "settings", "docs"];
const VIEW_STORAGE_KEY = "active_view";

function viewFromHash() {
  const raw = String(location.hash || "").replace(/^#\/?/, "").split(/[/?#]/)[0].trim();
  return WORKSPACE_VIEWS.includes(raw) ? raw : "";
}

function persistActiveView(view) {
  const v = WORKSPACE_VIEWS.includes(view) ? view : "chat";
  try { localStorage.setItem(VIEW_STORAGE_KEY, v); } catch (_) {}
  const want = "#" + v;
  if (location.hash !== want) {
    history.replaceState(null, "", want);
  }
}

function restoreActiveView() {
  const fromHash = viewFromHash();
  if (fromHash) return fromHash;
  try {
    const stored = localStorage.getItem(VIEW_STORAGE_KEY);
    if (WORKSPACE_VIEWS.includes(stored)) return stored;
  } catch (_) {}
  return "chat";
}

async function switchView(targetView, force = false) {
  if (!force && state.activeView === "settings" && targetView !== "settings" && state.settingsDirty) {
    showNavigationGuardModal(
      async () => {
        await autoSaveSettings();
        switchView(targetView, true);
      },
      () => {
        state.settingsDirty = false;
        loadSettings();
        switchView(targetView, true);
      },
      () => {
        // Do nothing
      }
    );
    return;
  }

  const navBtns = document.querySelectorAll(".sidebar-nav .nav-btn, .nav-view-trigger");
  const views = document.querySelectorAll(".workspace-view");
  const chatSubPanel = document.getElementById("sidebar-chat-sub");
  // 记录当前视图，供右侧指示条跟随（settings/docs 时停在对应入口上）
  state.activeView = targetView || "chat";

  // Toggle Nav active class
  navBtns.forEach(b => {
    if (b.getAttribute("data-view") === targetView) {
      b.classList.add("active");
    } else {
      b.classList.remove("active");
    }
  });

  // Toggle Views active class
  views.forEach(view => {
    if (view.id === `view-${targetView}`) {
      view.classList.add("active");
    } else {
      view.classList.remove("active");
    }
  });

  // Show/Hide sidebar helpers (cards & queue) & Slots Board
  const settingsSubPanel = document.getElementById("sidebar-settings-sub");
  const docsSubPanel = document.getElementById("sidebar-docs-sub");

  if (chatSubPanel) chatSubPanel.classList.add("hidden");
  if (settingsSubPanel) settingsSubPanel.classList.add("hidden");
  if (docsSubPanel) docsSubPanel.classList.add("hidden");

  if (targetView === "chat") {
    if (chatSubPanel) chatSubPanel.classList.remove("hidden");
    setParamPanelCollapsed(false);
  } else if (targetView === "settings") {
    if (settingsSubPanel) settingsSubPanel.classList.remove("hidden");
    setParamPanelCollapsed(true);
  } else if (targetView === "docs") {
    if (docsSubPanel) docsSubPanel.classList.remove("hidden");
    setParamPanelCollapsed(true);
  } else {
    setParamPanelCollapsed(true);
  }

  // 右侧指示条始终跟随当前入口（chat/settings/docs 都要刷新）
  setTimeout(syncChatModeButtonUI, 0);

  // Trigger view-specific loaders
  if (targetView === "settings") {
    loadSettings();
  } else if (targetView === "docs") {
    const allowedDocs = new Set(
      Array.from(document.querySelectorAll(".doc-sidebar-tab-btn")).map(b => b.getAttribute("data-doc"))
    );
    const storedDoc = (() => { try { return localStorage.getItem("active_doc"); } catch (_) { return ""; } })();
    const activeDocTab = document.querySelector(".doc-sidebar-tab-btn.active");
    const docName = (allowedDocs.has(storedDoc) && storedDoc)
      || (activeDocTab ? activeDocTab.getAttribute("data-doc") : "user_guide");
    document.querySelectorAll(".doc-sidebar-tab-btn").forEach(b => {
      b.classList.toggle("active", b.getAttribute("data-doc") === docName);
    });
    loadDocContent(docName);
  }

  persistActiveView(state.activeView);
}

function initNavigation() {
  const navBtns = document.querySelectorAll(".sidebar-nav .nav-btn, .nav-view-trigger");
  navBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      switchView(btn.getAttribute("data-view"));
    });
  });

  // 左上角 logo-title 点击返回主页效果
  document.getElementById("logo-title")?.addEventListener("click", () => {
    switchView("chat");
  });

  // ── 初始化折叠菜单 (默认折叠，支持 localStorage 记忆) ──
  const setupAccordion = (headerId, contentId, storageKey) => {
    const header = document.getElementById(headerId);
    const content = document.getElementById(contentId);
    if (!header || !content) return;

    // 默认折叠 (如果 localStorage 没有设定过，则默认为 'true' 折叠)
    const stored = localStorage.getItem(storageKey);
    const isCollapsed = stored === null ? true : (stored === 'true');

    if (isCollapsed) {
      header.classList.add("collapsed");
      content.classList.add("collapsed");
    } else {
      header.classList.remove("collapsed");
      content.classList.remove("collapsed");
    }

    header.addEventListener("click", () => {
      const willCollapse = !content.classList.contains("collapsed");
      if (willCollapse) {
        header.classList.add("collapsed");
        content.classList.add("collapsed");
      } else {
        header.classList.remove("collapsed");
        content.classList.remove("collapsed");
      }
      localStorage.setItem(storageKey, willCollapse ? 'true' : 'false');
    });
  };

  setupAccordion("header-system-tools", "content-system-tools", "nav_system_tools_collapsed");

  // Settings Save Form Page level
  const formSettingsPage = document.getElementById("form-settings-page");
  if (formSettingsPage) {
    // Bind click event to the top header save button
    const btnSaveSettings = document.getElementById("btn-save-settings");
    if (btnSaveSettings) {
      btnSaveSettings.addEventListener("click", () => {
        autoSaveSettings();
      });
    }

    // Bind modification listeners to set dirty flag
    formSettingsPage.addEventListener("input", () => {
      state.settingsDirty = true;
    });
    formSettingsPage.addEventListener("change", () => {
      state.settingsDirty = true;
    });

    // Setup preset dropdown to inputs linkage
    const setupResPresetLinkage = (presetId, wName, hName) => {
      const presetSelect = document.getElementById(presetId);
      const wInput = formSettingsPage.elements[wName];
      const hInput = formSettingsPage.elements[hName];
      
      if (presetSelect && wInput) {
        presetSelect.addEventListener("change", () => {
          const val = presetSelect.value;
          if (val && val !== "custom") {
            const [w, h] = val.split("x");
            wInput.value = w;
            if (hInput) {
              hInput.value = h;
            } else if (wName === "res_square_w") {
              const sqHInput = formSettingsPage.elements["res_square_h"];
              if (sqHInput) sqHInput.value = w;
            }
          }
        });
        
        const handleInputChange = () => {
          const wVal = wInput.value;
          const hVal = hInput ? hInput.value : wVal;
          const val = `${wVal}x${hVal}`;
          const hasOption = Array.from(presetSelect.options).some(opt => opt.value === val);
          presetSelect.value = hasOption ? val : "custom";
        };
        
        wInput.addEventListener("input", () => {
          if (wName === "res_square_w" && formSettingsPage.elements["res_square_h"]) {
            formSettingsPage.elements["res_square_h"].value = wInput.value;
          }
          handleInputChange();
        });
        if (hInput) {
          hInput.addEventListener("input", () => {
            if (wName === "res_square_w") {
              wInput.value = hInput.value;
            }
            handleInputChange();
          });
        }
      }
    };
    
    setupResPresetLinkage("settings-res-vertical-preset", "res_vertical_w", "res_vertical_h");
    setupResPresetLinkage("settings-res-horizontal-preset", "res_horizontal_w", "res_horizontal_h");
    setupResPresetLinkage("settings-res-square-preset", "res_square_w", "res_square_h");
    setupResPresetLinkage("settings-res-widescreen-preset", "res_widescreen_w", "res_widescreen_h");

    // Prevent default form submission and trigger auto-save instead
    formSettingsPage.addEventListener("submit", (e) => {
      e.preventDefault();
      autoSaveSettings();
    });


  }





  // Docs tabs navigation (sidebar vertical menu)
  const docTabs = document.querySelectorAll(".doc-sidebar-tab-btn");
  docTabs.forEach(btn => {
    btn.addEventListener("click", () => {
      docTabs.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const docName = btn.getAttribute("data-doc");
      try { localStorage.setItem("active_doc", docName); } catch (_) {}
      loadDocContent(docName);
    });
  });

  // 配置页左侧栏分区锚点导航：点击滚动到对应 settings-card-section 并高亮
  const settingsAnchorBtns = document.querySelectorAll(".sidebar-anchor-btn");
  settingsAnchorBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      const targetId = btn.getAttribute("data-anchor");
      const targetEl = document.getElementById(targetId);
      settingsAnchorBtns.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      if (targetEl) {
        targetEl.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  });

  window.addEventListener("hashchange", () => {
    const v = viewFromHash() || "chat";
    if (v !== state.activeView) switchView(v);
  });
  switchView(restoreActiveView());
}

function initKeyboardNavigation() {
  window.addEventListener("keydown", (e) => {
    // Ignore keypresses when user is editing/typing
    if (document.activeElement && (
      document.activeElement.tagName === "INPUT" ||
      document.activeElement.tagName === "TEXTAREA" ||
      document.activeElement.isContentEditable
    )) {
      return;
    }

    // Ignore if create modal or lightbox modal is open
    const createModal = document.getElementById("create-modal");
    const lightboxModal = document.getElementById("lightbox-modal");
    if (createModal && createModal.classList.contains("open")) return;
    if (lightboxModal && lightboxModal.classList.contains("open")) return;

    // Handle ArrowLeft and ArrowRight to switch card status filter tabs
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      const filterPills = Array.from(document.querySelectorAll("#card-status-filters .filter-pill"));
      if (filterPills.length > 0 && state.settings.chat_mode !== "draw") {
        e.preventDefault();
        const activeFilterIndex = filterPills.findIndex(pill => pill.classList.contains("active"));
        if (activeFilterIndex !== -1) {
          let nextFilterIndex;
          if (e.key === "ArrowLeft") {
            nextFilterIndex = activeFilterIndex - 1;
            if (nextFilterIndex < 0) {
              nextFilterIndex = filterPills.length - 1;
            }
          } else {
            nextFilterIndex = activeFilterIndex + 1;
            if (nextFilterIndex >= filterPills.length) {
              nextFilterIndex = 0;
            }
          }
          filterPills[nextFilterIndex].click();
        }
      }
      return;
    }

    const visibleCardElems = Array.from(document.querySelectorAll(".sidebar-card-item"));
    if (visibleCardElems.length === 0) return;

    // Find index of current active card in the visible DOM items
    const currentIndex = visibleCardElems.findIndex(item => item.getAttribute("data-card-id") === state.activeCardId);
    if (currentIndex === -1) return;

    const activeCardElem = visibleCardElems[currentIndex];
    const overlay = activeCardElem.querySelector(".card-delete-confirm-overlay");

    if (e.key === "ArrowUp") {
      e.preventDefault();
      if (currentIndex > 0) {
        const prevCardId = visibleCardElems[currentIndex - 1].getAttribute("data-card-id");
        selectCard(prevCardId);
      } else {
        const lastCardId = visibleCardElems[visibleCardElems.length - 1].getAttribute("data-card-id");
        selectCard(lastCardId);
      }
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      if (currentIndex < visibleCardElems.length - 1) {
        const nextCardId = visibleCardElems[currentIndex + 1].getAttribute("data-card-id");
        selectCard(nextCardId);
      } else {
        const firstCardId = visibleCardElems[0].getAttribute("data-card-id");
        selectCard(firstCardId);
      }
    } else if (e.key === "PageUp") {
      e.preventDefault();
      const firstCardId = visibleCardElems[0].getAttribute("data-card-id");
      selectCard(firstCardId);
    } else if (e.key === "PageDown") {
      e.preventDefault();
      const lastCardId = visibleCardElems[visibleCardElems.length - 1].getAttribute("data-card-id");
      selectCard(lastCardId);
    } else if (e.key === "Backspace" || e.key === "Delete") {
      if (overlay) {
        e.preventDefault();
        if (overlay.classList.contains("show")) {
          overlay.classList.remove("show");
          deleteCard(state.activeCardId);
        } else {
          overlay.classList.add("show");
        }
      }
    } else if (e.key === "Enter") {
      if (overlay && overlay.classList.contains("show")) {
        e.preventDefault();
        overlay.classList.remove("show");
        deleteCard(state.activeCardId);
      }
    } else if (e.key === "Escape") {
      if (overlay && overlay.classList.contains("show")) {
        e.preventDefault();
        overlay.classList.remove("show");
      }
    }
  });
}

// =====================================================================
// 🏢 Data Loading & API Fetching
// =====================================================================
function initResizers() {
  const leftSidebar = document.querySelector(".sidebar-left");
  const rightPanel = document.getElementById("param-panel");
  const leftHandle = document.getElementById("resize-handle-left");
  const rightHandle = document.getElementById("resize-handle-right");

  if (!leftSidebar || !leftHandle || !rightPanel || !rightHandle) return;

  // Restore saved widths
  const savedLeftWidth = localStorage.getItem("sidebar-left-width");
  if (savedLeftWidth) {
    leftSidebar.style.width = savedLeftWidth + "px";
  }
  const savedRightWidth = localStorage.getItem("sidebar-right-width");
  if (savedRightWidth) {
    rightPanel.style.width = savedRightWidth + "px";
  }

  // Left Sidebar Dragging
  leftHandle.addEventListener("mousedown", (e) => {
    e.preventDefault();
    document.body.classList.add("resizing");
    leftHandle.classList.add("active");

    const onMouseMove = (moveEvent) => {
      // 下限 240：低于此宽度卡片标题与状态徽标会被挤到换行，可读性崩坏
      let width = moveEvent.clientX;
      if (width < 240) width = 240;
      if (width > 500) width = 500;
      leftSidebar.style.width = width + "px";
    };

    const onMouseUp = () => {
      document.body.classList.remove("resizing");
      leftHandle.classList.remove("active");
      localStorage.setItem("sidebar-left-width", parseInt(leftSidebar.style.width));
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
    };

    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
  });

  // Right Panel Dragging
  rightHandle.addEventListener("mousedown", (e) => {
    e.preventDefault();
    document.body.classList.add("resizing");
    rightHandle.classList.add("active");

    const startWidth = rightPanel.getBoundingClientRect().width;
    const startX = e.clientX;

    const onMouseMove = (moveEvent) => {
      // 下限 340：低于此宽度 prompt 卡片头部（窗点+标题+字数徽标+复制钮）会折成两行
      let width = startWidth + (startX - moveEvent.clientX);
      if (width < 340) width = 340;
      if (width > 800) width = 800;
      rightPanel.style.width = width + "px";
    };

    const onMouseUp = () => {
      document.body.classList.remove("resizing");
      rightHandle.classList.remove("active");
      localStorage.setItem("sidebar-right-width", parseInt(rightPanel.style.width));
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
    };

    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
  });
}

// =====================================================================
// 🎬 Lightbox Overlay Zoom Control
// =====================================================================
function setParamPanelCollapsed(collapsed) {
  const panel = document.getElementById("param-panel");
  const expandBtn = document.getElementById("btn-expand-param-panel");
  const handle = document.getElementById("resize-handle-right");
  if (panel) panel.classList.toggle("collapsed", collapsed);
  // 分割线现由手柄绘制，收起看板时必须一并隐藏，否则窗口右缘会留一条孤线
  if (handle) handle.classList.toggle("is-hidden", collapsed);
  // 配置/文档视图本身就没有看板，此时不该冒出展开钮
  const showExpand = collapsed && state.activeView === "chat";
  if (expandBtn) expandBtn.classList.toggle("visible", showExpand);
}

// 兜底值与后端 DEFAULT_CONFIG.resolution_presets 保持一致，避免前后端各写一套数
function updateSidebarViewMode() {
  const isDraw = normalizeChatMode(state.settings && state.settings.chat_mode) === "draw";
  const filters = document.getElementById("card-status-filters");
  try {
    localStorage.setItem("chat_mode", isDraw ? "draw" : "cards");
  } catch (_) {}

  if (typeof _timeFilterMonths !== "undefined") {
    _timeFilterMonths = "";
  }

  if (isDraw) {
    document.documentElement.classList.remove("cards-mode-active");
    document.documentElement.classList.add("draw-mode-active");
    if (filters) filters.style.display = "none";
    // 抽卡模式右栏固定 guide，防止残留卡片参数板
    renderDrawGuidePanel(state.activeSessionId || state.pendingSessionId || null);
    // 仅交接锁期间跳过历史/自动选旧会话；正常刷新必须拉历史，否则标题有内容空
    const handoffLock = !!state.sessionUiLock;
    const preferId = state.pendingSessionId
      || state.activeSessionId
      || localStorage.getItem("active_session_id")
      || undefined;
    loadSessions({
      preferSessionId: preferId,
      skipHistory: handoffLock,
      skipAutoSelect: handoffLock && !state.pendingSessionId && !state.activeSessionId,
    });
  } else {
    document.documentElement.classList.remove("draw-mode-active");
    document.documentElement.classList.add("cards-mode-active");
    if (filters) filters.style.display = "flex";
    loadCards({ forceRender: true });
  }
}

// =====================================================================
// 💬 Chat History Actions: Delete Confirmations
// =====================================================================

