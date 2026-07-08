# -*- coding: utf-8 -*-
"""
冷库温度控制系统 - 后端API配置文件
====================================
所有可配置参数集中在此文件, 修改后重启服务生效。
无需修改代码即可调整PLC连接地址、端口号等。
"""

import os

# ============================================================
# PLC 连接配置 (S7-1500 主站)
# ============================================================
PLC_IP       = os.getenv("PLC_IP", "192.168.0.1")   # S7-1500 IP地址
PLC_RACK     = 0                                       # 机架号 (S7-1500 固定为0)
PLC_SLOT     = 1                                       # 槽号   (S7-1500 固定为1)
PLC_DB_NUM   = 100                                     # DB_GlobalData 的编号 (TIA Portal中分配)
PLC_TIMEOUT  = 2000                                    # 通信超时 (毫秒)

# ============================================================
# 后端服务配置
# ============================================================
API_HOST     = "0.0.0.0"                               # 监听地址 (0.0.0.0 = 所有网卡)
API_PORT     = 8080                                    # 监听端口
API_TITLE    = "冷库温度控制系统 - 后端API"
API_VERSION  = "1.0.0"

# ============================================================
# 运行模式
# ============================================================
# MOCK_MODE = True  : 模拟模式, 不连接真实PLC, 使用虚拟数据 (开发/演示用)
# MOCK_MODE = False : 真实模式, 通过 snap7 连接 S7-1500 PLC
MOCK_MODE    = os.getenv("MOCK_MODE", "true").lower() == "true"

# ============================================================
# 冷库系统参数
# ============================================================
ROOM_COUNT          = 9       # 冷库数量
COMPRESSOR_COUNT    = 10      # 每库压缩机数量

# DB_GlobalData 数据块中的偏移地址 (字节)
# 需与 TIA Portal 中 UDT_GlobalData 的内存布局一致
# 实际偏移需在 TIA Portal 中编译后从 DB 属性中确认
DB_OFFSETS = {
    # aRoom 数组: 每个冷库汇总数据, 起始偏移 0
    # 每个冷库结构体大小约 80 字节 (需根据实际UDT调整)
    "room_size":       80,     # 单个冷库结构体大小 (字节)
    "room_start":      0,      # aRoom[1] 起始偏移

    # 冷库结构体内部偏移
    "rTemp_Sensor1":   0,      # Real  (4字节)
    "rTemp_Sensor2":   4,      # Real  (4字节)
    "rTemp_Actual":    8,      # Real  (4字节)
    "rEvap_Temp":      12,     # Real  (4字节)
    "rTemp_HighLimit": 16,     # Real  (4字节)
    "rTemp_LowLimit":  20,     # Real  (4字节)
    "rTemp_AlarmHigh": 24,     # Real  (4字节)
    "bCooling_Demand": 28,     # Bool  (1字节)
    "bDefrost_Active": 29,     # Bool  (1字节)
    "bSystem_Enable":  30,     # Bool  (1字节)
    "bEmergency_Stop": 31,     # Bool  (1字节)
    "iActive_Count":   32,     # Int   (2字节)
    "iFault_Count":    34,     # Int   (2字节)
    "iAvailable_Count":36,     # Int   (2字节)
    "wCompRunning":    38,     # Word  (2字节)
    "wCompFault":      40,     # Word  (2字节)
    "wAlarm_Word":     42,     # Word  (2字节)
    "wStatus_Word":    44,     # Word  (2字节)
    "bAnyAlarm":       46,     # Bool  (1字节)
    "bCriticalAlarm":  47,     # Bool  (1字节)
    "bComm_OK":        48,     # Bool  (1字节)
    "iComm_Counter":   50,     # Int   (2字节)

    # 全局统计区 (aRoom 数组之后)
    "global_start":    720,    # 全局统计起始偏移 (9 * 80 = 720)
    "iTotalActive":    720,    # Int   (2字节)
    "iTotalFault":     722,    # Int   (2字节)
    "iTotalAvailable": 724,    # Int   (2字节)
    "bGlobalAlarm":    726,    # Bool  (1字节)
    "bGlobalCritical": 727,    # Bool  (1字节)
    "iAlarmRoomCount": 728,    # Int   (2字节)
}

# ============================================================
# 轮询配置
# ============================================================
POLL_INTERVAL = 1.0   # 后台数据刷新间隔 (秒)

# ============================================================
# 日志配置
# ============================================================
LOG_LEVEL    = "INFO"
LOG_FORMAT   = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_FILE     = "coldstorage_api.log"
