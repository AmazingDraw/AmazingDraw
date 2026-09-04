/* queue.js — 渲染队列面板与轮询
   由 app.js 拆分而来；加载顺序见 index.html，core.js 必须最先。 */

function initQueueCollapse() {
  const trigger = document.getElementById("queue-header-trigger");
  const panel = document.getElementById("queue-detail-list-panel");
  const arrow = document.getElementById("queue-collapse-arrow");
  if (!trigger || !panel || !arrow) return;
  
  const isCollapsed = localStorage.getItem("queue-panel-collapsed") !== "false";
  if (isCollapsed) {
    panel.classList.add("collapsed");
    arrow.classList.remove("expanded");
  } else {
    panel.classList.remove("collapsed");
    arrow.classList.add("expanded");
  }
  
  trigger.addEventListener("click", () => {
    const nowCollapsed = panel.classList.toggle("collapsed");
    arrow.classList.toggle("expanded", !nowCollapsed);
    localStorage.setItem("queue-panel-collapsed", nowCollapsed);
  });
}

async function removeQueueItem(position) {
  try {
    const res = await fetch("/api/queue/remove", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ position: position })
    });
    const data = await res.json().catch(() => ({}));
    if (data.status === "removed") {
      showToast(`已成功将第 ${position} 个任务移出队列`, "success");
      loadQueueStatus();
      return;
    }
    const statusHints = {
      empty: "队列已空，无需移除",
      invalid_position: "队列位置已变化，请刷新后再试",
      lock_busy: "队列正忙，请稍后重试",
      missing_arg: "缺少队列位置参数"
    };
    const detail = data.detail || data.error || data.description
      || statusHints[data.status] || data.status || "未知错误";
    const msg = typeof detail === "string" ? detail : JSON.stringify(detail);
    showToast(`移除失败: ${msg}`, "failed");
  } catch (err) {
    showToast(`请求错误: ${err.message}`, "failed");
  }
}

