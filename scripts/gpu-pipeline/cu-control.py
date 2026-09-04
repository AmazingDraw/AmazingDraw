#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ==============================================================================
# cu-control.py — ComfyUI 抽卡工作流后台队列与守护进程管理中心 (v1.2.0)
# ==============================================================================
# 设计职责：
#   负责协调本地 GPU 渲染流水线、排队管理、进程控制与自愈机制。作为 Telegram
#   机器人命令与后台真实进程（cu-worker.sh / cu-queue.py）的桥接控制台。
#
# 路径约定（自包含）：
#   - 本文件与 detached_spawn / cu-worker / cu-queue / comfyui-start 同目录解析
#   - WORK_DIR 读 config.json → tmp_dir（默认 /tmp/cu-card）
#   - ETA 无均时回退：调用同目录 cu-queue.py avg-eta（禁止硬编码分钟数）
#   - 旧路径 ~/.openclaw/workspace/scripts/cu-control.py 仅为兼容转发到本文件
#
# 核心功能模块：
#   1. 状态轮询与监控 (status)
#      - 扫描 tmp_dir 下的 PID 文件，分析 active_worker 进程的存活状态与命令行参数。
#      - 对接 ComfyUI API (/queue) 获取内部排队与运行计数，判定本地队列与 ComfyUI 状态。
#      - 利用 WebSocket (ws://127.0.0.1:8188/ws) 实时抓取采样节点的进度（progress_state），
#        计算高精度的渲染百分比、耗时与 ETA 剩余时间，提供进度状态反馈。
#      - 智能检测 Stall (卡死) 状态：发现残留锁而无活跃进程时，进行异常标注。
#   2. 任务暂停控制 (pause)
#      - 先以 job_id + lease token 将 QueueStore job 标为 paused，再保存展示快照。
#      - 使用 SIGTERM/SIGKILL 渐进式强杀 worker 进程组，释放 GPU 锁 (cu-gpu.lock) 以腾出显存。
#   3. 任务与队列恢复 (resume)
#      - 暂停 job 先回 pending，再统一由 cu-queue.py 执行 claim-before-spawn。
#      - 无暂停快照时，同样调用 cu-queue.py resume 续跑本地排队队列。
#   4. 服务终止与重置 (terminate)
#      - 强杀全部渲染 worker 进程与 cu-deliver.sh 投递脚本，防止未完成的图片继续发送。
#      - 强退 ComfyUI 后端服务器并释放全部 PyTorch 驻留显存。
#      - 清理所有 GPU 锁、暂停快照与草稿文件夹。
#   5. 队列强制清空 (clear)
#      - 通过 QueueStore CLI 清空等待任务，不直接改 cu-queue.json。
#
# 依赖状态文件（相对 tmp_dir，默认 /tmp/cu-card）：
#   - cu-gpu.lock            : GPU 忙碌标识
#   - cu-paused-task.json    : 暂停任务元数据快照
#   - cu-runtime.json        : 渲染 worker 运行期指标
#   - cu-submit-bg_*.pid     : 后台守护进程物理 PID 文件
#   - cu-draw-card.log       : 渲染引擎日志（WebUI/progress 同读此文件）
# ==============================================================================
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.request import urlopen

try:
    import websockets
except Exception:
    websockets = None

_GPU_DIR = Path(__file__).resolve().parent
_CONFIG_FILE = _GPU_DIR.parent / "config.json"


def _load_config() -> dict:
    if _CONFIG_FILE.exists():
        try:
            data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            pass
    return {}


def _cfg_path(key: str, default: str) -> Path:
    raw = _load_config().get(key) or default
    return Path(os.path.expanduser(str(raw))).resolve()


WORK_DIR = Path(os.path.expanduser(os.environ.get("CU_WORK_DIR") or str(
    _cfg_path("tmp_dir", "/tmp/cu-card")
))).resolve()
PID_GLOB = "cu-submit-bg_*.pid"
GPU_LOCK = WORK_DIR / "cu-gpu.lock"
PAUSED_STATE = WORK_DIR / "cu-paused-task.json"
RUNTIME_STATE = WORK_DIR / "cu-runtime.json"
QUEUE_SCRIPT = _GPU_DIR / "cu-queue.py"
COMFYUI_START = _GPU_DIR / "comfyui-start.sh"
WORKSPACE = Path(os.path.expanduser(
    os.environ.get("CU_WORKSPACE")
    or str(_cfg_path("openclaw_workspace_dir", str(Path.home() / ".openclaw" / "workspace")))
)).resolve()
DRAW_LOG = WORK_DIR / "cu-draw-card.log"


