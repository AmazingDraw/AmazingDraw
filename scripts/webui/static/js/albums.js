/* albums.js — 成品库网格与专辑 */

let _albumScrollBound = false;
let _albumAutoLoading = false;

function computeSmartAlbumBatch(gridEl) {
  const grid = gridEl || document.getElementById("album-grid");
  const rawW = (grid && grid.clientWidth) ? grid.clientWidth : Math.max(720, window.innerWidth - 360);
  const innerWidth = Math.max(360, rawW - 56);
  // 与 CSS minmax(168px, 1fr) + gap 16px 严格对齐计算当前列数
  const cols = Math.max(2, Math.floor((innerWidth + 16) / (168 + 16)));
  // 每次按整列数的 8 行对齐加载（如 4列=32、5列=40、6列=48），保证末行永远铺满不留缺口
  return cols * 8;
}

function initAlbum() {
  const createBtn = document.getElementById("btn-album-create");
  const confirmBtn = document.getElementById("btn-album-create-confirm");
  const cancelBtn = document.getElementById("btn-album-create-cancel");
  const closeBtn = document.getElementById("btn-close-album-create");
  const modal = document.getElementById("album-create-modal");
  const nameInput = document.getElementById("album-new-name");
  const timeSel = document.getElementById("album-time-filter");

  createBtn?.addEventListener("click", () => openAlbumCreateModal());
  confirmBtn?.addEventListener("click", () => createAlbumFromInput());
  cancelBtn?.addEventListener("click", () => closeAlbumCreateModal());
  closeBtn?.addEventListener("click", () => closeAlbumCreateModal());
  modal?.addEventListener("click", (e) => {
    if (e.target === modal) closeAlbumCreateModal();
  });
  nameInput?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      createAlbumFromInput();
    }
    if (e.key === "Escape") {
      e.preventDefault();
      closeAlbumCreateModal();
    }
  });
  const reload = () => {
    state.albumLimit = computeSmartAlbumBatch();
    loadAlbumPool();
  };
  timeSel?.addEventListener("change", () => {
    state.albumTimeFilter = timeSel.value || "all";
    reload();
  });
}

function openAlbumCreateModal() {
  const modal = document.getElementById("album-create-modal");
  const input = document.getElementById("album-new-name");
  if (!modal) return;
  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
  if (input) {
    input.value = "";
    setTimeout(() => input.focus(), 40);
  }
}

function closeAlbumCreateModal() {
  const modal = document.getElementById("album-create-modal");
  if (!modal) return;
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
}

async function createAlbumFromInput() {
  const input = document.getElementById("album-new-name");
  const name = String(input && input.value || "").trim();
  if (!name) {
    showToast("请先填写专辑名", "warning");
    input?.focus();
    return;
  }
  try {
    const res = await fetch("/api/albums", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "新建失败");
    if (input) input.value = "";
    closeAlbumCreateModal();
    state.albumFilter = data.album && data.album.id;
    state.albumPersonFilter = "";
    await refreshAlbumWorkspace();
    showToast("已新建专辑", "success");
  } catch (err) {
    showToast(`新建专辑失败：${err.message || err}`, "error");
  }
}

async function refreshAlbumWorkspace() {
  await loadAlbumIndex();
  await loadAlbumPool();
}

async function loadAlbumIndex() {
  const res = await fetch("/api/albums");
  if (!res.ok) throw new Error("专辑列表加载失败");
  const data = await res.json();
  state.albums = data.albums || [];
  state.albumVirtual = data.virtual || {};
  state.albumGroups = data.groups || { persons: [] };
  renderAlbumSidebar();
}

async function loadAlbumPool() {
  const params = new URLSearchParams();
  params.set("album_id", state.albumFilter || "all");
  params.set("month", state.albumTimeFilter || "all");
  if (state.albumPersonFilter) params.set("person", state.albumPersonFilter);
  if (state.albumSceneFilter) params.set("scene", state.albumSceneFilter);
  const res = await fetch(`/api/albums/pool?${params.toString()}`);
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || "成片池加载失败");
  }
  const data = await res.json();
  state.albumPool = data.items || [];
  state.albumPoolTotal = Number(data.total) || state.albumPool.length;
  renderAlbumFacets(data.facets || {});
  renderAlbumGrid();
}

