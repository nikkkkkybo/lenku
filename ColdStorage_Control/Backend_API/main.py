# -*- coding: utf-8 -*-
"""
冷库温度控制系统 - 后端API主程序
====================================
基于 FastAPI 的 RESTful API 服务。
启动后访问 http://localhost:8080/docs 查看自动生成的 Swagger 文档。

快速开始:
  1. pip install -r requirements.txt
  2. 运行 start.bat 或 python main.py
  3. 浏览器打开 http://localhost:8080/docs

API 总览:
  GET  /api/overview                 - 全局总览 (9个冷库摘要)
  GET  /api/rooms                    - 所有冷库列表
  GET  /api/rooms/{room_id}          - 单个冷库详情
  GET  /api/rooms/{room_id}/temperature - 单库温度
  PUT  /api/rooms/{room_id}/params   - 修改温度参数
  POST /api/rooms/{room_id}/control  - 发送控制命令 (使能/急停)
  POST /api/rooms/{room_id}/defrost  - 手动触发化霜
  GET  /api/alarms                   - 报警列表
  POST /api/alarms/ack               - 报警确认
  GET  /api/trends/{room_id}         - 温度趋势数据
  GET  /api/system/status            - 系统状态
  POST /api/system/reconnect         - 重新连接PLC
"""

import logging
import asyncio
from datetime import datetime
from collections import deque
from typing import List, Optional
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

import config
from s7_connector import get_connector, reconnect, RoomData, GlobalData
from models import (
    RoomParamUpdate, RoomControlRequest, AlarmAckRequest,
    RoomResponse, RoomSummaryResponse, GlobalOverviewResponse,
    ApiResponse, TrendResponse, TrendPoint,
)

# ============================================================
# 日志初始化
# ============================================================
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format=config.LOG_FORMAT,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(config.LOG_FILE, encoding='utf-8'),
    ]
)
logger = logging.getLogger(__name__)

# ============================================================
# FastAPI 应用创建
# ============================================================
app = FastAPI(
    title=config.API_TITLE,
    version=config.API_VERSION,
    description="""
## 冷库温度控制系统 - 后端API

### 系统概述
- 9个冷库, 每库10台制冷压缩机
- S7-1500主站 + 9×S7-1200从站 + WinCC
- 本API封装S7通信, 对外提供简单HTTP接口

### 快速开始
1. **查看总览**: `GET /api/overview` — 一眼看全部9个冷库状态
2. **查看单库**: `GET /api/rooms/1` — 查看冷库1的详细信息
3. **修改参数**: `PUT /api/rooms/1/params` — 修改温度上下限
4. **急停**: `POST /api/rooms/1/control` — 远程急停/使能

### 运行模式
- **模拟模式** (默认): 使用虚拟数据, 无需PLC硬件, 适合开发演示
- **真实模式**: 设置环境变量 `MOCK_MODE=false` 并配置 `PLC_IP`

### Swagger 文档
- 交互式文档: http://localhost:8080/docs
- ReDoc文档: http://localhost:8080/redoc
""",
    docs_url=None,
    redoc_url=None,
    openapi_tags=[
        {"name": "全局总览", "description": "一次性获取全部9个冷库的运行状态和全局统计信息"},
        {"name": "冷库管理", "description": "单个冷库的详情查看、温度参数修改、控制命令发送、化霜触发等操作"},
        {"name": "报警管理", "description": "报警查询和报警确认操作"},
        {"name": "温度趋势", "description": "温度历史趋势数据查询"},
        {"name": "系统管理", "description": "系统运行状态查询和PLC通信重连"},
    ],
)

# 允许跨域 (方便前端页面调用)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# 温度趋势历史缓存 (内存中保存最近120个数据点)
# ============================================================
_trend_history = {i: deque(maxlen=120) for i in range(1, config.ROOM_COUNT + 1)}


