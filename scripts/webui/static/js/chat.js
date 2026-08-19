/* chat.js — 对话渲染、发送流程、会话与抽卡交接
   由 app.js 拆分而来；加载顺序见 index.html，core.js 必须最先。 */

/* 流式期间该不该拦下这次历史加载。
   只需保护「正在打字的那个会话」的气泡：后台静默重载一律拦，
   主动切到别的会话必须放行，否则侧栏看着能点、消息区却纹丝不动。 */
function shouldBlockHistoryLoad(sessionId, silent, isDraw) {
  if (isDraw) {
    return !!(
      silent
      && sessionId
      && state.streamingTurns
      && state.streamingTurns.has(sessionId)
    );
  }
  if (!state.isChatBusy) return false;
  if (silent) return true;
  return true;                           // 卡片模式没有会话维度，维持原保护
}

/* 在途这一轮尚未落盘（后端是流走完才写历史），从磁盘重画会漏掉它。
   切回正在流式的会话时，把用户提问与已收到的回复补回界面。 */
function restoreStreamingTurn(sessionId, isDraw) {
  if (!isDraw || !state.streamingTurns) return;
  const turn = state.streamingTurns.get(sessionId);
  if (!turn) return;
  if (turn.userText) appendChatMessage("user", turn.userText, { persist: false });
  if (turn.replyText) appendChatMessage("ai", turn.replyText, { msgId: turn.msgId, persist: false });
}