function renderAlbumFacets(facets) {
  const monthSel = document.getElementById("album-time-filter");
  if (monthSel) {
    const current = state.albumTimeFilter || "all";
    monthSel.innerHTML = "";
    const all = document.createElement("option");
    all.value = "all";
    all.textContent = "全部月份";
    monthSel.appendChild(all);
    (facets.months || []).forEach((month) => {
      const opt = document.createElement("option");
      opt.value = month;
      const [year, mon] = String(month).split("-");
      opt.textContent = `${year} 年 ${Number(mon)} 月`;
      monthSel.appendChild(opt);
    });
    monthSel.value = current;
    if (monthSel.value !== current) monthSel.value = "all";
  }
}

function selectAlbumBucket({ albumId, person }) {
  state.albumFilter = albumId || "all";
  state.albumPersonFilter = person || "";
  state.albumLimit = computeSmartAlbumBatch();
  renderAlbumSidebar();
  loadAlbumPool().catch((err) => showToast(err.message || err, "error"));
}

function albumBucketActive(kind, value) {
  const albumId = state.albumFilter || "all";
  const person = state.albumPersonFilter || "";
  if (kind === "album") return !person && albumId === value;
  if (kind === "person") return albumId === "all" && person === value;
  return false;
}

function renderAlbumNavEmpty(list, text) {
  const empty = document.createElement("p");
  empty.className = "placeholder-text";
  empty.textContent = text;
  list.appendChild(empty);
}

function renderAlbumSidebar() {
  const list = document.getElementById("album-sidebar-list");
  const personList = document.getElementById("album-person-list");
  if (!list) return;
  const virtual = state.albumVirtual || {};
  const albums = state.albums || [];
  const systemRows = albums
    .filter((album) => album.system || album.id === "favorites")
    .map((album) => ({
      id: album.id,
      name: album.name,
      count: album.count || 0,
      virtual: false,
      system: true,
    }));
  const userRows = albums
    .filter((album) => !(album.system || album.id === "favorites"))
    .map((album) => ({
      id: album.id,
      name: album.name,
      count: album.count || 0,
      virtual: false,
      system: false,
    }));
  const rows = [
    { id: "all", name: (virtual.all && virtual.all.name) || "全部成片", count: (virtual.all && virtual.all.count) || 0, virtual: true },
    ...systemRows,
    { id: "unfiled", name: (virtual.unfiled && virtual.unfiled.name) || "未分类", count: (virtual.unfiled && virtual.unfiled.count) || 0, virtual: true },
    ...userRows,
  ];
  list.innerHTML = "";
  rows.forEach((row) => {
    const btn = document.createElement("div");
    btn.className = `album-nav-item${row.system ? " is-system" : ""}${albumBucketActive("album", row.id) ? " active" : ""}`;
    btn.setAttribute("data-album-id", row.id);
    const iconHtml = row.id === "x_collection"
      ? `<span class="album-nav-x-icon" aria-hidden="true">𝕏</span>`
      : `<i class="fa-regular ${row.system ? "fa-heart" : row.virtual ? "fa-images" : "fa-folder"}"></i>`;
    btn.innerHTML = `
      ${iconHtml}
      <span class="album-nav-name"></span>
      <span class="album-nav-count">${row.count} 条</span>
      ${row.virtual || row.system ? "" : `<span class="album-nav-tools">
        <button type="button" data-album-act="rename" title="重命名"><i class="fa-solid fa-pen"></i></button>
        <button type="button" data-album-act="delete" title="删除专辑"><i class="fa-solid fa-trash"></i></button>
      </span>`}
    `;
    btn.querySelector(".album-nav-name").textContent = row.name;
    btn.addEventListener("click", (e) => {
      if (e.target.closest("[data-album-act]")) return;
      selectAlbumBucket({ albumId: row.id });
    });
    if (!row.virtual) {
      btn.addEventListener("dragover", (e) => {
        e.preventDefault();
        btn.classList.add("album-drop-target");
      });
      btn.addEventListener("dragleave", () => btn.classList.remove("album-drop-target"));
      btn.addEventListener("drop", async (e) => {
        e.preventDefault();
        btn.classList.remove("album-drop-target");
        const cardId = e.dataTransfer.getData("text/plain");
        if (cardId) await addCardToAlbum(row.id, cardId);
      });
      btn.querySelector('[data-album-act="rename"]')?.addEventListener("click", (e) => {
        e.stopPropagation();
        renameAlbum(row.id, row.name);
      });
      btn.querySelector('[data-album-act="delete"]')?.addEventListener("click", (e) => {
        e.stopPropagation();
        confirmDeleteAlbum(row.id, row.name);
      });
    }
    list.appendChild(btn);
  });

  if (personList) {
    personList.innerHTML = "";
    const persons = (state.albumGroups && state.albumGroups.persons) || [];
    const minMain = Number((state.albumGroups && state.albumGroups.person_min) || 3);
    const main = persons.filter((row) => Number(row.count) >= minMain);
    const rare = persons.filter((row) => Number(row.count) < minMain);
    if (!persons.length) {
      renderAlbumNavEmpty(personList, "暂无角色标签");
    } else {
      const appendPerson = (row, nested) => {
        const btn = document.createElement("div");
        btn.className = `album-nav-item${nested ? " album-nav-nested" : ""}${albumBucketActive("person", row.name) ? " active" : ""}`;
        btn.innerHTML = `
          <i class="fa-regular fa-user"></i>
          <span class="album-nav-name"></span>
          <span class="album-nav-count">${row.count} 条</span>
        `;
        btn.querySelector(".album-nav-name").textContent = row.name;
        const aliases = Array.isArray(row.aliases) ? row.aliases.filter(Boolean) : [];
        btn.title = aliases.length ? `${row.name}（含 ${aliases.join("、")}）` : row.name;
        btn.addEventListener("click", () => selectAlbumBucket({ albumId: "all", person: row.name }));
        personList.appendChild(btn);
      };
      main.forEach((row) => appendPerson(row, false));
      if (rare.length) {
        const rareCount = rare.reduce((sum, row) => sum + Number(row.count || 0), 0);
        const fold = document.createElement("div");
        fold.className = `album-nav-item album-nav-other${albumBucketActive("person", "__other__") ? " active" : ""}`;
        fold.innerHTML = `
          <i class="fa-solid fa-ellipsis"></i>
          <span class="album-nav-name">其他</span>
          <span class="album-nav-count">${rare.length} 人 · ${rareCount} 条</span>
          <i class="fa-solid ${state.albumPersonRareOpen ? "fa-chevron-up" : "fa-chevron-down"} album-nav-caret"></i>
        `;
        fold.title = `不足 ${minMain} 条的角色收在这里`;
        fold.addEventListener("click", (e) => {
          if (e.target.closest(".album-nav-caret") || albumBucketActive("person", "__other__")) {
            e.stopPropagation();
            state.albumPersonRareOpen = !state.albumPersonRareOpen;
            renderAlbumSidebar();
            return;
          }
          state.albumPersonRareOpen = true;
          selectAlbumBucket({ albumId: "all", person: "__other__" });
        });
        personList.appendChild(fold);
        if (state.albumPersonRareOpen) rare.forEach((row) => appendPerson(row, true));
      }
    }
  }
}