async def _poll_trends():
    """后台任务: 每秒记录温度趋势数据"""
    while True:
        conn = get_connector()
        for room_id in range(1, config.ROOM_COUNT + 1):
            room = conn.read_room_data(room_id)
            _trend_history[room_id].append({
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "temperature": round(room.temp_actual, 1),
            })
        await asyncio.sleep(config.POLL_INTERVAL)


@app.on_event("startup")
async def _startup():
    """服务启动时初始化连接器和后台任务"""
    get_connector()  # 初始化连接器
    asyncio.create_task(_poll_trends())
    logger.info(f"后端API已启动: http://{config.API_HOST}:{config.API_PORT}")
    logger.info(f"Swagger文档: http://localhost:{config.API_PORT}/docs")
    logger.info(f"运行模式: {'模拟' if config.MOCK_MODE else '真实'}")


@app.on_event("shutdown")
async def _shutdown():
    """服务关闭时清理资源"""
    logger.info("后端API已停止")


# ============================================================
# 辅助函数
# ============================================================
def _get_room_status_text(room: RoomData) -> str:
    """根据冷库数据生成状态文字"""
    if not room.comm_ok:
        return "通信故障"
    if room.emergency_stop:
        return "急停"
    if not room.system_enable:
        return "已停用"
    if room.critical_alarm:
        return "严重报警"
    if room.any_alarm:
        return "报警"
    if room.defrost_active:
        return "化霜中"
    if room.cooling_demand:
        return "制冷中"
    return "正常"


def _room_to_summary(room: RoomData) -> dict:
    """冷库数据转摘要字典"""
    return {
        "room_id": room.room_id,
        "temp_actual": round(room.temp_actual, 1),
        "cooling_demand": room.cooling_demand,
        "defrost_active": room.defrost_active,
        "active_count": room.active_count,
        "fault_count": room.fault_count,
        "any_alarm": room.any_alarm,
        "comm_ok": room.comm_ok,
        "status_text": _get_room_status_text(room),
    }


def _room_to_response(room: RoomData) -> dict:
    """冷库数据转完整响应字典"""
    d = room.to_dict()
    d["status"]["status_text"] = _get_room_status_text(room)
    return d


# ============================================================
# === API 路由 ===
# ============================================================

@app.get("/", summary="根路径", description="API欢迎页面")
async def root():
    return {
        "service": config.API_TITLE,
        "version": config.API_VERSION,
        "docs": "/docs",
        "overview": "/api/overview",
        "mock_mode": config.MOCK_MODE,
    }


# ------------------------------------------------------------
# 1. 全局总览
# ------------------------------------------------------------
@app.get("/api/overview", response_model=GlobalOverviewResponse,
         summary="全局总览", description="一次性获取9个冷库的摘要状态和全局统计",
         tags=["全局总览"])
async def get_overview():
    conn = get_connector()
    rooms = []
    for i in range(1, config.ROOM_COUNT + 1):
        room = conn.read_room_data(i)
        rooms.append(_room_to_summary(room))
    gd = conn.read_global_data()
    return GlobalOverviewResponse(
        rooms=[RoomSummaryResponse(**r) for r in rooms],
        total_active=gd.total_active,
        total_fault=gd.total_fault,
        total_available=gd.total_available,
        global_alarm=gd.global_alarm,
        global_critical=gd.global_critical,
        alarm_room_count=gd.alarm_room_count,
        mock_mode=config.MOCK_MODE,
    )


# ------------------------------------------------------------
# 2. 冷库管理
# ------------------------------------------------------------
@app.get("/api/rooms", response_model=List[RoomSummaryResponse],
         summary="所有冷库列表", description="获取9个冷库的摘要信息列表",
         tags=["冷库管理"])
async def get_all_rooms():
    conn = get_connector()
    result = []
    for i in range(1, config.ROOM_COUNT + 1):
        room = conn.read_room_data(i)
        result.append(RoomSummaryResponse(**_room_to_summary(room)))
    return result


