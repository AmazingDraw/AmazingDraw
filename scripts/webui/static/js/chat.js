/* chat.js — 工作台气泡、直投 / 精选。抽卡对话已退役。 */

async function loadChatHistory(cardId, _sessionId = null, silent = false) {
  const body = document.getElementById("chat-body");
  if (!body) return;

  const token = ++state.historyLoadToken;
  if (!silent) {
    body.classList.remove("fade-in-transition");
    body.innerHTML = "";
    void body.offsetWidth;
    body.classList.add("fade-in-transition");
  }

  const url = `/api/chat/history?card_id=${encodeURIComponent(cardId || "")}`;

  try {
    const res = await fetch(url);
    if (token !== state.historyLoadToken) return;
    if (cardId && state.activeCardId && cardId !== state.activeCardId) return;

    const data = await res.json();
    if (token !== state.historyLoadToken) return;

    const messages = data.messages || [];
    if (silent) {
      const liveCount = body.querySelectorAll(".chat-message").length;
      if (liveCount > 0 && messages.length <= liveCount) return;
      if (liveCount === 0 && messages.length === 0) return;
      body.innerHTML = "";
    }

    let renderMsgIndex = -1;
    for (let i = messages.length - 1; i >= 0; i--) {
      const content = messages[i].content || "";
      if (messages[i].role !== "user" && (content.includes("渲染") || content.includes("出图") || content.includes("提交") || content.includes("更新视图") || content.includes("指令执行成功"))) {
        renderMsgIndex = i;
        break;
      }
    }

    let imageAppended = false;
    messages.forEach((m, idx) => {
      if (token !== state.historyLoadToken) return;
      appendChatMessage(m.role === "user" ? "user" : "ai", m.content, { persist: false, msgIndex: idx });

      if (idx === renderMsgIndex && state.activeCardData && state.activeCardData.card_id === cardId && state.activeCardData.render_image) {
        appendChatImageMessage(state.activeCardData.image_url || `/images/${state.activeCardData.render_image}`, "");
        imageAppended = true;
      }
    });

    if (!imageAppended && state.activeCardData && state.activeCardData.card_id === cardId && state.activeCardData.render_image) {
      if (token === state.historyLoadToken) {
        appendChatImageMessage(state.activeCardData.image_url || `/images/${state.activeCardData.render_image}`, "");
      }
    }
  } catch (err) {
    // 保持静默
  }
}

function setLoadingState(loading) {
  const sendBtn = document.getElementById("btn-chat-send");
  const stopBtn = document.getElementById("btn-chat-stop");
  const input = document.getElementById("chat-input");
  if (!input) return;

  if (loading) {
    if (sendBtn) sendBtn.classList.add("is-hidden");
    if (stopBtn) stopBtn.classList.remove("is-hidden");
  } else {
    if (stopBtn) stopBtn.classList.add("is-hidden");
    if (sendBtn) sendBtn.classList.remove("is-hidden");
    input.disabled = false;
    input.focus();
  }
}

function initChat() {
  const sendBtn = document.getElementById("btn-chat-send");
  const stopBtn = document.getElementById("btn-chat-stop");
  const input = document.getElementById("chat-input");
  if (!input) return;

  input.addEventListener("input", function() {
    this.style.height = "auto";
    const newHeight = this.scrollHeight;
    this.style.height = newHeight + "px";
    this.style.overflowY = newHeight >= 200 ? "auto" : "hidden";
  });

  if (stopBtn) {
    stopBtn.addEventListener("click", () => {
      showToast("工作台已取消 AI 对话，无需停止", "info");
    });
  }

  const submitDirect = async () => {
    const prompt = input.value.trim();
    if (!prompt) {
      showToast("请输入完整英文 prompt 再直投", "warning");
      input.focus();
      return;
    }
    await handleDirectSubmitFlow(prompt);
  };

  if (sendBtn) {
    sendBtn.addEventListener("click", submitDirect);
  }
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submitDirect();
    }
  });
}

