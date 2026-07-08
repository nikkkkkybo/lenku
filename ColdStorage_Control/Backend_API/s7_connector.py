# -*- coding: utf-8 -*-
"""
冷库温度控制系统 - S7通信封装层
====================================
封装 snap7 库, 对上层提供简洁的 Python 接口。
支持两种模式:
  1. 真实模式 (MOCK_MODE=False): 通过 snap7 连接 S7-1500 PLC
  2. 模拟模式 (MOCK_MODE=True):  使用虚拟数据, 无需PLC硬件

上层代码只需调用 read_room_data() / write_room_param() 等方法,
无需关心 snap7 细节和数据块偏移地址。
"""

import struct
import time
import random
import logging
import threading
from typing import Optional, Dict, Any

import config

logger = logging.getLogger(__name__)


# ============================================================
# 数据结构: 单个冷库的运行数据
# ============================================================
class RoomData:
    """单个冷库的实时运行数据"""
    def __init__(self, room_id: int):
        self.room_id = room_id
        # 温度数据
        self.temp_sensor1: float = 0.0
        self.temp_sensor2: float = 0.0
        self.temp_actual: float = 0.0
        self.evap_temp: float = 0.0
        # 设定值
        self.temp_high_limit: float = -16.0
        self.temp_low_limit: float = -20.0
        self.temp_alarm_high: float = -10.0
        # 运行状态
        self.cooling_demand: bool = False
        self.defrost_active: bool = False
        self.system_enable: bool = True
        self.emergency_stop: bool = False
        # 压缩机统计
        self.active_count: int = 0
        self.fault_count: int = 0
        self.available_count: int = 10
        self.comp_running: int = 0       # Word (位编码)
        self.comp_fault: int = 0         # Word (位编码)
        # 报警
        self.alarm_word: int = 0
        self.status_word: int = 0
        self.any_alarm: bool = False
        self.critical_alarm: bool = False
        # 通信
        self.comm_ok: bool = True
        self.comm_counter: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典 (用于API响应)"""
        return {
            "room_id": self.room_id,
            "temperature": {
                "sensor1": round(self.temp_sensor1, 1),
                "sensor2": round(self.temp_sensor2, 1),
                "actual": round(self.temp_actual, 1),
                "evaporator": round(self.evap_temp, 1),
            },
            "settings": {
                "high_limit": self.temp_high_limit,
                "low_limit": self.temp_low_limit,
                "alarm_high": self.temp_alarm_high,
            },
            "status": {
                "cooling_demand": self.cooling_demand,
                "defrost_active": self.defrost_active,
                "system_enable": self.system_enable,
                "emergency_stop": self.emergency_stop,
            },
            "compressors": {
                "active_count": self.active_count,
                "fault_count": self.fault_count,
                "available_count": self.available_count,
                "running_bits": self.comp_running,
                "fault_bits": self.comp_fault,
                "running_list": self._word_to_list(self.comp_running),
                "fault_list": self._word_to_list(self.comp_fault),
            },
            "alarms": {
                "alarm_word": self.alarm_word,
                "any_alarm": self.any_alarm,
                "critical_alarm": self.critical_alarm,
                "alarm_details": self._decode_alarms(self.alarm_word),
            },
            "communication": {
                "comm_ok": self.comm_ok,
                "comm_counter": self.comm_counter,
            },
        }

    @staticmethod
    def _word_to_list(word_val: int) -> list:
        """将Word位编码转为布尔列表 [comp1, comp2, ..., comp10]"""
        return [(word_val >> i) & 1 == 1 for i in range(10)]

    @staticmethod
    def _decode_alarms(alarm_word: int) -> list:
        """解码报警状态字为可读列表"""
        alarms = []
        alarm_map = {
            0:  "超温报警",
            1:  "传感器1故障",
            2:  "传感器2故障",
            3:  "双传感器故障",
            4:  "传感器温差预警",
            5:  "压缩机故障",
            6:  "压缩机过载",
            7:  "通信故障",
            8:  "急停",
            9:  "化霜超时",
            10: "可用压缩机不足",
        }
        for bit, desc in alarm_map.items():
            if alarm_word & (1 << bit):
                alarms.append(desc)
        return alarms


# ============================================================
# 全局统计数据
# ============================================================
class GlobalData:
    """全系统汇总数据"""
    def __init__(self):
        self.total_active: int = 0
        self.total_fault: int = 0
        self.total_available: int = 90
        self.global_alarm: bool = False
        self.global_critical: bool = False
        self.alarm_room_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_active": self.total_active,
            "total_fault": self.total_fault,
            "total_available": self.total_available,
            "global_alarm": self.global_alarm,
            "global_critical": self.global_critical,
            "alarm_room_count": self.alarm_room_count,
        }


# ============================================================
# S7 通信连接器 (真实模式)
# ============================================================
class S7Connector:
    """通过 snap7 连接 S7-1500 PLC"""

    def __init__(self):
        self._client = None
        self._connected = False
        self._lock = threading.Lock()

    def connect(self) -> bool:
        """连接到 S7-1500 PLC"""
        try:
            import snap7
            self._client = snap7.client.Client()
            self._client.connect(config.PLC_IP, config.PLC_RACK, config.PLC_SLOT)
            self._connected = True
            logger.info(f"已连接到 S7-1500 PLC: {config.PLC_IP}")
            return True
        except ImportError:
            logger.error("snap7 库未安装, 请运行: pip install python-snap7")
            return False
        except Exception as e:
            logger.error(f"连接PLC失败: {e}")
            self._connected = False
            return False

    def disconnect(self):
        """断开连接"""
        if self._client:
            self._client.disconnect()
            self._client.destroy()
            self._client = None
        self._connected = False
        logger.info("已断开PLC连接")

    @property
    def is_connected(self) -> bool:
        return self._connected

    def read_room_data(self, room_id: int) -> RoomData:
        """从 PLC 读取单个冷库数据"""
        room = RoomData(room_id)
        if not self._connected:
            return room

        with self._lock:
            offs = config.DB_OFFSETS
            base = offs["room_start"] + (room_id - 1) * offs["room_size"]
            db_num = config.PLC_DB_NUM

            try:
                # 读取整个冷库结构体 (80字节)
                data = self._client.db_read(db_num, base, offs["room_size"])

                room.temp_sensor1    = struct.unpack('>f', data[0:4])[0]
                room.temp_sensor2    = struct.unpack('>f', data[4:8])[0]
                room.temp_actual     = struct.unpack('>f', data[8:12])[0]
                room.evap_temp       = struct.unpack('>f', data[12:16])[0]
                room.temp_high_limit = struct.unpack('>f', data[16:20])[0]
                room.temp_low_limit  = struct.unpack('>f', data[20:24])[0]
                room.temp_alarm_high = struct.unpack('>f', data[24:28])[0]
                room.cooling_demand  = data[28] != 0
                room.defrost_active  = data[29] != 0
                room.system_enable   = data[30] != 0
                room.emergency_stop  = data[31] != 0
                room.active_count    = struct.unpack('>h', data[32:34])[0]
                room.fault_count     = struct.unpack('>h', data[34:36])[0]
                room.available_count = struct.unpack('>h', data[36:38])[0]
                room.comp_running    = struct.unpack('>H', data[38:40])[0]
                room.comp_fault      = struct.unpack('>H', data[40:42])[0]
                room.alarm_word      = struct.unpack('>H', data[42:44])[0]
                room.status_word     = struct.unpack('>H', data[44:46])[0]
                room.any_alarm       = data[46] != 0
                room.critical_alarm  = data[47] != 0
                room.comm_ok         = data[48] != 0
                room.comm_counter    = struct.unpack('>h', data[50:52])[0]

            except Exception as e:
                logger.error(f"读取冷库{room_id}数据失败: {e}")
                room.comm_ok = False

        return room

    def read_global_data(self) -> GlobalData:
        """从 PLC 读取全局统计数据"""
        gd = GlobalData()
        if not self._connected:
            return gd

        with self._lock:
            offs = config.DB_OFFSETS
            base = offs["global_start"]
            try:
                data = self._client.db_read(config.PLC_DB_NUM, base, 10)
                gd.total_active     = struct.unpack('>h', data[0:2])[0]
                gd.total_fault      = struct.unpack('>h', data[2:4])[0]
                gd.total_available  = struct.unpack('>h', data[4:6])[0]
                gd.global_alarm     = data[6] != 0
                gd.global_critical  = data[7] != 0
                gd.alarm_room_count = struct.unpack('>h', data[8:10])[0]
            except Exception as e:
                logger.error(f"读取全局数据失败: {e}")

        return gd

    def write_room_param(self, room_id: int, high_limit: Optional[float] = None,
                         low_limit: Optional[float] = None,
                         alarm_high: Optional[float] = None) -> bool:
        """向 PLC 写入冷库温度参数设定"""
        if not self._connected:
            return False

        with self._lock:
            offs = config.DB_OFFSETS
            base = offs["room_start"] + (room_id - 1) * offs["room_size"]

            try:
                if high_limit is not None:
                    data = struct.pack('>f', high_limit)
                    self._client.db_write(config.PLC_DB_NUM, base + 16, data)
                if low_limit is not None:
                    data = struct.pack('>f', low_limit)
                    self._client.db_write(config.PLC_DB_NUM, base + 20, data)
                if alarm_high is not None:
                    data = struct.pack('>f', alarm_high)
                    self._client.db_write(config.PLC_DB_NUM, base + 24, data)
                logger.info(f"冷库{room_id}参数已更新: 上限={high_limit}, 下限={low_limit}, 报警={alarm_high}")
                return True
            except Exception as e:
                logger.error(f"写入冷库{room_id}参数失败: {e}")
                return False

    def write_room_control(self, room_id: int, system_enable: Optional[bool] = None,
                           emergency_stop: Optional[bool] = None) -> bool:
        """向 PLC 写入冷库控制命令 (使能/急停)"""
        if not self._connected:
            return False

        with self._lock:
            offs = config.DB_OFFSETS
            base = offs["room_start"] + (room_id - 1) * offs["room_size"]

            try:
                if system_enable is not None:
                    data = bytes([1 if system_enable else 0])
                    self._client.db_write(config.PLC_DB_NUM, base + 30, data)
                if emergency_stop is not None:
                    data = bytes([1 if emergency_stop else 0])
                    self._client.db_write(config.PLC_DB_NUM, base + 31, data)
                logger.info(f"冷库{room_id}控制命令已发送: 使能={system_enable}, 急停={emergency_stop}")
                return True
            except Exception as e:
                logger.error(f"写入冷库{room_id}控制命令失败: {e}")
                return False


# ============================================================
# 模拟连接器 (模拟模式, 无需PLC硬件)
# ============================================================
class MockConnector:
    """模拟PLC数据, 用于开发测试和演示"""

    def __init__(self):
        self._rooms = {}
        self._global = GlobalData()
        self._tick = 0
        for i in range(1, config.ROOM_COUNT + 1):
            r = RoomData(i)
            r.temp_sensor1 = round(random.uniform(-22, -14), 1)
            r.temp_sensor2 = round(r.temp_sensor1 + random.uniform(-0.5, 0.5), 1)
            r.temp_actual = round((r.temp_sensor1 + r.temp_sensor2) / 2, 1)
            r.evap_temp = round(random.uniform(-8, -2), 1)
            r.temp_high_limit = -16.0
            r.temp_low_limit = -20.0
            r.temp_alarm_high = -10.0
            r.cooling_demand = r.temp_actual >= r.temp_high_limit
            r.system_enable = True
            r.available_count = 10
            r.active_count = 8 if r.cooling_demand else 0
            r.comm_ok = True
            r.comm_counter = 0
            self._rooms[i] = r
        logger.info("模拟模式已启动 - 使用虚拟PLC数据")

    def connect(self) -> bool:
        return True

    def disconnect(self):
        pass

    @property
    def is_connected(self) -> bool:
        return True

    def _simulate(self):
        """每轮调用, 模拟温度变化和压缩机启停"""
        self._tick += 1
        for room in self._rooms.values():
            if not room.system_enable or room.emergency_stop:
                room.cooling_demand = False
                room.active_count = 0
                room.comp_running = 0
                continue

            if room.defrost_active:
                room.cooling_demand = False
                room.active_count = 0
                room.comp_running = 0
                room.evap_temp += 0.5
                if room.evap_temp >= 10.0:
                    room.defrost_active = False
                continue

            # 温度模拟: 制冷时下降, 不制冷时上升
            if room.cooling_demand:
                room.temp_actual -= random.uniform(0.05, 0.15)
            else:
                room.temp_actual += random.uniform(0.02, 0.08)

            room.temp_sensor1 = round(room.temp_actual + random.uniform(-0.3, 0.3), 1)
            room.temp_sensor2 = round(room.temp_actual + random.uniform(-0.3, 0.3), 1)

            # 回差控制
            if room.temp_actual >= room.temp_high_limit:
                room.cooling_demand = True
            elif room.temp_actual <= room.temp_low_limit:
                room.cooling_demand = False

            # 压缩机运行状态
            if room.cooling_demand:
                room.active_count = room.available_count
                room.comp_running = (1 << room.available_count) - 1  # 前N台运行
            else:
                room.active_count = 0
                room.comp_running = 0

            # 超温报警
            room.any_alarm = room.temp_actual >= room.temp_alarm_high
            room.critical_alarm = room.any_alarm
            if room.any_alarm:
                room.alarm_word = 0x0001  # Bit0: 超温
            else:
                room.alarm_word = 0

            room.comm_counter += 1
            room.evap_temp = round(room.evap_temp, 1)

        # 更新全局统计
        self._global.total_active = sum(r.active_count for r in self._rooms.values())
        self._global.total_fault = sum(r.fault_count for r in self._rooms.values())
        self._global.total_available = sum(r.available_count for r in self._rooms.values())
        self._global.global_alarm = any(r.any_alarm for r in self._rooms.values())
        self._global.global_critical = any(r.critical_alarm for r in self._rooms.values())
        self._global.alarm_room_count = sum(1 for r in self._rooms.values() if r.any_alarm)

    def read_room_data(self, room_id: int) -> RoomData:
        self._simulate()
        return self._rooms.get(room_id, RoomData(room_id))

    def read_global_data(self) -> GlobalData:
        return self._global

    def write_room_param(self, room_id: int, high_limit=None, low_limit=None, alarm_high=None) -> bool:
        room = self._rooms.get(room_id)
        if room:
            if high_limit is not None:
                room.temp_high_limit = high_limit
            if low_limit is not None:
                room.temp_low_limit = low_limit
            if alarm_high is not None:
                room.temp_alarm_high = alarm_high
            logger.info(f"[模拟] 冷库{room_id}参数已更新")
            return True
        return False

    def write_room_control(self, room_id: int, system_enable=None, emergency_stop=None) -> bool:
        room = self._rooms.get(room_id)
        if room:
            if system_enable is not None:
                room.system_enable = system_enable
            if emergency_stop is not None:
                room.emergency_stop = emergency_stop
                if emergency_stop:
                    room.cooling_demand = False
                    room.active_count = 0
                    room.comp_running = 0
                    room.alarm_word = room.alarm_word | 0x0100  # Bit8: 急停
                    room.any_alarm = True
                    room.critical_alarm = True
            logger.info(f"[模拟] 冷库{room_id}控制命令已发送")
            return True
        return False


# ============================================================
# 连接器工厂: 根据配置选择真实/模拟
# ============================================================
_connector: Optional[object] = None

def get_connector():
    """获取全局连接器实例 (单例)"""
    global _connector
    if _connector is None:
        if config.MOCK_MODE:
            _connector = MockConnector()
            logger.info("使用模拟模式 (MOCK_MODE=True)")
        else:
            _connector = S7Connector()
            logger.info("使用真实模式 (MOCK_MODE=False)")
            _connector.connect()
    return _connector

def reconnect():
    """重新连接PLC (真实模式)"""
    global _connector
    if not config.MOCK_MODE and isinstance(_connector, S7Connector):
        _connector.disconnect()
        return _connector.connect()
    return True