async function appendRecoveredOperationNotice(sessionId, historyToken) {
  if (!sessionId) return;
  try {
    const res = await fetch(
      `/api/chat/operations?session_id=${encodeURIComponent(sessionId)}`,
    );
    if (!res.ok || historyToken !== state.historyLoadToken) return;
    const data = await res.json();
    if (historyToken !== state.historyLoadToken) return;
    if (sessionId !== state.activeSessionId) return;
    const recovered = (data.operations || []).filter(
      item => item.recovered && item.state === "unknown_remote",
    );
    if (!recovered.length) return;
    const body = document.getElementById("chat-body");
    if (!body || body.querySelector(".operation-recovery-notice")) return;
    const latest = recovered[recovered.length - 1];
    const shortId = String(latest.operation_id || "").slice(0, 8);
    const suffix = recovered.length > 1 ? `（共 ${recovered.length} 个未决操作）` : "";
    const notice = appendChatMessage(
      "ai",
      `⚠️ 上次运行在 WebUI 重启时中断，远端状态未知${suffix}。系统没有自动重放；你可以重新发送指令。${shortId ? `\n\n操作：\`${shortId}\`` : ""}`,
      { persist: false },
    );
    if (notice) notice.classList.add("operation-recovery-notice");
  } catch (err) {
    // 恢复提示不应影响正常历史加载。
  }
}

async function loadChatHistory(cardId, sessionId = null, silent = false) {
  const body = document.getElementById("chat-body");
  if (!body) return;

  const token = ++state.historyLoadToken;
  const isDraw = state.settings.chat_mode === "draw";

  if (shouldBlockHistoryLoad(sessionId, silent, isDraw)) return;

  // 交接锁定：只允许加载目标抽卡会话；未就绪时直接放弃
  if (state.sessionUiLock && isDraw) {
    const allowed = state.pendingSessionId || state.activeSessionId;
    if (!sessionId || !allowed || sessionId !== allowed) return;
  }

  // 非 silent 才清屏；silent 延后到确认仍是当前请求再清，避免旧请求抹掉新消息
  if (!silent) {
    body.classList.remove("fade-in-transition");
    body.innerHTML = "";
    void body.offsetWidth;
    body.classList.add("fade-in-transition");
  }

  const url = isDraw && sessionId
    ? `/api/chat/history?session_id=${encodeURIComponent(sessionId)}&chat_mode=draw`
    : `/api/chat/history?card_id=${encodeURIComponent(cardId || "")}`;

  try {
    const res = await fetch(url);
    if (token !== state.historyLoadToken) return;
    if (shouldBlockHistoryLoad(sessionId, silent, isDraw)) return;
    if (isDraw) {
      if (sessionId && state.activeSessionId && sessionId !== state.activeSessionId) return;
      if (state.sessionUiLock) {
        const allowed = state.pendingSessionId || state.activeSessionId;
        if (!sessionId || !allowed || sessionId !== allowed) return;
      }
    } else if (cardId && state.activeCardId && cardId !== state.activeCardId && state.settings.chat_mode !== "draw") {
      return;
    }

    const data = await res.json();
    if (token !== state.historyLoadToken) return;
    if (shouldBlockHistoryLoad(sessionId, silent, isDraw)) return;

    const messages = data.messages || [];
    // silent：只在「磁盘比 DOM 更新」时整页替换，避免流式结束后同内容闪一下
    if (silent) {
      const liveCount = body.querySelectorAll(".chat-message").length;
      // DOM 已有气泡且磁盘没有更多内容：保留 DOM（防闪）
      if (liveCount > 0 && messages.length <= liveCount) return;
      // DOM 为空且磁盘也为空：无事可做
      if (liveCount === 0 && messages.length === 0) return;
      body.innerHTML = "";
    }

    let renderMsgIndex = -1;
    if (!isDraw) {
      for (let i = messages.length - 1; i >= 0; i--) {
        const content = messages[i].content || "";
        if (messages[i].role !== "user" && (content.includes("渲染") || content.includes("出图") || content.includes("提交") || content.includes("更新视图") || content.includes("指令执行成功"))) {
          renderMsgIndex = i;
          break;
        }
      }
    }

    let imageAppended = false;
    messages.forEach((m, idx) => {
      if (token !== state.historyLoadToken) return;
      appendChatMessage(m.role === "user" ? "user" : "ai", m.content, { persist: false, msgIndex: idx });

      if (!isDraw && idx === renderMsgIndex && state.activeCardData && state.activeCardData.card_id === cardId && state.activeCardData.render_image) {
        appendChatImageMessage(state.activeCardData.image_url || `/images/${state.activeCardData.render_image}`, "");
        imageAppended = true;
      }
    });

    if (!isDraw && !imageAppended && state.activeCardData && state.activeCardData.card_id === cardId && state.activeCardData.render_image) {
      if (token === state.historyLoadToken) {
        appendChatImageMessage(state.activeCardData.image_url || `/images/${state.activeCardData.render_image}`, "");
      }
    }

    if (token === state.historyLoadToken) restoreStreamingTurn(sessionId, isDraw);
    if (isDraw && sessionId && token === state.historyLoadToken) {
      await appendRecoveredOperationNotice(sessionId, token);
    }
  } catch (err) {
    // 保持静默
  }
}

async function newChatWindow() {
  if (state.settings.chat_mode === "draw") {
    await newSession();
    return;
  }
  const cardId = state.activeCardId;
  try {
    await fetch("/api/chat/new", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ card_id: cardId })
    });
    await loadChatHistory(cardId);
    appendChatMessage("ai", "✅ 已新建当前对话窗口。下一次 AI 对话会重新注入完整规则。", { persist: false });
    showToast("已新建对话窗口", "success");
  } catch (err) {
    showToast("新建对话窗口失败", "error");
  }
}

function setLoadingState(loading) {
  const sendBtn = document.getElementById("btn-chat-send");
  const stopBtn = document.getElementById("btn-chat-stop");
  const input = document.getElementById("chat-input");
  if (!sendBtn || !stopBtn || !input) return;

  if (loading) {
    sendBtn.classList.add("is-hidden");
    stopBtn.classList.remove("is-hidden");
  } else {
    stopBtn.classList.add("is-hidden");
    sendBtn.classList.remove("is-hidden");
    input.disabled = false;
    input.focus();
  }
}

function createChatOperationId() {
  if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  return `webui-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/** Freeze every field that may affect execution at enqueue time. */
function freezeChatQueueItem(payload = {}) {
  return Object.freeze({
    operation_id: String(payload.operation_id || createChatOperationId()),
    session_id: payload.session_id == null ? null : String(payload.session_id),
    chat_mode: String(payload.chat_mode || "").toLowerCase() === "draw" ? "draw" : "cards",
    card_id: payload.card_id == null ? null : String(payload.card_id),
    message: String(payload.message ?? payload.text ?? "").trim(),
    include_context: !!(payload.include_context ?? payload.include_card_context),
    confirm: payload.confirm === true,
  });
}

/** Minimal per-session FIFO store, kept pure for the Node source contract test. */
function createSessionQueueStore() {
  const queues = new Map();
  return {
    enqueue(item) {
      const key = item.session_id || `cards:${item.card_id || "home"}`;
      if (!queues.has(key)) queues.set(key, []);
      queues.get(key).push(item);
      return key;
    },
    dequeue(key) {
      const queue = queues.get(key);
      if (!queue || queue.length === 0) return null;
      const item = queue.shift();
      if (queue.length === 0) queues.delete(key);
      return item;
    },
    pending(key) {
      const queue = queues.get(key);
      return queue ? queue.length : 0;
    },
    sessionIds() {
      return queues.keys();
    },
  };
}

const chatSessionQueues = createSessionQueueStore();
const activeChatOperations = new Map();

function activeChatQueueKey() {
  const mode = normalizeChatMode(state.settings && state.settings.chat_mode);
  return mode === "draw"
    ? state.activeSessionId
    : `cards:${state.activeCardId || "home"}`;
}

function syncChatLoadingState() {
  state.isChatBusy = activeChatOperations.size > 0;
  const key = activeChatQueueKey();
  setLoadingState(!!key && activeChatOperations.has(key));
}

async function requestOperationCancel(operationId) {
  const res = await fetch(
    `/api/chat/operations/${encodeURIComponent(operationId)}/cancel`,
    { method: "POST" },
  );
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail && (data.detail.message || data.detail.code);
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return data;
}

/** Stop only the operation visible in the active session. */
async function cancelActiveChatOperation() {
  const key = activeChatQueueKey();
  const active = key ? activeChatOperations.get(key) : null;
  if (!active) return false;
  try {
    const result = await requestOperationCancel(active.item.operation_id);
    const terminalState = result.operation && result.operation.terminal
      ? result.operation.state
      : null;
    if (result.cancelled !== true) {
      if (terminalState) {
        showToast(`操作已结束（${terminalState}），无需取消`, "warning");
        return false;
      }
      throw new Error("后端未确认取消");
    }
    active.controller.abort();
    showToast("当前会话操作已取消", "success");
    return true;
  } catch (err) {
    showToast(`停止失败：${err.message || err}`, "error");
    return false;
  }
}

// =====================================================================
// 💬 Centered Chat Dialog & API Driver
// =====================================================================
// 全局发送队列入口：卡片交接 / 抽卡普通发送共用，避免并发打同一 OpenClaw session
let enqueueDrawChatMessage = null;
let stopDrawChatQueue = null;

function initChat() {
  const sendBtn = document.getElementById("btn-chat-send");
  const stopBtn = document.getElementById("btn-chat-stop");
  const input = document.getElementById("chat-input");

  if (!sendBtn || !input) return;

  // 监听 textarea 高度自适应与动态滚动条隐藏
  input.addEventListener("input", function() {
    this.style.height = "auto";
    const newHeight = this.scrollHeight;
    this.style.height = newHeight + "px";
    this.style.overflowY = newHeight >= 200 ? "auto" : "hidden";
  });
  // 停止按钮只取消当前会话的精确 operation；其它会话 FIFO 保持不动。
  if (stopBtn) stopBtn.addEventListener("click", cancelActiveChatOperation);
  stopDrawChatQueue = cancelActiveChatOperation;

  const isGenerateCommand = (text) => {
    const compact = String(text || "").trim().replace(/\s+/g, "");
    if (["1", "画", "生成", "开始画", "出图", "渲染"].includes(compact)) return true;
    return /^(开始)?(生成|渲染|出图|画出来)/.test(compact);
  };

  const processQueue = async (queueKey) => {
    if (!queueKey || activeChatOperations.has(queueKey)) return;
    const item = chatSessionQueues.dequeue(queueKey);
    if (!item) {
      syncChatLoadingState();
      return;
    }

    const text = item.message;
    const controller = new AbortController();
    let aiBubbleCreated = false;
    const msgId = `ai-reply-${item.operation_id}`;
    let replyText = "";
    let metaData = null;
    let cancelledByServer = false;
    let unknownRemote = false;
    let recoveredTerminal = false;

    const showUnknownRemote = (detail = "") => {
      if (unknownRemote) return;
      unknownRemote = true;
      const warning = "⚠️ **连接已中断，远端执行结果未知。**\n\n系统没有自动重放；请先确认卡片或队列状态，再决定是否重试。";
      replyText = replyText ? `${replyText}\n\n${warning}` : warning;
      if (detail) replyText += `\n\n${detail}`;
      turn.replyText = replyText;
      if (streamViewVisible()) {
        if (!aiBubbleCreated) {
          if (thinkingId) removeChatThinking(thinkingId);
          aiBubbleCreated = true;
        }
        appendChatMessage("ai", replyText, { msgId, persist: false });
      }
    };

    const streamViewVisible = () => item.chat_mode !== "draw"
      || !item.session_id
      || state.activeSessionId === item.session_id;
    const thinkingId = streamViewVisible() ? appendChatThinking() : null;
    const turn = { userText: text, replyText: "", msgId };
    if (item.session_id) state.streamingTurns.set(item.session_id, turn);
    activeChatOperations.set(queueKey, { item, controller });
    syncChatLoadingState();

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          operation_id: item.operation_id,
          session_id: item.session_id,
          chat_mode: item.chat_mode,
          card_id: item.card_id,
          message: item.message,
          include_context: item.include_context,
          confirm: item.confirm
        }),
        signal: controller.signal
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop(); // keep partial last line

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed) continue;
          if (trimmed.startsWith("data: ")) {
            const dataStr = trimmed.slice(6);
            try {
              const data = JSON.parse(dataStr);
              if (data.type === "text") {
                replyText += data.chunk;
                turn.replyText = replyText;
                if (streamViewVisible()) {
                  if (!aiBubbleCreated) {
                    if (thinkingId) removeChatThinking(thinkingId);
                    aiBubbleCreated = true;
                  }
                  appendChatMessage("ai", replyText, { msgId, persist: false });
                }
              } else if (data.type === "meta") {
                metaData = data;
              } else if (data.type === "error") {
                replyText += `\n\n⚠️ **系统错误**:\n${data.error}`;
                turn.replyText = replyText;
                if (streamViewVisible()) {
                  if (!aiBubbleCreated) {
                    if (thinkingId) removeChatThinking(thinkingId);
                    aiBubbleCreated = true;
                  }
                  appendChatMessage("ai", replyText, { msgId, persist: false });
                }
              } else if (data.type === "cancelled") {
                cancelledByServer = true;
                const cancelText = "⏹️ 操作已取消。";
                replyText = replyText ? `${replyText}\n\n${cancelText}` : cancelText;
                turn.replyText = replyText;
                if (streamViewVisible()) {
                  if (!aiBubbleCreated) {
                    if (thinkingId) removeChatThinking(thinkingId);
                    aiBubbleCreated = true;
                  }
                  appendChatMessage("ai", replyText, { msgId, persist: false });
                }
              } else if (data.type === "unknown_remote") {
                showUnknownRemote(data.error || "");
              } else if (data.type === "operation") {
                const active = activeChatOperations.get(queueKey);
                if (active) active.state = data.state;
                if (data.state === "unknown_remote") {
                  showUnknownRemote(data.error || "");
                } else if (data.recovered && data.terminal) {
                  recoveredTerminal = true;
                }
              }
            } catch (e) {
              console.error("Failed to parse SSE line:", line, e);
            }
          }
        }
      }

      if (!aiBubbleCreated && streamViewVisible()) {
        if (thinkingId) removeChatThinking(thinkingId);
        if (recoveredTerminal) {
          if (item.session_id) state.streamingTurns.delete(item.session_id);
          if (item.chat_mode === "draw" && item.session_id) {
            await loadChatHistory(null, item.session_id, false);
          } else {
            await loadChatHistory(item.card_id, null, false);
          }
        } else if (metaData) {
          appendChatMessage("ai", "✅ 指令执行成功，已更新视图。", { persist: false });
        } else if (cancelledByServer) {
          appendChatMessage("ai", "⏹️ 操作已取消。", { persist: false });
        } else if (unknownRemote) {
          appendChatMessage("ai", "⚠️ 上次运行的远端状态未知，系统没有自动重放。", { persist: false });
        } else {
          appendChatMessage("ai", "❌ AI 返回为空：没有执行任何可见回复。请重试，或在界面重置当前对话上下文。", { persist: false });
        }
      }

      if (metaData) {
        // 只有主人还停在这轮所属会话时才回写选中态，否则会把他刚切过去的会话弹回来
        if (state.settings.chat_mode === "draw" && metaData.session_id && streamViewVisible()) {
          state.activeSessionId = metaData.session_id;
          localStorage.setItem("active_session_id", metaData.session_id);
        }
        if (metaData.refresh && streamViewVisible()) {
          if (metaData.action === "create" && metaData.card_id) {
            showToast("已创建新卡片", "success");
            await loadCards();
            selectCard(metaData.card_id);
          } else if (metaData.action === "patch") {
            // OpenClaw 只提供整轮文本流，无法给出 patch 的可靠实时完成点。
            // 静默刷新即可，避免在整轮结束后补发一个时机错误的成功 Toast。
            if (item.card_id) selectCard(item.card_id);
            loadCards();
          } else if (metaData.action === "submit") {
            // 入队结果由 Agent 正文/队列状态呈现；此处 meta 只是整轮结束后的快照。
            if (item.card_id) selectCard(item.card_id);
            loadCards();
          } else {
            if (item.card_id) selectCard(item.card_id);
            loadCards();
          }
        } else if (metaData.refresh) {
          loadCards();
        }
      }
    } catch (err) {
      const stopped = err.name === "AbortError";
      const tail = stopped ? "\n\n⏹️ [已停止]" : `\n\n❌ [连接中断: ${err.message || err}]`;
      const solo = stopped
        ? "⏹️ 已停止响应。"
        : `❌ 对话异常: ${err.message || err}。请确认 WebUI 后端服务正常。`;
      if (aiBubbleCreated) replyText += tail;
      turn.replyText = replyText;
      if (streamViewVisible()) {
        if (thinkingId) removeChatThinking(thinkingId);
        appendChatMessage("ai", aiBubbleCreated ? replyText : solo,
          aiBubbleCreated ? { msgId, persist: false } : { persist: false });
      }
    } finally {
      activeChatOperations.delete(queueKey);
      if (item.session_id) state.streamingTurns.delete(item.session_id);
      syncChatLoadingState();
      // 主人已经切走：这轮在后台默默跑完，给个提示免得他以为回复丢了
      if (!streamViewVisible() && replyText) {
        showToast("上一个会话的回复已完成", "success");
      }
      // 先刷侧栏（不拉历史）
      if (state.settings.chat_mode === "draw") {
        loadSessions({
          preferSessionId: state.pendingSessionId || state.activeSessionId || undefined,
          skipHistory: true,
          skipAutoSelect: !!state.sessionUiLock && !state.pendingSessionId && !state.activeSessionId,
        });
      }
      // 流式结束后：仅当 DOM 被清空（如卡片→抽卡交接竞态）时 silent 恢复；
      // DOM 已有完整气泡则不重载，避免「闪一下再完整出现」
      const sessionForHistory = item.session_id;
      const cardForHistory = item.card_id;
      const modeForHistory = item.chat_mode;
      setTimeout(async () => {
        if (activeChatOperations.has(queueKey)) return;
        if (state.sessionUiLock) return;
        const body = document.getElementById("chat-body");
        const liveCount = body ? body.querySelectorAll(".chat-message").length : 0;
        // 已有可见消息：不重载（防闪）
        if (liveCount > 0) return;
        // DOM 空：尝试从磁盘恢复（交接/误清屏）
        if (modeForHistory === "draw") {
          if (sessionForHistory && sessionForHistory === state.activeSessionId) {
            await loadChatHistory(null, sessionForHistory, true);
          }
        } else if (cardForHistory && cardForHistory === state.activeCardId) {
          await loadChatHistory(cardForHistory, null, true);
        }
      }, 800);
      processQueue(queueKey);
    }
  };

  // 暴露给交接 / 外部：统一走队列，杜绝双路径并发
  enqueueDrawChatMessage = (payload) => {
    const raw = typeof payload === "string" ? { text: payload } : (payload || {});
    const message = String(raw.message ?? raw.text ?? "").trim();
    const chatMode = raw.force_draw === false
      ? normalizeChatMode(raw.chat_mode || state.settings.chat_mode)
      : "draw";
    const item = freezeChatQueueItem({
      operation_id: raw.operation_id,
      session_id: raw.session_id !== undefined
        ? raw.session_id
        : (chatMode === "draw" ? state.activeSessionId : null),
      chat_mode: chatMode,
      card_id: raw.card_id !== undefined ? raw.card_id : state.activeCardId,
      message,
      include_context: raw.include_context ?? raw.include_card_context,
      confirm: raw.confirm !== undefined ? raw.confirm : isGenerateCommand(message),
    });
    if (!item.message) return;
    if (item.chat_mode === "draw" && !item.session_id) {
      showToast("请先选择或新建抽卡会话", "error");
      return;
    }
    const queueKey = chatSessionQueues.enqueue(item);
    processQueue(queueKey);
  };

  const handleSend = async () => {
    const text = String(input.value || "").trim();
    if (!text) return;

    // 卡片页：内部交接 → 抽卡会话 + 可选卡片上下文
    if (state.settings.chat_mode !== "draw") {
      input.value = "";
      input.style.height = "auto";
      input.style.overflowY = "hidden";
      await handoffCardsToDrawChat(text);
      return;
    }

    appendChatMessage("user", text, { persist: false });
    input.value = "";
    input.style.height = "auto"; // 重置输入框高度
    input.style.overflowY = "hidden"; // 重置滚动条

    enqueueDrawChatMessage({
      text,
      session_id: state.activeSessionId,
      chat_mode: "draw",
      card_id: state.activeCardId,
      include_context: false,
      confirm: isGenerateCommand(text),
      force_draw: true,
    });
  };

  sendBtn.addEventListener("click", handleSend);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      if (!e.shiftKey && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        handleSend();
      }
    }
  });
}

