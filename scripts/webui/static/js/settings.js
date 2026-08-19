/* settings.js — 模型发现、系统配置读写与文档
   由 app.js 拆分而来；加载顺序见 index.html，core.js 必须最先。 */

async function loadModels() {
  try {
    const res = await fetch("/api/config/models");
    const data = await res.json();
    
    if (data.scanned) {
      state.openclawModels = data.openclaw_models || [];
      state.cliproxyModels = data.cliproxy_models || [];
    } else {
      state.openclawModels = [];
      state.cliproxyModels = [];
    }
    
    updateModelDropdown();
  } catch (err) {
    showToast("无法加载 AI 模型列表", "error");
  }
}

function findMatchingModel(currentModel, availableModels, fallbackToFirst = true) {
  if (!currentModel || !availableModels || availableModels.length === 0) {
    return fallbackToFirst ? (availableModels[0] || "") : "";
  }
  if (availableModels.includes(currentModel)) {
    return currentModel;
  }
  const getBaseName = (m) => m.includes("/") ? m.split("/").slice(1).join("/") : m;
  const currentBase = getBaseName(currentModel);
  const matched = availableModels.find(m => getBaseName(m) === currentBase);
  if (matched) {
    return matched;
  }
  return fallbackToFirst ? (availableModels[0] || "") : "";
}

function updateModelDropdown() {
  const modelSelect = document.getElementById("settings-llm-model");
  const independentModelSelect = document.getElementById("settings-independent-llm-model");
  const fallbackModelSelect = document.getElementById("settings-llm-fallback-model");
  const warningBanner = document.getElementById("settings-agent-warning");
  if (!modelSelect) return;

  const backend = "openclaw";

  // 控制警告 Banner 显隐
  if (warningBanner) {
    const hasOpenclaw = state.openclawModels && state.openclawModels.length > 0;
    warningBanner.classList.toggle("is-hidden", !!hasOpenclaw);
  }

  let models = state.openclawModels || [];
  
  // 2. 填充主对话模型下拉列表
  modelSelect.innerHTML = "";
  
  if (models && models.length > 0) {
    models.forEach(model => {
      const opt = document.createElement("option");
      opt.value = model;
      opt.textContent = model;
      modelSelect.appendChild(opt);
    });
    
    const matchedMain = findMatchingModel(state.settings.llm_model, models, true);
    modelSelect.value = matchedMain;
  } else {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = `⚠️ 未检测到 ${backend} 可用模型`;
    modelSelect.appendChild(opt);
  }

  // 3. 填充独立调用模型下拉列表
  if (independentModelSelect) {
    independentModelSelect.innerHTML = "";
    
    // 默认空值选项（跟随主对话模型）
    const defaultOpt = document.createElement("option");
    defaultOpt.value = "";
    defaultOpt.textContent = "跟随主对话模型 (Default)";
    independentModelSelect.appendChild(defaultOpt);
    
    if (models && models.length > 0) {
      models.forEach(model => {
        const opt = document.createElement("option");
        opt.value = model;
        opt.textContent = model;
        independentModelSelect.appendChild(opt);
      });
      
      const matchedInd = findMatchingModel(state.settings.independent_llm_model, models, false);
      independentModelSelect.value = matchedInd;
    }
  }

  // 4. 填充满级备用模型下拉列表（单选，写入单元素数组保持配置格式不变）
  if (fallbackModelSelect) {
    fallbackModelSelect.innerHTML = "";
    const noneOpt = document.createElement("option");
    noneOpt.value = "";
    noneOpt.textContent = "不启用备用模型";
    fallbackModelSelect.appendChild(noneOpt);

    if (models && models.length > 0) {
      models.forEach(model => {
        const opt = document.createElement("option");
        opt.value = model;
        opt.textContent = model;
        fallbackModelSelect.appendChild(opt);
      });
      const currentFallback = Array.isArray(state.settings.llm_fallback_models)
        ? (state.settings.llm_fallback_models[0] || "")
        : (state.settings.llm_fallback_models || "");
      fallbackModelSelect.value = findMatchingModel(currentFallback, models, false);
    }
  }
}