def typical_render_minutes() -> Optional[float]:
    """与 cu-queue avg-eta / cu-submit 共用：最近成功交付均时（分钟）。"""
    try:
        proc = subprocess.run(
            [sys.executable, str(QUEUE_SCRIPT), "avg-eta"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        data = json.loads(proc.stdout or "{}")
        avg = data.get("avg_min")
        if avg is not None and float(avg) > 0:
            return float(avg)
    except Exception:
        pass
    return None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description='Control detached CU draw workers')
    sub = p.add_subparsers(dest='cmd', required=True)
    sub.add_parser('status', help='Show active draw worker status')
    pause = sub.add_parser('pause', help='Pause current draw worker and freeze queue')
    pause.add_argument('--force', action='store_true', help='Skip confirmation hints in output only')
    sub.add_parser('resume', help='Resume the last paused draw worker')
    sub.add_parser('terminate', help='Clear queue, kill workers, release GPU lock, stop ComfyUI')
    sub.add_parser('clear', help='Clear the local rendering queue')
    return p.parse_args()


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8')
    except Exception:
        return ''


def parse_log_metadata(log_path: Path) -> dict:
    text = read_text(log_path)
    meta = {'log_file': str(log_path)}
    for key in ('PROMPT_FILE', 'META_FILE', 'DONE_FILE'):
        m = re.search(rf'^{key}=(.+)$', text, re.M)
        if m:
            meta[key.lower()] = m.group(1).strip()
    return meta


def ps_command(pid: int) -> str:
    try:
        out = subprocess.check_output(['ps', '-p', str(pid), '-o', 'command='], text=True)
        return out.strip()
    except Exception:
        return ''


def ps_state(pid: int) -> str:
    try:
        out = subprocess.check_output(['ps', '-p', str(pid), '-o', 'stat='], text=True)
        return out.strip()
    except Exception:
        return ''


def parse_worker_args(command: str) -> dict:
    args = {
        'job_id': '',
        'card_id': '',
        'lease_token': '',
        'workflow': '',
        'seed': '',
        'lora': '',
        'width': '',
        'height': '',
    }
    for flag in (
        '--job-id',
        '--card-id',
        '--lease-token',
        '--workflow',
        '--seed',
        '--lora',
        '--width',
        '--height',
    ):
        m = re.search(rf'{re.escape(flag)}\s+(\S+)', command)
        if m:
            args[flag[2:].replace('-', '_')] = m.group(1)
    return args


def safe_json(path: str) -> dict:
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def queue_status() -> dict:
    try:
        proc = subprocess.run(
            [sys.executable, str(QUEUE_SCRIPT), 'status'],
            capture_output=True,
            text=True,
            timeout=10,
        )
        data = json.loads(proc.stdout or '{}')
        if proc.returncode != 0 or not data.get('ok'):
            return {
                'ok': False,
                'status': data.get('status') or 'status_failed',
                'error': data.get('error') or proc.stderr,
                'length': None,
                'queue': [],
                'jobs': [],
            }
        return data
    except Exception as exc:
        return {
            'ok': False,
            'status': 'status_failed',
            'error': str(exc),
            'length': None,
            'queue': [],
            'jobs': [],
        }


def queue_items(status: Optional[dict] = None) -> list[dict]:
    q = status if status is not None else queue_status()
    queue = q.get('queue')
    return queue if isinstance(queue, list) else []


def comfy_queue_counts() -> dict:
    try:
        qdata = json.loads(urlopen('http://127.0.0.1:8188/queue', timeout=3).read().decode('utf-8'))
        running = qdata.get('queue_running') or []
        pending = qdata.get('queue_pending') or []
        return {
            'running': len(running),
            'pending': len(pending),
        }
    except Exception:
        return {'running': 0, 'pending': 0}


def summarize_meta(meta: dict) -> dict:
    if not isinstance(meta, dict):
        return {'person': '', 'scene': '', 'theme': '', 'title': ''}
    person = str(meta.get('person') or '').strip()
    scene = str(meta.get('scene') or '').strip()
    theme = str(meta.get('theme') or '').strip()
    title = ' · '.join(x for x in [person, scene, theme] if x)
    return {'person': person, 'scene': scene, 'theme': theme, 'title': title}


def summarize_queue_item(item: dict) -> dict:
    meta_file = str(item.get('meta_file') or '')
    meta = safe_json(meta_file) if meta_file else {}
    summary = summarize_meta(meta)
    return {
        'meta_file': meta_file,
        'person': summary['person'],
        'scene': summary['scene'],
        'theme': summary['theme'],
        'title': summary['title'] or Path(meta_file or '?').name,
    }


def gather_active_workers() -> list[dict]:
    workers = []
    paused_meta = ''
    if PAUSED_STATE.exists():
        paused_meta = str((safe_json(str(PAUSED_STATE)) or {}).get('meta_file') or '')

    for pid_file in sorted(WORK_DIR.glob(PID_GLOB), key=lambda p: p.stat().st_mtime, reverse=True):
        raw = read_text(pid_file).strip()
        if not raw.isdigit():
            continue
        pid = int(raw)
        if not pid_alive(pid):
            continue
        state = ps_state(pid)
        if state.startswith('Z'):
            continue
        command = ps_command(pid)
        if 'cu-worker.sh' not in command and 'cu-draw-card.py' not in command:
            continue
        log_file = pid_file.with_suffix('.log')
        meta = parse_log_metadata(log_file)
        meta_file = str(meta.get('meta_file', ''))
        if paused_meta and meta_file == paused_meta:
            continue
        meta_json = safe_json(meta_file)
        parsed_args = parse_worker_args(command)
        runtime_json = safe_json(str(RUNTIME_STATE)) if RUNTIME_STATE.exists() else {}
        workers.append({
            'pid': pid,
            'pid_file': str(pid_file),
            'log_file': str(log_file),
            'command': command,
            'ps_state': state,
            'args': parsed_args,
            'job_id': parsed_args.get('job_id') or runtime_json.get('job_id') or '',
            'card_id': parsed_args.get('card_id') or runtime_json.get('card_id') or meta_json.get('card_id') or '',
            'lease_token': parsed_args.get('lease_token') or runtime_json.get('lease_token') or '',
            'workflow': parsed_args.get('workflow') or runtime_json.get('workflow') or '',
            'seed': parsed_args.get('seed') or runtime_json.get('seed'),
            'meta_file': meta_file,
            'prompt_file': meta.get('prompt_file', ''),
            'done_file': meta.get('done_file', ''),
            'meta': meta_json,
        })
    return workers


def format_summary(worker: dict) -> str:
    meta = worker.get('meta') or {}
    summary = summarize_meta(meta)
    if summary['title']:
        return summary['title']
    return Path(worker.get('meta_file') or '?').name


def human_lock() -> str:
    if not GPU_LOCK.exists():
        return 'inactive'
    age = int(time.time() - GPU_LOCK.stat().st_mtime)
    return f'active ({age}s)'


def human_duration(seconds: int) -> str:
    seconds = max(0, int(seconds or 0))
    mins, sec = divmod(seconds, 60)
    hrs, mins = divmod(mins, 60)
    if hrs:
        return f'{hrs}小时{mins}分'
    if mins:
        return f'{mins}分{sec}秒'
    return f'{sec}秒'


def human_minutes(seconds: int) -> str:
    seconds = max(0, int(seconds or 0))
    return f'{seconds / 60:.1f} 分钟'


def read_runtime_state() -> dict:
    return safe_json(str(RUNTIME_STATE)) if RUNTIME_STATE.exists() else {}


def comfyui_progress() -> dict:
    try:
        qdata = json.loads(urlopen('http://127.0.0.1:8188/queue', timeout=3).read().decode('utf-8'))
        running = qdata.get('queue_running') or []
        if not running:
            return {}
        item = running[0]
        prompt = item[2] if len(item) > 2 and isinstance(item[2], dict) else {}
        total_steps = 0
        sampler_steps = {}
        sampler_nodes = []
        for node_id, node in prompt.items():
            if isinstance(node, dict) and str(node.get('class_type', '')).startswith('KSampler'):
                try:
                    steps = int(node.get('inputs', {}).get('steps', 0) or 0)
                except Exception:
                    steps = 0
                total_steps += steps
                sampler_steps[str(node_id)] = steps
                sampler_nodes.append(str(node_id))
        return {
            'prompt_id': item[1] if len(item) > 1 else '',
            'total_steps': total_steps or 28,
            'sampler_steps': sampler_steps,
            'sampler_nodes': sampler_nodes,
            'prompt': prompt,
        }
    except Exception:
        return {}


async def _ws_live_progress(prompt_id: str) -> dict:
    if not websockets or not prompt_id:
        return {}
    uri = 'ws://127.0.0.1:8188/ws?clientId=cu-draw-card'
    result = {}
    async with websockets.connect(uri, open_timeout=2, close_timeout=1) as ws:
        for _ in range(8):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.6)
            except asyncio.TimeoutError:
                continue
            if isinstance(raw, bytes):
                continue
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            mtype = msg.get('type')
            data = msg.get('data') or {}
            if mtype == 'progress_state' and data.get('prompt_id') == prompt_id:
                result['progress_state'] = data
            elif mtype == 'progress' and data.get('prompt_id') == prompt_id:
                result['progress'] = data
            elif mtype == 'executing':
                if data.get('prompt_id') == prompt_id or data.get('node'):
                    result['executing'] = data
            if result.get('progress_state') and result.get('progress'):
                break
    return result