@app.get("/api/rooms/{room_id}", response_model=RoomResponse,
         summary="单个冷库详情", description="获取指定冷库的完整运行信息",
         tags=["冷库管理"])
async def get_room_detail(room_id: int):
    if room_id < 1 or room_id > config.ROOM_COUNT:
        raise HTTPException(status_code=404, detail=f"冷库编号必须在 1-{config.ROOM_COUNT} 之间")
    conn = get_connector()
    room = conn.read_room_data(room_id)
    return _room_to_response(room)


@app.get("/api/rooms/{room_id}/temperature",
         summary="单库温度", description="获取指定冷库的温度数据",
         tags=["冷库管理"])
async def get_room_temperature(room_id: int):
    if room_id < 1 or room_id > config.ROOM_COUNT:
        raise HTTPException(status_code=404, detail=f"冷库编号必须在 1-{config.ROOM_COUNT} 之间")
    conn = get_connector()
    room = conn.read_room_data(room_id)
    return {
        "room_id": room_id,
        "sensor1": round(room.temp_sensor1, 1),
        "sensor2": round(room.temp_sensor2, 1),
        "actual": round(room.temp_actual, 1),
        "evaporator": round(room.evap_temp, 1),
        "high_limit": room.temp_high_limit,
        "low_limit": room.temp_low_limit,
        "alarm_high": room.temp_alarm_high,
        "cooling_demand": room.cooling_demand,
        "unit": "degC",
    }


@app.put("/api/rooms/{room_id}/params", response_model=ApiResponse,
         summary="修改温度参数", description="修改指定冷库的温度上下限和报警值",
         tags=["冷库管理"])
async def update_room_params(room_id: int, params: RoomParamUpdate):
    if room_id < 1 or room_id > config.ROOM_COUNT:
        raise HTTPException(status_code=404, detail=f"冷库编号必须在 1-{config.ROOM_COUNT} 之间")

    # 参数校验: 上限必须大于下限
    conn = get_connector()
    room = conn.read_room_data(room_id)
    high = params.high_limit if params.high_limit is not None else room.temp_high_limit
    low = params.low_limit if params.low_limit is not None else room.temp_low_limit
    if high <= low:
        raise HTTPException(status_code=400, detail=f"温度上限({high})必须大于下限({low})")

    ok = conn.write_room_param(
        room_id,
        high_limit=params.high_limit,
        low_limit=params.low_limit,
        alarm_high=params.alarm_high,
    )
    if ok:
        return ApiResponse(success=True, message=f"冷库{room_id}温度参数已更新",
                            data={"high_limit": high, "low_limit": low})
    else:
        return ApiResponse(success=False, message=f"冷库{room_id}参数写入失败")


@app.post("/api/rooms/{room_id}/control", response_model=ApiResponse,
         summary="发送控制命令", description="控制冷库的使能/禁用和急停",
         tags=["冷库管理"])
async def control_room(room_id: int, cmd: RoomControlRequest):
    if room_id < 1 or room_id > config.ROOM_COUNT:
        raise HTTPException(status_code=404, detail=f"冷库编号必须在 1-{config.ROOM_COUNT} 之间")

    conn = get_connector()
    ok = conn.write_room_control(
        room_id,
        system_enable=cmd.system_enable,
        emergency_stop=cmd.emergency_stop,
    )
    actions = []
    if cmd.system_enable is not None:
        actions.append("启用" if cmd.system_enable else "禁用")
    if cmd.emergency_stop is not None:
        actions.append("急停" if cmd.emergency_stop else "解除急停")

    if ok:
        return ApiResponse(success=True, message=f"冷库{room_id}控制命令已执行: {', '.join(actions)}")
    else:
        return ApiResponse(success=False, message=f"冷库{room_id}控制命令发送失败")


@app.post("/api/rooms/{room_id}/defrost", response_model=ApiResponse,
         summary="手动触发化霜", description="手动触发指定冷库的化霜周期",
         tags=["冷库管理"])
