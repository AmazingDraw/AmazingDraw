/* cards.js — 卡片列表、筛选、清理与参数看板
   由 app.js 拆分而来；加载顺序见 index.html，core.js 必须最先。 */

// 独立于列表 DOM：轮询重绘或切换卡片时，归档中的按钮状态不会丢失。
const archivingCardIds = new Set();
const statusUpdatingCardIds = new Set();
const renderSubmittingCardIds = new Set();
const EDITABLE_CARD_STATUSES = new Set([
  "draft", "filled", "failed", "validated", "rendered", "delivered", "success",
]);
const RENDERABLE_CARD_STATUSES = new Set([
  "validated", "rendered", "delivered", "success",
]);

function isCardRenderable(card) {
  return Boolean(
    card
    && !card.is_virtual
    && RENDERABLE_CARD_STATUSES.has(String(card.status || "")),
  );
}

function newRenderRequestId() {
  if (
    globalThis.crypto
    && typeof globalThis.crypto.randomUUID === "function"
  ) {
    return globalThis.crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function isCardStatusEditable(card) {
  return Boolean(
    card
    && !card.is_virtual
    && Number.isInteger(Number(card.version))
    && EDITABLE_CARD_STATUSES.has(String(card.status || "draft")),
  );
}

function closeCardStatusMenus() {
  document.querySelectorAll(".card-status-menu").forEach(menu => {
    menu.hidden = true;
  });
  document.querySelectorAll(".card-status-toggle").forEach(button => {
    button.setAttribute("aria-expanded", "false");
  });
  document.querySelectorAll(".sidebar-card-item.status-menu-open").forEach(item => {
    item.classList.remove("status-menu-open");
  });
}

function initCardStatusMenus() {
  document.addEventListener("click", event => {
    if (!event.target.closest(".card-status-control")) {
      closeCardStatusMenus();
    }
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape") {
      closeCardStatusMenus();
    }
  });
}

async function loadCards(opts = {}) {
  try {
    const res = await fetch("/api/cards");
    state.cards = await res.json();

    // 初始化或同步轮询缓存，防止重复比对
    window.lastCardIds = state.cards.map(c => c.card_id);
    window.lastCardStatuses = {};
    state.cards.forEach(c => {
      window.lastCardStatuses[c.card_id] = c.status;
    });

    // 抽卡模式只缓存数据，不渲染卡片侧栏/参数板（避免刷新后错成卡片页）
    const isDraw = normalizeChatMode(state.settings && state.settings.chat_mode) === "draw";
    if (isDraw && !opts.forceRender) {
      return;
    }

    renderCardsList(state.cards);

    // 渲染完卡片列表后，自动恢复上次激活的卡片
    const savedActiveId = localStorage.getItem("active_card_id");
    if (savedActiveId && state.cards.some(c => c.card_id === savedActiveId)) {
      selectCard(savedActiveId);
    } else if (state.cards.length > 0) {
      selectCard(state.cards[0].card_id);
    }
  } catch (err) {
    showToast("载入卡片列表失败", "error");
  }
}

// 开启卡片列表增量比对轮询，每 3 秒检测一次
function initIncrementalPolling() {
  window.lastCardIds = [];
  window.lastCardStatuses = {};
  
    setInterval(async () => {
    try {
      if (state.settings.chat_mode === "draw") {
        const res = await fetch("/api/chat/sessions");
        if (!res.ok) return;
        const data = await res.json();
        const sessions = data.sessions || [];
        
        const currentIds = sessions.map(s => s.session_id);
        const isChanged = !window.lastSessionIds || 
                          currentIds.length !== window.lastSessionIds.length ||
                          currentIds.some((id, idx) => id !== window.lastSessionIds[idx]) ||
                          sessions.some(s => s.updated_at !== window.lastSessionMtimes[s.session_id]);
                          
        if (isChanged) {
          window.lastSessionIds = currentIds;
          window.lastSessionMtimes = {};
          sessions.forEach(s => {
            window.lastSessionMtimes[s.session_id] = s.updated_at;
          });
          state.sessions = sessions;
          renderSessionsList(sessions);
        }
        return;
      }
      
      const res = await fetch("/api/cards");
      if (!res.ok) return;
      const cards = await res.json();
      
      // 比对卡片 ID 列表、顺序、以及卡片状态
      const currentIds = cards.map(c => c.card_id);
      const isChanged = !window.lastCardIds || 
                        currentIds.length !== window.lastCardIds.length ||
                        currentIds.some((id, idx) => id !== window.lastCardIds[idx]) ||
                        cards.some(c => c.status !== window.lastCardStatuses[c.card_id]);
      
      if (isChanged) {
        const oldFirstId = window.lastCardIds ? window.lastCardIds[0] : null;
        
        // 保存当前最新的 ID 和 状态 映射
        window.lastCardIds = currentIds;
        window.lastCardStatuses = {};
        cards.forEach(c => {
          window.lastCardStatuses[c.card_id] = c.status;
        });
        
        state.cards = cards;
        renderCardsList(cards);
        
        // 如果当前选中的卡片状态发生改变，自动更新卡片详细数据与展示页
        if (state.activeCardId) {
          const matchingCard = cards.find(c => c.card_id === state.activeCardId);
          if (matchingCard && state.activeCardData && matchingCard.status !== state.activeCardData.status) {
            await selectCard(state.activeCardId);
            if (matchingCard.status === "rendered") {
              showToast("🎨 图片生成成功！", "success");
            }
          }
        }
        
        // 如果新增了卡片（顶部卡片 ID 发生改变），且新卡创建成功
        if (currentIds.length > 0 && currentIds[0] !== oldFirstId) {
          // 如果当前未选中卡片，或者当前活跃卡片是引导页，自动聚焦并选中最新的卡片
          if (!state.activeCardId) {
            selectCard(currentIds[0]);
          }
        }
      }
    } catch (err) {
      // 容错，不弹 Toast 以免打扰用户
    }
  }, 3000);
}

// =====================================================================
// 🖌️ UI Rendering (Sidebar Card list)
// =====================================================================
function initCardStatusFilters() {
  const filterContainer = document.getElementById("card-status-filters");
  if (!filterContainer) return;
  initCardStatusMenus();
  
  filterContainer.querySelectorAll(".filter-pill").forEach(pill => {
    pill.addEventListener("click", () => {
      filterContainer.querySelectorAll(".filter-pill").forEach(p => p.classList.remove("active"));
      pill.classList.add("active");
      state.activeFilter = pill.getAttribute("data-status") || "all";
      state.cardsLimit = 100;
      renderCardsList(state.cards);
      
      // Auto-select the first card of the newly filtered list if available
      const filtered = filterCardsByTime(
        filterCardsByStatus(state.cards, state.activeFilter),
        state.timeFilter
      );
      if (filtered.length > 0) {
        selectCard(filtered[0].card_id);
      }
    });
  });
}

// =====================================================================
// 🏢 Navigation Tab Switching Router
// =====================================================================

/**
 * 把「有卡片的月份」补进时间筛选下拉。
 * renderCardsList 每 3 秒被轮询调用一次，所以仅在月份集合真的变化时才重建 option，
 * 否则会把主人正展开的下拉重置掉。
 */
let _timeFilterMonths = "";
function syncTimeFilterOptions(cards) {
  const sel = document.getElementById("card-time-filter");
  if (!sel) return;

  const counts = new Map();
  for (const c of cards) {
    if (!c.mtime) continue;
    const k = monthKeyOf(c.mtime);
    counts.set(k, (counts.get(k) || 0) + 1);
  }
  const months = [...counts.keys()].sort().reverse();
  const signature = months.map(m => `${m}:${counts.get(m)}`).join(",");
  if (signature === _timeFilterMonths) return;
  _timeFilterMonths = signature;

  // 「全部月份」是 index.html 里的静态节点，这里只重建月份部分。
  // 按年分组：月份逐年累积后（几年即数十项）平铺会变成一长条，分组后每组最多 12 项。
  [...sel.querySelectorAll("optgroup")].forEach(n => n.remove());
  let currentYear = null;
  let group = null;
  for (const m of months) {
    const [year, mon] = m.split("-");
    if (year !== currentYear) {
      currentYear = year;
      group = document.createElement("optgroup");
      group.label = `${year} 年`;
      sel.appendChild(group);
    }
    const o = document.createElement("option");
    o.value = m;
    o.textContent = `${Number(mon)} 月 · ${counts.get(m)} 张`;
    group.appendChild(o);
  }
  // 选中的月份可能因卡片被删而消失，退回全部时间
  if (state.timeFilter !== "all" && !sel.querySelector(`option[value="${state.timeFilter}"]`)) {
    state.timeFilter = "all";
  }
  sel.value = state.timeFilter;
}

function initTimeFilter() {
  const sel = document.getElementById("card-time-filter");
  if (!sel) return;
  sel.addEventListener("change", () => {
    state.timeFilter = sel.value || "all";
    state.cardsLimit = 100;
    renderCardsList(state.cards);
    const first = filterCardsByTime(
      filterCardsByStatus(state.cards, state.activeFilter),
      state.timeFilter
    )[0];
    if (first) selectCard(first.card_id);
  });
}

function renderCardsList(cardsList) {
  const container = document.getElementById("sidebar-cards-list");
  if (!container) return;
  
  container.innerHTML = "";
  
  // Sort from newest to oldest by mtime
  cardsList.sort((a, b) => {
    const timeA = a.mtime || 0;
    const timeB = b.mtime || 0;
    return timeB - timeA;
  });

  // 状态与时间两层筛选叠加
  syncTimeFilterOptions(cardsList);
  const filtered = filterCardsByTime(
    filterCardsByStatus(cardsList, state.activeFilter),
    state.timeFilter
  );

  // 更新列表顶部状态汇总
  const infoContainer = document.getElementById("sidebar-list-info");
  if (infoContainer) {
    const typeName = (CARD_FILTERS[state.activeFilter] || {}).label || "全部";
    infoContainer.innerHTML = `
      <div class="list-summary">
        <div>
          <span class="summary-label">${typeName}列表</span>
          <span class="summary-count">共 ${filtered.length} 张</span>
        </div>
        ${state.activeFilter === "rendered" ? `
          <button id="btn-cleanup-missing" class="btn-cleanup-missing" title="一键清理本地图片已被手动删除的已完成卡片">
            <i class="fa-solid fa-broom"></i> 一键清理
          </button>
        ` : ""}
        ${state.activeFilter === "draft" ? `
          <button id="btn-cleanup-drafts" class="btn-cleanup-missing" title="一键清理所有草稿卡片">
            <i class="fa-solid fa-broom"></i> 一键清理
          </button>
        ` : ""}
        ${state.activeFilter === "pending" ? `
          <button id="btn-cleanup-queued" class="btn-cleanup-missing" title="一键清理所有定稿卡片">
            <i class="fa-solid fa-broom"></i> 一键清理
          </button>
        ` : ""}
        ${state.activeFilter === "failed" ? `
          <button id="btn-cleanup-failed" class="btn-cleanup-missing" title="一键清理所有失败卡片">
            <i class="fa-solid fa-broom"></i> 一键清理
          </button>
        ` : ""}
      </div>
    `;

    // 绑定一键清理事件（同一分类只会渲染出其中一个按钮）
    const cleanupHandlers = {
      "btn-cleanup-missing": openCleanupConfirmModal,
      "btn-cleanup-drafts": openCleanupDraftsConfirmModal,
      "btn-cleanup-queued": openCleanupQueuedConfirmModal,
      "btn-cleanup-failed": openCleanupFailedConfirmModal,
    };
    Object.entries(cleanupHandlers).forEach(([id, open]) => {
      const btn = document.getElementById(id);
      if (!btn) return;
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        open();
      });
    });
  }

  const totalCount = filtered.length;
  if (totalCount === 0) {
    container.innerHTML = `<p class="placeholder-text">当前分类下暂无卡片</p>`;
    return;
  }
  
  const itemsToRender = filtered.slice(0, state.cardsLimit || 100);
  
  itemsToRender.forEach((card, index) => {
    const div = document.createElement("div");
    const isActive = card.card_id === state.activeCardId;
    const canRender = isCardRenderable(card);
    const canArchive = ["rendered", "delivered", "success"].includes(card.status);
    const isSubmitted = ["submitted", "queued", "rendering"].includes(card.status);
    const isArchiving = archivingCardIds.has(card.card_id);
    const canEditStatus = isCardStatusEditable(card);
    const isStatusUpdating = statusUpdatingCardIds.has(card.card_id);
    const isDraftStatus = ["draft", "filled"].includes(card.status);
    const isValidatedStatus = card.status === "validated";
    const isRenderedStatus = ["rendered", "delivered", "success"].includes(card.status);
    div.className = `sidebar-card-item ${isActive ? 'active' : ''} ${isArchiving ? 'archiving' : ''}`;
    div.setAttribute("data-card-id", card.card_id);
    div.addEventListener("click", () => selectCard(card.card_id));
    
    // Calculate stable index based on active filtered category list (sorted newest to oldest)
    const filteredIdx = filtered.findIndex(c => c.card_id === card.card_id);
    const displayNum = filteredIdx !== -1 ? (filtered.length - filteredIdx) : (index + 1);

    div.innerHTML = `
      <div class="card-person"><span class="card-num">#${displayNum}</span>${escapeHtml(card.person || "随机人物")}</div>
      <div class="card-scene"><i class="fa-solid fa-location-dot"></i> ${escapeHtml(card.scene || "随机场景")}</div>
      
      <div class="card-item-footer">
        <span class="card-status-control">
          ${canEditStatus ? `
            <button type="button"
                    class="card-status-badge card-status-toggle ${escapeHtml(card.status || "draft")} ${isStatusUpdating ? "is-updating" : ""}"
                    aria-haspopup="menu"
                    aria-expanded="false"
                    aria-busy="${isStatusUpdating ? "true" : "false"}"
                    title="修改卡片状态"
                    ${isStatusUpdating ? "disabled" : ""}>
              ${isStatusUpdating ? '<span class="status-mini-spinner" aria-hidden="true"></span>' : escapeHtml(card.status || "unknown")}
              ${isStatusUpdating ? "" : '<span class="card-status-chevron" aria-hidden="true">▾</span>'}
            </button>
            <div class="card-status-menu" role="menu" hidden>
              <button type="button" role="menuitem" data-target-status="draft" ${isDraftStatus ? "disabled" : ""}>
                <span>草稿</span><small>DRAFT</small>
              </button>
              <button type="button" role="menuitem" data-target-status="validated" ${isValidatedStatus ? "disabled" : ""}>
                <span>定稿</span><small>VALIDATED</small>
              </button>
              <button type="button" role="menuitem" data-target-status="rendered" ${isRenderedStatus ? "disabled" : ""}>
                <span>完成</span><small>RENDERED</small>
              </button>
            </div>
          ` : `
            <span class="card-status-badge ${escapeHtml(card.status || "draft")}" title="该状态由引擎管理">
              ${escapeHtml(card.status || "unknown")}
            </span>
          `}
        </span>
      </div>

      <div class="card-time">${formatCardTime(card.mtime)}</div>

      <div class="card-action-buttons">
        ${isSubmitted ? `
          <button class="card-action-btn btn-rerender" title="加入队列"><svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg></button>
        ` : ''}
        ${canRender ? `
          <button class="card-action-btn btn-rerender" title="渲染" aria-label="渲染"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"></path><path d="M21 3v5h-5"></path></svg></button>
        ` : ''}
        ${canArchive ? `
          <button class="card-action-btn btn-archive ${isArchiving ? 'is-archiving' : ''}" title="${isArchiving ? '正在保存到 Obsidian' : '保存到 Obsidian'}" aria-label="${isArchiving ? '正在归档' : '保存到 Obsidian'}" aria-busy="${isArchiving ? 'true' : 'false'}" ${isArchiving ? 'disabled' : ''}>${isArchiving ? '<span class="archive-spinner" aria-hidden="true"></span>' : '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="21 8 21 21 3 21 3 8"></polyline><rect x="1" y="3" width="22" height="5"></rect><line x1="10" y1="12" x2="14" y2="12"></line></svg>'}</button>
        ` : ''}
        <button class="card-action-btn btn-delete" title="删除卡片"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg></button>
      </div>

      <div class="card-delete-confirm-overlay">
        <span>确认删除该卡？</span>
        <button class="confirm-yes">确定</button>
        <button class="confirm-no">取消</button>
      </div>
    `;
    
    const deleteBtn = div.querySelector(".btn-delete");
    const rerenderBtn = div.querySelector(".btn-rerender");
    const archiveBtn = div.querySelector(".btn-archive");
    const statusToggle = div.querySelector(".card-status-toggle");
    const statusMenu = div.querySelector(".card-status-menu");
    
    const overlay = div.querySelector(".card-delete-confirm-overlay");
    const confirmYes = div.querySelector(".confirm-yes");
    const confirmNo = div.querySelector(".confirm-no");
    
    if (deleteBtn && overlay) {
      deleteBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (overlay.classList.contains("show")) {
          overlay.classList.remove("show");
          deleteCard(card.card_id);
        } else {
          overlay.classList.add("show");
        }
      });
    }
    
    if (rerenderBtn) {
      rerenderBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        submitRenderCard(card.card_id);
      });
    }
    
    if (archiveBtn) {
      archiveBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        archiveCardToObsidian(card.card_id);
      });
    }

    if (statusToggle && statusMenu) {
      statusToggle.addEventListener("click", event => {
        event.preventDefault();
        event.stopPropagation();
        const willOpen = statusMenu.hidden;
        closeCardStatusMenus();
        statusMenu.hidden = !willOpen;
        statusToggle.setAttribute("aria-expanded", willOpen ? "true" : "false");
        div.classList.toggle("status-menu-open", willOpen);
      });
      statusMenu.querySelectorAll("[data-target-status]").forEach(option => {
        option.addEventListener("click", event => {
          event.preventDefault();
          event.stopPropagation();
          if (option.disabled) return;
          updateCardStatus(card.card_id, option.getAttribute("data-target-status"));
        });
      });
    }
    
    if (confirmYes) {
      confirmYes.addEventListener("click", (e) => {
        e.stopPropagation();
        overlay.classList.remove("show");
        deleteCard(card.card_id);
      });
    }
    
    if (confirmNo) {
      confirmNo.addEventListener("click", (e) => {
        e.stopPropagation();
        overlay.classList.remove("show");
      });
    }
    
    container.appendChild(div);
  });

  if (totalCount > (state.cardsLimit || 100)) {
    const loadMoreDiv = document.createElement("div");
    loadMoreDiv.className = "load-more-container";
    loadMoreDiv.innerHTML = `
      <button id="btn-load-more" class="btn btn-secondary-minimal btn-load-more">
        <i class="fa-solid fa-arrow-down-long"></i> 加载更多 (已显示 ${itemsToRender.length}/${totalCount})
      </button>
    `;
    container.appendChild(loadMoreDiv);
    
    const btnLoadMore = loadMoreDiv.querySelector("#btn-load-more");
    if (btnLoadMore) {
      btnLoadMore.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        state.cardsLimit = (state.cardsLimit || 100) + 100;
        renderCardsList(cardsList);
      });
    }
  }
}

