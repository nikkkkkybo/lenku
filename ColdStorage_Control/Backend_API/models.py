# -*- coding: utf-8 -*-
"""
冷库温度控制系统 - API 数据模型
====================================
Pydantic 模型定义, 用于请求体验证和响应体序列化。
FastAPI 会自动根据这些模型生成 Swagger 文档。
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from enum import Enum


# ============================================================
# 枚举类型
# ============================================================
class RoomStatus(str, Enum):
    """冷库运行状态"""
    NORMAL = "正常"
    COOLING = "制冷中"
    DEFROST = "化霜中"
    ALARM = "报警"
    STOPPED = "已停用"
    EMERGENCY = "急停"
    COMM_FAULT = "通信故障"


# ============================================================
# 请求模型 (客户端 → API)
# ============================================================

class RoomParamUpdate(BaseModel):
    """冷库温度参数修改请求"""
    high_limit: Optional[float] = Field(None, description="启动温度上限 (degC), 如 -16.0")
    low_limit: Optional[float] = Field(None, description="停止温度下限 (degC), 如 -20.0")
    alarm_high: Optional[float] = Field(None, description="超温报警值 (degC), 如 -10.0")

    @field_validator('high_limit')
    @classmethod
    def validate_high_limit(cls, v):
        if v is not None and (v < -50 or v > 50):
            raise ValueError("温度上限必须在 -50 ~ +50 degC 范围内")
        return v

    @field_validator('low_limit')
    @classmethod
    def validate_low_limit(cls, v):
        if v is not None and (v < -50 or v > 50):
            raise ValueError("温度下限必须在 -50 ~ +50 degC 范围内")
        return v

    @field_validator('alarm_high')
    @classmethod
    def validate_alarm_high(cls, v):
        if v is not None and (v < -50 or v > 50):
            raise ValueError("报警温度必须在 -50 ~ +50 degC 范围内")
        return v


class RoomControlRequest(BaseModel):
    """冷库控制命令请求"""
    system_enable: Optional[bool] = Field(None, description="系统使能 (true=启用, false=禁用)")
    emergency_stop: Optional[bool] = Field(None, description="急停 (true=急停, false=解除急停)")


class AlarmAckRequest(BaseModel):
    """报警确认请求"""
    room_id: Optional[int] = Field(None, ge=1, le=9, description="冷库编号 (1-9), 不填则确认全部")


# ============================================================
# 响应模型 (API → 客户端)
# ============================================================

class TemperatureInfo(BaseModel):
    """温度信息"""
    sensor1: float = Field(..., description="主传感器温度 (degC)")
    sensor2: float = Field(..., description="备用传感器温度 (degC)")
    actual: float = Field(..., description="实际使用温度 (degC)")
    evaporator: float = Field(..., description="蒸发器温度 (degC)")


class SettingsInfo(BaseModel):
    """温度设定信息"""
    high_limit: float = Field(..., description="启动温度上限 (degC)")
    low_limit: float = Field(..., description="停止温度下限 (degC)")
    alarm_high: float = Field(..., description="超温报警值 (degC)")


class CompressorInfo(BaseModel):
    """压缩机运行信息"""
    active_count: int = Field(..., description="运行台数")
    fault_count: int = Field(..., description="故障台数")
    available_count: int = Field(..., description="可用台数")
    running_list: List[bool] = Field(..., description="各台运行状态 [1号, 2号, ..., 10号]")
    fault_list: List[bool] = Field(..., description="各台故障状态 [1号, 2号, ..., 10号]")


class AlarmInfo(BaseModel):
    """报警信息"""
    alarm_word: int = Field(..., description="报警状态字 (位编码)")
    any_alarm: bool = Field(..., description="是否有报警")
    critical_alarm: bool = Field(..., description="是否严重报警")
    alarm_details: List[str] = Field(..., description="报警详情列表")


class RoomResponse(BaseModel):
    """单个冷库完整信息"""
    room_id: int = Field(..., description="冷库编号 (1-9)")
    temperature: TemperatureInfo
    settings: SettingsInfo
    status: dict = Field(..., description="运行状态")
    compressors: CompressorInfo
    alarms: AlarmInfo
    communication: dict = Field(..., description="通信状态")


class RoomSummaryResponse(BaseModel):
    """冷库摘要信息 (用于总览画面)"""
    room_id: int
    temp_actual: float = Field(..., description="实际温度 (degC)")
    cooling_demand: bool = Field(..., description="是否制冷中")
    defrost_active: bool = Field(..., description="是否化霜中")
    active_count: int = Field(..., description="运行台数")
    fault_count: int = Field(..., description="故障台数")
    any_alarm: bool = Field(..., description="是否有报警")
    comm_ok: bool = Field(..., description="通信是否正常")
    status_text: str = Field(..., description="状态文字描述")


class GlobalOverviewResponse(BaseModel):
    """全局总览响应"""
    rooms: List[RoomSummaryResponse] = Field(..., description="9个冷库摘要")
    total_active: int = Field(..., description="全系统运行压缩机总数")
    total_fault: int = Field(..., description="全系统故障压缩机总数")
    total_available: int = Field(..., description="全系统可用压缩机总数")
    global_alarm: bool = Field(..., description="全局报警")
    global_critical: bool = Field(..., description="全局严重报警")
    alarm_room_count: int = Field(..., description="报警冷库数量")
    mock_mode: bool = Field(..., description="是否模拟模式")


class ApiResponse(BaseModel):
    """通用API响应"""
    success: bool = Field(..., description="操作是否成功")
    message: str = Field(..., description="结果消息")
    data: Optional[dict] = Field(None, description="附加数据")


class TrendPoint(BaseModel):
    """趋势数据点"""
    timestamp: str = Field(..., description="时间戳")
    temperature: float = Field(..., description="温度 (degC)")


class TrendResponse(BaseModel):
    """温度趋势响应"""
    room_id: int
    points: List[TrendPoint] = Field(..., description="趋势数据点列表")