function updateComfyLink() {
  const comfyLink = document.getElementById("comfy-status-link");
  if (comfyLink) {
    comfyLink.href = state.settings.comfyui_host || "#";
  }
}

async function loadSettings() {
  try {
    const res = await fetch("/api/settings");
    state.settings = await res.json();
    if (state.settings) {
      state.settings.chat_mode = normalizeChatMode(state.settings.chat_mode);
      try { localStorage.setItem("chat_mode", state.settings.chat_mode); } catch (_) {}
    }
    
    const form = document.getElementById("form-settings-page");
    if (form) {
      if (form.elements["comfyui_host"]) form.elements["comfyui_host"].value = state.settings.comfyui_host || "";
      if (form.elements["output_dir"]) form.elements["output_dir"].value = state.settings.output_dir || "";
      if (form.elements["output_dir_archive"]) form.elements["output_dir_archive"].value = state.settings.output_dir_archive || "";
      if (form.elements["custom_presets_dir"]) form.elements["custom_presets_dir"].value = state.settings.custom_presets_dir || "";
      if (form.elements["delivery_telegram"]) {
        form.elements["delivery_telegram"].checked = state.settings.delivery_telegram !== false;
      }
      if (form.elements["delivery_webui"]) {
        form.elements["delivery_webui"].checked = state.settings.delivery_webui !== false;
      }

      // 载入新算法与目录字段
      if (form.elements["comfyui_dir"]) {
        form.elements["comfyui_dir"].value = state.settings.comfyui_dir || "";
      }
      if (form.elements["scene_cooldown_window"]) {
        form.elements["scene_cooldown_window"].value = state.settings.scene_cooldown_window || 10;
      }
      if (form.elements["openclaw_ws_timeout_seconds"]) {
        form.elements["openclaw_ws_timeout_seconds"].value = state.settings.openclaw_ws_timeout_seconds || 600;
      }
      if (form.elements["auto_horizontal_for_multi"]) {
        form.elements["auto_horizontal_for_multi"].checked = state.settings.auto_horizontal_for_multi !== false;
      }
      if (form.elements["lock_size_to_workflow"]) {
        form.elements["lock_size_to_workflow"].checked = state.settings.lock_size_to_workflow !== false;
      }
      if (form.elements["openclaw_workspace_dir"]) {
        form.elements["openclaw_workspace_dir"].value = state.settings.openclaw_workspace_dir || "";
      }
      if (form.elements["recording_dir"]) {
        form.elements["recording_dir"].value = state.settings.recording_dir || "";
      }
      if (form.elements["obsidian_vault_dir"]) {
        form.elements["obsidian_vault_dir"].value = state.settings.obsidian_vault_dir || "";
      }
      if (form.elements["tmp_dir"]) {
        form.elements["tmp_dir"].value = state.settings.tmp_dir || "";
      }
      if (form.elements["cards_dir"]) {
        form.elements["cards_dir"].value = state.settings.cards_dir || "";
      }

      if (form.elements["telegram_chat_id"]) {
        form.elements["telegram_chat_id"].value = state.settings.telegram_chat_id || "";
      }
      if (form.elements["telegram_bot_token"]) {
        form.elements["telegram_bot_token"].value = state.settings.telegram_bot_token || "";
      }
      if (form.elements["llm_retry_limit"]) {
        form.elements["llm_retry_limit"].value = state.settings.llm_retry_limit || 1;
      }
      // llm_fallback_models 为下拉单选，选中值由 updateModelDropdown() 统一设置
      if (form.elements["webui_host"]) {
        form.elements["webui_host"].value = state.settings.webui_host || "0.0.0.0";
      }
      if (form.elements["webui_port"]) {
        form.elements["webui_port"].value = state.settings.webui_port || 8318;
      }

      // ─── 初始化工作流配置管理界面 ───
      renderWorkflowsList();
      const defaultWfSelect = document.getElementById("settings-default-workflow");
      if (defaultWfSelect) {
        const aliases = state.settings.workflows_aliases || {};
        const val = state.settings.default_workflow || "moody";
        defaultWfSelect.value = aliases[val] || val;
        defaultWfSelect.onchange = () => {
          state.settings.default_workflow = defaultWfSelect.value;
        };
      }

      // 裸露级别 chips 多选（写入 exposure_allowed_modes 集合 + 派生 exposure_limit 区间兼容）
      const EXPOSURE_LEVELS = [
        ["none", "全遮 (不漏)"],
        ["half_covered", "擦边 (半遮)"],
        ["upper", "露上 (Topless)"],
        ["lower", "露下 (Bottomless)"],
        ["half_nude", "半裸 (局部露点)"],
        ["both", "全裸 (三点全露)"],
      ];
      const chipsBox = document.getElementById("settings-exposure-chips");
      if (chipsBox) {
        const configured = Array.isArray(state.settings.exposure_allowed_modes)
          ? state.settings.exposure_allowed_modes.filter(Boolean)
          : [];
        let selected;
        if (configured.length > 0) {
          selected = configured;
        } else {
          // 向后兼容：从旧的 exposure_limit 区间展开为集合
          const range = state.settings.exposure_limit || ["none", "both"];
          const order = EXPOSURE_LEVELS.map(x => x[0]);
          let i0 = order.indexOf(range[0]); if (i0 < 0) i0 = 0;
          let i1 = order.indexOf(range[1]); if (i1 < 0) i1 = order.length - 1;
          if (i0 > i1) [i0, i1] = [i1, i0];
          selected = order.slice(i0, i1 + 1);
        }
        chipsBox.innerHTML = "";
        EXPOSURE_LEVELS.forEach(([value, label]) => {
          const chip = document.createElement("button");
          chip.type = "button";
          chip.dataset.value = value;
          chip.textContent = label;
          const paint = () => {
            const on = chip.dataset.on === "1";
            chip.style.cssText = `padding: 2px 9px; border-radius: 10px; font-size: 0.74rem; line-height: 1.5; cursor: pointer; transition: all .15s ease; font-weight: ${on ? "500" : "400"}; border: 1px solid ${on ? "rgba(80, 120, 200, 0.55)" : "var(--border-color, #3a3f4b)"}; background: ${on ? "rgba(80, 120, 200, 0.12)" : "transparent"}; color: ${on ? "#3a5fad" : "var(--text-muted, #8a8f9c)"};`;
          };
          chip.dataset.on = selected.includes(value) ? "1" : "0";
          paint();
          chip.onclick = () => {
            const onCount = chipsBox.querySelectorAll('[data-on="1"]').length;
            if (chip.dataset.on === "1" && onCount <= 1) return; // 至少保留一项
            chip.dataset.on = chip.dataset.on === "1" ? "0" : "1";
            paint();
          };
          chipsBox.appendChild(chip);
        });
      }
      if (form.elements["restrict_roles"]) {
        const restrict = state.settings.restrict_roles;
        form.elements["restrict_roles"].checked =
          restrict === undefined ? true : !!restrict;
      }
      


      // 分辨率规格预设
      
      const { width: vertW, height: vertH } = getPresetSize("vertical");
      if (form.elements["res_vertical_w"]) form.elements["res_vertical_w"].value = vertW;
      if (form.elements["res_vertical_h"]) form.elements["res_vertical_h"].value = vertH;
      
      const vertPresetSelect = document.getElementById("settings-res-vertical-preset");
      if (vertPresetSelect) {
        const val = `${vertW}x${vertH}`;
        const hasOption = Array.from(vertPresetSelect.options).some(opt => opt.value === val);
        vertPresetSelect.value = hasOption ? val : "custom";
      }

      const { width: horizW, height: horizH } = getPresetSize("horizontal");
      if (form.elements["res_horizontal_w"]) form.elements["res_horizontal_w"].value = horizW;
      if (form.elements["res_horizontal_h"]) form.elements["res_horizontal_h"].value = horizH;

      const horizPresetSelect = document.getElementById("settings-res-horizontal-preset");
      if (horizPresetSelect) {
        const val = `${horizW}x${horizH}`;
        const hasOption = Array.from(horizPresetSelect.options).some(opt => opt.value === val);
        horizPresetSelect.value = hasOption ? val : "custom";
      }

      const { width: sqW } = getPresetSize("square");
      if (form.elements["res_square_w"]) form.elements["res_square_w"].value = sqW;
      if (form.elements["res_square_h"]) form.elements["res_square_h"].value = sqW;

      const sqPresetSelect = document.getElementById("settings-res-square-preset");
      if (sqPresetSelect) {
        const val = `${sqW}x${sqW}`;
        const hasOption = Array.from(sqPresetSelect.options).some(opt => opt.value === val);
        sqPresetSelect.value = hasOption ? val : "custom";
      }

      const { width: wideW, height: wideH } = getPresetSize("widescreen");
      if (form.elements["res_widescreen_w"]) form.elements["res_widescreen_w"].value = wideW;
      if (form.elements["res_widescreen_h"]) form.elements["res_widescreen_h"].value = wideH;

      const widePresetSelect = document.getElementById("settings-res-widescreen-preset");
      if (widePresetSelect) {
        const val = `${wideW}x${wideH}`;
        const hasOption = Array.from(widePresetSelect.options).some(opt => opt.value === val);
        widePresetSelect.value = hasOption ? val : "custom";
      }

      // 动态载入场景权重（config 无 scene_registry 时用内置库表兜底，避免空白）
      const weightsContainer = document.getElementById("scene-weights-container");
      if (weightsContainer) {
        weightsContainer.innerHTML = "";
        const defaultWeights = {
          school_scenes: 5,
          general_scenes: 5,
          medical_scenes: 3,
          workplace_scenes: 3,
          sm_scenes: 5,
          special_scenes: 5,
          perspective_scenes: 0
        };
        const fallbackLibraries = {
          school_scenes: { type: "scene", enabled: true, name: "校园场景" },
          general_scenes: { type: "scene", enabled: true, name: "通用场景" },
          medical_scenes: { type: "scene", enabled: true, name: "医疗场景" },
          workplace_scenes: { type: "scene", enabled: true, name: "职场场景" },
          sm_scenes: { type: "scene", enabled: true, name: "SM场景" },
          special_scenes: { type: "scene", enabled: true, name: "特殊场景" },
          perspective_scenes: { type: "scene", enabled: true, name: "视角场景" }
        };
        const registry = state.settings.scene_registry || {};
        let libraries = registry.libraries || {};
        if (!libraries || Object.keys(libraries).length === 0) {
          libraries = fallbackLibraries;
        }
        const weights = state.settings.scene_library_weights || {};

        Object.entries(libraries).forEach(([libKey, libInfo]) => {
          if (!libInfo || libInfo.type !== "scene" || libInfo.enabled === false) return;
          const libName = libInfo.name || libKey;
          const weightVal = weights[libKey] !== undefined
            ? weights[libKey]
            : (defaultWeights[libKey] !== undefined ? defaultWeights[libKey] : 3);

          const formRow = document.createElement("div");
          formRow.className = "form-row";
          formRow.innerHTML = `
              <label>${escapeHtml(libName)} (${libKey.replace("_scenes", "")})</label>
              <input type="number" name="weight_${libKey}" data-weight-key="${libKey}" value="${weightVal}" min="0" style="width: 100%;">
            `;
          weightsContainer.appendChild(formRow);

          const input = formRow.querySelector("input");
          // 移除了自动保存监听
        });
      }
      

    }
    
    await loadModels();
    
    if (form && state.settings.llm_model && form.elements["llm_model"]) {
      form.elements["llm_model"].value = state.settings.llm_model;
    }
    if (form && state.settings.independent_llm_model && form.elements["independent_llm_model"]) {
      form.elements["independent_llm_model"].value = state.settings.independent_llm_model;
    }
    updateComfyLink();
    // 始终完整同步按钮+指示条；侧栏由 boot / 显式切换负责，避免二次 loadCards
    renderChatModeButtons({ skipSidebar: true });
    state.settingsDirty = false;
  } catch (err) {
    showToast("无法加载环境配置", "error");
  }
}