function _createAlbumTile(card, { realAlbum, isFavorites, favoriteIds }) {
  const tile = document.createElement("article");
  tile.className = "album-tile";
  tile.draggable = true;
  tile.dataset.cardId = card.card_id;
  const imgSrc = card.image_url || (card.render_image ? `/images/${encodeURIComponent(card.render_image)}` : "");
  const heading = [card.person, card.scene].filter(Boolean).join(" · ") || card.card_id;
  const frame = document.createElement("div");
  frame.className = "album-tile-frame";
  const favorited = favoriteIds.has(card.card_id);
  const xPost = card.x_post && typeof card.x_post === "object" ? card.x_post : null;
  let xBadgeHtml = "";
  if (xPost) {
    const ts = Number(xPost.posted_at || 0);
    const when = ts ? new Date(ts * 1000).toLocaleString("zh-CN", { hour12: false }) : "";
    const tip = [
      "已发 X",
      xPost.handle || "",
      when ? `(${when})` : "",
      xPost.status_url ? "· 点击查看原帖" : "",
    ].filter(Boolean).join(" ");
    const safeUrl = xPost.status_url && /^https?:\/\//i.test(xPost.status_url) ? xPost.status_url : "";
    xBadgeHtml = safeUrl
      ? `<a class="album-tile-x-badge" href="${escapeHtml(safeUrl)}" target="_blank" rel="noopener noreferrer" title="${escapeHtml(tip)}" aria-label="${escapeHtml(tip)}">𝕏</a>`
      : `<span class="album-tile-x-badge" title="${escapeHtml(tip)}" aria-label="${escapeHtml(tip)}">𝕏</span>`;
  }
  frame.innerHTML = `
    ${xBadgeHtml}
    <div class="album-tile-quick">
      <button type="button" data-album-fav class="${favorited ? "is-on" : ""}" title="${favorited ? "取消收藏" : "收藏"}" aria-label="${favorited ? "取消收藏" : "收藏"}">
        <i class="fa-${favorited ? "solid" : "regular"} fa-heart"></i>
      </button>
      <button type="button" data-album-del title="删除卡片" aria-label="删除卡片">
        <i class="fa-regular fa-trash-can"></i>
      </button>
    </div>
    <div class="album-tile-meta">
      <div class="album-tile-title"></div>
      <div class="album-tile-sub">${escapeHtml(card.status || "")}</div>
      <div class="album-tile-actions">
        <button type="button" data-album-open>工作台打开</button>
      </div>
    </div>
  `;
  frame.querySelector(".album-tile-title").textContent = heading;
  if (imgSrc) {
    const img = document.createElement("img");
    img.className = "gallery-img album-thumb loaded";
    img.alt = heading;
    img.decoding = "async";
    img.loading = "lazy";
    img.addEventListener("error", () => {
      img.classList.add("is-missing");
    });
    img.src = imgSrc;
    frame.insertBefore(img, frame.firstChild);
  } else {
    const missing = document.createElement("div");
    missing.className = "album-tile-missing";
    missing.textContent = "无图";
    frame.insertBefore(missing, frame.firstChild);
  }
  tile.appendChild(frame);
  tile.addEventListener("dragstart", (e) => {
    e.dataTransfer.setData("text/plain", card.card_id);
  });
  tile.querySelector(".album-tile-x-badge")?.addEventListener("click", (e) => {
    e.stopPropagation();
  });
  tile.querySelector("[data-album-open]")?.addEventListener("click", () => openCardInWorkbench(card.card_id));
  tile.querySelector("[data-album-fav]")?.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    const isNowOn = e.currentTarget.classList.contains("is-on");
    toggleFavoriteCard(card.card_id, isNowOn);
  });
  tile.querySelector("[data-album-del]")?.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    confirmDeleteAlbumCard(card);
  });
  return tile;
}

