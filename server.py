"""
TPad Server - 笔记本端控制服务器
接收小程序的WebSocket连接，模拟键盘/鼠标/手柄操作

依赖:
    - websockets: WebSocket服务器
    - pynput: 键盘鼠标控制
"""

APP_VERSION = "V1.3.0"

import asyncio
import websockets
import socket
import json
import time
import threading
import os
import sys
import random
import tkinter as tk
from tkinter import ttk, font, messagebox, colorchooser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pynput import mouse, keyboard
from pynput.mouse import Button, Controller as MouseController
from pynput.keyboard import Key, Controller as KeyboardController

try:
    from ble_client import get_ble_peripheral, LOG_FILE as BLE_LOG_FILE
    BLE_AVAILABLE = True
except ImportError:
    BLE_AVAILABLE = False
    BLE_LOG_FILE = None

# 应用所在目录（打包后为 exe 所在目录，开发模式为脚本所在目录）
if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(sys.executable)
    # PyInstaller onefile 模式下 --add-data 文件解压到临时目录
    _MEI_DIR = getattr(sys, '_MEIPASS', None)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    _MEI_DIR = None

def _resource_path(filename):
    """查找资源文件路径（兼容 PyInstaller 打包和开发模式）

    优先顺序：exe 同级目录 → PyInstaller 临时解压目录 → 返回 APP_DIR 下的路径
    """
    # 1. 先查 exe/脚本 同级目录（用户手动放的或之前版本遗留的）
    p = os.path.join(APP_DIR, filename)
    if os.path.exists(p):
        return p
    # 2. 再查 PyInstaller 临时解压目录（--add-data 带进来的）
    if _MEI_DIR:
        p = os.path.join(_MEI_DIR, filename)
        if os.path.exists(p):
            return p
    # 3. 都没找到，返回 APP_DIR 下的路径（让调用方自己判断）
    return os.path.join(APP_DIR, filename)

# 变身图片保存路径（放在 exe 所在目录，避免临时目录被清理）
IMAGE_SAVE_PATH = os.path.join(APP_DIR, 'transform_image.jpg')
HTTP_PORT = 8766

# 用户配置文件（持久化保存颜色等偏好）
CONFIG_PATH = os.path.join(APP_DIR, 'server_config.json')

# 服务端软件下载目录
DOWNLOAD_DIR = os.path.join(APP_DIR, 'downloads')
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