function applyEditorialStyles(html) {
  // 已取消杂志风首字放大；保留函数以免调用方改动
  return html;
}

function renderAiMessage(text) {
  // 1. 解析并去重 <tool> 标签
  const toolsMap = new Map();
  const toolRegex = /<tool\s+id="([^"]+)"\s+name="([^"]+)"\s+input="([^"]+)"\s+status="([^"]+)"(?:[^>]*)>([\s\S]*?)<\/tool>/g;
  let match;
  while ((match = toolRegex.exec(text)) !== null) {
    const [fullMatch, id, name, input, status, content] = match;
    toolsMap.set(id, { id, name, input, status, content });
  }

  // 清除所有的 tool 标签和未闭合部分（防止在流式输出中产生渲染杂质）
  let cleanText = text.replace(/<tool\s+id="[^"]+"[^>]*>([\s\S]*?)<\/tool>/g, "");
  cleanText = cleanText.replace(/<tool\s+id="[^"]+"[^>]*>([\s\S]*?)$/g, "");

  // 2. 构建工具执行里程碑 HTML
  let toolsTimelineHtml = "";
  let hasRunningTool = false;

  if (toolsMap.size > 0) {
    let itemsHtml = "";
    for (const tool of toolsMap.values()) {
      const isRunning = tool.status === "running";
      if (isRunning) hasRunningTool = true;

      const iconMap = {
        running: "fa-spinner fa-spin",
        success: "fa-circle-check",
        error: "fa-circle-xmark"
      };
      const statusTextMap = {
        running: "正在执行...",
        success: "已完成",
        error: "执行失败"
      };

      const icon = iconMap[tool.status] || "fa-circle-question";
      const statusText = statusTextMap[tool.status] || tool.status;

      let parsedInput = tool.input;
      try {
        const unescapedInput = decodeHtmlEntities(tool.input);
        const parsedObj = JSON.parse(unescapedInput);
        parsedInput = JSON.stringify(parsedObj, null, 2);
      } catch (e) {}

      // 工具名/状态/参数/输出全部来自 agent，输出更可能夹带它读到的文件内容，
      // 原样拼进 innerHTML 就是注入面，一律转义后再放
      itemsHtml += `
        <div class="timeline-item ${escapeHtml(tool.status)}">
          <div class="timeline-node"><i class="fa-solid ${icon}"></i></div>
          <div class="timeline-header" onclick="const b = this.nextElementSibling; if (b) { b.style.display = b.style.display === 'none' ? 'flex' : 'none'; }">
            <span class="timeline-title">执行工具 <code>${escapeHtml(tool.name)}</code></span>
            <span class="timeline-status-text">${escapeHtml(statusText)}</span>
          </div>
          <div class="timeline-body" style="display: ${isRunning ? 'flex' : 'none'};">
            <div class="input-section">
              <b style="font-size:0.65rem; color:var(--text-muted);">参数 (Input):</b>
              <pre>${escapeHtml(parsedInput)}</pre>
            </div>
            ${tool.content && tool.content.trim() && tool.content !== "正在执行..." ? `
            <div class="output-section">
              <b style="font-size:0.65rem; color:var(--text-muted);">输出 (Output):</b>
              <pre>${escapeHtml(tool.content.trim())}</pre>
            </div>` : ""}
          </div>
        </div>
      `;
    }

    const isCollapsedClass = hasRunningTool ? "" : "collapsed";
    const headerIcon = hasRunningTool ? "fa-spinner fa-spin" : "fa-circle-check";
    const headerTitle = hasRunningTool ? "工具箱正在执行步骤..." : "工具箱执行步骤已完成";

    toolsTimelineHtml = `
      <div class="ai-tools-box ${isCollapsedClass}">
        <div class="ai-tools-header" onclick="this.parentElement.classList.toggle('collapsed'); const body = document.getElementById('chat-body'); if(body) body.scrollTop = body.scrollHeight;">
          <span class="ai-tools-icon"><i class="fa-solid fa-screwdriver-wrench ${headerIcon}"></i></span>
          <span class="ai-tools-title">${headerTitle} (共 ${toolsMap.size} 步)</span>
          <span class="ai-tools-arrow"><i class="fa-solid fa-chevron-down"></i></span>
        </div>
        <div class="ai-tools-content">
          <div class="tools-timeline">
            ${itemsHtml}
          </div>
        </div>
      </div>
    `;
  }

  // 3. 彻底丢弃并洗净所有的思维链思考文本 (包含已闭合与流式未闭合)
  let cleanTextNoThink = cleanText.replace(/<(think|thinking)>[\s\S]*?<\/\1>/g, "");
  cleanTextNoThink = cleanTextNoThink.replace(/<(think|thinking)>[\s\S]*?$/g, "");

  const md = markdownForChat();
  const mdHtml = md ? md.parse(cleanTextNoThink) : escapeHtml(cleanTextNoThink).replace(/\n/g, "<br>");
  const styledMdHtml = applyEditorialStyles(mdHtml);
  return toolsTimelineHtml + styledMdHtml;
}

/* 用户气泡的极简 markdown：只认行内代码与粗斜体。
   不复用 renderAiMessage —— 它会扫 <tool>/<think> 标签、套 AI 专用排版，
   底层 marked 还默认放行原始 HTML，而这里的文本直接来自输入框。
   所以先整体转义再按白名单放行；顺带避免主人打个「#」就被当成标题。 */
function renderUserMessage(text) {
  const escaped = escapeHtml(String(text || ""));
  // 单趟交替匹配，代码优先，免得先替换出的标签又被后一条规则啃一遍。
  // 不支持单星号斜体：那会把「2*3*4」这类算式吃成 2<em>3</em>4，
  // 而 ** 与反引号成对出现时几乎不会是字面量，误伤代价小得多。
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
  // 卡片页：AI 消息不渲染机器人头像（避免刷新后 CSS class 未就绪又闪出来）
  const showAvatar = !(isAi && isCardsChatMode());
  const avatarIcon = isAi ? "fa-robot" : "fa-user";
  const avatarHtml = showAvatar
    ? `<div class="msg-avatar"><i class="fa-solid ${avatarIcon}"></i></div>`
    : "";
  const formattedTime = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  
  let htmlContent = text;
  if (isAi) {
    htmlContent = renderAiMessage(text);
  } else {
    htmlContent = renderUserMessage(text);
  }
  
  if (options.msgId) {
    msg = document.getElementById(options.msgId);
  }
  
  if (msg) {
    const bubble = msg.querySelector(".msg-bubble");
    if (bubble) {
      bubble.innerHTML = htmlContent;
    }
  } else {
    msg = document.createElement("div");
    msg.className = `chat-message ${isAi ? 'ai' : 'user'}`;
    if (options.msgId) {
      msg.id = options.msgId;
    }
    
    const hasIndex = options.msgIndex !== undefined;
    if (hasIndex) {
      msg.setAttribute("data-msg-index", options.msgIndex);
      msg.innerHTML = `
        ${avatarHtml}
        <div style="position: relative; max-width: 100%;">
          <div class="msg-bubble-container">
            <div class="msg-bubble">${htmlContent}</div>
            <button class="btn-delete-msg" title="删除此条消息" onclick="confirmDeleteMessage(${options.msgIndex})">
              <i class="fa-regular fa-trash-can"></i>
            </button>
          </div>
          <div class="msg-time">${formattedTime}</div>
        </div>
      `;
    } else {
      msg.innerHTML = `
        ${avatarHtml}
        <div>
          <div class="msg-bubble">${htmlContent}</div>
          <div class="msg-time">${formattedTime}</div>
        </div>
      `;
    }
    body.appendChild(msg);
  }
  
  body.scrollTop = body.scrollHeight;
  return msg;
}

function appendChatImageMessage(imageUrl, caption = "") {
  const body = document.getElementById("chat-body");
  if (!body) return;
  
  const formattedTime = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const msg = document.createElement("div");
  msg.className = "chat-message ai";
  
  const avatarHtml = isCardsChatMode()
    ? ""
    : `<div class="msg-avatar"><i class="fa-solid fa-robot"></i></div>`;
  msg.innerHTML = `
    ${avatarHtml}
    <div style="flex: 1; display: flex; flex-direction: column; align-items: center; min-width: 0; width: 100%;">
      <div class="msg-bubble chat-image-bubble" style="padding: 8px; background: var(--bg-elevated); max-width: 100%; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.15); width: fit-content; box-sizing: border-box;">
        <div style="border-radius: 8px; overflow: hidden; margin-bottom: ${caption ? '6px' : '0'}; display: flex; justify-content: center; align-items: center; max-width: 100%;">
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
      if (img.naturalWidth === 0) {
        img.onerror();
      } else {
        img.classList.add("loaded");
      }
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
          <span></span>
          <span></span>
          <span></span>
          <span></span>
          <span></span>
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
  if (el) {
    if (el.dataset.intervalId) {
      clearInterval(Number(el.dataset.intervalId));
    }
    if (el.parentNode) {
      el.parentNode.removeChild(el);
    }
  }
}

// =====================================================================
// 🗳️ Modals, Collapsibles, and Queue commands bindings
// =====================================================================
function initDirectMode() {
  // 参数看板折叠开关统一在 initModals 绑定，避免重复监听互相抵消

  // 绑定对话输入框右侧的「直投」与「精选」按钮
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

/** 卡片页发送 → 切换抽卡 + 新会话 + 首条携带卡片上下文 */
/**
 * 建卡后交给 AI 的接手指令。
 * 命令与流程全在 create --help（含常规模式 R0-R6）、输出格式在 doc draw，
 * 这里只指路加交代停在哪；重述一遍只会多出一份会过期的真相。
 */
function buildTakeoverPrompt(cardId, form) {
  const bits = [];
  if (form.person) bits.push(`人物「${form.person}」`);
  if (form.scene) bits.push(`场景「${form.scene}」`);
  const known = bits.length ? `（${bits.join(" · ")}）` : "";
  return [
    `骨架卡 \`${cardId}\` 已建好${known}，创作诉求：${form.user_input}`,
    "直接用这个 card_id 接手，不要重新建卡。",
    "流程与命令查 `card_cli.py create --help`，输出格式查 `card_cli.py doc draw`。",
    "完整输出 present 的 `text_template` 后停下等我指令；我没说「画 / 1 / 61」之前不要 submit。",
  ].join("\n");
}