def ws_live_progress(prompt_id: str) -> dict:
    try:
        return asyncio.run(_ws_live_progress(prompt_id))
    except Exception:
        return {}


def render_progress(runtime: dict) -> dict:
    start_epoch = int(runtime.get('start_epoch') or 0)
    if not start_epoch:
        return {}
    elapsed = max(0, int(time.time() - start_epoch))
    comfy = comfyui_progress()
    stage = str(runtime.get('stage') or '')
    pct = None
    eta_seconds = None
    source = 'estimate'
    node_label = ''

    if stage == 'delivering':
        pct = 98
        eta_seconds = 20
        source = 'stage'
    elif comfy:
        prompt_id = str(comfy.get('prompt_id') or '')
        live = ws_live_progress(prompt_id)
        progress_state = live.get('progress_state') or {}
        progress = live.get('progress') or {}
        sampler_steps = comfy.get('sampler_steps') or {}
        total_sampler_steps = sum(int(v or 0) for v in sampler_steps.values()) or int(comfy.get('total_steps') or 28)
        completed = 0.0
        running_done = 0.0
        running_node = ''

        nodes = progress_state.get('nodes') or {}
        for node_id, info in nodes.items():
            if str(node_id) not in sampler_steps:
                continue
            configured_steps = int(sampler_steps.get(str(node_id)) or 0)
            state = str((info or {}).get('state') or '')
            value = float((info or {}).get('value') or 0)
            maxv = float((info or {}).get('max') or 0)
            if state == 'finished':
                completed += configured_steps
            elif state == 'running':
                running_node = str(node_id)
                if maxv > 0:
                    running_done = configured_steps * min(1.0, value / maxv)
                else:
                    running_done = min(configured_steps, value)

        if not running_done and progress:
            node_id = str(progress.get('node') or '')
            configured_steps = int(sampler_steps.get(node_id) or 0)
            value = float(progress.get('value') or 0)
            maxv = float(progress.get('max') or 0)
            running_node = node_id
            if configured_steps and maxv > 0:
                running_done = configured_steps * min(1.0, value / maxv)

        if total_sampler_steps > 0 and (completed > 0 or running_done > 0):
            exact_pct = round(((completed + running_done) / total_sampler_steps) * 100)
            pct = min(97, max(1, exact_pct))
            typical_seconds = max(120, int(total_sampler_steps * 28))
            if pct > 0:
                projected_total = max(elapsed, int(elapsed / max(0.01, pct / 100)))
                eta_seconds = max(0, projected_total - elapsed)
            else:
                eta_seconds = max(0, typical_seconds - elapsed)
            source = 'websocket'
            node_label = running_node
        else:
            total_steps = int(comfy.get('total_steps') or 28)
            typical_seconds = max(120, int(total_steps * 28))
            pct = min(97, max(1, round(elapsed / typical_seconds * 100)))
            eta_seconds = max(0, typical_seconds - elapsed)
            source = 'steps-estimate'
    else:
        avg_m = typical_render_minutes()
        if avg_m and avg_m > 0:
            typical_seconds = int(avg_m * 60)
            pct = min(95, max(1, round(elapsed / typical_seconds * 100)))
            eta_seconds = max(0, typical_seconds - elapsed)
            source = 'delivery-avg'
        else:
            pct = None
            eta_seconds = None
            source = 'none'

    return {
        'elapsed_seconds': elapsed,
        'progress_pct': pct,
        'eta_seconds': eta_seconds,
        'source': source,
        'stage': stage,
        'node_label': node_label,
    }