function renderAlbumGrid(opts = {}) {
  const grid = document.getElementById("album-grid");
  const title = document.getElementById("album-header-title");
  const info = document.getElementById("album-sidebar-info");
  if (!grid) return;

  if (!_albumScrollBound) {
    _albumScrollBound = true;
    grid.addEventListener("scroll", () => {
      if (_albumAutoLoading) return;
      if (grid.scrollTop <= 0) return;
      const items = state.albumPool || [];
      const currentLimit = state.albumLimit || 0;
      if (currentLimit >= items.length) return;
      if (grid.scrollTop + grid.clientHeight >= grid.scrollHeight - 260) {
        _albumAutoLoading = true;
        state.albumLimit = currentLimit + computeSmartAlbumBatch(grid);
        renderAlbumGrid({ append: true });
        setTimeout(() => {
          _albumAutoLoading = false;
        }, 180);
      }
    }, { passive: true });
  }

  const items = state.albumPool || [];
  const step = computeSmartAlbumBatch(grid);
  if (!state.albumLimit || state.albumLimit < step) {
    state.albumLimit = step;
  }
  const limit = state.albumLimit;
  const shown = items.slice(0, limit);
  const albumName = albumTitleFor(state.albumFilter);
  if (title) {
    title.innerHTML = `<i class="fa-regular fa-images"></i> ${escapeHtml(albumName)} · ${items.length} 条`;
  }
  if (info) info.textContent = `显示 ${shown.length} / ${items.length} 条`;

  const realAlbum = (state.albums || []).some((a) => a.id === state.albumFilter);
  const isFavorites = state.albumFilter === "favorites";
  const favoriteIds = new Set(((state.albums || []).find((a) => a.id === "favorites") || {}).card_ids || []);

  if (opts.append) {
    const oldMore = grid.querySelector(".load-more-container");
    if (oldMore) oldMore.remove();
    const existingCount = grid.querySelectorAll(".album-tile").length;
    shown.slice(existingCount).forEach((card) => {
      grid.appendChild(_createAlbumTile(card, { realAlbum, isFavorites, favoriteIds }));
    });
  } else {
    const prevScrollTop = opts.preserveScroll ? grid.scrollTop : 0;
    grid.innerHTML = "";
    if (!shown.length) {
      const empty = document.createElement("p");
      empty.className = "placeholder-text";
      empty.textContent = "这个分组里还没有成片。把卡片拖到左侧专辑即可分类。";
      grid.appendChild(empty);
      grid.scrollTop = 0;
      return;
    }
    shown.forEach((card) => {
      grid.appendChild(_createAlbumTile(card, { realAlbum, isFavorites, favoriteIds }));
    });
    grid.scrollTop = prevScrollTop;
  }

  if (items.length > shown.length) {
    const more = document.createElement("div");
    more.className = "load-more-container";
    const nextBatch = Math.min(step, items.length - shown.length);
    more.innerHTML = `<button type="button" class="btn-load-more" id="btn-album-load-more"><i class="fa-solid fa-arrow-down-long"></i> 继续加载 ${nextBatch} 张 (已显示 ${shown.length}/${items.length} · 下滑到底部自动续载)</button>`;
    more.querySelector("button").addEventListener("click", () => {
      state.albumLimit = shown.length + computeSmartAlbumBatch(grid);
      renderAlbumGrid({ append: true });
    });
    grid.appendChild(more);
  }
}