async function handoffCardsToDrawChat(text) {
  const cardId = state.activeCardId;
  const handoffId = ++state.handoffGen;
  let targetSessionId = null;

  // ① 立刻清屏 + 锁 UI + 作废在途历史，杜绝闪旧会话
  const body = document.getElementById("chat-body");
  if (body) body.innerHTML = "";
  state.sessionUiLock = true;
  state.pendingSessionId = null;
  state.activeSessionId = null;
  localStorage.removeItem("active_session_id");
  state.historyLoadToken++;

  // 侧栏标题先占位，避免模式切换瞬间仍显示旧会话标题
  const titleElem = document.getElementById("chat-active-card-title");
  if (titleElem) {
    titleElem.innerHTML = `🎬 抽卡会话: <strong style="color:var(--text-bright);">卡片交接…</strong>`;
  }

  try {
    state.settings.chat_mode = "draw";
    renderChatModeButtons(); // → loadSessions；锁 + 无 pending 时只刷列表不选旧会话
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(state.settings)
    });
    const data = await res.json();
    if (handoffId !== state.handoffGen) return;
    if (data && data.settings) state.settings = data.settings;
    state.settings.chat_mode = "draw";

    // ② 新建会话并保持锁，直到首条入队且列表对齐
    const newId = await newSession({ silent: true, keepLock: true, placeholderTitle: "卡片交接…" });
    targetSessionId = newId;
    if (handoffId !== state.handoffGen) return;

    // 用户气泡挂在新会话上（newSession 已 skipHistory 清屏）
    appendChatMessage("user", text, { persist: false });
    if (typeof enqueueDrawChatMessage === "function") {
      enqueueDrawChatMessage({
        text,
        session_id: newId,
        chat_mode: "draw",
        include_context: !!cardId,
        card_id: cardId,
        confirm: false,
        force_draw: true,
      });
    } else {
      await sendDrawChatMessage(text, {
        session_id: newId,
        include_context: !!cardId,
        card_id: cardId,
      });
    }

    // 再刷一次侧栏，确保高亮新会话
    if (newId) {
      await loadSessions({ preferSessionId: newId, skipHistory: true });
    }
  } catch (err) {
    if (handoffId === state.handoffGen) {
      showToast(`交接失败: ${err.message || err}`, "error");
      state.sessionUiLock = false;
      state.pendingSessionId = null;
    }
  } finally {
    // ③ 保持锁足够久，覆盖 list/history 竞态；仅本代交接可解锁
    setTimeout(() => {
      if (handoffId !== state.handoffGen) return;
      state.sessionUiLock = false;
      state.pendingSessionId = null;
      // 若仍在流式：等结束后由 processQueue finally 按需恢复
      if (targetSessionId && activeChatOperations.has(targetSessionId)) return;
      // DOM 已有气泡：不重载（防闪）；仅空窗时从磁盘拉回交接消息
      const body = document.getElementById("chat-body");
      const liveCount = body ? body.querySelectorAll(".chat-message").length : 0;
      if (liveCount > 0) return;
      if (state.activeSessionId) {
        loadChatHistory(null, state.activeSessionId, true).catch(() => {});
      }
    }, 3000);
  }
}