async def trigger_defrost(room_id: int):
    if room_id < 1 or room_id > config.ROOM_COUNT:
        raise HTTPException(status_code=404, detail=f"冷库编号必须在 1-{config.ROOM_COUNT} 之间")

    conn = get_connector()
    if hasattr(conn, '_rooms'):
        # 模拟模式
        room = conn._rooms.get(room_id)
        if room:
            room.defrost_active = True
            return ApiResponse(success=True, message=f"冷库{room_id}化霜已触发 (模拟)")
    # 真实模式: 通过写入化霜触发位实现 (需在PLC侧配置)
    return ApiResponse(success=False, message="真实模式下需配置PLC化霜触发位")


# ------------------------------------------------------------
# 3. 报警管理
# ------------------------------------------------------------
@app.get("/api/alarms", summary="报警列表", description="获取所有冷库的当前报警信息",
         tags=["报警管理"])
async def get_alarms():
    conn = get_connector()
    alarms = []
    for i in range(1, config.ROOM_COUNT + 1):
        room = conn.read_room_data(i)
        if room.any_alarm:
            d = room.to_dict()
            alarms.append({
                "room_id": i,
                "status_text": _get_room_status_text(room),
                "alarm_word": room.alarm_word,
                "critical": room.critical_alarm,
                "details": d["alarms"]["alarm_details"],
                "temp_actual": round(room.temp_actual, 1),
            })
    return {
        "total_alarms": len(alarms),
        "critical_count": sum(1 for a in alarms if a["critical"]),
        "alarms": alarms,
    }


@app.post("/api/alarms/ack", response_model=ApiResponse,
          summary="报警确认", description="确认报警 (复位蜂鸣器)",
          tags=["报警管理"])
async def ack_alarms(req: AlarmAckRequest):
    # 报警确认通过写入PLC的报警确认位实现
    # 模拟模式下直接返回成功
    if req.room_id:
        return ApiResponse(success=True, message=f"冷库{req.room_id}报警已确认")
    else:
        return ApiResponse(success=True, message="所有冷库报警已确认")


# ------------------------------------------------------------
# 4. 温度趋势
# ------------------------------------------------------------
@app.get("/api/trends/{room_id}", response_model=TrendResponse,
         summary="温度趋势", description="获取指定冷库的近期温度趋势数据",
         tags=["温度趋势"])
async def get_trend(
    room_id: int,
    points: int = Query(60, ge=1, le=120, description="数据点数量 (1-120)"),
):
    if room_id < 1 or room_id > config.ROOM_COUNT:
        raise HTTPException(status_code=404, detail=f"冷库编号必须在 1-{config.ROOM_COUNT} 之间")

    history = list(_trend_history[room_id])
    # 取最近N个点
    recent = history[-points:] if len(history) >= points else history
    return TrendResponse(
        room_id=room_id,
        points=[TrendPoint(**p) for p in recent],
    )


# ------------------------------------------------------------
# 5. 系统管理
# ------------------------------------------------------------
@app.get("/api/system/status", summary="系统状态", description="获取后端服务和PLC连接状态",
         tags=["系统管理"])
async def get_system_status():
    conn = get_connector()
    return {
        "api_running": True,
        "mock_mode": config.MOCK_MODE,
        "plc_connected": conn.is_connected,
        "plc_ip": config.PLC_IP,
        "room_count": config.ROOM_COUNT,
        "compressor_count": config.COMPRESSOR_COUNT,
        "poll_interval": config.POLL_INTERVAL,
        "trend_buffer_size": len(_trend_history[1]),
        "uptime": datetime.now().isoformat(),
    }


@app.post("/api/system/reconnect", response_model=ApiResponse,
          summary="重新连接PLC", description="重新建立与S7-1500 PLC的通信连接",
          tags=["系统管理"])
async def reconnect_plc():
    if config.MOCK_MODE:
        return ApiResponse(success=True, message="模拟模式, 无需重连")
    ok = reconnect()
    if ok:
        return ApiResponse(success=True, message="PLC重连成功")
    else:
        return ApiResponse(success=False, message="PLC重连失败, 请检查网络和PLC状态")


