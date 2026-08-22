# server/text_tracker.py
import json
import os
from datetime import datetime
from pathlib import Path
from common.utils import BASE_DIR, safe_get
import threading

TEXT_LATEST_FILE = BASE_DIR / "latest" / "text_latest.json"
TEXT_LATEST_FILE.parent.mkdir(parents=True, exist_ok=True)

class TextTracker:
    """
    文本追踪器，用于管理跨客户端的文本数据。
    数据结构：
    - latest_global: 全局最新的文本条目（完整字典）
    - clients: 字典，键为客户端名称，值为该客户端的最新条目
    - global_ids: 列表，按添加顺序存储最近 N 个条目的 ID
    """
    def __init__(self):
        self.lock = threading.Lock()
        self.data = self._load()

    def _load(self):
        default = {
            "latest_global": None,
            "clients": {},
            "global_ids": []
        }
        if os.path.exists(TEXT_LATEST_FILE):
            try:
                with open(TEXT_LATEST_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # 确保所有必需的键都存在
                for key in default:
                    if key not in data:
                        data[key] = default[key]
                return data
            except (json.JSONDecodeError, FileNotFoundError):
                return default
        return default

    def _save(self):
        with open(TEXT_LATEST_FILE, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def is_duplicate(self, item_id: str) -> bool:
        """检查 ID 是否已存在（去重）"""
        with self.lock:
            self.data = self._load()
            return item_id in self.data["global_ids"]

    def update(self, item: dict, force_latest=False):
        # 写入时加锁，保证原子性
        with self.lock:
            # 多个进程可能共用同一个记录文件，写入前必须刷新。
            self.data = self._load()
            source = item.get("source", "unknown")
            item_id = item["id"]

            if item_id in self.data["global_ids"]:
                return   # 绝对重复，直接忽略

            self.data["global_ids"].append(item_id)
            self.data["clients"][source] = item

            # 限制 global_ids 最大长度
            MAX_IDS = 5
            if len(self.data["global_ids"]) > MAX_IDS:
                # 计算需要移除的数量
                remove_count = len(self.data["global_ids"]) - MAX_IDS
                # 移除最旧的 remove_count 个 ID
                self.data["global_ids"] = self.data["global_ids"][remove_count:]

            if force_latest:
                self.data["latest_global"] = item
            else:
                global_item = self.data["latest_global"]
                if global_item is None:
                    self.data["latest_global"] = item
                else:
                    if item["timestamp"] > global_item["timestamp"]:
                        self.data["latest_global"] = item

            self._save()

    def get_global_latest(self):
        """返回最新的文字内容对象"""
        with self.lock:
            # 重新加载最新数据，防止覆盖其他进程已添加的 id
            self.data = self._load()
            latest = self.data.get("latest_global")
            return latest.copy() if latest else None

    def get_latest_global_content(self):
        """返回最新的文字内容"""
        with self.lock:
            self.data = self._load()
            return safe_get(self.data, "latest_global", "content")

    def mark_pasted(self, client_name: str, item: dict):
        """标记客户端已粘贴某内容，更新对应客户端条目和全局最新状态"""
        with self.lock:
            self.data = self._load()
            # 更新该客户端的条目（如果还不存在就创建）
            self.data["clients"][client_name] = item
            # 如果全局最新的 id 正好是这个条目的 id，把 global 的 pasted 也设为 true
            latest = self.data.get("latest_global")
            if latest and latest.get("id") == item["id"]:
                latest["pasted"] = True
                self.data["latest_global"] = latest
            self._save()
