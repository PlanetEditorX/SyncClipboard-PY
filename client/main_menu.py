import os
import sys
import uuid
import time
import json
import logging
import requests
import threading
import pyperclip
import win32con
import win32api
import win32clipboard
from pathlib import Path
from datetime import datetime
from common.utils import BASE_DIR, SAFE_POST
from server.core.text_tracker import TextTracker

logger = logging.getLogger("client")

class SyncClient:
    """剪贴板同步客户端：推送本地变化 + 拉取远程最新"""
    def __init__(self, config, file_server=None):
        self.server_url = f"http://{config['server_host']}:{config['server_port']}"
        self.key = config["key"]
        self.local_name = config["local_name"]
        self.last_text = ""
        self.running = False
        self.last_remote_id = None
        self._last_remote_content = None
        self.push_thread = None
        self.pull_thread = None
        # 文件服务
        self.file_server = file_server
        # 全局锁，避免同时读写剪贴板
        self.clipboard_lock = threading.Lock()
        self.tracker = TextTracker()

    def safe_paste(self, retries=5):
        for _ in range(retries):
            try:
                return pyperclip.paste()
            except Exception:
                time.sleep(0.05)
        return ""

    def start(self):
        self.running = True
        self.last_text = self.safe_paste()
        logger.info("客户端剪贴板监听启动")

        # 推送线程
        self.push_thread = threading.Thread(target=self._push_loop, daemon=True)
        self.push_thread.start()

        # self.pull_thread = threading.Thread(target=self._pull_loop, daemon=True)
        # self.pull_thread.start()

    def _push_loop(self):
        self.last_text = self.safe_paste() or ""
        self.last_file_set = None
        while self.running:
            try:
                files = self.get_clipboard_files()
                if files:
                    current_set = frozenset(files)
                    if current_set != self.last_file_set:
                        self.last_file_set = current_set
                        self._push_latest_file(files)
                    time.sleep(1)
                    continue

                self.last_file_set = None
                with self.clipboard_lock:
                    text = self.safe_paste()
                if text is None:
                    text = ""
                if text != self.last_text:
                    if text and text != self._last_remote_content:
                        self.push_text(text)
                    self.last_text = text
            except Exception as e:
                logger.error(f"监听异常: {e}")
            time.sleep(0.5)

    def push_text(self, text):
        try:
            latest_global = self.tracker.get_global_latest()
            if latest_global is None or latest_global["content"] != text:
                resp = SAFE_POST(
                    f"{self.server_url}/text_sync",
                    json={
                        "key": self.key,
                        "content": text,
                        "source": self.local_name
                    },
                    timeout=30
                )
                if resp.status_code == 200:
                    logger.info(f"推送成功: {text[:50]}...")
                else:
                    logger.warning(f"推送失败: {resp.status_code} {resp.text}")
        except Exception:
            logger.exception("连接服务端失败")

    def _push_latest_file(self, file_paths):
        """
        推送最新的文件
        """
        if not file_paths:
            logger.warning("没有文件需要推送")
            return

        file_list = []
        # 推送前先清空之前的共享
        if hasattr(self, 'file_server') and self.file_server:
            self.file_server.clear_files()

        for path in file_paths:
            if not os.path.isfile(path):
                sanitized = path.encode('utf-8', 'surrogatepass').decode('utf-8', 'replace')
                logger.warning(f"文件不存在，跳过: {sanitized}")
                continue

            name = os.path.basename(path)
            size = os.path.getsize(path)
            file_id = str(uuid.uuid4())
            # 注册到 FileServer
            if hasattr(self, 'file_server') and self.file_server:
                self.file_server.register_file(file_id, path)
            file_list.append({
                "file_id": file_id,
                "path": path,
                "name": name,
                "size": size
            })

        try:
            resp = requests.post(
                f"{self.server_url}/file_sync",
                headers={"key": self.key},
                json={
                    "file_list": file_list,
                    "source": getattr(self, 'local_name', 'unknown'),
                    "port": getattr(self.file_server, 'port', None)
                },
                timeout=10
            )

            if resp.status_code == 200:
                logger.info(f"文件路径已同步: {name} ({size} bytes)")
            else:
                logger.error(f"同步失败: {name}, 状态码: {resp.status_code}, 内容: {resp.text}")
        except Exception as e:
            logger.error(f"同步文件路径失败: {name}, 错误: {e}")

    def _pull_loop(self):
        while self.running:
            try:
                resp = requests.get(
                    f"{self.server_url}/latest?source={self.local_name}",
                    headers={
                        "key": self.key
                    },
                    timeout=5
                )
                if resp.status_code == 200:
                    data = resp.json()
                    latest = data.get("latest_global")
                    if latest and latest.get("source") != self.local_name:
                        if latest["id"] != self.last_remote_id:
                            with self.clipboard_lock:
                                pyperclip.copy(latest["content"])
                            self.last_remote_id = latest["id"]
                            self._last_remote_content = latest["content"]
                            self.last_text = latest["content"]
                            logger.info(f"拉取并更新剪贴板: {latest['content'][:50]} (来自 {latest['source']})")
            except Exception as e:
                logger.error(f"拉取失败: {e} 等待10秒后重试")
                time.sleep(7)
            time.sleep(3)

    def stop(self):
        self.running = False
        logger.info("客户端已停止")

    def get_clipboard_files(self):
        """
        获取剪贴板中的文件路径列表。
        如果剪贴板中包含从资源管理器复制的文件，则返回文件路径列表（仅包含有效的、存在的路径）；
        否则返回 None。
        """
        try:
            win32clipboard.OpenClipboard()
            if not win32clipboard.IsClipboardFormatAvailable(win32con.CF_HDROP):
                return None

            hdrop = win32clipboard.GetClipboardData(win32con.CF_HDROP)

            # ---- 情况1: 如果返回的是元组/列表（直接是文件路径列表） ----
            if isinstance(hdrop, (list, tuple)):
                # 过滤出存在的有效路径（避免乱码或无效内容）
                valid_paths = [p for p in hdrop if isinstance(p, str) and os.path.exists(p)]
                return valid_paths if valid_paths else None

            # ---- 情况2: 返回的是 PyHANDLE 或整数句柄 ----
            try:
                hdrop_int = int(hdrop)   # 尝试转为整数句柄
            except (TypeError, ValueError):
                # 如果转换失败，说明类型不支持，直接返回 None
                return None

            file_count = win32api.DragQueryFile(hdrop_int, -1)
            if file_count == 0:
                return None

            file_paths = []
            for i in range(file_count):
                path = win32api.DragQueryFile(hdrop_int, i)
                if path and isinstance(path, str) and os.path.exists(path):
                    file_paths.append(path)
            return file_paths if file_paths else None

        except Exception as e:
            print(f"获取剪贴板文件失败: {e}", file=sys.stderr)
            return None
        finally:
            try:
                win32clipboard.CloseClipboard()
            except Exception as e:
                print(f"关闭剪贴板失败: {e}", file=sys.stderr)