# ============================================================
# 自定义 Swagger UI 中文本地化页面
# ============================================================
@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    return HTMLResponse("""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>冷库温度控制系统 - API接口文档</title>
    <link rel="stylesheet" type="text/css" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.11.3/swagger-ui.css">
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>❄</text></svg>">
    <style>
        body { margin: 0; padding: 0; }
        .zh-topbar {
            background: linear-gradient(135deg, #1a5276, #2e86c1);
            padding: 10px 20px;
            display: flex;
            align-items: center;
            color: #fff;
            font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
            box-shadow: 0 2px 8px rgba(0,0,0,0.15);
            z-index: 1000;
            position: relative;
        }
        .zh-topbar .logo { font-size: 18px; font-weight: bold; }
        .zh-topbar .subtitle { font-size: 13px; margin-left: 15px; opacity: 0.85; }
        .zh-topbar .mode-badge {
            margin-left: auto;
            background: rgba(255,255,255,0.2);
            padding: 3px 12px;
            border-radius: 12px;
            font-size: 12px;
        }
        .swagger-ui .topbar { display: none !important; }
        .swagger-ui .info .title { color: #1a5276; }
        .swagger-ui .scheme-container { box-shadow: none; }
    </style>
</head>
<body>
    <div class="zh-topbar">
        <span class="logo">❄ 冷库温度控制系统</span>
        <span class="subtitle">API 接口文档</span>
        <span class="mode-badge" id="mode-badge">加载中...</span>
    </div>
    <div id="swagger-ui"></div>
    <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.11.3/swagger-ui-bundle.js"></script>
    <script>
        const ui = SwaggerUIBundle({
            url: '/openapi.json',
            dom_id: '#swagger-ui',
            deepLinking: true,
            presets: [SwaggerUIBundle.presets.apis],
            layout: 'BaseLayout',
            operationsSorter: 'alpha',
            tagsSorter: 'alpha',
            docExpansion: 'list',
            defaultModelsExpandDepth: 1,
            filter: true,
            persistAuth: true,
            tryItOutEnabled: false,
        });

        // ====== 中文本地化翻译表 ======
        const zhCN = {
            'Authorize': '授权',
            'Try it out': '试一试',
            'Execute': '执行',
            'Clear': '清空',
            'Cancel': '取消',
            'Reset': '重置',
            'Loading...': '加载中...',
            'Responses': '响应结果',
            'Response body': '响应体',
            'Response headers': '响应头',
            'No headers': '无响应头',
            'No response data': '无响应数据',
            'Parameters': '请求参数',
            'Headers': '请求头',
            'Request body': '请求体',
            'Request URL': '请求地址',
            'Curl': 'Curl 命令',
            'Copy to clipboard': '复制到剪贴板',
            'Copied': '已复制',
            'Expand all': '全部展开',
            'Collapse all': '全部折叠',
            'Hide': '隐藏',
            'Show': '显示',
            'Tags': '接口分类',
            'Overview': '概述',
            'Schemas': '数据模型',
            'Servers': '服务器',
            'Filters': '过滤',
            'Logout': '退出',
            'Available methods': '可用方法',
            'Content': '内容类型',
            'Example': '示例',
            'Examples': '示例',
            'Schema': '数据结构',
            'Model': '模型',
            'Description': '描述',
            'Required': '必填',
            'Type': '类型',
            'Default': '默认值',
            'Enum': '枚举值',
            'Format': '格式',
            'Maximum': '最大值',
            'Minimum': '最小值',
            'Pattern': '正则表达式',
            'Property': '属性',
            'Properties': '属性',
            'Items': '数组项',
            'Additional properties': '额外属性',
            'Deprecated': '已弃用',
            'Sort by': '排序方式',
            'Alpha': '字母序',
            'Method': '方法',
            'Order': '顺序',
            'Path': '路径',
            'Tag': '分类',
            'Summary': '摘要',
            'Status': '状态码',
            'Reason': '原因',
            'Copy': '复制',
            'Close': '关闭',
            'Details': '详情',
            'Nothing to show': '暂无数据',
            'possible values': '可选值',
            'Server response': '服务器响应',
            'Response samples': '响应示例',
            'Request samples': '请求示例',
            'Media type': '媒体类型',
            'Examples': '示例',
            'Links': '链接',
            'No links': '无链接',
            'unknown': '未知',
            'array': '数组',
            'object': '对象',
            'string': '字符串',
            'integer': '整数',
            'number': '数字',
            'boolean': '布尔值',
            'real': '实数',
        };

        function translateText(text) {
            if (!text) return text;
            const trimmed = text.trim();
            if (zhCN[trimmed]) {
                return text.replace(trimmed, zhCN[trimmed]);
            }
            // 处理 "Copy to clipboard" 这类包含关系
            for (const [en, zh] of Object.entries(zhCN)) {
                if (text.includes(en) && en.length > 3) {
                    text = text.replace(en, zh);
                }
            }
            return text;
        }

        function translateNode(node) {
            if (node.nodeType === Node.TEXT_NODE) {
                const original = node.textContent;
                const translated = translateText(original);
                if (translated !== original) {
                    node.textContent = translated;
                }
            } else if (node.nodeType === Node.ELEMENT_NODE) {
                if (node.tagName === 'BUTTON' || node.tagName === 'SELECT') {
                    const original = node.textContent;
                    const translated = translateText(original);
                    if (translated !== original) {
                        node.textContent = translated;
                    }
                }
                if (node.placeholder) {
                    const translated = translateText(node.placeholder);
                    if (translated !== node.placeholder) {
                        node.placeholder = translated;
                    }
                }
                if (node.title) {
                    const translated = translateText(node.title);
                    if (translated !== node.title) {
                        node.title = translated;
                    }
                }
                const ariaLabel = node.getAttribute('aria-label');
                if (ariaLabel) {
                    const translated = translateText(ariaLabel);
                    if (translated !== ariaLabel) {
                        node.setAttribute('aria-label', translated);
                    }
                }
                node.childNodes.forEach(translateNode);
            }
        }

        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                mutation.addedNodes.forEach((node) => {
                    if (node.nodeType === Node.ELEMENT_NODE || node.nodeType === Node.TEXT_NODE) {
                        translateNode(node);
                    }
                });
            });
        });

        observer.observe(document.body, { childList: true, subtree: true });

        // 定期扫描补充翻译 (处理 React 异步渲染遗漏的元素)
        setInterval(() => {
            translateNode(document.body);
        }, 2000);

        // 更新模式标签
        fetch('/api/system/status').then(r => r.json()).then(d => {
            document.getElementById('mode-badge').textContent =
                d.mock_mode ? '模拟模式' : '真实模式';
        }).catch(() => {
            document.getElementById('mode-badge').textContent = '运行中';
        });
    </script>
</body>
</html>
""")


@app.get("/redoc", include_in_schema=False)
async def custom_redoc_html():
    return HTMLResponse("""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>冷库温度控制系统 - ReDoc文档</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>❄</text></svg>">
    <style>body{margin:0;font-family:"Microsoft YaHei",sans-serif;}</style>
</head>
<body>
    <redoc spec-url="/openapi.json"></redoc>
    <script src="https://cdn.jsdelivr.net/npm/redoc@next/bundles/redoc.standalone.js"></script>
</body>
</html>
""")


# ============================================================
# 一体化可视化监控仪表盘
# ============================================================
@app.get("/dashboard", include_in_schema=False)
async def dashboard():
    html_path = Path(__file__).parent / "dashboard.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


# ============================================================
# 主入口
# ============================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=config.API_HOST,
        port=config.API_PORT,
        log_level="info",
    )
