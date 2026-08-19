/* widgets.js — 弹窗、自动补全、灯箱与诗词挂件
   由 app.js 拆分而来；加载顺序见 index.html，core.js 必须最先。 */

function initModals() {
  // Toggle 右侧看板：收起后面板宽度归零，改由浮标按钮负责展开
  const togglePanelBtn = document.getElementById("btn-toggle-param-panel");
  const expandPanelBtn = document.getElementById("btn-expand-param-panel");
  if (togglePanelBtn) {
    togglePanelBtn.addEventListener("click", () => setParamPanelCollapsed(true));
  }
  if (expandPanelBtn) {
    expandPanelBtn.addEventListener("click", () => setParamPanelCollapsed(false));
  }
  const closeCreate = document.getElementById("btn-close-create");
  const createModal = document.getElementById("create-modal");
  const openCreate = document.getElementById("btn-create-card");

  if (closeCreate && createModal) {
    closeCreate.addEventListener("click", () => createModal.classList.remove("open"));
  }

  if (openCreate && createModal) {
    openCreate.addEventListener("click", () => {
      createModal.classList.add("open");
      const focusTarget = document.getElementById("create-user-input");
      if (focusTarget) focusTarget.focus();
    });
    createModal.addEventListener("click", (e) => {
      if (e.target === createModal) createModal.classList.remove("open");
    });
  }

  // 通用危险确认弹窗事件绑定
  const dangerConfirmModal = document.getElementById("danger-confirm-modal");
  const closeDangerConfirm = document.getElementById("btn-close-danger-confirm");
  const dangerCancel = document.getElementById("btn-danger-cancel");
  const dangerConfirmOk = document.getElementById("btn-danger-confirm-ok");

  if (dangerConfirmModal) {
    if (closeDangerConfirm) {
      closeDangerConfirm.addEventListener("click", () => closeDangerConfirmModal());
    }
    if (dangerCancel) {
      dangerCancel.addEventListener("click", () => closeDangerConfirmModal());
    }
    if (dangerConfirmOk) {
      dangerConfirmOk.addEventListener("click", async () => {
        const action = state.dangerConfirmAction;
        closeDangerConfirmModal();
        if (action) {
          await action();
        }
      });
    }
  }
  
  /**
   * 建卡进度态：禁用表单、按钮转圈、显示阶段与已用秒数。
   * 不伪造百分比进度——后端是单次不可分割的请求，只如实报「在做什么 + 已等多久 + 预计多久」。
   */
  function beginCreateProgress(form, isFastPath) {
    const submitBtn = form.querySelector('button[type="submit"]');
    const original = submitBtn ? submitBtn.innerHTML : "";
    const fields = [...form.querySelectorAll("input, select, textarea, button")];
    const disabledBefore = fields.map(el => el.disabled);
    fields.forEach(el => { el.disabled = true; });

    let status = form.querySelector(".create-progress");
    if (!status) {
      status = document.createElement("div");
      status.className = "create-progress";
      form.appendChild(status);
    }
    const expect = isFastPath
      ? "已指定人物与场景，通常 1 秒内完成。"
      : "人物 / 场景交由引擎随机路由，通常需要 10–20 秒，请勿关闭窗口。";
    let phase = "正在解析创作诉求并生成骨架…";
    const started = Date.now();

    const paint = () => {
      const secs = Math.floor((Date.now() - started) / 1000);
      status.innerHTML =
        `<i class="fa-solid fa-spinner fa-spin"></i>` +
        `<div><div class="create-progress-phase">${escapeHtml(phase)} <b>${secs}s</b></div>` +
        `<div class="create-progress-hint">${escapeHtml(expect)}</div></div>`;
    };
    paint();
    const timer = setInterval(paint, 1000);
    if (submitBtn) {
      submitBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> 生成中…`;
    }

    const restore = () => {
      clearInterval(timer);
      fields.forEach((el, i) => { el.disabled = disabledBefore[i]; });
      if (submitBtn) submitBtn.innerHTML = original;
      status.remove();
    };

    return {
      setPhase(text) { phase = text; paint(); },
      finish: restore,
      fail: restore,
    };
  }

  const formCreate = document.getElementById("form-create");
  if (formCreate) {
    formCreate.addEventListener("submit", async (e) => {
      e.preventDefault();
      const userInput = (formCreate.elements["user_input"].value || "").trim();
      if (!userInput) {
        showToast("请先填写创作诉求，引擎需要它解析用户约束", "error");
        return;
      }
      const data = {
        mode: formCreate.elements["mode"].value,
        person: formCreate.elements["person"].value,
        scene: formCreate.elements["scene"].value,
        aspect: formCreate.elements["aspect"].value,
        profile: formCreate.elements["profile"].value,
        user_input: userInput,
        bundle: formCreate.elements["bundle"].checked ? "auto" : null
      };
      // 未指定人物/场景时引擎要调 LLM 路由，实测 10~16 秒；
      // 期间若毫无反馈会被当成卡死，所以整段过程都要有进度态。
      const progress = beginCreateProgress(formCreate, Boolean(data.person && data.scene));
      try {
        const res = await fetch("/api/cards/create", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data)
        });
        const result = await res.json();
        if (!res.ok) {
          progress.fail();
          showToast(result.detail || "创建骨架失败", "error");
          return;
        }

        progress.setPhase("骨架已生成，正在交接给 AI…");
        await loadCards();
        await selectCard(result.card_id);
        progress.finish();
        if (createModal) createModal.classList.remove("open");
        formCreate.reset();
        showToast("卡片骨架创建成功，正在交给 AI 接手", "success");

        // 复用卡片→抽卡交接：切到 draw 会话并带上卡片上下文，让 AI 按常规流程往下跑
        await handoffCardsToDrawChat(buildTakeoverPrompt(result.card_id, data));
      } catch (err) {
        progress.fail();
        showToast("创建骨架失败", "error");
      }
    });
  }

  // Queue actions (Quick commands)
  const btnTerminate = document.getElementById("btn-quick-terminate");
  const btnClear = document.getElementById("btn-quick-clear");
  const clearOverlay = document.getElementById("queue-clear-confirm-overlay");
  const clearConfirmYes = document.getElementById("btn-clear-confirm-yes");
  const clearConfirmNo = document.getElementById("btn-clear-confirm-no");

  if (btnTerminate) {
    btnTerminate.addEventListener("click", () => terminateQueue());
  }

  if (btnClear && clearOverlay) {
    btnClear.addEventListener("click", (e) => {
      e.stopPropagation();
      clearOverlay.classList.add("show");
    });
  }

  if (clearConfirmNo && clearOverlay) {
    clearConfirmNo.addEventListener("click", (e) => {
      e.stopPropagation();
      clearOverlay.classList.remove("show");
    });
  }

  if (clearConfirmYes && clearOverlay) {
    clearConfirmYes.addEventListener("click", async (e) => {
      e.stopPropagation();
      clearOverlay.classList.remove("show");
      await clearRenderQueue();
    });
  }
}

/* 明星有 106 位，仅靠输入即筛不够用：认不全名字时得能翻。
   所以聚焦就摊开按首字母分组的全量列表，输入再收敛。
   命中三种写法：中文名、全拼(liuyifei)、首字母缩写(lyf)。 */
function celebrityMatches(val) {
  const list = state.celebrities || [];
  const hit = !val ? list.slice() : list.filter(c =>
    (c.name || "").toLowerCase().includes(val) ||
    (c.pinyin || "").includes(val) ||
    (c.abbr || "").includes(val)
  );
  // 必须按首字母排好再交给渲染：接口给的是文件原序，首字母来回跳，
  // 分组时「与上一条不同就插组头」会把 17 个字母拆成几十个重复组头。
  return hit.sort((a, b) =>
    (a.initial || "#").localeCompare(b.initial || "#") ||
    (a.pinyin || a.name).localeCompare(b.pinyin || b.name)
  );
}

function isCelebrityMode() {
  const sel = document.getElementById("create-mode");
  return !!sel && sel.value === "celebrity";
}

/* 候选池跟着抽卡模式走，两边互斥：模式已经决定了引擎用哪个池子，
   混在一起只会让人在 154 条里挑，还可能选到当前模式根本用不上的那类。 */
function collectPersonMatches(val) {
  if (isCelebrityMode()) {
    return celebrityMatches(val).map(c => ({
      label: c.name,
      hint: c.abbr ? c.abbr.toUpperCase() : "",
      value: c.name,
      source: "celebrity",
      group: c.initial || "#",
    }));
  }

  const profiles = [];
  Object.keys(state.profiles || {}).forEach(key => {
    const p = state.profiles[key];
    const dn = (p.display_name || "").toLowerCase();
    if (!val || key.toLowerCase().includes(val) || dn.includes(val)) {
      profiles.push({
        label: `${key} (${p.display_name})`,
        hint: "",
        value: p.display_name,
        source: p.source,
        // 只剩一类时不必再挂组头
        group: "",
      });
    }
  });
  return profiles;
}

function setupAutocompleteBinding(inputId, suggestionsId, type) {
  const inputEl = document.getElementById(inputId);
  const suggsEl = document.getElementById(suggestionsId);
  if (!inputEl || !suggsEl) return;

  const applyPick = (value) => {
    inputEl.value = value;
    suggsEl.style.display = "none";
    if (type !== "person") return;
    const selectProf = document.getElementById("create-profile");
    const key = Object.keys(state.profiles || {}).find(k => state.profiles[k].display_name === value);
    if (key && selectProf) selectProf.value = key;
  };

  const render = () => {
    const val = inputEl.value.trim().toLowerCase();
    suggsEl.innerHTML = "";

    let matches = [];
    if (type === "person") {
      matches = collectPersonMatches(val);
    } else if (type === "scene") {
      if (!val) { suggsEl.style.display = "none"; return; }
      matches = (state.scenes || [])
        .filter(s => s.label.toLowerCase().includes(val) || s.scene.toLowerCase().includes(val))
        .map(s => ({ label: `${s.label} (${s.scene})`, hint: "", value: s.label, source: s.source, group: "" }));
    }

    if (!matches.length) {
      suggsEl.style.display = "none";
      return;
    }

    // 浏览全量时不截断（靠面板滚动）；有输入时给个上限避免刷屏
    const shown = val ? matches.slice(0, 40) : matches;
    let lastGroup = null;
    shown.forEach(m => {
      if (m.group && m.group !== lastGroup) {
        lastGroup = m.group;
        const head = document.createElement("div");
        head.className = "autocomplete-group";
        head.textContent = m.group;
        suggsEl.appendChild(head);
      }
      const item = document.createElement("div");
      item.className = "autocomplete-item";
      const srcText = m.source === "builtin" ? "内置" : (m.source === "third-party" ? "第三方" : "明星");
      item.innerHTML = `
        <span>${escapeHtml(m.label)}${m.hint ? ` <span class="autocomplete-hint">${escapeHtml(m.hint)}</span>` : ""}</span>
        <span class="badge-src ${m.source}">${srcText}</span>
      `;
      item.addEventListener("mousedown", (e) => {
        e.preventDefault();   // 抢在 blur 之前，否则面板先收起点不中
        applyPick(m.value);
      });
      suggsEl.appendChild(item);
    });
    suggsEl.style.display = "block";
    suggsEl.scrollTop = 0;
  };

  inputEl.addEventListener("input", render);
  inputEl.addEventListener("focus", render);

  document.addEventListener("click", (e) => {
    if (e.target !== inputEl && !suggsEl.contains(e.target)) suggsEl.style.display = "none";
  });
}

function initAutocomplete() {
  setupAutocompleteBinding("create-person", "person-suggestions", "person");
  setupAutocompleteBinding("create-scene", "scene-suggestions", "scene");

  // 切模式时候选池会变（明星模式只出明星），已选的人物多半也不再适用，清掉重选
  const modeSel = document.getElementById("create-mode");
  const personEl = document.getElementById("create-person");
  const suggsEl = document.getElementById("person-suggestions");
  if (!modeSel || !personEl) return;

  const syncPersonField = () => {
    const celeb = modeSel.value === "celebrity";
    personEl.placeholder = celeb
      ? "输入或选择明星（支持拼音，如 lyf）..."
      : "输入或选择角色预设/身份（如 OL、护士）...";
    if (suggsEl) suggsEl.style.display = "none";
  };

  modeSel.addEventListener("change", () => {
    personEl.value = "";
    syncPersonField();
  });
  syncPersonField();
}

// initWorkflowConverter deleted

// =====================================================================
// ⚡ Direct Mode (直投模式) Logic
// =====================================================================
function initLightbox() {
  const modal = document.getElementById("lightbox-modal");
  const closeBtn = document.getElementById("btn-close-lightbox");
  if (!modal) return;

  const openLightbox = (src) => {
    const img = document.getElementById("lightbox-img");
    if (!img || !src) return;
    img.src = src;
    img.style.display = "block";
    modal.classList.add("open");
  };

  const closeLightbox = () => {
    modal.classList.remove("open");
    const img = document.getElementById("lightbox-img");
    if (img) {
      img.removeAttribute("src");
      img.style.display = "none";
    }
  };

  closeBtn?.addEventListener("click", closeLightbox);
  modal.addEventListener("click", (e) => {
    if (e.target === modal || e.target.id === "lightbox-img" || e.target.closest("#btn-close-lightbox")) {
      closeLightbox();
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && modal.classList.contains("open")) {
      closeLightbox();
    }
  });

  // Global event delegation for images that support zooming
  document.addEventListener("click", (e) => {
    if (e.target.tagName === "IMG" && (e.target.classList.contains("gallery-img") || e.target.closest(".chat-image-bubble"))) {
      openLightbox(e.target.src);
    }
  });
}

// =====================================================================
// 🤖 Draw Chat (draw) Native Sessions Management
// =====================================================================
/**
 * 加载抽卡会话列表。
 * opts.preferSessionId — 优先选中该会话（交接/新建后）
 * opts.skipHistory — 只刷侧栏，不重载聊天区（避免闪旧历史）
 * opts.skipAutoSelect — 只刷新列表，不改变当前选中
 */
function initPoetryWidget() {
  const textEl = document.getElementById("poetry-text");
  const infoEl = document.getElementById("poetry-info");
  const playBtn = document.getElementById("btn-play-poetry");
  if (!textEl) return;

  let poetryAudio = null;
  let currentAudioUrl = null;

  const refreshAction = async () => {
    // 停止当前播放的音频
    if (poetryAudio) {
      poetryAudio.pause();
      poetryAudio = null;
    }
    if (playBtn) {
      playBtn.style.display = "none";
      const icon = playBtn.querySelector("i");
      if (icon) icon.className = "fa-solid fa-play";
    }
    currentAudioUrl = null;

    textEl.innerText = "加载中...";
    if (infoEl) infoEl.innerText = "正在吟诗...";

    try {
      const res = await fetch("/api/poetry");
      const data = await res.json();
      if (data.status === "ok" || data.status === "fallback") {
        textEl.innerText = data.quote;
        if (infoEl) {
          const titleStr = data.title ? ` · 《${data.title}》` : "";
          infoEl.innerText = `[${data.dynasty}] ${data.author}${titleStr}`;
        }
        // 如果有音频数据，则记录链接并显示播放按钮
        if (data.audio) {
          currentAudioUrl = data.audio;
          if (playBtn) playBtn.style.display = "flex";
        }
      } else {
        throw new Error("API status not ok");
      }
    } catch (err) {
      const offlinePoems = [
        {
          quote: "春眠不觉晓，处处闻啼鸟。\n夜来风雨声，花落知多少。",
          title: "春晓",
          author: "孟浩然",
          dynasty: "唐"
        },
        {
          quote: "楚天千里清秋，水随天去秋无际。\n献愁供恨，玉簪螺髻。\n落日楼头，断鸿声里，江南游子。\n把吴钩看了，栏干拍遍，无人会、登临意。",
          title: "水龙吟·登建康赏心亭",
          author: "辛弃疾",
          dynasty: "宋"
        },
        {
          quote: "落霞与孤鹜齐飞，秋水共长天一色。\n渔舟唱晚，响穷彭蠡之滨；\n雁阵惊寒，声断衡阳之浦。",
          title: "滕王阁序",
          author: "王勃",
          dynasty: "唐"
        },
        {
          quote: "明月几时有？把酒问青天。\n不知天上宫阙，今夕是何年。\n我欲乘风归去，又恐琼楼玉宇，高处不胜寒。\n起舞弄清影，何似在人间。",
          title: "水调歌头·明月几时有",
          author: "苏轼",
          dynasty: "宋"
        },
        {
          quote: "锦瑟无端五十弦，一弦一柱思华年。\n庄生晓梦迷蝴蝶，望帝春心托杜鹃。\n沧海月明珠有泪，蓝田日暖玉生烟。\n此情可待成追忆？只是当时已惘然。",
          title: "锦瑟",
          author: "李商隐",
          dynasty: "唐"
        },
        {
          quote: "春江潮水连海平，海上明月共潮生。\n滟滟随波千万里，何处春江无月明！",
          title: "春江花月夜",
          author: "张若虚",
          dynasty: "唐"
        },
        {
          quote: "君不见，黄河之水天上来，奔流到海不复回。\n君不见，高堂明镜悲白发，朝如青丝暮成雪。\n人生得意须尽欢，莫使金樽空对月。",
          title: "将进酒",
          author: "李白",
          dynasty: "唐"
        },
        {
          quote: "红豆生南国，春来发几枝。\n愿君多采撷，此物最相思。",
          title: "相思",
          author: "王维",
          dynasty: "唐"
        },
        {
          quote: "结庐在人境，而无车马喧。\n问君何能尔？心远地自偏。\n采菊东篱下，悠然见南山。",
          title: "饮酒·其五",
          author: "陶渊明",
          dynasty: "东晋"
        },
        {
          quote: "离离原上草，一岁一枯荣。\n野火烧不尽，春风吹又生。\n远芳侵古道，晴翠接荒城。",
          title: "赋得古原草送别",
          author: "白居易",
          dynasty: "唐"
        }
      ];
      const randomFb = offlinePoems[Math.floor(Math.random() * offlinePoems.length)];
      textEl.innerText = randomFb.quote;
      if (infoEl) {
        const titleStr = randomFb.title ? ` · 《${randomFb.title}》` : "";
        infoEl.innerText = `[${randomFb.dynasty}] ${randomFb.author}${titleStr}`;
      }
    }
  };

  const copyAction = () => {
    navigator.clipboard.writeText(textEl.innerText).then(() => {
      showToast("诗句已复制到剪贴板", "success");
      textEl.style.transform = "scale(0.98)";
      setTimeout(() => { textEl.style.transform = "scale(1)"; }, 100);
    }).catch(() => {
      showToast("复制失败，请手动选取复制", "error");
    });
  };

  const playAction = (e) => {
    e.stopPropagation();
    if (!currentAudioUrl) return;

    const icon = playBtn.querySelector("i");
    if (!poetryAudio) {
      poetryAudio = new Audio(currentAudioUrl);
      poetryAudio.addEventListener("ended", () => {
        if (icon) icon.className = "fa-solid fa-play";
      });
      poetryAudio.addEventListener("pause", () => {
        if (icon) icon.className = "fa-solid fa-play";
      });
      poetryAudio.addEventListener("play", () => {
        if (icon) icon.className = "fa-solid fa-pause";
      });
    }

    if (poetryAudio.paused) {
      poetryAudio.play().catch((err) => {
        console.error("Audio play failed:", err);
        showToast("音频播放失败", "error");
      });
    } else {
      poetryAudio.pause();
    }
  };

  // 绑定事件
  textEl.addEventListener("click", copyAction);
  playBtn?.addEventListener("click", playAction);

  // 初始化首个诗词
  refreshAction();
}

// =====================================================================
// 🎬 工作流下拉填充（仅默认工作流选择，列表 UI 已移除）
// =====================================================================