function albumTitleFor(id) {
  if (state.albumPersonFilter === "__other__") return "角色 · 其他";
  if (state.albumPersonFilter) return `角色 · ${state.albumPersonFilter}`;
  if (id === "unfiled") return "未分类";
  const found = (state.albums || []).find((a) => a.id === id);
  if (found) return found.name;
  return "全部成片";
}

function favoriteAlbum() {
  return (state.albums || []).find((album) => album.id === "favorites") || null;
}

async function toggleFavoriteCard(cardId, currentlyOn) {
  const album = favoriteAlbum();
  if (!album) {
    showToast("收藏分类还没准备好", "warning");
    return;
  }
  if (currentlyOn) {
    await removeCardFromAlbum(album.id, cardId, { silent: true, toast: "已取消收藏" });
  } else {
    await addCardToAlbum(album.id, cardId, { silent: true, toast: "已收藏" });
  }
}

function _removeTileFromAlbumGrid(cardId) {
  const grid = document.getElementById("album-grid");
  const title = document.getElementById("album-header-title");
  const info = document.getElementById("album-sidebar-info");

  state.albumPool = (state.albumPool || []).filter((c) => c.card_id !== cardId);
  const items = state.albumPool;

  if (!grid) return;
  const tile = Array.from(grid.querySelectorAll(".album-tile")).find(
    (el) => el.dataset.cardId === cardId
  );
  if (tile) tile.remove();

  const currentTiles = grid.querySelectorAll(".album-tile").length;
  const limit = state.albumLimit || currentTiles;
  const oldMore = grid.querySelector(".load-more-container");

  // 如果池子里还有未渲染的后继卡片，顺位补一张进来保持网格整齐
  if (currentTiles < limit && items.length > currentTiles) {
    const nextCard = items[currentTiles];
    if (nextCard) {
      const realAlbum = (state.albums || []).some((a) => a.id === state.albumFilter);
      const isFavorites = state.albumFilter === "favorites";
      const favoriteIds = new Set(((state.albums || []).find((a) => a.id === "favorites") || {}).card_ids || []);
      const nextTile = _createAlbumTile(nextCard, { realAlbum, isFavorites, favoriteIds });
      if (oldMore) grid.insertBefore(nextTile, oldMore);
      else grid.appendChild(nextTile);
    }
  }

  const shownCount = grid.querySelectorAll(".album-tile").length;
  const albumName = albumTitleFor(state.albumFilter);
  if (title) {
    title.innerHTML = `<i class="fa-regular fa-images"></i> ${escapeHtml(albumName)} · ${items.length} 条`;
  }
  if (info) info.textContent = `显示 ${shownCount} / ${items.length} 条`;

  if (!shownCount) {
    if (oldMore) oldMore.remove();
    const empty = document.createElement("p");
    empty.className = "placeholder-text";
    empty.textContent = "这个分组里还没有成片。把卡片拖到左侧专辑即可分类。";
    grid.appendChild(empty);
  } else if (oldMore) {
    if (items.length <= shownCount) {
      oldMore.remove();
    } else {
      const step = computeSmartAlbumBatch(grid);
      const nextBatch = Math.min(step, items.length - shownCount);
      const btn = oldMore.querySelector("button");
      if (btn) {
        btn.innerHTML = `<i class="fa-solid fa-arrow-down-long"></i> 继续加载 ${nextBatch} 张 (已显示 ${shownCount}/${items.length} · 下滑到底部自动续载)`;
      }
    }
  }
}