async function loadPresets() {
  try {
    let res = await fetch("/api/config/roles");
    const rolesData = await res.json();
    state.profiles = rolesData.profiles;
    state.celebrities = rolesData.celebrities;
    
    res = await fetch("/api/config/scenes");
    state.scenes = await res.json();
    
    // 新建卡片表单的 profile 下拉
    const profileSelect = document.getElementById("create-profile");
    if (profileSelect) {
      profileSelect.innerHTML = `<option value="default">默认关联 (Default)</option>`;
    }
    Object.keys(state.profiles).forEach(key => {
      const opt = document.createElement("option");
      opt.value = key;
      opt.textContent = `${key} (${state.profiles[key].display_name || "无名称"})`;
      if (profileSelect) profileSelect.appendChild(opt);
    });
  } catch (err) {
    showToast("无法加载预设包", "error");
  }
}

async function autoSaveSettings() {
  const form = document.getElementById("form-settings-page");
  if (!form) return;
  
  const data = Object.assign({}, state.settings || {}, {
    agent_backend: form.elements["agent_backend"] ? form.elements["agent_backend"].value : (state.settings.agent_backend || "openclaw"),
    llm_model: form.elements["llm_model"].value,
    comfyui_host: form.elements["comfyui_host"].value.trim(),
    output_dir: form.elements["output_dir"] ? form.elements["output_dir"].value.trim() : (state.settings.output_dir || ""),
    output_dir_archive: form.elements["output_dir_archive"] ? form.elements["output_dir_archive"].value.trim() : (state.settings.output_dir_archive || ""),
    custom_presets_dir: form.elements["custom_presets_dir"] ? form.elements["custom_presets_dir"].value.trim() : (state.settings.custom_presets_dir || ""),
    recording_dir: form.elements["recording_dir"] ? form.elements["recording_dir"].value.trim() : (state.settings.recording_dir || ""),
    delivery_telegram: form.elements["delivery_telegram"] ? form.elements["delivery_telegram"].checked : (state.settings.delivery_telegram !== false),
    delivery_webui: form.elements["delivery_webui"] ? form.elements["delivery_webui"].checked : (state.settings.delivery_webui !== false),
    independent_llm_model: form.elements["independent_llm_model"] ? form.elements["independent_llm_model"].value : (state.settings.independent_llm_model || ""),
    telegram_chat_id: form.elements["telegram_chat_id"] ? form.elements["telegram_chat_id"].value.trim() : (state.settings.telegram_chat_id || ""),
    telegram_bot_token: form.elements["telegram_bot_token"] ? form.elements["telegram_bot_token"].value.trim() : (state.settings.telegram_bot_token || ""),
    llm_retry_limit: form.elements["llm_retry_limit"]
      ? Math.min(5, Math.max(1, parseInt(form.elements["llm_retry_limit"].value, 10) || 1))
      : (state.settings.llm_retry_limit || 1),
    llm_fallback_models: form.elements["llm_fallback_models"] ? form.elements["llm_fallback_models"].value.split(",").map(s => s.trim()).filter(Boolean) : (state.settings.llm_fallback_models || []),
    webui_host: form.elements["webui_host"] ? form.elements["webui_host"].value.trim() : (state.settings.webui_host || "0.0.0.0"),
    webui_port: form.elements["webui_port"] ? parseInt(form.elements["webui_port"].value, 10) || 8318 : 8318,
    
    // A 组路径与算法配置
    comfyui_dir: form.elements["comfyui_dir"] ? form.elements["comfyui_dir"].value.trim() : (state.settings.comfyui_dir || ""),
    openclaw_workspace_dir: form.elements["openclaw_workspace_dir"] ? form.elements["openclaw_workspace_dir"].value.trim() : (state.settings.openclaw_workspace_dir || ""),
    obsidian_vault_dir: form.elements["obsidian_vault_dir"] ? form.elements["obsidian_vault_dir"].value.trim() : (state.settings.obsidian_vault_dir || ""),
    tmp_dir: form.elements["tmp_dir"] ? form.elements["tmp_dir"].value.trim() : (state.settings.tmp_dir || ""),
    cards_dir: form.elements["cards_dir"] ? form.elements["cards_dir"].value.trim() : (state.settings.cards_dir || ""),

    default_workflow: form.elements["default_workflow"] ? form.elements["default_workflow"].value : (state.settings.default_workflow || "moody"),
    scene_cooldown_window: form.elements["scene_cooldown_window"] ? parseInt(form.elements["scene_cooldown_window"].value, 10) || 10 : 10,
    openclaw_ws_timeout_seconds: form.elements["openclaw_ws_timeout_seconds"]
      ? Math.min(7200, Math.max(60, parseInt(form.elements["openclaw_ws_timeout_seconds"].value, 10) || 600))
      : (state.settings.openclaw_ws_timeout_seconds || 600),
    auto_horizontal_for_multi: form.elements["auto_horizontal_for_multi"] ? form.elements["auto_horizontal_for_multi"].checked : true,
    lock_size_to_workflow: form.elements["lock_size_to_workflow"] ? form.elements["lock_size_to_workflow"].checked : true,
    llm_temperature: form.elements["llm_temperature"] ? parseFloat(form.elements["llm_temperature"].value) : (state.settings.llm_temperature !== undefined ? state.settings.llm_temperature : 0.7),
    exposure_allowed_modes: (() => {
      const box = document.getElementById("settings-exposure-chips");
      if (!box) return (state.settings.exposure_allowed_modes || []);
      const order = ["none", "half_covered", "upper", "lower", "half_nude", "both"];
      const picked = [...box.querySelectorAll('[data-on="1"]')].map(c => c.dataset.value);
      return order.filter(v => picked.includes(v));
    })(),
    exposure_limit: (() => {
      // 兼容旧消费方：由选中集合派生 [min, max] 区间
      const box = document.getElementById("settings-exposure-chips");
      const order = ["none", "half_covered", "upper", "lower", "half_nude", "both"];
      const picked = box ? [...box.querySelectorAll('[data-on="1"]')].map(c => c.dataset.value) : [];
      const idxs = picked.map(v => order.indexOf(v)).filter(i => i >= 0).sort((a, b) => a - b);
      if (idxs.length === 0) return (state.settings.exposure_limit || ["none", "both"]);
      return [order[idxs[0]], order[idxs[idxs.length - 1]]];
    })(),
    restrict_roles: form.elements["restrict_roles"]
      ? form.elements["restrict_roles"].checked
      : (state.settings.restrict_roles !== undefined
          ? !!state.settings.restrict_roles
          : true),
    
    // B 组分辨率规格预设
    resolution_presets: (() => {
      const readSize = (key, wField, hField) => {
        const fallback = RESOLUTION_FALLBACK[key];
        const readOne = (field, dflt) => {
          const el = form.elements[field];
          return el ? parseInt(el.value, 10) || dflt : dflt;
        };
        return {
          width: readOne(wField, fallback.width),
          height: readOne(hField, fallback.height),
        };
      };
      const square = readSize("square", "res_square_w", "res_square_w");
      return {
        vertical: readSize("vertical", "res_vertical_w", "res_vertical_h"),
        horizontal: readSize("horizontal", "res_horizontal_w", "res_horizontal_h"),
        square: { width: square.width, height: square.width },
        widescreen: readSize("widescreen", "res_widescreen_w", "res_widescreen_h"),
      };
    })(),

    // 动态提取并保存场景权重；容器为空时保留原值，避免自动保存写成 {}
    scene_library_weights: (() => {
      const inputs = form.querySelectorAll("#scene-weights-container input[data-weight-key]");
      if (!inputs.length) {
        return state.settings.scene_library_weights || {};
      }
      const weights = { ...(state.settings.scene_library_weights || {}) };
      inputs.forEach(input => {
        const key = input.getAttribute("data-weight-key");
        const val = parseInt(input.value, 10);
        weights[key] = isNaN(val) ? 0 : val;
      });
      return weights;
    })()
  });

  try {
    await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data)
    });
    state.settings = data;
    updateComfyLink();
    loadPresets();
    state.settingsDirty = false;
    showToast("系统配置保存成功！", "success");
  } catch (err) {
    console.error("保存配置失败", err);
    showToast("保存配置失败：" + err.message, "error");
  }
}