/** 抽卡页单条发送后备路径（仅 initChat 未就绪时） */
async function sendDrawChatMessage(text, opts = {}) {
  if (typeof enqueueDrawChatMessage !== "function") {
    throw new Error("chat queue is not initialized");
  }
  enqueueDrawChatMessage({
    text,
    session_id: opts.session_id !== undefined ? opts.session_id : state.activeSessionId,
    chat_mode: "draw",
    include_context: !!(opts.include_context ?? opts.include_card_context),
    card_id: opts.card_id !== undefined ? opts.card_id : state.activeCardId,
    confirm: opts.confirm === true,
    force_draw: true,
  });
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
      appendChatMessage("ai", `❌ 精选失败: ${data.detail || res.statusText}`, { persist: false });
      return;
    }
    if (data.card_id) {
      appendChatMessage("ai", `🎲 精选卡片已创建并提交渲染！\n卡片ID: \`${data.card_id}\``, { persist: false });
      showToast("精选已入队", "success");
      await loadCards();
      selectCard(data.card_id);
    } else {
      appendChatMessage("ai", `❌ 精选失败: ${data.detail || "未知错误"}`, { persist: false });
    }
  } catch (err) {
    removeChatThinking(thinkingId);
    setLoadingState(false);
    appendChatMessage("ai", `❌ 请求失败: ${err.message}`, { persist: false });
  }
}