function confirmDeleteAlbumCard(card) {
  const label = [card.person, card.scene].filter(Boolean).join(" · ") || card.card_id;
  openDangerConfirmModal({
    title: "删除卡片",
    message: `删除「${label}」会拿掉卡片和图片，收藏和专辑里也会去掉。`,
    confirmLabel: "删除",
    onConfirm: async () => {
      if (typeof deleteCard === "function") {
        await deleteCard(card.card_id);
      }
      _removeTileFromAlbumGrid(card.card_id);
      loadAlbumIndex().catch(() => {});
    },
  });
}

function _syncTileFavoriteButton(cardId, isOn) {
  const grid = document.getElementById("album-grid");
  if (!grid) return;
  const tile = Array.from(grid.querySelectorAll(".album-tile")).find(
    (el) => el.dataset.cardId === cardId
  );
  const btn = tile?.querySelector("[data-album-fav]");
  if (!btn) return;
  btn.classList.toggle("is-on", isOn);
  btn.title = isOn ? "取消收藏" : "收藏";
  btn.setAttribute("aria-label", isOn ? "取消收藏" : "收藏");
  const icon = btn.querySelector("i");
  if (icon) icon.className = `fa-${isOn ? "solid" : "regular"} fa-heart`;
}

async function addCardToAlbum(albumId, cardId, options = {}) {
  try {
    const res = await fetch(`/api/albums/${encodeURIComponent(albumId)}/cards`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ add: [cardId] }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || "移入失败");
    if (state.albumFilter === albumId) {
      await refreshAlbumWorkspace();
    } else {
      if (albumId === "favorites") _syncTileFavoriteButton(cardId, true);
      loadAlbumIndex().catch(() => {});
    }
    showToast(options.toast || "已加入专辑", "success");
  } catch (err) {
    showToast(`移入失败：${err.message || err}`, "error");
  }
}

async function removeCardFromAlbum(albumId, cardId, options = {}) {
  try {
    const res = await fetch(`/api/albums/${encodeURIComponent(albumId)}/cards`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ remove: [cardId] }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || "移出失败");
    if (state.albumFilter === albumId) {
      _removeTileFromAlbumGrid(cardId);
      loadAlbumIndex().catch(() => {});
    } else {
      if (albumId === "favorites") _syncTileFavoriteButton(cardId, false);
      loadAlbumIndex().catch(() => {});
    }
    showToast(options.toast || "已移出专辑", "success");
  } catch (err) {
    showToast(`移出失败：${err.message || err}`, "error");
  }
}

async function setAlbumCover(albumId, cardId) {
  try {
    const res = await fetch(`/api/albums/${encodeURIComponent(albumId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cover_card_id: cardId }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || "设置封面失败");
    await loadAlbumIndex();
    showToast("已设为封面", "success");
  } catch (err) {
    showToast(`设置封面失败：${err.message || err}`, "error");
  }
}

async function renameAlbum(albumId, currentName) {
  const next = window.prompt("专辑新名称", currentName || "");
  if (next == null) return;
  const name = String(next).trim();
  if (!name) {
    showToast("专辑名不能为空", "warning");
    return;
  }
  try {
    const res = await fetch(`/api/albums/${encodeURIComponent(albumId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || "重命名失败");
    await refreshAlbumWorkspace();
  } catch (err) {
    showToast(`重命名失败：${err.message || err}`, "error");
  }
}

function confirmDeleteAlbum(albumId, name) {
  openDangerConfirmModal({
    title: "删除专辑",
    message: `删除「${name}」只去掉分组，卡片和图片都还在。`,
    confirmLabel: "删除专辑",
    onConfirm: async () => {
      const res = await fetch(`/api/albums/${encodeURIComponent(albumId)}`, { method: "DELETE" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        showToast(data.detail || "删除失败", "error");
        return;
      }
      if (state.albumFilter === albumId) state.albumFilter = "all";
      await refreshAlbumWorkspace();
      showToast("专辑已删除", "success");
    },
  });
}

function openCardInWorkbench(cardId) {
  switchView("chat");
  if (typeof selectCard === "function") selectCard(cardId);
}

async function ensureAlbumViewLoaded() {
  try {
    await refreshAlbumWorkspace();
  } catch (err) {
    showToast(`相册加载失败：${err.message || err}`, "error");
  }
}