// =====================================================================
// ↕️ Sidebar & Panel Resizer Controls
// =====================================================================
async function testConnection(customHost = null) {
  let host = customHost;
  if (!host) {
    const form = document.getElementById("form-settings-page");
    host = form ? form.elements["comfyui_host"].value.trim() : "";
  }
  if (!host) {
    showToast("请输入 ComfyUI 服务地址", "error");
    return;
  }
  showToast("连接 ComfyUI 中...", "info");
  try {
    const res = await fetch(`${host}/system_stats`, { mode: "cors" });
    const data = await res.json();
    if (data.system && data.system.ram_free) {
       showToast("✅ 连接 ComfyUI 后端成功！", "success");
    } else {
       showToast("连接异常，请确保端口无误", "error");
    }
  } catch (err) {
    showToast("❌ 连接失败：ComfyUI 未启动", "error");
  }
}

function stripMarkdownFrontmatter(raw) {
  if (!raw || typeof raw !== "string") return "";
  // YAML frontmatter at file start: --- ... ---
  if (raw.startsWith("---")) {
    const end = raw.indexOf("\n---", 3);
    if (end !== -1) {
      return raw.slice(end + 4).replace(/^\s+/, "");
    }
  }
  return raw;
}

const EVM_ADDRESS_RE = /^0x[a-fA-F0-9]{40}$/;

