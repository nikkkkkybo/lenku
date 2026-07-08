# 冷库温度控制系统

基于西门子 S7-1500 + 9×S7-1200 PLC 的分布式冷库温度控制系统，配套 Python/FastAPI 后端API与 WinCC 上位机组态。

## 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                    外部客户端                            │
│         (Web页面 / 手机APP / ERP系统 / MES)              │
└────────────────────┬────────────────────────────────────┘
                     │ HTTP REST API (JSON)
┌────────────────────┴────────────────────────────────────┐
│              后端API服务 (Python/FastAPI)                │
│              Swagger文档: /docs                          │
└────────────────────┬────────────────────────────────────┘
                     │ snap7 / S7协议
┌────────────────────┴────────────────────────────────────┐
│            WinCC 上位机 (SCADA监控)                      │
│            5个画面: 总览/详情/报警/参数/趋势             │
└────────────────────┬────────────────────────────────────┘
                     │ PROFINET
┌────────────────────┴────────────────────────────────────┐
│          S7-1500 主站 (192.168.0.1)                     │
│          通信管理 + 数据汇总 + WinCC接口                 │
└──┬───────┬───────┬───────┬───────┬───────┬───────┬──────┘
   │       │       │       │       │       │       │
┌──┴──┐ ┌─┴───┐ ┌─┴───┐ ┌─┴───┐ ┌─┴───┐ ┌─┴───┐ ┌─┴───┐
│S7-  │ │S7-  │ │S7-  │ │S7-  │ │S7-  │ │S7-  │ │S7-  │
│1200 │ │1200 │ │1200 │ │1200 │ │1200 │ │1200 │ │1200 │
│库1  │ │库2  │ │库3  │ │库4  │ │库5  │ │库6-8│ │库9  │
│10台 │ │10台 │ │10台 │ │10台 │ │10台 │ │...  │ │10台 │
└─────┘ └─────┘ └─────┘ └─────┘ └─────┘ └─────┘ └─────┘
```

## 功能特性

- **9个冷库独立控制** - 每个冷库配备一套S7-1200控制器，主站通信中断不影响各库独立运行
- **每库10台制冷压缩机** - 支持错峰启动、轮换运行、故障隔离
- **双PT100传感器冗余** - 双正常取平均，单故障切备用，双故障保持
- **回差温度控制** - 上限启动，下限停止，防止压缩机短循环
- **定时化霜控制** - 定时化霜 + 温度终止 + 排水等待
- **完善的安全报警** - 报警汇总 + 状态字 + 蜂鸣器锁存
- **REST API接口** - Python/FastAPI 提供12个HTTP接口，支持二次开发
- **模拟模式** - 无需PLC硬件即可运行演示和开发测试
- **WinCC上位机** - 5个监控画面：总览/详情/报警/参数/趋势

## 项目结构

```
ColdStorage_Control/
├── S7-1200_ColdRoom/          # S7-1200 冷库控制器程序 (11个文件)
│   ├── UDT_Types.scl          # UDT数据类型定义
│   ├── FB_TempControl.scl     # 温度控制FB
│   ├── FB_Compressor.scl      # 压缩机控制FB
│   ├── FB_GroupStart.scl      # 错峰启动FB
│   ├── FB_Rotation.scl        # 轮换运行FB
│   ├── FB_Defrost.scl         # 化霜控制FB
│   ├── FB_SafetyAlarm.scl     # 安全报警FB
│   ├── OB1_Main.scl           # 主循环OB
│   ├── OB35_Cyclic.scl        # 100ms循环中断
│   └── OB82_OB122_Error.scl   # 硬件诊断/错误处理
├── S7-1500_Master/            # S7-1500 主站程序 (5个文件)
│   ├── UDT_GlobalData.scl     # 全局UDT定义
│   ├── FB_S7Communication.scl # S7通信FB
│   ├── FB_DataCollect.scl     # 数据汇总FB
│   ├── OB1_Main.scl           # 主循环OB
│   └── DB_GlobalData.scl      # 全局DB
├── WinCC/                     # WinCC上位机配置 (2个文件)
│   ├── WinCC_TagTables.txt    # 变量表/报警/归档
│   └── WinCC_ScreenDesign.txt # 画面设计
├── Communication/             # 通信配置 (1个文件)
│   └── PROFINET_Config.txt    # PROFINET网络配置
├── Backend_API/               # 后端API服务 (7个文件)
│   ├── main.py                # FastAPI主程序
│   ├── config.py              # 配置文件
│   ├── models.py              # Pydantic数据模型
│   ├── s7_connector.py        # S7通信封装
│   ├── requirements.txt       # Python依赖
│   ├── start.bat              # 一键启动脚本
│   ├── API_Guide.txt          # API使用指南
│   └── dashboard.html         # 演示仪表盘
└── Project_Overview.txt       # 项目总览
```

## 快速开始

### 后端API（无需PLC硬件）

1. 安装 [Python 3.9+](https://www.python.org/downloads/)
2. 进入 `ColdStorage_Control/Backend_API/` 目录
3. 双击运行 `start.bat`，选择 **1 (模拟模式)**
4. 浏览器访问 http://localhost:8080/docs 查看Swagger文档

### API 接口一览

| 序号 | 方法 | 路径 | 功能 |
|------|------|------|------|
| 1 | GET | `/api/overview` | 全局总览 (9个冷库) |
| 2 | GET | `/api/rooms` | 所有冷库列表 |
| 3 | GET | `/api/rooms/{room_id}` | 单库详情 |
| 4 | GET | `/api/rooms/{room_id}/temperature` | 单库温度 |
| 5 | PUT | `/api/rooms/{room_id}/params` | 修改温度参数 |
| 6 | POST | `/api/rooms/{room_id}/control` | 控制命令 (使能/急停) |
| 7 | POST | `/api/rooms/{room_id}/defrost` | 手动化霜 |
| 8 | GET | `/api/alarms` | 报警列表 |
| 9 | POST | `/api/alarms/ack` | 报警确认 |
| 10 | GET | `/api/trends/{room_id}` | 温度趋势 |
| 11 | GET | `/api/system/status` | 系统状态 |
| 12 | POST | `/api/system/reconnect` | 重连PLC |

### PLC程序导入

1. 创建TIA Portal项目 (V17+)
2. 添加1个S7-1500站点 + 9个S7-1200站点
3. 配置PROFINET网络和IP地址（见 `Communication/PROFINET_Config.txt`）
4. S7-1200启用PUT/GET（CPU属性→连接机制）
5. 导入SCL源文件（项目树→外部源文件→添加新外部源）：
   - 先导入 UDT 定义文件
   - 再导入各 FB 和 OB 文件
   - 最后导入 DB 文件
6. 配置WinCC变量表和画面

## 技术栈

| 层级 | 技术 |
|------|------|
| PLC (S7-1200/S7-1500) | 西门子 TIA Portal, SCL (结构化控制语言) |
| 上位机 | 西门子 WinCC |
| 后端API | Python 3.9+, FastAPI, Uvicorn, snap7 |
| 通信协议 | PROFINET, S7 协议, HTTP/REST |

## 核心设计原则

1. **独立性** - 每个S7-1200独立运行，主站通信中断不影响各库控制
2. **模块化** - 每个功能独立FB，可单独测试和使能/禁用
3. **故障隔离** - 单台压缩机故障仅隔离该台，不影响其他9台
4. **回差控制** - 温度上限启动，下限停止，中间保持（防短循环）
5. **错峰启动** - 10台分3组间隔5秒启动（避免电网冲击）
6. **轮换均衡** - 按运行时间排序，运行少的优先（均衡磨损）
7. **双传感器冗余** - 双正常取平均，单故障切备用，双故障保持
8. **傻瓜式API** - 模拟模式即开即用，Swagger自动文档，一键启动

## 项目统计

- 目录数: 5个
- 文件数: 25个
- 代码行数: ~4375行
- PLC程序: 16个SCL文件 (~2331行)
- 后端API: 7个Python/配置文件 (~1422行)
- 配置文档: 3个TXT文件 (~622行)

## 许可证

本项目仅供学习和参考使用。