def detect_stalled_state(workers: list[dict], queue: list[dict]) -> dict:
    done_files = sorted(WORK_DIR.glob('cu-draw-card-done_*.json'), key=lambda p: p.stat().st_mtime, reverse=True)
    recent_done = done_files[0] if done_files else None
    if GPU_LOCK.exists() and not workers and queue:
        return {
            'stalled': True,
            'reason': '队列未推进',
            'done_file': str(recent_done) if recent_done else '',
        }
    if GPU_LOCK.exists() and not workers and recent_done:
        return {
            'stalled': True,
            'reason': '存在完成文件但无活跃 worker',
            'done_file': str(recent_done),
        }
    return {'stalled': False, 'reason': '', 'done_file': ''}


def cmd_status() -> int:
    workers = gather_active_workers()
    local_status = queue_status()
    queue_ok = bool(local_status.get('ok'))
    queue = queue_items(local_status)
    paused = safe_json(str(PAUSED_STATE)) if PAUSED_STATE.exists() else {}
    comfy_counts = comfy_queue_counts()
    local_queue_len = len(queue)
    comfy_running = int(comfy_counts.get('running') or 0)
    comfy_pending = int(comfy_counts.get('pending') or 0)

    runtime = read_runtime_state()
    stalled = detect_stalled_state(workers, queue)
    lines = ['> 🎬 **draw_status**', '>']

    gpu_age = int(time.time() - GPU_LOCK.stat().st_mtime) if GPU_LOCK.exists() else 0
    if not queue_ok:
        state_label = '队列状态不可用'
    elif paused:
        state_label = '已暂停'
    elif stalled.get('stalled'):
        state_label = '异常卡住'
    elif workers or comfy_running:
        state_label = '渲染中'
    else:
        state_label = '空闲'
    lines.append('> **总览**')
    lines.append(f'> • GPU：{human_minutes(gpu_age) if GPU_LOCK.exists() else "空闲"}')
    lines.append(f'> • 本地队列：{local_queue_len if queue_ok else "不可用"}')
    lines.append(f'> • ComfyUI 运行中：{comfy_running}')
    lines.append(f'> • ComfyUI 排队：{comfy_pending}')
    lines.append(f'> • 待处理：{local_queue_len + comfy_pending if queue_ok else "不可用"}')
    lines.append(f'> • 状态：{state_label}')

    lines.append('>')
    lines.append('> **当前任务**')

    if workers:
        w = workers[0]
        s = summarize_meta(w.get('meta') or {})
        progress = render_progress(runtime if runtime else {'start_epoch': GPU_LOCK.stat().st_mtime if GPU_LOCK.exists() else 0, 'stage': 'rendering'})
        stage_map = {'boot': '准备中', 'startup': '启动中', 'rendering': '渲染中', 'delivering': '发送中'}
        lines.append(f'> • 人物：{s["person"] or "未识别"}')
        lines.append(f'> • 场景：{s["scene"] or "未识别"}')
        lines.append(f'> • 主题：{s["theme"] or "未识别"}')
        if progress:
            pct = progress.get("progress_pct")
            stage_label = stage_map.get(progress.get("stage"), "处理中")
            if pct is None:
                progress_text = f'进行中（{stage_label}，暂无均时样本）'
            else:
                progress_text = f'{pct}%（{stage_label}）'
                if progress.get('source') == 'websocket':
                    progress_text += ' [实时]'
                elif progress.get('source') == 'delivery-avg':
                    progress_text += ' [均时]'
            lines.append(f'> • 进度：{progress_text}')
            lines.append(f'> • 已渲染：{human_duration(progress.get("elapsed_seconds", 0))}')
            eta = progress.get("eta_seconds")
            if eta is not None:
                lines.append(f'> • 预计剩余：{human_duration(eta)}')
    elif paused:
        meta = paused.get('meta') or {}
        s = summarize_meta(meta)
        lines.append(f'> • 人物：{s["person"] or "未识别"}')
        lines.append(f'> • 场景：{s["scene"] or "未识别"}')
        lines.append(f'> • 主题：{s["theme"] or "未识别"}')
        lines.append('> • 状态：等待恢复')
    else:
        if stalled.get('stalled'):
            lines.append('> • 当前没有活跃绘图任务')
            lines.append(f'> • 异常：{stalled.get("reason") or "队列可能卡住"}')
        else:
            lines.append('> • 当前没有活跃绘图任务')

    lines.append('>')
    lines.append('> **队列**')
    if not queue_ok:
        lines.append(f'> • QueueStore 查询失败：{local_status.get("status")} / {local_status.get("error")}')
    elif queue:
        for idx, item in enumerate(queue, 1):
            q = summarize_queue_item(item)
            lines.append(f'> {idx}. {q["person"] or "未命名任务"}')
            if q['scene']:
                lines.append(f'>    • 场景：{q["scene"]}')
            if q['theme']:
                lines.append(f'>    • 主题：{q["theme"]}')
            if idx != len(queue):
                lines.append('>')
    elif comfy_pending:
        lines.append(f'> • 本地队列为空，但 ComfyUI 内部仍有 {comfy_pending} 个待处理任务')
    else:
        lines.append('> • 队列为空')

    print('\n'.join(lines))
    return 0