function enhanceDocCopyTargets(root) {
  if (!root) return;
  root.querySelectorAll("pre").forEach((pre) => {
    const text = (pre.innerText || "").trim();
    if (!EVM_ADDRESS_RE.test(text) || pre.classList.contains("docs-copy-target")) return;
    pre.classList.add("docs-copy-target");
    pre.setAttribute("role", "button");
    pre.setAttribute("tabindex", "0");
    pre.setAttribute("title", "点击复制地址");
    const hint = document.createElement("span");
    hint.className = "docs-copy-hint";
    hint.innerHTML = '<i class="fa-regular fa-copy"></i> 点击复制';
    pre.appendChild(hint);
    const resetHint = () => {
      hint.innerHTML = '<i class="fa-regular fa-copy"></i> 点击复制';
      pre.classList.remove("copied");
    };
    const copyAddr = async () => {
      try {
        await navigator.clipboard.writeText(text);
        showToast("EVM 地址已复制", "success");
        pre.classList.add("copied");
        hint.innerHTML = '<i class="fa-solid fa-check"></i> 已复制';
        setTimeout(resetHint, 1500);
      } catch (err) {
        showToast("复制失败，请手动选取复制", "error");
      }
    };
    pre.addEventListener("click", copyAddr);
    pre.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        copyAddr();
      }
    });
  });
}