function applyEditorialStyles(html) {
  return html;
}

function visibleChatText(text) {
  let clean = String(text || "");
  clean = clean.replace(/<(think|thinking)>[\s\S]*?<\/\1>/g, "");
  clean = clean.replace(/<(think|thinking)>[\s\S]*?$/g, "");
  return clean.trim();
}

function renderAiMessage(text) {
  const cleanTextNoThink = visibleChatText(text);
  const md = typeof markdownForChat === "function" ? markdownForChat() : null;
  const mdHtml = md ? md.parse(cleanTextNoThink) : escapeHtml(cleanTextNoThink).replace(/\n/g, "<br>");
  return applyEditorialStyles(mdHtml);
}

function renderUserMessage(text) {
  const escaped = escapeHtml(String(text || ""));
  const inlined = escaped.replace(
    /`([^`\n]+)`|\*\*([^*\n]+)\*\*/g,
    (_m, code, bold) => (code !== undefined ? `<code>${code}</code>` : `<strong>${bold}</strong>`)
  );
  return inlined.replace(/\n/g, "<br>");
}

function isCardsChatMode() {
  const mode = normalizeChatMode(state.settings && state.settings.chat_mode);
  return mode === "cards" || document.documentElement.classList.contains("cards-mode-active");
}

function appendChatMessage(sender, text, options = {}) {
  const body = document.getElementById("chat-body");
  if (!body) return null;

  let msg;
  const isAi = sender === "ai" || sender === "assistant";
  const showAvatar = !(isAi && isCardsChatMode());
  const avatarIcon = isAi ? "fa-robot" : "fa-user";
  const avatarHtml = showAvatar
    ? `<div class="msg-avatar"><i class="fa-solid ${avatarIcon}"></i></div>`
    : "";
  const formattedTime = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  let htmlContent = isAi ? renderAiMessage(text) : renderUserMessage(text);

  if (options.msgId) {
    msg = document.getElementById(options.msgId);
  }

  if (msg) {
    const bubble = msg.querySelector(".msg-bubble");
    if (bubble) bubble.innerHTML = htmlContent;
  } else {
    msg = document.createElement("div");
    msg.className = `chat-message ${isAi ? "ai" : "user"}`;
    if (options.msgId) msg.id = options.msgId;
    msg.innerHTML = `
      ${avatarHtml}
      <div>
        <div class="msg-bubble">${htmlContent}</div>
        <div class="msg-time">${formattedTime}</div>
      </div>
    `;
    body.appendChild(msg);
  }

  body.scrollTop = body.scrollHeight;
  return msg;
}

function appendChatImageMessage(imageUrl, caption = "") {
  const body = document.getElementById("chat-body");
  if (!body) return;

  const formattedTime = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const msg = document.createElement("div");
  msg.className = "chat-message ai";

  const avatarHtml = isCardsChatMode()
    ? ""
    : `<div class="msg-avatar"><i class="fa-solid fa-robot"></i></div>`;
  msg.innerHTML = `
    ${avatarHtml}
    <div style="flex: 1; display: flex; flex-direction: column; align-items: center; min-width: 0; width: 100%;">
      <div class="msg-bubble chat-image-bubble" style="padding: 8px; background: var(--bg-elevated); max-width: 100%; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.15); width: fit-content; box-sizing: border-box;">
        <div style="border-radius: 8px; overflow: hidden; margin-bottom: ${caption ? "6px" : "0"}; display: flex; justify-content: center; align-items: center; max-width: 100%;">
          <img src="${imageUrl}" style="max-width: 100%; max-height: 70vh; width: auto; height: auto; display: block; object-fit: contain;" alt="渲染图">
        </div>
        ${caption ? `<div style="font-size: 0.72rem; color: var(--text-muted); line-height: 1.4; padding: 0 4px; text-align: center;">${escapeHtml(caption)}</div>` : ""}
      </div>
      <div class="msg-time" style="margin-top: 4px; text-align: center;">${formattedTime}</div>
    </div>
  `;

  const img = msg.querySelector(".chat-image-bubble img");
  if (img) {
    img.onload = () => {
      img.classList.add("loaded");
      body.scrollTop = body.scrollHeight;
    };
    img.onerror = () => {
      const bubble = msg.querySelector(".chat-image-bubble");
      if (bubble) {
        bubble.innerHTML = `
          <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 20px 24px; color: var(--text-muted); font-family: var(--font-sans);">
            <i class="fa-regular fa-image" style="font-size: 2rem; margin-bottom: 8px; opacity: 0.5;"></i>
            <span style="font-size: 0.75rem; font-weight: 500; opacity: 0.75;">图片已清理或不存在</span>
          </div>
        `;
        bubble.style.width = "220px";
        bubble.style.maxWidth = "100%";
        bubble.style.background = "var(--bg-secondary)";
        bubble.style.border = "1px dashed var(--border-soft)";
        bubble.style.boxShadow = "none";
      }
      body.scrollTop = body.scrollHeight;
    };
    if (img.complete) {
      if (img.naturalWidth === 0) img.onerror();
      else img.classList.add("loaded");
    }
  }

  body.appendChild(msg);
  body.scrollTop = body.scrollHeight;
}

function appendChatThinking() {
  const body = document.getElementById("chat-body");
  if (!body) return "";
  const id = "thinking-" + new Date().getTime();
  const msg = document.createElement("div");
  msg.className = "chat-message ai thinking-bubble-active";
  msg.id = id;

  const thinkingAvatar = isCardsChatMode()
    ? ""
    : `<div class="msg-avatar"><i class="fa-solid fa-clapperboard"></i></div>`;
  msg.innerHTML = `
    ${thinkingAvatar}
    <div>
      <div class="msg-bubble thinking-glow-bubble" style="padding: 8px 12px; background: var(--bg-elevated); border-radius: 12px; display: inline-flex; align-items: center; justify-content: center; height: 26px; box-shadow: 0 4px 16px rgba(0,0,0,0.15); border: 1px solid rgba(255,255,255,0.08); position: relative; overflow: hidden;">
        <div class="thinking-wave-loader">
          <span></span><span></span><span></span><span></span><span></span>
        </div>
      </div>
    </div>
  `;
  body.appendChild(msg);
  body.scrollTop = body.scrollHeight;
  return id;
}

function removeChatThinking(id) {
  const el = document.getElementById(id);
  if (el && el.parentNode) el.parentNode.removeChild(el);
}

function initDirectMode() {
  const btnDirectToggle = document.getElementById("btn-chat-direct-toggle");
  const btnFeatured = document.getElementById("btn-chat-featured");
  const chatInput = document.getElementById("chat-input");

  if (btnDirectToggle) {
    btnDirectToggle.addEventListener("click", async () => {
      const prompt = chatInput ? chatInput.value.trim() : "";
      if (!prompt) {
        showToast("请输入完整英文 prompt 再直投", "warning");
        if (chatInput) chatInput.focus();
        return;
      }
      await handleDirectSubmitFlow(prompt);
    });
  }

  if (btnFeatured) {
    btnFeatured.addEventListener("click", async () => {
      await handleFeaturedSubmitFlow();
    });
  }
}

function appendGuidedChatError(markdownText, actions) {
  const msg = appendChatMessage("ai", markdownText, { persist: false });
  if (!msg) return null;
  attachGuidedErrorActions(msg, actions);
  return msg;
}

function attachGuidedErrorActions(msg, actions) {
  if (!msg || !Array.isArray(actions) || !actions.length) return;
  const existing = msg.querySelector(".guided-error-actions");
  if (existing) existing.remove();
  const host = msg.querySelector(".msg-bubble")?.parentElement || msg;
  const bar = document.createElement("div");
  bar.className = "guided-error-actions";
  actions.forEach((action) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "guided-error-btn";
    btn.textContent = action.label || "去配置";
    btn.addEventListener("click", () => {
      if (action.view && typeof switchView === "function") {
        switchView(action.view);
      }
      if (action.focus) {
        setTimeout(() => {
          const form = document.getElementById("form-settings-page");
          let el = form && form.elements ? form.elements[action.focus] : null;
          if (!el) el = document.querySelector(`[name="${action.focus}"]`);
          if (el && typeof el.focus === "function") {
            el.focus();
            if (typeof el.scrollIntoView === "function") {
              el.scrollIntoView({ behavior: "smooth", block: "center" });
            }
          }
        }, 160);
      }
    });
    bar.appendChild(btn);
  });
  host.appendChild(bar);
  const body = document.getElementById("chat-body");
  if (body) body.scrollTop = body.scrollHeight;
}

function formatFeaturedFailureDetail(detail) {
  const raw = String(detail || "未知错误");
  const isVault = /找不到\s*Obsidian\s*灵感库|灵感库目录|obsidian_vault_dir|Obsidian/i.test(raw);
  const isEmptyMd = /未找到任何\s*\.md|没有可用的\s*\.md|\.md\s*文件/i.test(raw);
  if (isVault || isEmptyMd) {
    return {
      text: `❌ **精选失败**\n\n${raw}\n\n请在「配置」中把 \`obsidian_vault_dir\` 设为 **Vault 根目录**（不要填「灵感库」本身），并确保其中有 \`灵感库/*.md\`。`,
      actions: [{ label: "去配置 Obsidian 路径", view: "settings", focus: "obsidian_vault_dir" }],
    };
  }
  return {
    text: `❌ **精选失败**\n\n${raw}`,
    actions: [],
  };
}

