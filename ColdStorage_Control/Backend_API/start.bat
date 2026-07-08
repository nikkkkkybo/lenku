@echo off
chcp 65001 >nul
title 冷库温度控制系统 - 后端API服务

echo ============================================================
echo   冷库温度控制系统 - 后端API启动脚本
echo ============================================================
echo.

:: 检查 Python 是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python, 请先安装 Python 3.9+
    echo        下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: 检查是否首次运行 (是否需要安装依赖)
python -c "import fastapi" >nul 2>&1
if errorlevel 1 (
    echo [提示] 首次运行, 正在安装依赖包...
    echo.
    pip install -r "%~dp0requirements.txt"
    if errorlevel 1 (
        echo [错误] 依赖安装失败, 请检查网络连接
        pause
        exit /b 1
    )
    echo.
    echo [成功] 依赖安装完成
    echo.
)

:: 选择运行模式
echo 请选择运行模式:
echo   1. 模拟模式 (默认, 无需PLC硬件, 使用虚拟数据)
echo   2. 真实模式 (连接S7-1500 PLC)
echo.
set /p mode="请输入选择 (1/2, 默认1): "

if "%mode%"=="2" (
    set MOCK_MODE=false
    echo.
    echo [真实模式] 将连接 PLC: 192.168.0.1
) else (
    set MOCK_MODE=true
    echo.
    echo [模拟模式] 使用虚拟数据, 无需PLC硬件
)

echo.
echo ============================================================
echo   服务启动中...
echo   Swagger文档: http://localhost:8080/docs
echo   全局总览API: http://localhost:8080/api/overview
echo   按 Ctrl+C 停止服务
echo ============================================================
echo.

set MOCK_MODE=%MOCK_MODE%
python "%~dp0main.py"

pause