async function loadDocContent(docName) {
  const contentElem = document.getElementById("docs-reader-content-page");
  if (!contentElem) return;
  contentElem.innerHTML = "<div class='docs-loading'>载入中...</div>";
  try {
    const res = await fetch(`/api/docs/${docName}`);
    const data = await res.json();
    const raw = stripMarkdownFrontmatter(data.content || "");
    // 用独立实例，不再全局 setOptions —— 那会顺带改掉聊天区的渲染，
    // 让聊天行为取决于主人有没有打开过文档页
    const md = markdownForDoc();
    if (md) {
      contentElem.innerHTML = md.parse(raw);
      enhanceDocCopyTargets(contentElem);
    } else {
      contentElem.textContent = raw;
    }
    // Soft-scroll to top on doc switch
    contentElem.scrollTop = 0;
  } catch (err) {
    contentElem.innerHTML = "<span style='color:var(--color-danger);'>载入说明书失败。</span>";
  }
}



function renderWorkflowsList() {
  const workflows = state.settings.workflows || {};
  const defaultWf = state.settings.default_workflow || "moody";
  const aliases = state.settings.workflows_aliases || {};
  const normalizedDefault = aliases[defaultWf] || defaultWf;

  const defaultSelect = document.getElementById("settings-default-workflow");
  if (!defaultSelect) return;

  const currentVal = defaultSelect.value || normalizedDefault;
  defaultSelect.innerHTML = "";
  Object.keys(workflows).forEach(key => {
    const opt = document.createElement("option");
    opt.value = key;
    opt.textContent = `${workflows[key].name || key} (${key})`;
    defaultSelect.appendChild(opt);
  });
  defaultSelect.value = currentVal;
  if (!defaultSelect.value && defaultSelect.options.length > 0) {
    defaultSelect.value = defaultSelect.options[0].value;
  }
}