async function updateCardStatus(cardId, targetStatus) {
  const card = (state.cards || []).find(item => item.card_id === cardId);
  if (!isCardStatusEditable(card) || statusUpdatingCardIds.has(cardId)) return;

  statusUpdatingCardIds.add(cardId);
  closeCardStatusMenus();
  renderCardsList(state.cards);
  try {
    const encodedCardId = encodeURIComponent(cardId);
    const res = await fetch(`/api/cards/${encodedCardId}/status`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        status: targetStatus,
        expected_version: Number(card.version),
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = typeof data.detail === "string"
        ? data.detail
        : (data.detail?.message || "修改卡片状态失败");
      throw new Error(detail);
    }

    card.status = data.status;
    card.version = data.version;
    if (state.activeCardData && state.activeCardData.card_id === cardId) {
      state.activeCardData.status = data.status;
      state.activeCardData.version = data.version;
    }
    if (window.lastCardStatuses) {
      window.lastCardStatuses[cardId] = data.status;
    }
    const statusMessages = {
      draft: "已改为草稿",
      validated: "已改为定稿",
      rendered: "已恢复为完成",
    };
    const message = statusMessages[data.status] || "卡片状态已更新";
    showToast(message, "success");
    announceCardStatus(message);
  } catch (err) {
    const message = err && err.message ? err.message : "修改卡片状态失败";
    showToast(message, "error");
    announceCardStatus(`修改状态失败：${message}`);
  } finally {
    statusUpdatingCardIds.delete(cardId);
    renderCardsList(state.cards);
  }
}