// 3. 直投拦截流程
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

// =====================================================================
// 💾 Settings Auto-Save Logic (Global Helper)
// =====================================================================
async function loadSessions(opts = {}) {
  try {
    const res = await fetch("/api/chat/sessions");
    const data = await res.json();
    state.sessions = data.sessions || [];

    window.lastSessionIds = state.sessions.map(s => s.session_id);
    window.lastSessionMtimes = {};
    state.sessions.forEach(s => {
      window.lastSessionMtimes[s.session_id] = s.updated_at;
    });

    renderSessionsList(state.sessions);

    if (opts.skipAutoSelect) {
      return state.sessions;
    }

    // 交接/新建中：只允许选中锁定会话，绝不回落到旧会话
    const lockedId = state.pendingSessionId || opts.preferSessionId || state.activeSessionId || null;
    if (state.sessionUiLock) {
      if (lockedId) {
        if (state.sessions.some(s => s.session_id === lockedId)) {
          // 列表有了目标会话：只高亮，默认不拉历史（避免闪旧）
          await selectSession(lockedId, {
            skipHistory: opts.skipHistory !== false,
            placeholderTitle: "卡片交接…",
          });
        } else {
          // 列表尚未出现新会话：保持目标 ID，绝不选 sessions[0]
          state.activeSessionId = lockedId;
          localStorage.setItem("active_session_id", lockedId);
          renderSessionsList(state.sessions);
          if (opts.skipHistory === false) {
            // 仅显式要求历史时才清屏，否则保留交接气泡
            const body = document.getElementById("chat-body");
            if (body && !body.querySelector(".msg-user, .msg-ai, .chat-msg")) {
              body.innerHTML = "";
            }
          }
        }
      }
      // lockedId 尚未就绪：只刷列表，不选任何旧会话
      return state.sessions;
    }

    const targetSessionId = opts.preferSessionId
      || state.activeSessionId
      || localStorage.getItem("active_session_id");
    if (targetSessionId && state.sessions.some(s => s.session_id === targetSessionId)) {
      await selectSession(targetSessionId, { skipHistory: !!opts.skipHistory });
    } else if (targetSessionId && !state.sessions.some(s => s.session_id === targetSessionId)) {
      // 目标尚未进列表：不要回落到第一条旧会话
      state.activeSessionId = targetSessionId;
      localStorage.setItem("active_session_id", targetSessionId);
      renderSessionsList(state.sessions);
    } else if (state.sessions.length > 0) {
      await selectSession(state.sessions[0].session_id, { skipHistory: !!opts.skipHistory });
    } else {
      await selectSession(null, { skipHistory: !!opts.skipHistory });
    }
    return state.sessions;
  } catch (err) {
    showToast("载入会话列表失败", "error");
    return [];
  }
}