def log(msg):
    """全局日志函数，同时输出到控制台和日志文件"""
    print(msg)
    if BLE_LOG_FILE:
        try:
            import datetime
            line = f'[{datetime.datetime.now().strftime("%H:%M:%S")}] {msg}'
            with open(BLE_LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(line + '\n')
        except Exception:
            pass

# 控制器实例（全局初始化一次，避免频繁创建销毁）
mouse_controller = MouseController()
keyboard_controller = KeyboardController()

# 心跳配置（超时时间可设置，默认5分钟）
HEARTBEAT_INTERVAL = 60
IDLE_TIMEOUT_MINUTES = 5
IDLE_TIMEOUT_OPTIONS = [1, 2, 3, 5, 10, 20, 30, 60]

# 变身图片保存路径连接码配置
pair_code = ''
PAIR_CODE_LENGTH = 4

# 全局状态
connected_clients = 0
server_running = False
server_thread = None
ws_server = None
ws_loop = None  # 保存事件循环引用
gui_callbacks = None
http_server = None
http_thread = None

# ============ 双鼠标（宝剑光标）全局状态 ============
double_mouse_enabled = False
sword_cursor_pos = (0, 0)        # 宝剑光标当前热点位置
_system_mouse_backup = None      # 点击时系统鼠标备份（用于恢复）
sword_cursor_window = None       # SwordCursorOverlay 实例


def generate_pair_code():
    """生成随机4位数字连接码"""
    global pair_code
    pair_code = ''.join([str(random.randint(0, 9)) for _ in range(PAIR_CODE_LENGTH)])
    print(f'[配对] 新连接码: {pair_code}')
    if gui_callbacks and 'on_pair_code_update' in gui_callbacks:
        gui_callbacks['on_pair_code_update'](pair_code)
    return pair_code


def parse_multipart_file(body, boundary_str):
    """从multipart/form-data中提取文件内容"""
    boundary = ('--' + boundary_str).encode()
    parts = body.split(boundary)
    for part in parts:
        part = part.strip(b'\r\n')
        if not part or part == b'--':
            continue
        idx = part.find(b'\r\n\r\n')
        if idx == -1:
            continue
        headers_raw = part[:idx].decode('utf-8', errors='ignore')
        file_data = part[idx + 4:]
        if file_data.endswith(b'\r\n'):
            file_data = file_data[:-2]
        if 'filename=' in headers_raw:
            return file_data
    return None


class ImageUploadHandler(BaseHTTPRequestHandler):
    """处理图片上传和软件下载的HTTP请求处理器"""

    def do_GET(self):
        if self.path == '/download/list':
            # 返回可下载的服务端软件列表
            try:
                files = []
                for f in os.listdir(DOWNLOAD_DIR):
                    fp = os.path.join(DOWNLOAD_DIR, f)
                    if os.path.isfile(fp):
                        size = os.path.getsize(fp)
                        files.append({'name': f, 'size': size})
                data = json.dumps(files).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                self.send_response(500)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(f'Error: {str(e)}'.encode())
        elif self.path.startswith('/download/'):
            # 下载文件
            filename = self.path[len('/download/'):]
            # 防止路径穿越
            filename = os.path.basename(filename)
            fp = os.path.join(DOWNLOAD_DIR, filename)
            if os.path.isfile(fp):
                try:
                    with open(fp, 'rb') as f:
                        file_data = f.read()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/octet-stream')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
                    self.send_header('Content-Length', str(len(file_data)))
                    self.end_headers()
                    self.wfile.write(file_data)
                except Exception as e:
                    self.send_response(500)
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(f'Error: {str(e)}'.encode())
            else:
                self.send_response(404)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(b'File not found')
        else:
            self.send_response(404)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

    def do_POST(self):
        if self.path == '/upload':
            content_type = self.headers.get('Content-Type', '')
            content_length = int(self.headers.get('Content-Length', 0))
            log(f'[上传] 收到上传请求, Content-Length={content_length}, Content-Type={content_type}')
            body = self.rfile.read(content_length)

            try:
                if 'multipart/form-data' in content_type:
                    boundary_str = content_type.split('boundary=')[1]
                    file_data = parse_multipart_file(body, boundary_str)
                else:
                    file_data = body

                if file_data:
                    with open(IMAGE_SAVE_PATH, 'wb') as f:
                        f.write(file_data)
                    log(f'[上传] 图片保存成功, 大小={len(file_data)} 字节, 路径={IMAGE_SAVE_PATH}')
                    if gui_callbacks and 'on_image_uploaded' in gui_callbacks:
                        gui_callbacks['on_image_uploaded'](len(file_data))
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/plain')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(b'OK')
                else:
                    print('[上传] 未找到文件数据')
                    self.send_response(400)
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(b'No file found')
            except Exception as e:
                print('[上传] 上传异常:', e)
                self.send_response(500)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(f'Error: {str(e)}'.encode())
        else:
            self.send_response(404)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def log_message(self, format, *args):
        pass


def start_http_server():
    """启动HTTP服务器（用于接收图片上传）"""
    global http_server
    http_server = HTTPServer(('0.0.0.0', HTTP_PORT), ImageUploadHandler)
    http_server.serve_forever()


def stop_http_server():
    """停止HTTP服务器"""
    global http_server, http_thread
    if http_server:
        http_server.shutdown()
        http_server.server_close()
        http_server = None
    if http_thread:
        http_thread = None

# 键盘按键映射
KEY_MAP = {
    'a': 'a', 'b': 'b', 'c': 'c', 'd': 'd', 'e': 'e', 'f': 'f',
    'g': 'g', 'h': 'h', 'i': 'i', 'j': 'j', 'k': 'k', 'l': 'l',
    'm': 'm', 'n': 'n', 'o': 'o', 'p': 'p', 'q': 'q', 'r': 'r',
    's': 's', 't': 't', 'u': 'u', 'v': 'v', 'w': 'w', 'x': 'x',
    'y': 'y', 'z': 'z',
    'A': 'A', 'B': 'B', 'C': 'C', 'D': 'D', 'E': 'E', 'F': 'F',
    'G': 'G', 'H': 'H', 'I': 'I', 'J': 'J', 'K': 'K', 'L': 'L',
    'M': 'M', 'N': 'N', 'O': 'O', 'P': 'P', 'Q': 'Q', 'R': 'R',
    'S': 'S', 'T': 'T', 'U': 'U', 'V': 'V', 'W': 'W', 'X': 'X',
    'Y': 'Y', 'Z': 'Z',
    '0': '0', '1': '1', '2': '2', '3': '3', '4': '4',
    '5': '5', '6': '6', '7': '7', '8': '8', '9': '9',
    '!': '!', '@': '@', '#': '#', '$': '$', '%': '%',
    '^': '^', '&': '&', '*': '*', '(':'(', ')': ')',
    '-': '-', '_': '_', '=': '=', '+': '+',
    '[': '[', ']': ']', '{': '{', '}': '}',
    ';': ';', ':': ':', "'": "'", '"': '"',
    ',': ',', '.': '.', '<': '<', '>': '>',
    '/': '/', '?': '?', '\\': '\\', '|': '|',
    '`': '`', '~': '~',
    'SPACE': Key.space,
    'ENTER': Key.enter,
    'TAB': Key.tab,
    'BACKSPACE': Key.backspace,
    'DELETE': Key.delete,
    'ESC': Key.esc,
    'ARROW_UP': Key.up,
    'ARROW_DOWN': Key.down,
    'ARROW_LEFT': Key.left,
    'ARROW_RIGHT': Key.right,
    'F1': Key.f1, 'F2': Key.f2, 'F3': Key.f3, 'F4': Key.f4,
    'F5': Key.f5, 'F6': Key.f6, 'F7': Key.f7, 'F8': Key.f8,
    'F9': Key.f9, 'F10': Key.f10, 'F11': Key.f11, 'F12': Key.f12,
    'SHIFT': Key.shift,
    'CTRL': Key.ctrl,
    'ALT': Key.alt,
    'CAPS': Key.caps_lock,
}

GAMEPAD_KEY_MAP = {
    'A': Key.enter, 'B': Key.esc, 'X': 'x', 'Y': 'y',
    'DPAD_UP': Key.up, 'DPAD_DOWN': Key.down,
    'DPAD_LEFT': Key.left, 'DPAD_RIGHT': Key.right,
    'L1': 'q', 'R1': 'e', 'L2': 'w', 'R2': 'r',
    'START': Key.enter, 'SELECT': Key.esc,
    'L3': Key.shift, 'R3': Key.ctrl,
}


def get_local_ip():
    """获取本机IP地址"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def parse_command(message):
    """解析命令: 格式为 'TYPE|DATA'"""
    parts = message.split('|', 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    elif len(parts) == 1:
        return parts[0], ''
    return None, None


# ============ ctypes SendInput 底层鼠标控制（Windows） ============
try:
    import ctypes as _ctypes
    _user32 = _ctypes.windll.user32

    class _MOUSEINPUT(_ctypes.Structure):
        _fields_ = [
            ('dx', _ctypes.c_long), ('dy', _ctypes.c_long),
            ('mouseData', _ctypes.c_ulong), ('dwFlags', _ctypes.c_ulong),
            ('time', _ctypes.c_ulong), ('dwExtraInfo', _ctypes.c_void_p),
        ]

    class _INPUT_UNION(_ctypes.Union):
        _fields_ = [('mi', _MOUSEINPUT)]

    class _INPUT(_ctypes.Structure):
        _fields_ = [('type', _ctypes.c_ulong), ('union', _INPUT_UNION)]

    _INPUT_MOUSE = 0
    _MOUSEEVENTF_LEFTDOWN = 0x0002
    _MOUSEEVENTF_LEFTUP = 0x0004
    _MOUSEEVENTF_RIGHTDOWN = 0x0008
    _MOUSEEVENTF_RIGHTUP = 0x0010
    _MOUSEEVENTF_MIDDLEDOWN = 0x0020
    _MOUSEEVENTF_MIDDLEUP = 0x0040

    def _ctypes_send_mouse(flags):
        """发送单个鼠标事件"""
        inp = _INPUT()
        inp.type = _INPUT_MOUSE
        inp.union.mi = _MOUSEINPUT(0, 0, 0, flags, 0, None)
        _user32.SendInput(1, _ctypes.byref(inp), _ctypes.sizeof(_INPUT))

    def _button_flags(button, down):
        """Button 枚举 → SendInput flags"""
        if button == Button.left:
            return _MOUSEEVENTF_LEFTDOWN if down else _MOUSEEVENTF_LEFTUP
        elif button == Button.right:
            return _MOUSEEVENTF_RIGHTDOWN if down else _MOUSEEVENTF_RIGHTUP
        elif button == Button.middle:
            return _MOUSEEVENTF_MIDDLEDOWN if down else _MOUSEEVENTF_MIDDLEUP
        return 0

    _CTYPES_OK = True
except Exception:
    _CTYPES_OK = False
    log('[警告] ctypes SendInput 初始化失败，点击可能不生效')


def _sword_press(button):
    """双鼠标模式：隐藏宝剑 → 瞬移 → press（不恢复位置）"""
    global _system_mouse_backup
    # 关键：点击前先隐藏宝剑窗口，防止它拦截 SendInput 事件
    _sword_hide_sync()
    _system_mouse_backup = mouse_controller.position
    if _CTYPES_OK:
        _user32.SetCursorPos(sword_cursor_pos[0], sword_cursor_pos[1])
        time.sleep(0.02)
        _ctypes_send_mouse(_button_flags(button, True))
    else:
        mouse_controller.position = sword_cursor_pos
        time.sleep(0.02)
        mouse_controller.press(button)


def _sword_release(button):
    """双鼠标模式：release → 恢复系统鼠标 → 恢复宝剑显示"""
    global _system_mouse_backup
    if _CTYPES_OK:
        _ctypes_send_mouse(_button_flags(button, False))
        time.sleep(0.03)
        if _system_mouse_backup:
            _user32.SetCursorPos(_system_mouse_backup[0], _system_mouse_backup[1])
            _system_mouse_backup = None
    else:
        mouse_controller.release(button)
        time.sleep(0.03)
        if _system_mouse_backup:
            mouse_controller.position = _system_mouse_backup
            _system_mouse_backup = None
    # 恢复宝剑显示
    _sword_show_sync()


def _sword_click(button, count=1):
    """双鼠标模式：隐藏宝剑 → 瞬移 → 完整 click → 恢复位置 → 恢复宝剑"""
    _sword_hide_sync()
    if _CTYPES_OK:
        backup = mouse_controller.position
        _user32.SetCursorPos(sword_cursor_pos[0], sword_cursor_pos[1])
        time.sleep(0.02)
        down_flag = _button_flags(button, True)
        up_flag = _button_flags(button, False)
        for _ in range(count):
            _ctypes_send_mouse(down_flag)
            time.sleep(0.04)
            _ctypes_send_mouse(up_flag)
            time.sleep(0.04)
        _user32.SetCursorPos(backup[0], backup[1])
    else:
        global _system_mouse_backup
        backup = mouse_controller.position
        mouse_controller.position = sword_cursor_pos
        time.sleep(0.02)
        for _ in range(count):
            mouse_controller.press(button)
            time.sleep(0.04)
            mouse_controller.release(button)
            time.sleep(0.04)
        mouse_controller.position = backup
    _sword_show_sync()


def _sword_hide_sync():
    """线程安全地隐藏宝剑窗口（切主线程 + 等待完成）"""
    if sword_cursor_window and sword_cursor_window.root:
        _done = threading.Event()
        sword_cursor_window.root.after(0, lambda: (sword_cursor_window.hide(), _done.set()))
        _done.wait(timeout=1)


def _sword_show_sync():
    """线程安全地显示宝剑窗口（切主线程 + 等待完成）"""
    if sword_cursor_window and sword_cursor_window.root:
        _done = threading.Event()
        sword_cursor_window.root.after(0, lambda: (sword_cursor_window.show(), _done.set()))
        _done.wait(timeout=1)


def handle_mouse_command(cmd_type, data):
    """处理鼠标命令（支持双鼠标宝剑光标模式）"""
    global double_mouse_enabled, sword_cursor_pos
    try:
        if double_mouse_enabled:
            log(f'[双鼠标] 收到 MOUSE 命令: {cmd_type}, sword_pos={sword_cursor_pos}, _CTYPES_OK={_CTYPES_OK}')

        # ============ 双鼠标宝剑光标模式 ============
        if double_mouse_enabled:
            if cmd_type == 'MOUSE_MOVE':
                parts = data.split(',')
                if len(parts) == 2:
                    dx, dy = int(parts[0]), int(parts[1])
                    sword_cursor_pos = (
                        sword_cursor_pos[0] + dx,
                        sword_cursor_pos[1] + dy
                    )
                    if gui_callbacks and 'on_sword_move' in gui_callbacks:
                        gui_callbacks['on_sword_move'](sword_cursor_pos)

            elif cmd_type == 'MOUSE_SCROLL':
                parts = data.split(',')
                if len(parts) == 2:
                    dx, dy = int(parts[0]), int(parts[1])
                    mouse_controller.position = sword_cursor_pos
                    mouse_controller.scroll(-dx * 2, -dy * 2)

            elif cmd_type == 'MOUSE_LEFT_DOWN':
                log(f'[双鼠标] _sword_press LEFT at {sword_cursor_pos}')
                _sword_press(Button.left)
            elif cmd_type == 'MOUSE_LEFT_UP':
                log(f'[双鼠标] _sword_release LEFT')
                _sword_release(Button.left)
            elif cmd_type == 'MOUSE_RIGHT_DOWN':
                log(f'[双鼠标] _sword_press RIGHT at {sword_cursor_pos}')
                _sword_press(Button.right)
            elif cmd_type == 'MOUSE_RIGHT_UP':
                log(f'[双鼠标] _sword_release RIGHT')
                _sword_release(Button.right)
            elif cmd_type == 'MOUSE_MIDDLE_DOWN':
                _sword_press(Button.middle)
            elif cmd_type == 'MOUSE_MIDDLE_UP':
                _sword_release(Button.middle)

        # ============ 原有模式（单鼠标） ============
        else:
            if cmd_type == 'MOUSE_MOVE':
                parts = data.split(',')
                if len(parts) == 2:
                    mouse_controller.move(int(parts[0]), int(parts[1]))

            elif cmd_type == 'MOUSE_SCROLL':
                parts = data.split(',')
                if len(parts) == 2:
                    dx, dy = int(parts[0]), int(parts[1])
                    mouse_controller.scroll(-dx * 2, -dy * 2)

            elif cmd_type == 'MOUSE_LEFT_DOWN':
                mouse_controller.press(Button.left)
            elif cmd_type == 'MOUSE_LEFT_UP':
                mouse_controller.release(Button.left)
            elif cmd_type == 'MOUSE_RIGHT_DOWN':
                mouse_controller.press(Button.right)
            elif cmd_type == 'MOUSE_RIGHT_UP':
                mouse_controller.release(Button.right)
            elif cmd_type == 'MOUSE_MIDDLE_DOWN':
                mouse_controller.press(Button.middle)
            elif cmd_type == 'MOUSE_MIDDLE_UP':
                mouse_controller.release(Button.middle)

    except Exception:
        pass


def handle_touchpad_command(cmd_type, data):
    """处理触控板命令（支持双鼠标宝剑光标模式）"""
    global double_mouse_enabled, sword_cursor_pos
    try:
        if double_mouse_enabled:
            log(f'[双鼠标] 收到 TOUCHPAD 命令: {cmd_type}, sword_pos={sword_cursor_pos}')

        if double_mouse_enabled:
            # ============ 双鼠标宝剑光标模式 ============
            if cmd_type == 'TOUCHPAD_MOVE':
                parts = data.split(',')
                if len(parts) == 2:
                    dx, dy = int(parts[0]), int(parts[1])
                    sword_cursor_pos = (
                        sword_cursor_pos[0] + dx,
                        sword_cursor_pos[1] + dy
                    )
                    if gui_callbacks and 'on_sword_move' in gui_callbacks:
                        gui_callbacks['on_sword_move'](sword_cursor_pos)

            elif cmd_type == 'TOUCHPAD_SCROLL':
                parts = data.split(',')
                if len(parts) == 2:
                    mouse_controller.position = sword_cursor_pos
                    mouse_controller.scroll(int(parts[0]), int(parts[1]))

            elif cmd_type == 'TOUCHPAD_CLICK':
                log(f'[双鼠标] TOUCHPAD_CLICK -> _sword_click at {sword_cursor_pos}')
                _sword_click(Button.left, 1)

            elif cmd_type == 'TOUCHPAD_DOUBLE_CLICK':
                log(f'[双鼠标] TOUCHPAD_DOUBLE_CLICK -> _sword_click x2')
                _sword_click(Button.left, 2)

            elif cmd_type == 'TOUCHPAD_RIGHT_DOWN':
                log(f'[双鼠标] TOUCHPAD_RIGHT_DOWN -> _sword_press RIGHT')
                _sword_press(Button.right)

            elif cmd_type == 'TOUCHPAD_RIGHT_UP':
                log(f'[双鼠标] TOUCHPAD_RIGHT_UP -> _sword_release RIGHT')
                _sword_release(Button.right)

        else:
            # ============ 原有模式（单鼠标） ============
            if cmd_type == 'TOUCHPAD_MOVE':
                parts = data.split(',')
                if len(parts) == 2:
                    mouse_controller.move(int(parts[0]), int(parts[1]))

            elif cmd_type == 'TOUCHPAD_SCROLL':
                parts = data.split(',')
                if len(parts) == 2:
                    mouse_controller.scroll(int(parts[0]), int(parts[1]))

            elif cmd_type == 'TOUCHPAD_CLICK':
                mouse_controller.click(Button.left, 1)
            elif cmd_type == 'TOUCHPAD_DOUBLE_CLICK':
                mouse_controller.click(Button.left, 2)
            elif cmd_type == 'TOUCHPAD_RIGHT_DOWN':
                mouse_controller.press(Button.right)
            elif cmd_type == 'TOUCHPAD_RIGHT_UP':
                mouse_controller.release(Button.right)

    except Exception:
        pass


def handle_keyboard_command(cmd_type, data):
    """处理键盘命令"""
    try:
        key = KEY_MAP.get(data, data)
        if cmd_type == 'KEY_PRESS':
            keyboard_controller.press(key)
            keyboard_controller.release(key)
        elif cmd_type == 'KEY_DOWN':
            keyboard_controller.press(key)
        elif cmd_type == 'KEY_UP':
            keyboard_controller.release(key)
    except Exception:
        pass


def handle_shutdown_command(cmd_type, data):
    """处理远程关机命令
    data: 'now' 立即关机, 'delay:<秒数>' 延时关机
    使用 Windows shutdown 命令，延时关机可用 'shutdown /a' 取消
    """
    try:
        if data == 'now':
            os.system('shutdown /s /t 0 /f')
            print('[SHUTDOWN] 收到立即关机命令，正在关机...')
        elif data.startswith('delay:'):
            seconds = int(data.split(':')[1])
            if seconds < 0:
                seconds = 0
            os.system(f'shutdown /s /t {seconds} /f')
            print(f'[SHUTDOWN] 收到延时关机命令，{seconds} 秒后关机')
    except Exception as e:
        print(f'[SHUTDOWN] 关机命令执行失败: {e}')


def handle_reboot_command(cmd_type, data):
    """处理远程重启命令
    data: 'now' 立即重启, 'delay:<秒数>' 延时重启
    使用 Windows shutdown 命令，延时重启可用 'shutdown /a' 取消
    """
    try:
        if data == 'now':
            os.system('shutdown /r /t 0 /f')
            print('[REBOOT] 收到立即重启命令，正在重启...')
        elif data.startswith('delay:'):
            seconds = int(data.split(':')[1])
            if seconds < 0:
                seconds = 0
            os.system(f'shutdown /r /t {seconds} /f')
            print(f'[REBOOT] 收到延时重启命令，{seconds} 秒后重启')
    except Exception as e:
        print(f'[REBOOT] 重启命令执行失败: {e}')


def handle_gamepad_command(cmd_type, data):
    """处理游戏手柄命令"""
    try:
        if cmd_type == 'GAMEPAD_DOWN':
            key = GAMEPAD_KEY_MAP.get(data, data)
            keyboard_controller.press(key)
        elif cmd_type == 'GAMEPAD_UP':
            key = GAMEPAD_KEY_MAP.get(data, data)
            keyboard_controller.release(key)
        elif cmd_type == 'GAMEPAD_LEFT_STICK':
            parts = data.split(',')
            if len(parts) == 2:
                dx = int(parts[0]) * 0.5
                dy = int(parts[1]) * 0.5
                if abs(dx) > 2 or abs(dy) > 2:
                    mouse_controller.move(dx, dy)
        elif cmd_type == 'GAMEPAD_RIGHT_STICK':
            parts = data.split(',')
            if len(parts) == 2:
                dy = int(parts[1]) * 0.2
                if abs(dy) > 2:
                    mouse_controller.scroll(0, dy)
    except Exception:
        pass


async def heartbeat(websocket, last_msg_time):
    """心跳检测任务"""
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            current_time = time.time()
            timeout_seconds = IDLE_TIMEOUT_MINUTES * 60
            if current_time - last_msg_time[0] > timeout_seconds:
                await websocket.close()
                break
            try:
                await websocket.ping()
            except Exception:
                break
    except asyncio.CancelledError:
        pass
    except Exception:
        pass


async def handle_connection(websocket):
    """处理WebSocket连接"""
    global connected_clients, pair_code
    client_addr = websocket.remote_address
    client_ip = client_addr[0] if client_addr else '未知'

    # 连接码验证：等待客户端发送配对码
    try:
        # 设置5秒超时等待配对码
        auth_message = await asyncio.wait_for(websocket.recv(), timeout=5)
        
        if not auth_message.startswith('PAIR|'):
            await websocket.send('AUTH_FAIL|连接码格式错误')
            await websocket.close()
            return
        
        received_code = auth_message[5:]  # 去掉 'PAIR|' 前缀
        
        if received_code != pair_code:
            await websocket.send(f'AUTH_FAIL|连接码错误')
            print(f'[配对] 客户端 {client_ip} 连接码错误: {received_code} (正确: {pair_code})')
            await websocket.close()
            return
        
        # 验证通过
        await websocket.send('AUTH_OK|配对成功')
        print(f'[配对] 客户端 {client_ip} 配对成功')
        
        # 配对成功后生成新的连接码（防止重复连接）
        generate_pair_code()
        
    except asyncio.TimeoutError:
        await websocket.send('AUTH_FAIL|配对超时')
        await websocket.close()
        print(f'[配对] 客户端 {client_ip} 配对超时')
        return
    except websockets.exceptions.ConnectionClosed:
        print(f'[配对] 客户端 {client_ip} 连接中断')
        return

    # 检查是否已有设备连接（仅允许1台）
    if connected_clients >= 1:
        await websocket.send('AUTH_FAIL|已有设备连接，请稍后再试')
        await websocket.close()
        print(f'[配对] 客户端 {client_ip} 被拒绝：已有设备连接')
        return

    connected_clients += 1

    if gui_callbacks:
        gui_callbacks['on_client_connect'](client_ip, connected_clients)

    last_msg_time = [time.time()]
    heartbeat_task = None

    try:
        heartbeat_task = asyncio.create_task(heartbeat(websocket, last_msg_time))

        async for message in websocket:
            last_msg_time[0] = time.time()

            if message == 'PING':
                await websocket.send('PONG')
                continue

            cmd_type, data = parse_command(message)
            if cmd_type is None:
                continue

            if cmd_type.startswith('MOUSE_'):
                handle_mouse_command(cmd_type, data)
            elif cmd_type.startswith('TOUCHPAD_'):
                handle_touchpad_command(cmd_type, data)
            elif cmd_type.startswith('KEY_'):
                handle_keyboard_command(cmd_type, data)
            elif cmd_type.startswith('GAMEPAD_'):
                handle_gamepad_command(cmd_type, data)
            elif cmd_type == 'TRANSFORM_SHOW':
                log(f'[变身] 收到TRANSFORM_SHOW指令')
                log(f'[变身] gui_callbacks: {gui_callbacks}')
                log(f'[变身] on_show_transform_image in gui_callbacks: {gui_callbacks and "on_show_transform_image" in gui_callbacks}')
                if gui_callbacks and 'on_show_transform_image' in gui_callbacks:
                    log('[变身] 调用on_show_transform_image回调')
                    gui_callbacks['on_show_transform_image']()
                else:
                    log('[变身] gui_callbacks为空或缺少on_show_transform_image回调')
            elif cmd_type == 'SHUTDOWN':
                handle_shutdown_command(cmd_type, data)
            elif cmd_type == 'REBOOT':
                handle_reboot_command(cmd_type, data)

            try:
                await websocket.send(f"OK|{cmd_type}")
            except Exception:
                break

    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception:
        pass
    finally:
        if heartbeat_task:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except Exception:
                pass
        connected_clients -= 1
        if gui_callbacks:
            gui_callbacks['on_client_disconnect'](connected_clients)


async def run_server(ip, port):
    """启动WebSocket服务器"""
    global ws_server, ws_loop
    ws_loop = asyncio.get_running_loop()
    ws_server = await websockets.serve(
        handle_connection, ip, port,
        ping_interval=HEARTBEAT_INTERVAL,
        ping_timeout=IDLE_TIMEOUT_MINUTES * 60
    )
    await ws_server.wait_closed()


def server_thread_func(ip, port):
    """服务器线程函数"""
    global server_running, ws_server, ws_loop
    try:
        asyncio.run(run_server(ip, port))
    except Exception:
        pass
    finally:
        server_running = False
        ws_server = None
        ws_loop = None
        if gui_callbacks:
            gui_callbacks['on_server_stopped']()


class SwordCursorOverlay:
    """宝剑光标悬浮窗口（双鼠标模式的"分裂鼠标"视觉层）"""

    TRANSPARENT_COLOR = 'magenta'  # 用品红色做透明色标记（Windows 特有）
    SWORD_TIP_SEARCH_CORNERS = ['top', 'right', 'bottom', 'left']  # 扫描顺序

    def __init__(self, root, line_color=(0, 0, 0)):
        self.root = root
        self.window = None
        self.canvas = None
        self.photo = None  # 保持 ImageTk 引用，防止 GC
        self.sword_img = None  # PIL Image
        self.tip_offset = (0, 0)  # 剑尖相对于图片左上的像素偏移
        self.img_w = 0
        self.img_h = 0
        self.line_color = line_color  # 线条颜色 (R, G, B)
        self._build()

    def _load_and_prepare(self):
        """加载宝剑图片 → 白色转透明 → 旋转 +45° → 缩放 → 找剑尖"""
        import math
        # 用 _resource_path 查找（兼容 PyInstaller 打包和开发模式）
        sword_path = _resource_path('宝剑1.jpg')
        if not os.path.exists(sword_path):
            sword_path = _resource_path('宝剑1.png')
        if not os.path.exists(sword_path):
            raise FileNotFoundError(f'宝剑图片不存在: 请将 宝剑1.jpg 放入 exe 同级目录')

        try:
            from PIL import Image
        except ImportError:
            raise ImportError('Pillow 未安装，请 pip install Pillow')

        # 加载并转 RGBA
        img = Image.open(sword_path).convert('RGBA')

        # 白色/近白色 → 完全透明 (alpha=0)
        # 线条 → 指定颜色 (alpha=255)
        # 不用 magenta 做像素颜色！ImageTk 会直接用 RGBA alpha 通道控制透明
        lc = self.line_color
        datas = img.getdata()
        new_data = []
        for item in datas:
            if item[0] > 240 and item[1] > 240 and item[2] > 240:
                new_data.append((0, 0, 0, 0))      # 完全透明
            else:
                new_data.append((lc[0], lc[1], lc[2], 255))  # 指定颜色
        img.putdata(new_data)

        # 旋转 +45°（PIL rotate 是逆时针，+45° = 逆时针 45°）
        try:
            resample = Image.Resampling.BICUBIC
        except AttributeError:
            resample = Image.BICUBIC
        rotated = img.rotate(45, expand=True, resample=resample)

        # ⚠️ 关键：旋转+缩放后 BICUBIC 插值会产生半透明混合色，
        # 这些混合色不是纯 magenta，transparentcolor 不会把它们变透明，
        # 就会在屏幕上显示成玫红色/灰色的毛刺。必须做后处理清理。
        rotated = self._cleanup_pixels(rotated)

        # 缩放到合理大小（旋转后可能太大）
        target_height = 120  # 宝剑在屏幕上显示约 120px 高
        ratio = target_height / rotated.height
        new_size = (int(rotated.width * ratio), int(rotated.height * ratio))
        rotated = rotated.resize(new_size, resample)

        # 缩放后可能又有插值问题，再清理一次
        rotated = self._cleanup_pixels(rotated)

        # 扫描四个角落，找到剑尖（第一个非透明像素）
        self.tip_offset = self._find_tip_pixel(rotated)

        self.sword_img = rotated
        self.img_w, self.img_h = rotated.size
        log(f'[宝剑光标] 图片加载完成: {self.img_w}x{self.img_h}, 剑尖偏移: {self.tip_offset}')

    def _cleanup_pixels(self, img):
        """清理旋转/缩放后 BICUBIC 插值产生的半透明混合像素

        用 RGBA alpha 通道控制透明，不依赖 transparentcolor。
        alpha < 30 → 完全透明 (0,0,0,0)  — 阈值 30，保护细线条不被冲淡
        alpha >= 30 → 指定线条颜色 + alpha=255
        """
        lc = self.line_color
        pixels = img.load()
        w, h = img.size
        for y in range(h):
            for x in range(w):
                r, g, b, a = pixels[x, y]
                if a < 30:
                    pixels[x, y] = (0, 0, 0, 0)           # 完全透明
                else:
                    pixels[x, y] = (lc[0], lc[1], lc[2], 255)  # 指定颜色
        return img

    def _find_tip_pixel(self, img):
        """从四个角落往里扫描，找到第一个非透明像素作为剑尖

        原始剑是竖直向上，旋转 +45° 后剑尖会在某个角附近。
        依次扫描 top→right→bottom→left 四个方向。
        """
        pixels = img.load()
        w, h = img.size
        found_points = []

        # 从顶部往下扫
        for y in range(h):
            for x in range(w):
                if pixels[x, y][3] > 128:
                    found_points.append((x, y, 'top'))
                    break
            if found_points:
                break

        # 从右边往左扫
        if not found_points:
            for x in range(w - 1, -1, -1):
                for y in range(h):
                    if pixels[x, y][3] > 128:
                        found_points.append((x, y, 'right'))
                        break
                if found_points:
                    break

        # 从底部往上扫
        if not found_points:
            for y in range(h - 1, -1, -1):
                for x in range(w):
                    if pixels[x, y][3] > 128:
                        found_points.append((x, y, 'bottom'))
                        break
                if found_points:
                    break

        # 从左边往右扫
        if not found_points:
            for x in range(w):
                for y in range(h):
                    if pixels[x, y][3] > 128:
                        found_points.append((x, y, 'left'))
                        break
                if found_points:
                    break

        if found_points:
            return (found_points[0][0], found_points[0][1])
        return (0, 0)  # fallback

    def _build(self):
        """创建透明 Toplevel 窗口并绘制宝剑"""
        from PIL import ImageTk

        self._load_and_prepare()

        self.window = tk.Toplevel(self.root)
        self.window.title('SwordCursor')
        self.window.overrideredirect(True)       # 去掉标题栏
        self.window.attributes('-topmost', True)  # 始终置顶
        # Windows 特有：设置透明色（用 Canvas + PhotoImage 的 mask 也能实现，但 transparentcolor 最简单）
        try:
            self.window.attributes('-transparentcolor', self.TRANSPARENT_COLOR)
        except tk.TclError:
            pass  # 非 Windows 平台可能不支持

        # 窗口尺寸 = 宝剑图片尺寸
        self.window.geometry(f'{self.img_w}x{self.img_h}+-10000+-10000')  # 初始移出屏幕

        self.canvas = tk.Canvas(
            self.window,
            width=self.img_w, height=self.img_h,
            bg=self.TRANSPARENT_COLOR,
            highlightthickness=0, bd=0
        )
        self.canvas.pack()

        # 绘制宝剑图片（ImageTk.PhotoImage 必须持有引用）
        self.photo = ImageTk.PhotoImage(self.sword_img)
        self.canvas.create_image(0, 0, anchor='nw', image=self.photo)

        # ⚠️ 关键：给窗口加 WS_EX_TRANSPARENT，让鼠标事件穿透到下面的窗口
        # 否则 SetCursorPos+SendInput 的点击会被这个透明窗口拦截！
        try:
            import ctypes as _ct
            hwnd = self.window.winfo_id()
            GWL_EXSTYLE = -20
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_TOOLWINDOW = 0x00000080  # 也加上，让它不出现在任务栏/Alt+Tab
            ex_style = _ct.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            _ct.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE,
                ex_style | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW
            )
            log(f'[宝剑光标] 已设置点击穿透 (WS_EX_TRANSPARENT+WS_EX_TOOLWINDOW), HWND={hwnd}, style={hex(ex_style | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW)}')
        except Exception as _e:
            log(f'[宝剑光标] 设置点击穿透失败: {_e}')

        self.window.withdraw()  # 初始隐藏

    def move_to(self, x, y):
        """把剑尖热点移到屏幕坐标 (x, y)"""
        if not self.window:
            return
        # 窗口左上 = 目标 - 剑尖偏移
        win_x = x - self.tip_offset[0]
        win_y = y - self.tip_offset[1]
        self.window.geometry(f'+{win_x}+{win_y}')
        self.window.deiconify()  # 确保显示

    def hide(self):
        """点击前临时隐藏（防止窗口拦截 SendInput 点击）"""
        if self.window:
            try:
                self.window.withdraw()
            except Exception:
                pass

    def show(self):
        """点击后恢复显示"""
        if self.window:
            try:
                self.window.deiconify()
            except Exception:
                pass

    def destroy(self):
        """销毁宝剑窗口"""
        if self.window:
            try:
                self.window.destroy()
            except Exception:
                pass
            self.window = None
            self.canvas = None
            self.photo = None
            self.sword_img = None

    def reload_color(self, line_color):
        """切换线条颜色：重新加载图片 → 重绘 Canvas（不重建窗口）"""
        from PIL import ImageTk
        self.line_color = line_color
        self._load_and_prepare()  # 用新颜色重新处理图片
        if self.canvas and self.window:
            # 重绘 Canvas
            self.canvas.delete('all')
            self.photo = ImageTk.PhotoImage(self.sword_img)
            self.canvas.create_image(0, 0, anchor='nw', image=self.photo)
            # 如果宝剑当前是显示状态，还需要重新定位窗口（尺寸可能变了）
            if self.window.state() != 'withdrawn':
                self.window.geometry(f'{self.img_w}x{self.img_h}')


class TPadServerGUI:
    """TPad Server GUI界面"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("百变控制器 服务端")
        self.root.geometry("500x780")
        self.root.resizable(False, False)
        self.root.configure(bg='#f0f0f0')

        # 窗口居中
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - 500) // 2
        y = (self.root.winfo_screenheight() - 750) // 2
        self.root.geometry(f"500x750+{x}+{y}")

        # 关闭窗口时清理
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # 设置全局回调
        global gui_callbacks
        gui_callbacks = {
            'on_client_connect': self.on_client_connect,
            'on_client_disconnect': self.on_client_disconnect,
            'on_server_stopped': self.on_server_stopped,
            'on_show_transform_image': self.on_show_transform_image,
            'on_image_uploaded': self.on_image_uploaded,
            'on_pair_code_update': self.on_pair_code_update,
            'on_sword_move': self.on_sword_move
        }

        self.ble_peripheral = None
        self.ble_advertising = False

        self.build_ui()

        # 加载用户配置（颜色等偏好）
        self._load_config()

        # 初始化蓝牙
        if BLE_AVAILABLE:
            try:
                self.ble_peripheral = get_ble_peripheral()
                self.ble_peripheral.on_data_received = self._on_ble_data_received
                self.ble_peripheral.on_connection_change = self._on_ble_connection_change
                self._write_ble_log('[Server] 蓝牙模块初始化成功')
            except Exception as e:
                self._write_ble_log(f'[Server] 蓝牙初始化失败: {e}')
                self.ble_peripheral = None
        else:
            self._write_ble_log('[Server] 蓝牙模块不可用 (BLE_AVAILABLE=False)')

        # 自动启动服务
        self.root.after(100, self.start_server)

        # BLE 心跳检测：每 10 秒检查一次，超过 20 秒没收到数据则认为断开
        self._last_ble_data_time = 0
        self._ble_heartbeat_running = False
        self._start_ble_heartbeat()

    def build_ui(self):
        """构建界面"""
        # 标题区域
        title_frame = tk.Frame(self.root, bg='#2c3e50', height=70)
        title_frame.pack(fill='x')
        title_frame.pack_propagate(False)

        title_left = tk.Frame(title_frame, bg='#2c3e50')
        title_left.pack(side='left', padx=(20, 0), pady=(12, 0))

        tk.Label(
            title_left, text="百变控制器",
            font=('微软雅黑', 22, 'bold'),
            fg='white', bg='#2c3e50'
        ).pack()

        tk.Label(
            title_left, text="手机远程控制服务端",
            font=('微软雅黑', 10),
            fg='#95a5a6', bg='#2c3e50'
        ).pack()

        tk.Label(
            title_frame, text=APP_VERSION,
            font=('微软雅黑', 10), fg='#95a5a6', bg='#2c3e50'
        ).pack(side='right', padx=(0, 20), pady=(12, 0))

        # 状态指示灯
        self.status_frame = tk.Frame(self.root, bg='#f0f0f0')
        self.status_frame.pack(fill='x', padx=30, pady=(12, 6))

        self.status_dot = tk.Canvas(self.status_frame, width=16, height=16, bg='#f0f0f0', highlightthickness=0)
        self.status_dot.pack(side='left')
        self.status_dot.create_oval(2, 2, 14, 14, fill='#e74c3c', outline='', tags='dot')

        self.status_label = tk.Label(
            self.status_frame, text="  服务未启动",
            font=('微软雅黑', 13), fg='#7f8c8d', bg='#f0f0f0'
        )
        self.status_label.pack(side='left')

        # 开机自启动勾选框
        self.auto_start_var = tk.BooleanVar(value=self._check_auto_start())
        self.auto_start_cb = tk.Checkbutton(
            self.status_frame, text="开机自启", variable=self.auto_start_var,
            font=('微软雅黑', 10), fg='#7f8c8d', bg='#f0f0f0',
            activebackground='#f0f0f0', activeforeground='#7f8c8d',
            selectcolor='white', command=self._toggle_auto_start
        )
        self.auto_start_cb.pack(side='right')

        # 信息卡片
        info_frame = tk.Frame(self.root, bg='white', relief='solid', bd=1)
        info_frame.pack(fill='x', padx=30, pady=6)

        # IP地址
        ip_row = tk.Frame(info_frame, bg='white')
        ip_row.pack(fill='x', padx=20, pady=(10, 5))
        tk.Label(ip_row, text="IP 地址", font=('微软雅黑', 10), fg='#95a5a6', bg='white', width=8, anchor='w').pack(side='left')
        self.ip_label = tk.Label(ip_row, text="获取中...", font=('Consolas', 15, 'bold'), fg='#2c3e50', bg='white')
        self.ip_label.pack(side='right')

        # 端口
        port_row = tk.Frame(info_frame, bg='white')
        port_row.pack(fill='x', padx=20, pady=5)
        tk.Label(port_row, text="端口", font=('微软雅黑', 10), fg='#95a5a6', bg='white', width=8, anchor='w').pack(side='left')
        self.port_label = tk.Label(port_row, text="8765", font=('Consolas', 15, 'bold'), fg='#2c3e50', bg='white')
        self.port_label.pack(side='right')

        # 连接码
        pair_row = tk.Frame(info_frame, bg='white')
        pair_row.pack(fill='x', padx=20, pady=5)
        tk.Label(pair_row, text="连接码", font=('微软雅黑', 10), fg='#95a5a6', bg='white', width=8, anchor='w').pack(side='left')
        self.pair_code_label = tk.Label(pair_row, text="----", font=('Consolas', 24, 'bold'), fg='#e74c3c', bg='white')
        self.pair_code_label.pack(side='right')
        
        # 刷新连接码按钮
        refresh_row = tk.Frame(info_frame, bg='white')
        refresh_row.pack(fill='x', padx=20, pady=(0, 5))
        tk.Label(refresh_row, text="", font=('微软雅黑', 10), bg='white', width=8).pack(side='left')
        self.refresh_btn = tk.Button(
            refresh_row, text="🔄 刷新连接码",
            font=('微软雅黑', 9), fg='#3498db', bg='white',
            relief='flat', cursor='hand2', command=self.refresh_pair_code
        )
        self.refresh_btn.pack(side='right')

        # 分割线
        tk.Frame(info_frame, bg='#ecf0f1', height=1).pack(fill='x', padx=20, pady=3)

        # 连接状态
        conn_row = tk.Frame(info_frame, bg='white')
        conn_row.pack(fill='x', padx=20, pady=(3, 5))
        tk.Label(conn_row, text="已连接", font=('微软雅黑', 10), fg='#95a5a6', bg='white', width=8, anchor='w').pack(side='left')
        self.conn_label = tk.Label(conn_row, text="0 台设备", font=('微软雅黑', 13, 'bold'), fg='#bdc3c7', bg='white')
        self.conn_label.pack(side='right')

        # 分割线
        tk.Frame(info_frame, bg='#ecf0f1', height=1).pack(fill='x', padx=20, pady=3)

        # 超时设置
        timeout_row = tk.Frame(info_frame, bg='white')
        timeout_row.pack(fill='x', padx=20, pady=(3, 5))
        tk.Label(timeout_row, text="超时时间", font=('微软雅黑', 10), fg='#95a5a6', bg='white', width=8, anchor='w').pack(side='left')
        self.timeout_var = tk.StringVar(value=str(IDLE_TIMEOUT_MINUTES) + '分钟')
        self.timeout_combobox = ttk.Combobox(
            timeout_row, textvariable=self.timeout_var,
            values=[str(m) + '分钟' for m in IDLE_TIMEOUT_OPTIONS],
            state='readonly', width=12, font=('微软雅黑', 11)
        )
        self.timeout_combobox.pack(side='right')
        self.timeout_combobox.bind('<<ComboboxSelected>>', self.on_timeout_change)

        # 分割线
        tk.Frame(info_frame, bg='#ecf0f1', height=1).pack(fill='x', padx=20, pady=3)

        # 变身图片状态
        image_row = tk.Frame(info_frame, bg='white')
        image_row.pack(fill='x', padx=20, pady=(3, 5))
        tk.Label(image_row, text="变身图片", font=('微软雅黑', 10), fg='#95a5a6', bg='white', width=8, anchor='w').pack(side='left')
        self.image_status_label = tk.Label(image_row, text="等待上传", font=('微软雅黑', 12), fg='#bdc3c7', bg='white')
        self.image_status_label.pack(side='right')

        # 分割线
        tk.Frame(info_frame, bg='#ecf0f1', height=1).pack(fill='x', padx=20, pady=3)

        # 双鼠标（宝剑光标）
        sword_row = tk.Frame(info_frame, bg='white')
        sword_row.pack(fill='x', padx=20, pady=(3, 5))
        tk.Label(sword_row, text="双鼠标", font=('微软雅黑', 10), fg='#95a5a6', bg='white', width=8, anchor='w').pack(side='left')

        # 宝剑颜色下拉框 + 自选按钮
        SWORD_COLORS = [
            ('黑色', (0, 0, 0)),
            ('白色', (255, 255, 255)),
            ('红色', (231, 76, 60)),
            ('蓝色', (52, 152, 219)),
            ('绿色', (46, 204, 113)),
            ('金色', (241, 196, 15)),
            ('紫色', (155, 89, 182)),
        ]
        self._sword_color_map = dict(SWORD_COLORS)  # {'黑色': (0,0,0), ...}
        self._sword_custom_color = None  # 自选颜色缓存
        # 默认红色，启动时会从配置文件覆盖
        self.sword_color_var = tk.StringVar(value='红色')
        self._sword_color_rgb = (231, 76, 60)  # 当前实际使用的颜色 RGB（默认红色）
        self.sword_color_cb = ttk.Combobox(
            sword_row, textvariable=self.sword_color_var,
            values=[c[0] for c in SWORD_COLORS] + ['自选...'],
            width=7, state='readonly',
            font=('微软雅黑', 9),
        )
        self.sword_color_cb.pack(side='left', padx=(0, 4))
        self.sword_color_cb.bind('<<ComboboxSelected>>', self._on_sword_color_change)

        # 色块按钮：点击打开颜色选择器，同时显示当前颜色
        self.sword_color_btn = tk.Button(
            sword_row, text='', width=4, height=1,
            relief='solid', bd=1, cursor='hand2',
            bg=self._rgb_to_hex(self._sword_color_rgb),
            command=self._pick_custom_color,
        )
        self.sword_color_btn.pack(side='left', padx=(0, 10))

        self.double_mouse_var = tk.BooleanVar(value=False)
        self.double_mouse_cb = tk.Checkbutton(
            sword_row, text="启用宝剑光标", variable=self.double_mouse_var,
            font=('微软雅黑', 11), fg='#3498db', bg='white',
            activebackground='white', activeforeground='#3498db',
            selectcolor='white', command=self.toggle_double_mouse,
            cursor='hand2'
        )
        self.double_mouse_cb.pack(side='right')

        # 分割线
        tk.Frame(info_frame, bg='#ecf0f1', height=1).pack(fill='x', padx=20, pady=3)

        # WiFi服务
        wifi_row = tk.Frame(info_frame, bg='white')
        wifi_row.pack(fill='x', padx=20, pady=(3, 5))
        tk.Label(wifi_row, text="WiFi", font=('微软雅黑', 10), fg='#95a5a6', bg='white', width=8, anchor='w').pack(side='left')
        self.wifi_status_label = tk.Label(wifi_row, text="未启动", font=('微软雅黑', 12), fg='#bdc3c7', bg='white')
        self.wifi_status_label.pack(side='left')
        self.wifi_toggle_btn = tk.Button(
            wifi_row, text="启动服务",
            font=('微软雅黑', 9), fg='#27ae60', bg='white',
            relief='flat', cursor='hand2', command=self.toggle_wifi_server
        )
        self.wifi_toggle_btn.pack(side='right')

        # 蓝牙服务
        ble_row = tk.Frame(info_frame, bg='white')
        ble_row.pack(fill='x', padx=20, pady=(3, 10))
        tk.Label(ble_row, text="蓝牙", font=('微软雅黑', 10), fg='#95a5a6', bg='white', width=8, anchor='w').pack(side='left')
        self.ble_status_label = tk.Label(ble_row, text="未开启", font=('微软雅黑', 12), fg='#bdc3c7', bg='white')
        self.ble_status_label.pack(side='left')
        self.ble_advertise_btn = tk.Button(
            ble_row, text="开启广播",
            font=('微软雅黑', 9), fg='#3498db', bg='white',
            relief='flat', cursor='hand2', command=self.toggle_ble_advertise
        )
        self.ble_advertise_btn.pack(side='right')

        # 提示信息（可滚动）
        tip_outer = tk.Frame(self.root, bg='#f0f0f0')
        tip_outer.pack(fill='both', expand=True, padx=30, pady=6)

        tk.Label(
            tip_outer, text="使用说明",
            font=('微软雅黑', 11, 'bold'), fg='#2c3e50', bg='#f0f0f0'
        ).pack(anchor='w', pady=(0, 5))

        # Canvas + Scrollbar 实现可滚动
        tip_canvas = tk.Canvas(tip_outer, bg='#f0f0f0', highlightthickness=0, height=120)
        tip_scrollbar = ttk.Scrollbar(tip_outer, orient='vertical', command=tip_canvas.yview)
        tip_inner = tk.Frame(tip_canvas, bg='#f0f0f0')

        tip_inner.bind(
            '<Configure>',
            lambda e: tip_canvas.configure(scrollregion=tip_canvas.bbox('all'))
        )
        tip_canvas.create_window((0, 0), window=tip_inner, anchor='nw')
        tip_canvas.configure(yscrollcommand=tip_scrollbar.set)

        tip_canvas.pack(side='left', fill='both', expand=True)
        tip_scrollbar.pack(side='right', fill='y')

        # 鼠标滚轮绑定（Windows）
        def _on_mousewheel(event):
            tip_canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')
        tip_canvas.bind('<Enter>', lambda e: tip_canvas.bind_all('<MouseWheel>', _on_mousewheel))
        tip_canvas.bind('<Leave>', lambda e: tip_canvas.unbind_all('<MouseWheel>'))

        tips = [
            "1. WiFi模式：确保手机和电脑在同一WiFi网络",
            "2. 点击WiFi右侧的\"启动服务\"按钮开启WiFi",
            "3. 在小程序中输入上方IP地址和连接码连接",
            "4. 蓝牙模式：点击蓝牙右侧的\"开启广播\"按钮",
            "5. 在小程序蓝牙页面搜索并连接您的电脑",
            "6. 如控制无效，请以管理员身份运行",
            "7. 设备连接超时无通信将自动断开（可设置）",
            "8. 双鼠标模式：勾选后手机控制宝剑光标，物理鼠标正常使用",
            "9. 双鼠标点击时系统鼠标会暂时瞬移到宝剑位置执行点击",
        ]
        for tip in tips:
            tk.Label(
                tip_inner, text=tip,
                font=('微软雅黑', 10), fg='#7f8c8d', bg='#f0f0f0', anchor='w'
            ).pack(anchor='w', pady=1)

        # 底部间距
        tk.Frame(self.root, bg='#f0f0f0', height=10).pack(fill='x')

    def _check_auto_start(self):
        """检查是否已设置开机自启动"""
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_READ
            )
            winreg.QueryValueEx(key, "TPadServer")
            winreg.CloseKey(key)
            return True
        except (FileNotFoundError, OSError):
            return False
        except Exception:
            return False

    def _toggle_auto_start(self):
        """切换开机自启动"""
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            if self.auto_start_var.get():
                exe_path = sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(__file__)
                key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
                winreg.SetValueEx(key, "TPadServer", 0, winreg.REG_SZ, f'"{exe_path}"')
                winreg.CloseKey(key)
            else:
                try:
                    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
                    winreg.DeleteValue(key, "TPadServer")
                    winreg.CloseKey(key)
                except FileNotFoundError:
                    pass
        except Exception as e:
            messagebox.showerror("错误", f"设置开机自启动失败:\n{e}")
            self.auto_start_var.set(not self.auto_start_var.get())

    def toggle_wifi_server(self):
        """切换WiFi服务"""
        global server_running
        if server_running:
            self.stop_server()
        else:
            self.start_server()

    def start_server(self):
        """启动服务"""
        global server_running, server_thread, http_thread

        if server_running:
            return

        ip = get_local_ip()
        port = 8765

        self.ip_label.config(text=ip)
        server_running = True
        
        # 生成连接码
        generate_pair_code()
        
        server_thread = threading.Thread(target=server_thread_func, args=(ip, port), daemon=True)
        server_thread.start()

        # 启动HTTP服务器（用于图片上传）
        http_thread = threading.Thread(target=start_http_server, daemon=True)
        http_thread.start()

        # 更新UI
        self.status_dot.itemconfig('dot', fill='#27ae60')
        self.status_label.config(text="  服务运行中", fg='#27ae60')
        self.conn_label.config(text="0 台设备", fg='#bdc3c7')
        self.pair_code_label.config(text=pair_code, fg='#e74c3c')
        self.refresh_btn.config(state='normal')
        self.wifi_status_label.config(text="运行中", fg='#27ae60')
        self.wifi_toggle_btn.config(text="停止服务", fg='#e74c3c')

    def stop_server(self):
        """停止服务"""
        global server_running, ws_server, ws_loop

        if not server_running:
            return

        server_running = False

        # 通过事件循环安全地关闭WebSocket服务器
        if ws_server and ws_loop:
            try:
                ws_loop.call_soon_threadsafe(ws_server.close)
            except Exception:
                pass

        # 停止HTTP服务器
        stop_http_server()

        # 更新UI
        self.status_dot.itemconfig('dot', fill='#e74c3c')
        self.status_label.config(text="  服务已停止", fg='#e74c3c')
        self.conn_label.config(text="0 台设备", fg='#bdc3c7')
        self.pair_code_label.config(text="----")
        self.refresh_btn.config(state='disabled')
        self.wifi_status_label.config(text="未启动", fg='#bdc3c7')
        self.wifi_toggle_btn.config(text="启动服务", fg='#27ae60')

    def on_client_connect(self, client_ip, count):
        """客户端连接回调（子线程调用）"""
        self.root.after(0, lambda: self._update_client_connect(client_ip, count))

    def _update_client_connect(self, client_ip, count):
        """更新客户端连接UI"""
        self.conn_label.config(text=f"{count} 台设备", fg='#27ae60')
        self.pair_code_label.config(text="••••", fg='#bdc3c7')
        self.refresh_btn.config(state='disabled')

    def on_client_disconnect(self, count):
        """客户端断开回调（子线程调用）"""
        self.root.after(0, lambda: self._update_client_disconnect(count))

    def _update_client_disconnect(self, count):
        """更新客户端断开UI"""
        if count > 0:
            self.conn_label.config(text=f"{count} 台设备", fg='#27ae60')
        else:
            self.conn_label.config(text="0 台设备", fg='#bdc3c7')
            self.pair_code_label.config(text=pair_code, fg='#e74c3c')
            self.refresh_btn.config(state='normal')

    def on_server_stopped(self):
        """服务停止回调（子线程调用）"""
        self.root.after(0, self._update_server_stopped)

    def _update_server_stopped(self):
        """更新服务停止UI"""
        global server_running
        server_running = False
        self.status_dot.itemconfig('dot', fill='#e74c3c')
        self.status_label.config(text="  服务已停止", fg='#e74c3c')
        self.conn_label.config(text="0 台设备", fg='#bdc3c7')
        self.client_list_label.config(text="无", fg='#bdc3c7')
        self.wifi_status_label.config(text="未启动", fg='#bdc3c7')
        self.wifi_toggle_btn.config(text="启动服务", fg='#27ae60')

    def on_timeout_change(self, event):
        """超时时间变更处理"""
        global IDLE_TIMEOUT_MINUTES
        selected = self.timeout_var.get()
        IDLE_TIMEOUT_MINUTES = int(selected.replace('分钟', ''))
        print(f'[设置] 超时时间已改为 {IDLE_TIMEOUT_MINUTES} 分钟')

    def on_show_transform_image(self):
        """显示变身图片（子线程调用）"""
        print('[变身] 收到显示变身图片命令')
        self.root.after(0, self._show_transform_image)

    def refresh_pair_code(self):
        """手动刷新连接码"""
        generate_pair_code()

    def on_pair_code_update(self, code):
        """连接码更新回调（子线程调用）"""
        self.root.after(0, lambda: self._update_pair_code(code))

    def _update_pair_code(self, code):
        """更新连接码显示"""
        if connected_clients > 0:
            self.pair_code_label.config(text="••••", fg='#bdc3c7')
        else:
            self.pair_code_label.config(text=code, fg='#e74c3c')

    def on_image_uploaded(self, file_size):
        """图片上传成功回调（子线程调用）"""
        self.root.after(0, lambda: self._update_image_status(file_size))

    def _update_image_status(self, file_size):
        """更新图片上传状态显示"""
        size_kb = file_size / 1024
        self.image_status_label.config(
            text=f"已上传 ({size_kb:.1f} KB)",
            fg='#27ae60'
        )

    # ============ 双鼠标宝剑光标 ============

    def toggle_double_mouse(self):
        """切换双鼠标开关"""
        global double_mouse_enabled, sword_cursor_pos, sword_cursor_window
        enabled = self.double_mouse_var.get()

        if enabled:
            # 启用：创建宝剑窗口，初始位置 = 当前系统鼠标位置
            try:
                color_name = self.sword_color_var.get()
                if color_name == '自选...' and self._sword_custom_color:
                    color_rgb = self._sword_custom_color
                else:
                    color_rgb = self._sword_color_map.get(color_name, (0, 0, 0))
                sword_cursor_window = SwordCursorOverlay(self.root, line_color=color_rgb)
                self._apply_sword_color(color_rgb, color_name if color_name != '自选...' else None)
                double_mouse_enabled = True
                # 初始宝剑位置设为当前系统鼠标位置
                sword_cursor_pos = (mouse_controller.position[0], mouse_controller.position[1])
                sword_cursor_window.move_to(*sword_cursor_pos)
                log(f'[双鼠标] 宝剑光标已启用 (颜色: {color_name})')
            except Exception as e:
                log(f'[双鼠标] 启用失败: {e}')
                self.double_mouse_var.set(False)
                sword_cursor_window = None
                double_mouse_enabled = False
                messagebox.showerror('错误', f'宝剑光标启用失败:\n{e}')
        else:
            # 关闭：销毁宝剑窗口
            double_mouse_enabled = False
            if sword_cursor_window:
                sword_cursor_window.destroy()
                sword_cursor_window = None
            log('[双鼠标] 宝剑光标已关闭')

    @staticmethod
    def _rgb_to_hex(rgb):
        """(R,G,B) → '#RRGGBB'"""
        return '#{:02x}{:02x}{:02x}'.format(rgb[0], rgb[1], rgb[2])

    def _apply_sword_color(self, color_rgb, color_name=None):
        """统一入口：应用颜色到宝剑 + 更新色块按钮 + 持久化保存"""
        global sword_cursor_window
        self._sword_color_rgb = color_rgb
        # 更新色块按钮
        hex_color = self._rgb_to_hex(color_rgb)
        self.sword_color_btn.config(bg=hex_color)
        # 更新宝剑
        if sword_cursor_window:
            sword_cursor_window.reload_color(color_rgb)
            name_info = color_name or hex_color
            log(f'[双鼠标] 宝剑颜色切换为: {name_info}')
        # 持久化保存
        self._save_config()

    def _save_config(self):
        """保存用户偏好到 server_config.json"""
        try:
            config = {}
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            # 保存宝剑颜色
            color_name = self.sword_color_var.get()
            config['sword_color'] = {
                'name': color_name,              # 如 '红色' 或 '自选...'
                'rgb': list(self._sword_color_rgb),  # [R, G, B] 数组
                'custom_rgb': list(self._sword_custom_color) if self._sword_custom_color else None,
            }
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log(f'[配置] 保存失败: {e}')

    def _load_config(self):
        """从 server_config.json 加载用户偏好（启动时调用）"""
        try:
            if not os.path.exists(CONFIG_PATH):
                return
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                config = json.load(f)
            sc = config.get('sword_color', {})
            color_name = sc.get('name', '红色')
            color_rgb = tuple(sc.get('rgb', [231, 76, 60]))

            # 如果有自选颜色缓存
            custom = sc.get('custom_rgb')
            if custom:
                self._sword_custom_color = tuple(custom)

            # 更新 UI
            self.sword_color_var.set(color_name)
            self._sword_color_rgb = color_rgb
            self.sword_color_btn.config(bg=self._rgb_to_hex(color_rgb))
        except Exception as e:
            log(f'[配置] 加载失败: {e}')

    def _on_sword_color_change(self, event=None):
        """颜色下拉框切换回调"""
        color_name = self.sword_color_var.get()
        if color_name == '自选...':
            self._pick_custom_color()
            return
        color_rgb = self._sword_color_map.get(color_name, (0, 0, 0))
        self._apply_sword_color(color_rgb, color_name)

    def _pick_custom_color(self):
        """打开系统颜色选择器，自选颜色"""
        # colorchooser 返回 ((R,G,B), '#RRGGBB') 或 (None, None)
        result = colorchooser.askcolor(
            color=self._rgb_to_hex(self._sword_color_rgb),
            title='选择宝剑颜色'
        )
        if result and result[0]:
            color_rgb = (int(result[0][0]), int(result[0][1]), int(result[0][2]))
            self._sword_custom_color = color_rgb
            # 下拉框显示"自选..."
            self.sword_color_var.set('自选...')
            self._apply_sword_color(color_rgb, '自选')

    def on_sword_move(self, pos):
        """宝剑移动回调（子线程调用，需切到主线程）"""
        self.root.after(0, lambda: self._move_sword(pos))

    def _move_sword(self, pos):
        """主线程移动宝剑窗口"""
        global sword_cursor_window
        if sword_cursor_window:
            sword_cursor_window.move_to(pos[0], pos[1])

    def _show_transform_image(self):
        """在主线程显示变身图片（闪现效果）"""
        log(f'[变身] 检查图片路径: {IMAGE_SAVE_PATH}')
        log(f'[变身] 图片是否存在: {os.path.exists(IMAGE_SAVE_PATH)}')
        if not os.path.exists(IMAGE_SAVE_PATH):
            log('[变身] 图片不存在，取消显示')
            return

        try:
            from PIL import Image, ImageTk
            log('[变身] Pillow 导入成功')
        except ImportError:
            log('[变身] Pillow 未安装')
            return

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        log(f'[变身] 屏幕尺寸: {screen_w}x{screen_h}')

        top = tk.Toplevel(self.root)
        top.configure(bg='white')
        top.attributes('-topmost', True)
        top.geometry(f"{screen_w}x{screen_h}+0+0")
        top.overrideredirect(True)

        canvas = tk.Canvas(top, width=screen_w, height=screen_h, bg='white', highlightthickness=0)
        canvas.pack(fill='both', expand=True)

        # 预加载图片
        try:
            img = Image.open(IMAGE_SAVE_PATH)
            log(f'[变身] 图片打开成功, 尺寸: {img.size}, 模式: {img.mode}')
            try:
                resample = Image.Resampling.LANCZOS
            except AttributeError:
                resample = Image.LANCZOS
            if img.mode not in ('RGB', 'RGBA'):
                img = img.convert('RGB')
            # 等比缩放到屏幕大小
            img_w, img_h = img.size
            ratio = min(screen_w / img_w, screen_h / img_h) * 0.85
            new_w = int(img_w * ratio)
            new_h = int(img_h * ratio)
            img = img.resize((new_w, new_h), resample)
            photo = ImageTk.PhotoImage(img)
            canvas._photo = photo
            log(f'[变身] 图片缩放后: {new_w}x{new_h}')
        except Exception as e:
            log(f'[变身] 图片加载异常: {e}')
            top.destroy()
            return

        # 白色闪光200ms，然后显示图片
        def show_image():
            try:
                canvas.config(bg='black')
                canvas.create_image(screen_w // 2, screen_h // 2, image=photo, anchor='center')
                log('[变身] 图片显示成功')
            except Exception as e:
                log(f'[变身] 图片绘制异常: {e}')

        top.after(200, show_image)

        # 点击关闭
        def close_top(event):
            top.destroy()
        canvas.bind('<Button-1>', close_top)
        top.bind('<Button-1>', close_top)

        # 3秒后自动关闭
        top.after(3000, top.destroy)

    def _write_ble_log(self, msg):
        if not BLE_LOG_FILE:
            return
        try:
            import datetime
            line = f'[{datetime.datetime.now().strftime("%H:%M:%S")}] {msg}'
            with open(BLE_LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(line + '\n')
        except Exception:
            pass

    def open_ble_log(self):
        if BLE_LOG_FILE and os.path.exists(BLE_LOG_FILE):
            os.startfile(BLE_LOG_FILE)
        else:
            messagebox.showinfo('提示', f'日志文件不存在\n路径: {BLE_LOG_FILE}')

    def toggle_ble_advertise(self):
        """切换蓝牙广播"""
        if not self.ble_peripheral or not BLE_AVAILABLE:
            tk.messagebox.showinfo('提示', '蓝牙功能不可用')
            return
        
        if self.ble_peripheral.is_connected():
            self._ble_disconnect()
            return
        
        if self.ble_advertising:
            self._ble_stop_advertising()
        else:
            self._ble_start_advertising()

    def _ble_start_advertising(self):
        """开始蓝牙广播"""
        def start_thread():
            try:
                success = self.ble_peripheral.start()
                if success:
                    import time
                    time.sleep(0.5)
                    if self.ble_peripheral.is_advertising():
                        self.root.after(0, self._ble_advertising_started)
                    else:
                        self.root.after(0, self._ble_advertising_failed)
                else:
                    self.root.after(0, self._ble_advertising_failed)
            except Exception as e:
                print(f'[BLE] 启动广播异常: {e}')
                self.root.after(0, self._ble_advertising_failed)

        self.ble_status_label.config(text='启动中...', fg='#f39c12')
        self.ble_advertise_btn.config(text='启动中...', state='disabled')
        threading.Thread(target=start_thread, daemon=True).start()

    def _ble_advertising_started(self):
        self.ble_advertising = True
        self.ble_status_label.config(text='等待连接...', fg='#f39c12')
        self.ble_advertise_btn.config(text='停止广播', state='normal')
        print('[BLE] 蓝牙广播已启动')

    def _ble_advertising_failed(self):
        self.ble_advertising = False
        self.ble_status_label.config(text='启动失败', fg='#e74c3c')
        self.ble_advertise_btn.config(text='开启广播', state='normal')
        tk.messagebox.showerror('错误', '蓝牙广播启动失败，请检查：\n1. 蓝牙已开启\n2. 以管理员身份运行程序\n3. 蓝牙适配器支持 Peripheral 模式')

    def _ble_stop_advertising(self):
        """停止蓝牙广播"""
        if self.ble_peripheral:
            self.ble_peripheral.stop()
        self.ble_advertising = False
        self.ble_status_label.config(text='未开启', fg='#bdc3c7')
        self.ble_advertise_btn.config(text='开启广播', state='normal')
        print('[BLE] 蓝牙广播已停止')

    def _on_ble_connection_change(self, connected):
        """蓝牙连接状态变化回调"""
        self.root.after(0, lambda: self._ble_update_connection_status(connected))

    def _ble_update_connection_status(self, connected):
        if connected:
            self.ble_advertising = False
            self.ble_status_label.config(text='已连接', fg='#27ae60')
            self.ble_advertise_btn.config(text='断开', state='normal')
            print('[BLE] 蓝牙已连接')
        else:
            self.ble_status_label.config(text='已断开', fg='#e74c3c')
            self.ble_advertise_btn.config(text='开启广播', state='normal')
            self.ble_advertising = False
            print('[BLE] 蓝牙已断开')

    def _ble_disconnect(self):
        if self.ble_peripheral:
            self.ble_peripheral.stop()
        self.ble_advertising = False
        self.ble_status_label.config(text='未开启', fg='#bdc3c7')
        self.ble_advertise_btn.config(text='开启广播', state='normal')

    def _start_ble_heartbeat(self):
        """启动 BLE 心跳检测定时器"""
        if self._ble_heartbeat_running:
            return
        self._ble_heartbeat_running = True
        self._ble_heartbeat_tick()

    def _ble_heartbeat_tick(self):
        """心跳检测：每 10 秒检查一次 BLE 连接状态"""
        if not self._ble_heartbeat_running:
            return
        try:
            if self.ble_peripheral and self.ble_peripheral.connected:
                # 已连接状态：检查最后数据时间
                if self._last_ble_data_time > 0:
                    idle = time.time() - self._last_ble_data_time
                    if idle > 20:
                        # 超过 20 秒没收到数据，可能已断开
                        print(f'[BLE] 心跳超时 {idle:.0f}s，判定连接断开')
                        self._write_ble_log(f'[心跳] 超时 {idle:.0f}s，判定断开')
                        # 标记为断开并重新广播
                        self.ble_peripheral.connected = False
                        self._ble_update_connection_status(False)
                        # 立即重新开启广播，不延迟
                        self._auto_restart_advertising()
        except Exception as e:
            print(f'[BLE] 心跳检测异常: {e}')
        # 10 秒后再检查
        self.root.after(10000, self._ble_heartbeat_tick)

    def _auto_restart_advertising(self):
        """断开后自动重新开启广播"""
        if self.ble_peripheral and not self.ble_peripheral.connected and not self.ble_advertising:
            print('[BLE] 自动重新开启广播')
            self._write_ble_log('[心跳] 自动重新广播')
            self._ble_start_advertising()

    def _on_ble_data_received(self, text, raw_data):
        """处理蓝牙收到的数据"""
        # 更新最后收到数据的时间（用于心跳检测）
        self._last_ble_data_time = time.time()
        lines = text.strip().split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue
            cmd_type, data = parse_command(line)
            if not cmd_type:
                continue

            if cmd_type.startswith('MOUSE_'):
                handle_mouse_command(cmd_type, data)
            elif cmd_type.startswith('TOUCHPAD_'):
                handle_touchpad_command(cmd_type, data)
            elif cmd_type.startswith('KEY_'):
                handle_keyboard_command(cmd_type, data)
            elif cmd_type.startswith('GAMEPAD_'):
                handle_gamepad_command(cmd_type, data)
            elif cmd_type == 'SHUTDOWN':
                handle_shutdown_command(cmd_type, data)
            elif cmd_type == 'REBOOT':
                handle_reboot_command(cmd_type, data)

    def on_close(self):
        """关闭窗口"""
        # 先销毁宝剑光标窗口
        global sword_cursor_window, double_mouse_enabled
        double_mouse_enabled = False
        if sword_cursor_window:
            try:
                sword_cursor_window.destroy()
            except Exception:
                pass
            sword_cursor_window = None

        if self.ble_peripheral:
            try:
                self.ble_peripheral.stop()
            except Exception:
                pass
        self.stop_server()
        self.root.destroy()

    def run(self):
        """运行GUI"""
        self.root.mainloop()


if __name__ == "__main__":
    app = TPadServerGUI()
    app.run()