function announceCardStatus(message) {
  const region = document.getElementById("card-status-announcer");
  if (!region) return;
  region.textContent = "";
  window.requestAnimationFrame(() => {
    region.textContent = message;
  });
}

async function submitRenderCard(cardId) {
  if (renderSubmittingCardIds.has(cardId)) return;
  renderSubmittingCardIds.add(cardId);
  try {
    const card = state.cards.find(c => c.card_id === cardId);
    const isSubmitted = card && ["submitted", "queued", "rendering"].includes(card.status);
    const actionText = isSubmitted ? "加入队列" : "渲染";

    const res = await fetch(`/api/cards/${encodeURIComponent(cardId)}/submit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request_id: newRenderRequestId() })
    });
    if (res.ok) {
      const toastMsg = isSubmitted ? "🚀 任务已成功加入队列！" : `🚀 ${actionText}任务已提交队列！`;
      showToast(toastMsg, "success");
      loadQueueStatus();
    } else {
      const errData = await res.json();
      const errMsg = errData.detail?.message || errData.detail || `提交${actionText}失败`;
      showToast(errMsg, "error");
    }
  } catch (err) {
    showToast("网络请求失败，请稍后重试", "error");
  } finally {
    renderSubmittingCardIds.delete(cardId);
  }
}

async function archiveCardToObsidian(cardId) {
  if (archivingCardIds.has(cardId)) return;
  setCardArchiving(cardId, true);
  announceArchiveStatus("正在归档卡片，请稍候");
  try {
    const encodedCardId = encodeURIComponent(cardId);
    const res = await fetch(`/api/cards/${encodedCardId}/archive`, { method: "POST" });
    if (res.ok) {
      const data = await res.json().catch(() => ({}));
      const message = data.already_archived
        ? "该卡已保存过，无需重复保存。"
        : "📸 已成功保存至 Obsidian 灵感库！";
      showToast(message, "success");
      announceArchiveStatus(data.already_archived ? "该卡已保存过，无需重复保存" : "卡片归档成功");
    } else {
      const errData = await res.json().catch(() => ({}));
      const detail = typeof errData.detail === "string"
        ? errData.detail
        : (errData.detail?.message || "保存到 Obsidian 失败");
      showToast(detail, "error");
      announceArchiveStatus(`卡片归档失败：${detail}`);
    }
  } catch (err) {
    showToast("网络请求失败，请稍后重试", "error");
    announceArchiveStatus("卡片归档失败：网络请求异常");
  } finally {
    setCardArchiving(cardId, false);
  }
}

function findRenderedCardItem(cardId) {
  return Array.from(document.querySelectorAll(".sidebar-card-item"))
    .find(item => item.getAttribute("data-card-id") === cardId) || null;
}

function setCardArchiving(cardId, isArchiving) {
  if (isArchiving) {
    archivingCardIds.add(cardId);
  } else {
    archivingCardIds.delete(cardId);
  }

  const item = findRenderedCardItem(cardId);
  if (!item) return;
  const button = item.querySelector(".btn-archive");
  item.classList.toggle("archiving", isArchiving);
  if (!button) return;

  button.disabled = isArchiving;
  button.classList.toggle("is-archiving", isArchiving);
  button.setAttribute("aria-busy", isArchiving ? "true" : "false");
  button.setAttribute("aria-label", isArchiving ? "正在归档" : "保存到 Obsidian");
  button.title = isArchiving ? "正在保存到 Obsidian" : "保存到 Obsidian";
  button.innerHTML = isArchiving
    ? '<span class="archive-spinner" aria-hidden="true"></span>'
    : '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="21 8 21 21 3 21 3 8"></polyline><rect x="1" y="3" width="22" height="5"></rect><line x1="10" y1="12" x2="14" y2="12"></line></svg>';
}

function announceArchiveStatus(message) {
  const region = document.getElementById("archive-status-announcer");
  if (!region) return;
  region.textContent = "";
  window.requestAnimationFrame(() => {
    region.textContent = message;
  });
}

async function deleteCard(cardId) {
  // Find the next card in order to select before deleting
  const visibleCardElems = Array.from(document.querySelectorAll(".sidebar-card-item"));
  let nextSelectedId = null;
  if (visibleCardElems.length > 1) {
    const currentIndex = visibleCardElems.findIndex(item => item.getAttribute("data-card-id") === cardId);
    if (currentIndex !== -1) {
      if (currentIndex < visibleCardElems.length - 1) {
        nextSelectedId = visibleCardElems[currentIndex + 1].getAttribute("data-card-id");
      } else {
        nextSelectedId = visibleCardElems[currentIndex - 1].getAttribute("data-card-id");
      }
    }
  }

  try {
    const res = await fetch(`/api/cards/${cardId}`, { method: "DELETE" });
    if (res.ok) {
      showToast("已成功删除卡片", "success");
      
      if (state.activeCardId === cardId) {
        if (nextSelectedId) {
          localStorage.setItem("active_card_id", nextSelectedId);
        } else {
          localStorage.removeItem("active_card_id");
        }
        state.activeCardId = null;
        state.activeCardData = null;
        const titleElem = document.getElementById("chat-active-card-title");
        if (titleElem) titleElem.innerHTML = "";
        const panelBody = document.getElementById("param-panel-body");
        if (panelBody) panelBody.innerHTML = '<p class="placeholder-text">选择卡片后将在此显示slots配置参数。</p>';
      }
      loadCards();
    } else {
      showToast("删除卡片失败", "error");
    }
  } catch (err) {
    showToast("删除卡片失败", "error");
  }
}

// =====================================================================
// 🎨 Card Selection & Observer Panel Reload
// =====================================================================
async function selectCard(cardId) {
  if (!cardId) return;

  // 收起所有边栏卡片的删除确认框
  document.querySelectorAll(".card-delete-confirm-overlay.show").forEach(overlay => {
    overlay.classList.remove("show");
  });

  state.activeCardId = cardId;
  localStorage.setItem("active_card_id", cardId);
  // 1. 更新边栏高亮类并滚动可见
  document.querySelectorAll(".sidebar-card-item").forEach(item => {
    if (item.getAttribute("data-card-id") === cardId) {
      item.classList.add("active");
      item.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } else {
      item.classList.remove("active");
    }
  });

  const isDraw = normalizeChatMode(state.settings && state.settings.chat_mode) === "draw";
  // 抽卡模式：只缓存卡数据供交接，不改标题/右栏/聊天区
  if (isDraw || state.sessionUiLock) {
    try {
      const res = await fetch(`/api/cards/${cardId}`);
      if (res.ok) state.activeCardData = await res.json();
    } catch (e) {
      const localCard = state.cards.find(c => c.card_id === cardId);
      if (localCard) state.activeCardData = localCard;
    }
    return;
  }

  // 补救机制：在 API 异步网络请求完成前，如果本地 state.cards 已有卡片，立即预渲染右侧看板，彻底防止出现空白页！
  const localCard = state.cards.find(c => c.card_id === cardId);
  if (localCard) {
    try { renderParamPanel(localCard); } catch (e) {}
  }

  try {
    const res = await fetch(`/api/cards/${cardId}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const card = await res.json();
    state.activeCardData = card; // 缓存卡片详细数据供大模型网关读取

    // 自动同步 Lightbox 大图视图（如果已经开启）
    const lightboxModal = document.getElementById("lightbox-modal");
    if (lightboxModal && lightboxModal.classList.contains("open")) {
      const lightboxImg = document.getElementById("lightbox-img");
      if (lightboxImg && card.render_image) {
        lightboxImg.src = card.image_url || `/images/${card.render_image}`;
      } else {
        lightboxModal.classList.remove("open");
      }
    }

    // 2. 更新聊天头部活跃卡片名
    const titleElem = document.getElementById("chat-active-card-title");
    const person = card.subject?.display_name || "未知人物";
    const scene = card.scene?.name || "随机场景";
    const theme = card.theme_zh || card._render_output?.meta_theme || "";

    if (titleElem) {
      const themePart = theme ? ` · ${escapeHtml(theme)}` : "";
      titleElem.innerHTML = `
        🎬 当前卡片: <strong style="color:var(--text-bright); font-weight:600;">${escapeHtml(person)}</strong> · ${escapeHtml(scene)}${themePart}
      `;
    }

    // 3. 渲染右侧参数看板；仅「卡片」模式加载卡片聊天历史
    renderParamPanel(card);
    if (!state.sessionUiLock) {
      await loadChatHistory(cardId);
    }

  } catch (err) {
    console.warn("载入远程卡片详情失败，已使用本地预渲染", err);
    if (localCard) {
      renderParamPanel(localCard);
      if (!state.sessionUiLock) {
        await loadChatHistory(cardId).catch(() => {});
      }
    }
  }
}

/** 参数看板收起后宽度归零、自身按钮不可见，需同步切换右侧浮标展开钮 */
function renderParamPanel(card) {
  const panelBody = document.getElementById("param-panel-body");
  if (!panelBody) return;

  // 1. 智能合成/读取英文提示词
  let englishPrompt = "";
  if (card._render_output && card._render_output.prompt) {
    englishPrompt = card._render_output.prompt;
  } else {
    // 降级自拼装：字段与引擎 SLOT_RENDER_ORDER 保持一致，另加不参与排序的 body_shape
    const slotsFields = [
      "lighting", "clothing", "pose", "expression_gaze",
      "style_quality", "makeup_hair", "accessories", "imperfections",
      "tattoo", "props", "pet", "liquids"
    ];
    const parts = [];
    if (card.scene && card.scene.keywords) parts.push(card.scene.keywords);
    if (card.subject && card.subject.trigger) parts.push(card.subject.trigger);
    if (card.slots && card.slots.body_shape) parts.push(card.slots.body_shape);
    slotsFields.forEach(k => {
      if (card.slots && card.slots[k]) {
        parts.push(card.slots[k]);
      }
    });
    englishPrompt = parts.join(", ");
  }

  const zhVal = card.director?.story_elevation_zh || card.narrative_zh || card.director?.story_frame || "未生成中文描述";

  // 2. 比对新旧内容以触发高亮动画
  const prevPrompt = state.lastSlots?.englishPrompt || "";
  const prevZh = state.lastSlots?.zhVal || "";
  const promptUpdated = prevPrompt && prevPrompt !== englishPrompt;
  const zhUpdated = prevZh && prevZh !== zhVal;

  // 统计英文提示词中的单词总数
  const wordCount = englishPrompt ? englishPrompt.split(/\s+/).filter(x => x.trim().length > 0).length : 0;

  let html = `
    <div class="prompt-board-wrapper">
      <!-- 英文提示词卡片 -->
      <div class="prompt-section-card ${promptUpdated ? 'updated-flash' : ''}">
        <div class="prompt-card-header">
          <div class="mac-window-dots">
            <span class="dot close"></span>
            <span class="dot minimize"></span>
            <span class="dot maximize"></span>
          </div>
          <span class="prompt-card-title"><i class="fa-solid fa-code"></i> prompt</span>
          <div class="prompt-card-actions">
            <span class="prompt-words-badge">${wordCount} words</span>
            <button class="btn-copy-prompt" title="复制提示词" data-prompt="${escapeHtml(englishPrompt)}" onclick="navigator.clipboard.writeText(this.getAttribute('data-prompt') || ''); showToast('提示词已复制', 'success')">
              <i class="fa-regular fa-copy"></i>
            </button>
          </div>
        </div>
        <div class="prompt-content-area">${englishPrompt ? escapeHtml(englishPrompt) : '<em style="color:var(--text-muted);">暂无提示词</em>'}</div>
      </div>

      <!-- 中文描述卡片 -->
      <div class="prompt-section-card ${zhUpdated ? 'updated-flash' : ''}">
        <div class="prompt-card-header">
          <div class="mac-window-dots">
            <span class="dot close"></span>
            <span class="dot minimize"></span>
            <span class="dot maximize"></span>
          </div>
          <span class="prompt-card-title"><i class="fa-solid fa-language"></i> 中文摘要</span>
        </div>
        <div class="prompt-content-area chinese-content">${escapeHtml(zhVal)}</div>
      </div>
    </div>
  `;

  panelBody.innerHTML = html;

  // 3. 记录上次的状态
  state.lastSlots = {
    englishPrompt: englishPrompt,
    zhVal: zhVal
  };

  // 1.2 秒后自动移除闪烁动画
  setTimeout(() => {
    document.querySelectorAll(".prompt-section-card.updated-flash").forEach(item => {
      item.classList.remove("updated-flash");
    });
  }, 1200);
}

function openDangerConfirmModal(options = {}) {
  const modal = document.getElementById("danger-confirm-modal");
  if (!modal) return;

  const titleEl = document.getElementById("danger-confirm-title");
  const messageEl = document.getElementById("danger-confirm-message");
  const hintEl = document.getElementById("danger-confirm-hint");
  const countLineEl = document.getElementById("danger-confirm-count-line");
  const countEl = document.getElementById("danger-confirm-count");
  const okBtn = document.getElementById("btn-danger-confirm-ok");

  if (titleEl) titleEl.textContent = options.title || "确认操作";
  if (messageEl) messageEl.textContent = options.message || "";
  if (hintEl) hintEl.textContent = options.hint || "";

  const hasCount = typeof options.count === "number";
  if (countLineEl) countLineEl.classList.toggle("is-hidden", !hasCount);
  if (countEl) countEl.textContent = hasCount ? String(options.count) : "0";

  if (okBtn) {
    okBtn.textContent = options.confirmLabel || "确定";
    okBtn.disabled = !!options.disabled;
    okBtn.style.opacity = options.disabled ? "0.5" : "1";
    okBtn.style.cursor = options.disabled ? "not-allowed" : "pointer";
  }

  state.dangerConfirmAction = typeof options.onConfirm === "function" ? options.onConfirm : null;
  modal.classList.add("open");
}

function closeDangerConfirmModal() {
  const modal = document.getElementById("danger-confirm-modal");
  if (modal) modal.classList.remove("open");
  state.dangerConfirmAction = null;
}

/** 与后端 cleanup_* 一致：仅时间戳卡 / featured_ 临时卡可被一键清理 */
function hasLocalCardImage(card) {
  return Boolean(card && card.image_url);
}

function countCleanupMissingImages() {
  const cards = state.cards || [];
  return cards.filter((c) => {
    if (!isCleanupEligibleCardId(c.card_id)) return false;
    if (!["rendered", "success"].includes(c.status)) return false;
    // list API 仅在本地图片存在时填 image_url
    return !c.image_url;
  }).length;
}

// 计数口径必须与后端 cleanup_* 的删除条件一致，否则弹窗里的「预计清理 N 张」会谎报
function countCleanupDrafts() {
  const eligible = (state.cards || []).filter(c => isCleanupEligibleCardId(c.card_id));
  return filterCardsByStatus(eligible, "draft").filter(c => !hasLocalCardImage(c)).length;
}

function countCleanupQueued() {
  const eligible = (state.cards || []).filter(c => isCleanupEligibleCardId(c.card_id));
  return filterCardsByStatus(eligible, "pending").filter(c => !hasLocalCardImage(c)).length;
}

function countCleanupFailed() {
  const eligible = (state.cards || []).filter(c => isCleanupEligibleCardId(c.card_id));
  return filterCardsByStatus(eligible, "failed").filter(c => !hasLocalCardImage(c)).length;
}

function countCleanupImageProtected(filterKey) {
  const eligible = (state.cards || []).filter(c => isCleanupEligibleCardId(c.card_id));
  return filterCardsByStatus(eligible, filterKey).filter(hasLocalCardImage).length;
}

/** 四个一键清理只差端点、按钮与文案，合并为同一实现避免行为漂移。 */
/**
 * 四个一键清理弹窗只差文案与执行体，合并为同一实现。
 * 清理白名单只覆盖时间戳卡与 featured_ 临时卡，因此可清理数可能小于该分类的卡片总数，
 * 差额需在提示里讲清楚，否则「列表 49 张 / 预计清理 47 张」会让人以为算错了。
 */
function openCleanupModal({
  filterKey,
  title,
  message,
  hint,
  count,
  protectedCount = 0,
  run,
}) {
  const eligible = count;
  const total = filterKey ? filterCardsByStatus(state.cards || [], filterKey).length : eligible;
  const skipped = Math.max(0, total - eligible - protectedCount);
  const skippedNote = skipped > 0
    ? `另有 ${skipped} 张为非时间戳卡（如手工命名的开发卡），不在一键清理范围内，需手动删除。`
    : "";
  const imageProtectionNote = protectedCount > 0
    ? `图片保护：检测到 ${protectedCount} 张卡片仍有本地对应图片，将自动跳过，不会删除。`
    : "图片保护：任何状态下，只要卡片仍有本地对应图片，一键清理都会自动跳过。";
  // 清理按状态执行，不看时间筛选；不讲清楚会让人以为只删当前可见的那几张
  const timeNote = state.timeFilter && state.timeFilter !== "all"
    ? "注意：一键清理不受上方时间筛选影响，会清理该状态下的全部卡片。"
    : "";
  openDangerConfirmModal({
    title,
    message,
    hint: [hint, imageProtectionNote, skippedNote, timeNote].filter(Boolean).join(" "),
    count: eligible,
    confirmLabel: "确定清理",
    disabled: eligible <= 0,
    onConfirm: run,
  });
}

function openCleanupConfirmModal() {
  openCleanupModal({
    filterKey: null,
    title: "确认一键清理",
    message: "确认一键清理所有「已完成但本地图片已不存在」的卡片？",
    hint: "此操作将不可逆地从列表中删除这些卡片及其全部对话记录。",
    count: countCleanupMissingImages(),
    protectedCount: countCleanupImageProtected("rendered"),
    run: runCleanupMissingImages,
  });
}

function openCleanupDraftsConfirmModal() {
  openCleanupModal({
    filterKey: "draft",
    title: "确认一键清理草稿",
    message: "确认一键清理所有「草稿」卡片？",
    hint: "此操作将不可逆地删除所有草稿（未出图的在制卡）及其全部对话记录。",
    count: countCleanupDrafts(),
    protectedCount: countCleanupImageProtected("draft"),
    run: runCleanupDrafts,
  });
}

function openCleanupQueuedConfirmModal() {
  openCleanupModal({
    filterKey: "pending",
    title: "确认一键清理定稿",
    message: "确认一键清理所有「定稿」卡片？",
    hint: "此操作将不可逆地删除所有定稿（校验通过 / 已提交 / 排队 / 渲染中）卡片及其全部对话记录。",
    count: countCleanupQueued(),
    protectedCount: countCleanupImageProtected("pending"),
    run: runCleanupQueued,
  });
}

function openCleanupFailedConfirmModal() {
  openCleanupModal({
    filterKey: "failed",
    title: "确认一键清理失败卡片",
    message: "确认一键清理所有「失败」卡片？",
    hint: "此操作将不可逆地删除所有校验或提交失败的卡片及其全部对话记录。",
    count: countCleanupFailed(),
    protectedCount: countCleanupImageProtected("failed"),
    run: runCleanupFailed,
  });
}

function cleanupResultMessage(data, noun) {
  const cleaned = Number(data && data.cleaned_count) || 0;
  const protectedCount = Number(data && data.skipped_image_count) || 0;
  if (protectedCount > 0) {
    return `🧹 已清理 ${cleaned} 张${noun}；另有 ${protectedCount} 张因存在本地图片已自动跳过。`;
  }
  return `🧹 成功清理 ${cleaned} 张${noun}！`;
}

async function runCleanup({ endpoint, buttonId, noun }) {
  const btn = document.getElementById(buttonId);
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> 清理中...`;
  }
  try {
    const res = await fetch(endpoint, { method: "POST" });
    if (res.ok) {
      const data = await res.json();
      showToast(cleanupResultMessage(data, noun), "success");
      await loadCards();
    } else {
      const errData = await res.json().catch(() => ({}));
      showToast(errData.detail || "清理失败", "error");
    }
  } catch (err) {
    showToast("网络请求失败，请稍后重试", "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `<i class="fa-solid fa-broom"></i> 一键清理`;
    }
  }
}

const runCleanupMissingImages = () =>
  runCleanup({ endpoint: "/api/cards/cleanup-missing-images", buttonId: "btn-cleanup-missing", noun: "无图卡片" });

const runCleanupDrafts = () =>
  runCleanup({ endpoint: "/api/cards/cleanup-drafts", buttonId: "btn-cleanup-drafts", noun: "草稿卡片" });

const runCleanupQueued = () =>
  runCleanup({ endpoint: "/api/cards/cleanup-queued", buttonId: "btn-cleanup-queued", noun: "定稿卡片" });

const runCleanupFailed = () =>
  runCleanup({ endpoint: "/api/cards/cleanup-failed", buttonId: "btn-cleanup-failed", noun: "失败卡片" });