async function handleFeaturedSubmitFlow() {
  appendChatMessage("user", "🎲 精选模式：随机灵感库入队", { persist: false });
  const thinkingId = appendChatThinking();
  setLoadingState(true);
  try {
    const res = await fetch("/api/featured", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({})
    });
    const data = await res.json().catch(() => ({}));
    removeChatThinking(thinkingId);
    setLoadingState(false);
    if (!res.ok) {
      const guided = formatFeaturedFailureDetail(data.detail || res.statusText);
      appendGuidedChatError(guided.text, guided.actions);
      return;
    }
    if (data.card_id) {
      appendChatMessage("ai", `🎲 精选卡片已创建并提交渲染！\n卡片ID: \`${data.card_id}\``, { persist: false });
      showToast("精选已入队", "success");
      await loadCards();
      selectCard(data.card_id);
    } else {
      const guided = formatFeaturedFailureDetail(data.detail || "未知错误");
      appendGuidedChatError(guided.text, guided.actions);
    }
  } catch (err) {
    removeChatThinking(thinkingId);
    setLoadingState(false);
    appendGuidedChatError(`❌ 请求失败: ${err.message}`, []);
  }
}

async function handleDirectSubmitFlow(prompt) {
  appendChatMessage("user", prompt, { persist: false });
  const chatInput = document.getElementById("chat-input");
  if (chatInput) {
    chatInput.value = "";
    chatInput.style.height = "auto";
    chatInput.style.overflowY = "hidden";
  }

  const thinkingId = appendChatThinking();
  setLoadingState(true);

  try {
    const res = await fetch("/api/direct/submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt: prompt,
        ...getPresetSize("vertical")
      })
    });
    const data = await res.json();
    removeChatThinking(thinkingId);
    setLoadingState(false);

    if (data.card_id) {
      appendChatMessage("ai", `🚀 直投卡片已创建并提交渲染队列！\n卡片ID: \`${data.card_id}\``, { persist: false });
      showToast("已成功提交直投卡片渲染", "success");
      await loadCards();
      selectCard(data.card_id);
    } else {
      appendChatMessage("ai", `❌ 直投提交失败: ${data.detail || "未知错误"}`, { persist: false });
    }
  } catch (err) {
    removeChatThinking(thinkingId);
    setLoadingState(false);
    appendChatMessage("ai", `❌ 请求失败: ${err.message}`, { persist: false });
  }
}