// =====================================================================
// ⚡ Queue Monitoring & Real-time Render Widget
// =====================================================================
async function loadQueueStatus() {
  try {
    const res = await fetch("/api/queue/status");
    const q = await res.json();
    
    // 1. 更新顶部或边栏队列数字徽章
    const qBadge = document.getElementById("queue-count-badge");
    const detailCont = document.getElementById("queue-runtime-detail");
    if (!qBadge || !detailCont) return;
    
    if (q.gpu_lock.active) {
      qBadge.textContent = "Locked";
      qBadge.className = "badge-text failed";
    } else {
      qBadge.textContent = q.local_queue.length > 0 ? `${q.local_queue.length} PENDING` : "Idle";
      qBadge.className = q.local_queue.length > 0 ? "badge-text warning" : "badge-text success";
    }
    
    // 1b. 更新 ComfyUI 状态指示灯（仅顶栏；侧栏改展示 OpenClaw/Telegram/Obsidian）
    const comfyDot = document.getElementById("comfy-status-dot");
    if (q.comfyui_online) {
      if (comfyDot) { comfyDot.className = "comfy-status-dot online"; comfyDot.parentNode.title = "ComfyUI 在线"; }
    } else {
      if (comfyDot) { comfyDot.className = "comfy-status-dot offline"; comfyDot.parentNode.title = "ComfyUI 离线"; }
    }
    if (q.integrations && typeof updateSettingsIntegrationChips === "function") {
      updateSettingsIntegrationChips(q.integrations);
    }
    
    // 2. 渲染当前在跑的 runtime 状态；boot/startup/rendering/delivering 都要显示，避免开始阶段看不到状态
    const rt = q.runtime || {};
    const hasRuntime = !!(rt.stage);
    if (hasRuntime) {
      const summary = rt.summary || {};
      const startEpoch = rt.start_epoch || 0;
      const nowEpoch = Math.floor(Date.now() / 1000);
      const elapsedSeconds = startEpoch > 0 ? Math.max(0, nowEpoch - startEpoch) : 0;
      
      // 使用渐近指数增长曲线：t=300s -> 63%, t=600s -> 86%, t=900s -> 95%
      const percent = Math.min(99, Math.floor((1 - Math.exp(-elapsedSeconds / 450)) * 100)); 
      
      const formatTime = (sec) => {
        const m = Math.floor(sec / 60);
        const s = sec % 60;
        return m > 0 ? `${m}分${s}秒` : `${s}秒`;
      };

      const stageTextMap = {
        boot: "启动中",
        startup: "启动 ComfyUI",
        rendering: "正在生图",
        delivering: "正在交付"
      };
      const stageText = stageTextMap[rt.stage] || (q.comfyui?.running > 0 ? "ComfyUI 运行中" : "GPU 忙碌");

      detailCont.innerHTML = `
        <div class="queue-runtime-content">
          <div style="font-weight:600; color:var(--text-bright); display:flex; align-items:center; gap:6px;">
            <i class="fa-solid fa-spinner fa-spin" style="color:var(--color-primary);"></i> ${stageText}: ${escapeHtml(summary.person || "未知")}
          </div>
          <div style="color:var(--text-muted); font-size:0.75rem; margin-top:2px;">场景: ${escapeHtml(summary.scene || "未知")} · stage: ${escapeHtml(rt.stage || "unknown")}</div>
          <div class="render-progress-wrapper">
            <div style="display:flex; justify-content:space-between; font-size:0.7rem; color:var(--text-muted); margin-bottom: 4px;">
              <span>进度: ${percent}%</span>
              <span>已耗时: ${formatTime(elapsedSeconds)}</span>
            </div>
            <div class="render-progress-bar-bg">
              <div class="render-progress-bar-fill" style="width: ${percent}%;"></div>
            </div>
          </div>
        </div>
        <button class="queue-cancel-btn" title="取消当前任务"><i class="fa-solid fa-stop"></i></button>
        <div class="queue-cancel-confirm-overlay">
          <span>确认取消当前渲染？</span>
          <div class="confirm-buttons">
            <button class="confirm-yes">确定</button>
            <button class="confirm-no">取消</button>
          </div>
        </div>
      `;

      const cancelBtn = detailCont.querySelector(".queue-cancel-btn");
      const cancelOverlay = detailCont.querySelector(".queue-cancel-confirm-overlay");
      const cancelYes = detailCont.querySelector(".confirm-yes");
      const cancelNo = detailCont.querySelector(".confirm-no");
      
      if (cancelBtn && cancelOverlay) {
        cancelBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          cancelOverlay.classList.add("show");
        });
      }
      if (cancelYes && cancelOverlay) {
        cancelYes.addEventListener("click", (e) => {
          e.stopPropagation();
          cancelOverlay.classList.remove("show");
          cancelCurrentTask();
        });
      }
      if (cancelNo && cancelOverlay) {
        cancelNo.addEventListener("click", (e) => {
          e.stopPropagation();
          cancelOverlay.classList.remove("show");
        });
      }
    } else {
      if (q.local_queue.length > 0) {
        detailCont.innerHTML = `<p style="color:var(--text-muted); font-style:italic;">等待队列渲染中 (队列前列: ${escapeHtml(q.local_queue[0].person)})</p>`;
      } else {
        detailCont.innerHTML = `<p class="status-empty">无正在渲染的任务</p>`;
      }
    }
    
    // 3. 渲染本地排队详情列表
    const listPanel = document.getElementById("queue-detail-list-panel");
    if (listPanel) {
      if (q.local_queue && q.local_queue.length > 0) {
        let listHtml = "";
        q.local_queue.forEach((item, index) => {
          const pos = index + 1;
          const personName = item.person || "未知角色";
          const sceneName = item.scene || "未知场景";
          listHtml += `
            <div class="queue-item-row">
              <div class="queue-item-info">
                <span class="queue-item-title">#${pos} ${escapeHtml(personName)}</span>
                <span class="queue-item-meta">${escapeHtml(sceneName)}</span>
              </div>
              <button class="queue-item-del-btn" data-pos="${pos}" title="移出排队"><i class="fa-regular fa-circle-xmark"></i></button>
              
              <!-- 移出排队确认浮层 -->
              <div class="queue-item-confirm-overlay">
                <span>移出此任务？</span>
                <div class="confirm-buttons">
                  <button class="confirm-yes" data-pos="${pos}">确定</button>
                  <button class="confirm-no">取消</button>
                </div>
              </div>
            </div>
          `;
        });
        listPanel.innerHTML = listHtml;
        
        // 绑定删除与确认/取消按钮事件
        listPanel.querySelectorAll(".queue-item-row").forEach(row => {
          const delBtn = row.querySelector(".queue-item-del-btn");
          const overlay = row.querySelector(".queue-item-confirm-overlay");
          const confirmYes = row.querySelector(".confirm-yes");
          const confirmNo = row.querySelector(".confirm-no");
          
          if (delBtn && overlay) {
            delBtn.addEventListener("click", (e) => {
              e.stopPropagation();
              // 先关闭其他排队行可能已打开的确认浮层
              listPanel.querySelectorAll(".queue-item-confirm-overlay").forEach(ov => {
                if (ov !== overlay) ov.classList.remove("show");
              });
              overlay.classList.add("show");
            });
          }
          
          if (confirmYes && overlay) {
            confirmYes.addEventListener("click", (e) => {
              e.stopPropagation();
              const pos = confirmYes.getAttribute("data-pos");
              overlay.classList.remove("show");
              removeQueueItem(parseInt(pos));
            });
          }
          
          if (confirmNo && overlay) {
            confirmNo.addEventListener("click", (e) => {
              e.stopPropagation();
              overlay.classList.remove("show");
            });
          }
        });
      } else {
        listPanel.innerHTML = `<div style="padding:12px; text-align:center; font-size:0.7rem; color:var(--text-muted); font-style:italic;">排队队列为空</div>`;
      }
    }
  } catch (err) {
    // 轮询静默失败
  }
}

async function cancelCurrentTask() {
  try {
    const res = await fetch("/api/queue/cancel", { method: "POST" });
    const result = await res.json();
    if (result.status === "cancelled" || result.status === "lock_cleaned" || result.status === "process_not_found") {
      showToast("已成功取消当前任务并解锁 GPU！", "success");
    } else {
      showToast("没有正在运行的任务可取消", "info");
    }
    loadQueueStatus();
  } catch (err) {
    showToast("取消任务失败", "error");
  }
}
// 切换到"发送中"状态 (全局状态器，供常规对话与直投逻辑调用)
async function terminateQueue() {
  showToast("正在发送终止指令...", "info");
  try {
    const res = await fetch("/api/queue/terminate", { method: "POST" });
    if (res.ok) {
      showToast("✅ 渲染队列及相关进程已成功终止！", "success");
      loadQueueStatus();
      loadCards();
    } else {
      showToast("终止队列失败", "error");
    }
  } catch (err) {
    showToast("网络请求失败，请稍后重试", "error");
  }
}

async function clearRenderQueue() {
  try {
    const res = await fetch("/api/queue/clear", { method: "POST" });
    if (res.ok) {
      showToast("排队队列已清空", "success");
      loadQueueStatus();
      loadCards();
    } else {
      showToast("清空队列失败", "error");
    }
  } catch (err) {
    showToast("清空队列失败", "error");
  }
}

// =====================================================================
// 🏢 Autocomplete Suggestion Logic
// =====================================================================