function renderSessionsList(sessions) {
  const container = document.getElementById("sidebar-cards-list");
  if (!container) return;
  
  container.innerHTML = "";
  
  const infoContainer = document.getElementById("sidebar-list-info");
  if (infoContainer) {
    infoContainer.innerHTML = `
      <div class="list-summary">
        <span class="summary-label">历史对话</span>
        <span class="summary-count">共 ${sessions.length} 个</span>
      </div>
    `;
  }
  
  if (sessions.length === 0) {
    container.innerHTML = `<p class="placeholder-text">暂无历史对话</p>`;
    return;
  }
  
  sessions.forEach((sess) => {
    const div = document.createElement("div");
    const isActive = sess.session_id === state.activeSessionId;
    div.className = `sidebar-card-item ${isActive ? 'active' : ''}`;
    div.setAttribute("data-session-id", sess.session_id);
    div.addEventListener("click", () => selectSession(sess.session_id));
    
    div.innerHTML = `
      <div class="session-title">
        <i class="fa-regular fa-comment-dots" style="margin-right: 6px; color: var(--color-primary);"></i>
        ${escapeHtml(sess.title) || "未命名会话"}
      </div>
      <div class="card-scene" style="font-size: 0.68rem; margin-top: 4px; opacity: 0.7;">ID: ${sess.session_id.substring(0, 12)}...</div>
      <div class="card-time">${formatCardTime(sess.updated_at)}</div>
      
      <div class="card-action-buttons">
        <button class="card-action-btn btn-delete" title="删除会话"><i class="fa-solid fa-trash-can"></i></button>
      </div>

      <div class="card-delete-confirm-overlay">
        <span>确认删除该对话？</span>
        <button class="confirm-yes">确定</button>
        <button class="confirm-no">取消</button>
      </div>
    `;
    
    const deleteBtn = div.querySelector(".btn-delete");
    const overlay = div.querySelector(".card-delete-confirm-overlay");
    const confirmYes = div.querySelector(".confirm-yes");
    const confirmNo = div.querySelector(".confirm-no");
    
    if (deleteBtn && overlay) {
      deleteBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        overlay.classList.add("show");
      });
    }
    
    if (confirmYes) {
      confirmYes.addEventListener("click", async (e) => {
        e.stopPropagation();
        overlay.classList.remove("show");
        await deleteSession(sess.session_id);
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
}

async function deleteSession(sessionId, cancelActive = false) {
  try {
    const suffix = cancelActive ? "?cancel_active=true" : "";
    const res = await fetch(`/api/chat/sessions/${encodeURIComponent(sessionId)}${suffix}`, {
      method: "DELETE"
    });
    const data = await res.json().catch(() => ({}));
    if (res.status === 409 && !cancelActive && data.detail?.code === "session_active") {
      openDangerConfirmModal({
        title: "会话仍在运行",
        message: "要精确取消该会话的活动操作并删除会话吗？",
        hint: "其它会话的运行与待发消息不会受影响。",
        confirmLabel: "取消操作并删除",
        onConfirm: () => deleteSession(sessionId, true),
      });
      return;
    }
    if (res.ok && data.status === "ok") {
      showToast("对话已删除", "success");
      if (state.activeSessionId === sessionId) {
        state.activeSessionId = null;
        localStorage.removeItem("active_session_id");
      }
      await loadSessions();
    } else {
      const detail = data.detail?.message || data.detail?.code || data.detail;
      showToast(`删除对话失败${detail ? `：${detail}` : ""}`, "error");
    }
  } catch (err) {
    showToast("删除对话失败", "error");
  }
}

/**
 * 选中抽卡会话。
 * opts.skipHistory — 不拉历史（交接空会话时避免闪旧/空请求）
 * opts.placeholderTitle — 标题占位（新会话尚未入列表时）
 * opts.preserveBody — skipHistory 时不清空聊天区（保留交接中已渲染的气泡）
 */
async function selectSession(sessionId, opts = {}) {
  // 交接锁定期间：禁止切到非目标会话（pending 或 active 均可作目标）
  if (state.sessionUiLock) {
    const allowed = state.pendingSessionId || state.activeSessionId;
    if (sessionId && allowed && sessionId !== allowed) return;
    // 锁着且目标尚未确定：禁止选任何具体旧会话
    if (sessionId && !allowed) return;
  }

  state.activeSessionId = sessionId;
  if (sessionId) {
    localStorage.setItem("active_session_id", sessionId);
  } else {
    localStorage.removeItem("active_session_id");
  }
  syncChatLoadingState();
  document.querySelectorAll(".sidebar-card-item").forEach(item => {
    if (item.getAttribute("data-session-id") === sessionId) {
      item.classList.add("active");
    } else {
      item.classList.remove("active");
    }
  });

  const titleElem = document.getElementById("chat-active-card-title");
  if (titleElem) {
    if (sessionId) {
      const activeSess = state.sessions ? state.sessions.find(s => s.session_id === sessionId) : null;
      const title = (activeSess && activeSess.title) || opts.placeholderTitle || "新会话";
      titleElem.innerHTML = `
        🎬 抽卡会话: <strong style="color:var(--text-bright);">${escapeHtml(title)}</strong> 
        · <span style="color:var(--text-muted); font-size:0.8rem;">ID: ${sessionId.substring(0, 12)}...</span>
      `;
    } else if (state.sessionUiLock) {
      titleElem.innerHTML = `🎬 抽卡会话: <strong style="color:var(--text-bright);">${escapeHtml(opts.placeholderTitle || "卡片交接…")}</strong>`;
    } else {
      titleElem.innerHTML = `🎬 请在左侧选择或新建抽卡会话`;
    }
  }

  renderDrawGuidePanel(sessionId);

  if (opts.skipHistory) {
    // 不拉历史时默认保留当前气泡。
    // 旧逻辑在 !sessionUiLock 时清空 body，会导致流式结束后 loadSessions(skipHistory)
    // 把刚画完的交接/对话消息抹掉（刷新后才从磁盘回来）。
    // 仅显式 clearBody 时清屏。
    if (opts.clearBody) {
      const body = document.getElementById("chat-body");
      if (body) body.innerHTML = "";
    }
    return;
  }

  await loadChatHistory(null, sessionId);
}

function renderDrawGuidePanel(sessionId) {
  const panelBody = document.getElementById("param-panel-body");
  if (!panelBody) return;

  const activeSess = sessionId && state.sessions
    ? state.sessions.find(s => s.session_id === sessionId)
    : null;
  const sessionTitle = activeSess?.title || (sessionId ? "未命名会话" : "尚未选择会话");
  const sessionMeta = sessionId
    ? `${escapeHtml(sessionId.substring(0, 16))}…`
    : "左侧新建或点选会话";
  const sessionCount = Array.isArray(state.sessions) ? state.sessions.length : 0;

  panelBody.innerHTML = `
    <div class="draw-guide-panel">
      <div class="draw-guide-header">
        <span class="draw-guide-kicker"><i class="fa-solid fa-wand-magic-sparkles"></i> DRAW</span>
        <h4>抽卡对话工作台</h4>
        <p>在这里通过 AI 对话出卡。可选择常规、连抽或直投模式。</p>
      </div>

      <div class="draw-guide-session">
        <span class="label">当前会话</span>
        <span class="value">${escapeHtml(sessionTitle)}</span>
        <span class="meta">${sessionMeta}${sessionCount ? ` · 共 ${sessionCount} 条` : ""}</span>
      </div>

      <div class="draw-guide-actions">
        <button type="button" class="draw-guide-action" data-draw-action="new-session">
          <i class="fa-solid fa-plus"></i>
          <span class="title">新建会话</span>
          <span class="desc">干净上下文开聊</span>
        </button>
        <button type="button" class="draw-guide-action" data-draw-action="chain">
          <i class="fa-solid fa-layer-group"></i>
          <span class="title">连抽</span>
          <span class="desc">发送连抽指令</span>
        </button>
        <button type="button" class="draw-guide-action" data-draw-action="normal">
          <i class="fa-solid fa-comment-dots"></i>
          <span class="title">常规</span>
          <span class="desc">发送常规指令</span>
        </button>
        <button type="button" class="draw-guide-action" data-draw-action="direct">
          <i class="fa-solid fa-paper-plane"></i>
          <span class="title">直投</span>
          <span class="desc">发送直投指令</span>
        </button>
      </div>

      </div>
  `;

  panelBody.querySelectorAll("[data-draw-action]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const action = btn.getAttribute("data-draw-action");
      try {
        if (action === "new-session") {
          await newSession();
        } else if (action === "chain") {
          await sendModePrompt("进入连抽模式");
        } else if (action === "normal") {
          await sendModePrompt("进入常规模式");
        } else if (action === "direct") {
          await sendModePrompt("进入直投模式");
        }
      } catch (err) {
        showToast("操作失败", "error");
      }
    });
  });
}