def kill_process_group(pid: int, sig: int) -> None:
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, sig)
    except Exception:
        pass


def wait_dead(pid: int, seconds: float) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.2)
    return not pid_alive(pid)


def cmd_pause() -> int:
    workers = gather_active_workers()
    if not workers:
        lines = ['> ⏸️ **draw_pause**', '>']
        lines.append('> **结果**')
        lines.append('> • 当前没有活跃绘图 worker')
        lines.append(f'> • GPU 锁：{human_lock()}')
        if GPU_LOCK.exists():
            lines.append('> • 如需只清锁，请手动处理或后续补 draw_cancel')
        print('\n'.join(lines))
        return 0

    w = workers[0]
    job_id = str(w.get('job_id') or '')
    lease_token = str(w.get('lease_token') or '')
    if not job_id or not lease_token:
        print('\n'.join([
            '> ⏸️ **draw_pause**',
            '>',
            '> **结果**',
            '> • 当前 worker 缺少 job_id / lease token，拒绝无条件暂停',
        ]))
        return 1
    try:
        pause_proc = subprocess.run(
            [
                sys.executable,
                str(QUEUE_SCRIPT),
                'pause',
                '--job-id',
                job_id,
                '--lease-token',
                lease_token,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        pause_ack = json.loads(pause_proc.stdout or '{}')
    except Exception as exc:
        pause_ack = {'ok': False, 'status': 'pause_error', 'error': str(exc)}
        pause_proc = None
    if not pause_ack.get('ok') or pause_ack.get('status') != 'paused':
        print('\n'.join([
            '> ⏸️ **draw_pause**',
            '>',
            '> **结果**',
            f'> • QueueStore 未确认暂停，worker 保持运行：{pause_ack}',
        ]))
        return 1

    pause_state = {
        'pausedAt': int(time.time()),
        'job_id': job_id,
        'card_id': w.get('card_id') or '',
        'lease_token': lease_token,
        'workflow': w.get('workflow') or '',
        'seed': w.get('seed'),
        'pid': w['pid'],
        'pid_file': w['pid_file'],
        'log_file': w['log_file'],
        'meta_file': w['meta_file'],
        'prompt_file': w['prompt_file'],
        'done_file': w['done_file'],
        'args': w.get('args') or {},
        'meta': w.get('meta') or {},
        'summary': format_summary(w),
        'idempotency_key': w.get('idempotency_key'),
    }
    PAUSED_STATE.write_text(json.dumps(pause_state, ensure_ascii=False, indent=2), encoding='utf-8')

    kill_process_group(w['pid'], signal.SIGTERM)
    if not wait_dead(w['pid'], 3.0):
        kill_process_group(w['pid'], signal.SIGKILL)
        wait_dead(w['pid'], 2.0)

    GPU_LOCK.unlink(missing_ok=True)

    lines = ['> ⏸️ **draw_pause**', '>']
    lines.append('> **结果**')
    lines.append('> • 已暂停')
    lines.append(f'> • 任务：{pause_state["summary"]}')
    lines.append(f'> • Worker：#{w["pid"]}')
    lines.append('> • GPU 锁：已释放')
    lines.append('>')
    lines.append('> **后续操作**')
    lines.append('> • 现在可以先修改卡片内容')
    lines.append('> • 修改完后，可手动继续 chain --resume')
    lines.append('> • 或直接使用 /draw_resume 恢复后台任务')
    print('\n'.join(lines))
    return 0


def cmd_resume() -> int:
    paused = safe_json(str(PAUSED_STATE)) if PAUSED_STATE.exists() else {}
    job_id = str(paused.get('job_id') or '')
    cmd = [sys.executable, str(QUEUE_SCRIPT), 'resume']
    if job_id:
        cmd += ['--job-id', job_id]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        res = json.loads(proc.stdout or '{}')
    except Exception as exc:
        print('\n'.join([
            '> ▶️ **draw_resume**',
            '>',
            '> **结果**',
            f'> • 恢复队列发生异常：{exc}',
        ]))
        return 1

    status = res.get('status')
    if status == 'lock_busy':
        print('\n'.join([
            '> ▶️ **draw_resume**',
            '>',
            '> **结果**',
            '> • QueueStore 正在执行另一笔事务，请稍后重试',
        ]))
        return 75
    if proc.returncode != 0 or not res.get('ok'):
        print('\n'.join([
            '> ▶️ **draw_resume**',
            '>',
            '> **结果**',
            f'> • QueueStore 恢复未确认：{res.get("error") or status or proc.stderr}',
        ]))
        return 1
    if status == 'started':
        PAUSED_STATE.unlink(missing_ok=True)
        print('\n'.join([
            '> ▶️ **draw_resume**',
            '>',
            '> **结果**',
            f'> • {"已恢复暂停任务" if job_id else "已自动续跑本地队列"}',
            f'> • Job：{res.get("job_id") or "unknown"}',
            f'> • 任务：{res.get("summary", {}).get("title") or paused.get("summary") or "未命名"}',
            f'> • Worker：#{res.get("pid") or "unknown"}',
            f'> • 队列剩余：{res.get("remaining", 0)}',
        ]))
        return 0
    if status == 'busy':
        reason_map = {'gpu_lock_active': 'GPU 锁占用中', 'worker_running': '工作线程运行中'}
        reason = reason_map.get(res.get('reason'), res.get('reason'))
        print('\n'.join([
            '> ▶️ **draw_resume**',
            '>',
            '> **结果**',
            f'> • 队列当前正忙，无需恢复 ({reason})',
        ]))
        return 0
    if status == 'empty':
        print('\n'.join([
            '> ▶️ **draw_resume**',
            '>',
            '> **结果**',
            '> • 本地队列为空',
        ]))
        return 0
    print('\n'.join([
        '> ▶️ **draw_resume**',
        '>',
        '> **结果**',
        f'> • 未知恢复 ACK：{res}',
    ]))
    return 1


def cmd_terminate() -> int:
    workers = gather_active_workers()
    killed = 0
    queue_failures = []
    for w in workers:
        job_id = str(w.get('job_id') or '')
        lease_token = str(w.get('lease_token') or '')
        if job_id and lease_token:
            try:
                qproc = subprocess.run(
                    [
                        sys.executable,
                        str(QUEUE_SCRIPT),
                        'nack',
                        '--job-id',
                        job_id,
                        '--lease-token',
                        lease_token,
                        '--error',
                        'terminated_by_control',
                        '--no-retry',
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                qack = json.loads(qproc.stdout or '{}')
                if qproc.returncode != 0 or not qack.get('ok'):
                    queue_failures.append(qack or {'status': 'invalid_ack'})
            except Exception as exc:
                queue_failures.append({'status': 'nack_error', 'error': str(exc)})
        kill_process_group(w['pid'], signal.SIGTERM)
        if not wait_dead(w['pid'], 3.0):
            kill_process_group(w['pid'], signal.SIGKILL)
            wait_dead(w['pid'], 2.0)
        killed += 1

    # 杀掉正在运行的 delivery/draw-card 进程（防止已完成的图片继续发送）
    deliver_killed = 0
    try:
        result = subprocess.run(['pgrep', '-f', r'cu-deliver\.sh|cu-draw-card\.py'],
                                capture_output=True, text=True, timeout=5)
        for pid_str in (result.stdout or '').strip().splitlines():
            pid_str = pid_str.strip()
            if not pid_str or not pid_str.isdigit():
                continue
            pid = int(pid_str)
            try:
                os.kill(pid, signal.SIGTERM)
                deliver_killed += 1
            except (ProcessLookupError, PermissionError):
                pass
    except Exception:
        pass

    GPU_LOCK.unlink(missing_ok=True)
    PAUSED_STATE.unlink(missing_ok=True)

    cleared_count = 0
    try:
        clear_proc = subprocess.run(
            [sys.executable, str(QUEUE_SCRIPT), 'clear', '--force'],
            capture_output=True,
            text=True,
            timeout=10,
        )
        clear_ack = json.loads(clear_proc.stdout or '{}')
        if clear_proc.returncode != 0 or not clear_ack.get('ok'):
            queue_failures.append(clear_ack or {'status': 'clear_invalid_ack'})
        else:
            cleared_count = int(clear_ack.get('count') or 0)
    except Exception as exc:
        queue_failures.append({'status': 'clear_error', 'error': str(exc)})

    try:
        subprocess.run([sys.executable, str(QUEUE_SCRIPT), 'drafts', '--clean'], capture_output=True, text=True, timeout=10)
    except Exception:
        pass

    try:
        subprocess.run(['bash', str(COMFYUI_START), 'stop'],
                       capture_output=True, text=True, timeout=30)
    except Exception:
        pass

    lines = ['> 💣 **draw_terminate**', '>']
    lines.append('> **结果**')
    lines.append(f'> • 已终止 {killed} 个 worker')
    lines.append(f'> • 已清理 {cleared_count} 个等待任务')
    if deliver_killed:
        lines.append(f'> • 已终止 {deliver_killed} 个 delivery 进程')
    lines.append('> • GPU 锁已释放')
    lines.append('> • 草稿已清理')
    lines.append('> • ComfyUI 已停止')
    if queue_failures:
        lines.append(f'> • ⚠️ QueueStore 未完全确认：{queue_failures}')
    print('\n'.join(lines))
    return 1 if queue_failures else 0


def cmd_clear() -> int:
    try:
        proc = subprocess.run([sys.executable, str(QUEUE_SCRIPT), 'clear', '--force'], capture_output=True, text=True, timeout=10)
        res = json.loads(proc.stdout)
        status = res.get('status')
        if status == 'cleared':
            print('\n'.join([
                '> 🧹 **draw_clear**',
                '>',
                '> **结果**',
                f'> • 成功清空本地队列（移除了 {res.get("count", 0)} 张卡片）',
            ]))
            return 0
        elif status == 'already_empty':
            print('\n'.join([
                '> 🧹 **draw_clear**',
                '>',
                '> **结果**',
                '> • 本地队列本来就是空的，无需清理',
            ]))
            return 0
        else:
            print('\n'.join([
                '> 🧹 **draw_clear**',
                '>',
                '> **结果**',
                f'> • 清空失败: {proc.stdout or proc.stderr}',
            ]))
            return 1
    except Exception as e:
        print('\n'.join([
            '> 🧹 **draw_clear**',
            '>',
            '> **结果**',
            f'> • 清空发生异常：{e}',
        ]))
        return 1


def main() -> int:
    args = parse_args()
    if args.cmd == 'status':
        return cmd_status()
    if args.cmd == 'pause':
        return cmd_pause()
    if args.cmd == 'resume':
        return cmd_resume()
    if args.cmd == 'terminate':
        return cmd_terminate()
    if args.cmd == 'clear':
        return cmd_clear()
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