/** 引导快捷钮：确保 Draw + 会话后，先画用户气泡再入发送队列 */
async function sendModePrompt(text) {
  const prompt = String(text || "").trim();
  if (!prompt) return;

  if (state.settings.chat_mode !== "draw") {
    state.settings.chat_mode = "draw";
    renderChatModeButtons();
  }
  // 回到聊天视图，避免仍停在配置/文档
  if (state.activeView && state.activeView !== "chat") {
    switchView("chat");
  }
  if (!state.activeSessionId) {
    await newSession({ silent: true });
  }

  appendChatMessage("user", prompt, { persist: false });
  if (typeof enqueueDrawChatMessage === "function") {
    enqueueDrawChatMessage(prompt);
  }
}

async function newSession(opts = {}) {
  // 立刻清空聊天区，避免切到 draw 时先渲染旧会话历史
  const body = document.getElementById("chat-body");
  if (body) body.innerHTML = "";
  state.historyLoadToken++;

  state.sessionUiLock = true;
  state.pendingSessionId = null;
  // 先清空 active，防止并发 loadSessions 用旧 active 选中并拉历史
  state.activeSessionId = null;
  localStorage.removeItem("active_session_id");

  try {
    const res = await fetch("/api/chat/new", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_mode: "draw"
      })
    });
    const data = await res.json();
    const newSessionId = data.session_id;
    if (!newSessionId) throw new Error("no session_id");

    state.pendingSessionId = newSessionId;
    state.activeSessionId = newSessionId;
    localStorage.setItem("active_session_id", newSessionId);

    // 先占位选中新会话（不拉历史、保留空 body），再刷列表
    await selectSession(newSessionId, {
      skipHistory: true,
      preserveBody: true,
      placeholderTitle: opts.placeholderTitle || "交接中…",
    });
    await loadSessions({ preferSessionId: newSessionId, skipHistory: true });

    if (!opts.keepLock) {
      state.sessionUiLock = false;
      state.pendingSessionId = null;
    }
    if (!opts.silent) showToast("新对话已开启", "success");
    return newSessionId;
  } catch (err) {
    state.sessionUiLock = false;
    state.pendingSessionId = null;
    showToast("开启新对话失败", "error");
    throw err;
  }
}

window.confirmDeleteMessage = function(idx) {
  state.deleteMsgIndex = idx;
  openDangerConfirmModal({
    title: "确认删除单条消息",
    message: "确认删除这条对话消息？",
    hint: "此操作将从会话记录中物理删除该条消息气泡，且无法撤销。",
    confirmLabel: "确定删除",
    onConfirm: async () => {
      const targetIdx = state.deleteMsgIndex;
      if (targetIdx === undefined || targetIdx === null) return;
      const isDraw = state.settings.chat_mode === "draw";
      const cardId = state.activeCardId;
      const sessionId = state.activeSessionId;
      try {
        const res = await fetch("/api/chat/delete_message", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ card_id: cardId, session_id: sessionId, index: targetIdx })
        });
        if (res.ok) {
          showToast("已删除该条对话消息", "success");
          if (isDraw) {
            await loadChatHistory(null, sessionId, true);
          } else {
            await loadChatHistory(cardId, null, true);
          }
        } else {
          showToast("删除消息失败", "error");
        }
      } catch (err) {
        showToast("删除消息失败", "error");
      }
    }
  });
};

// =====================================================================
// 📝 西窗烛诗词小挂件初始化
// =====================================================================
