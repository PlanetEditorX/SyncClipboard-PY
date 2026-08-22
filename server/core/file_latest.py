import os
import json
import time
from pathlib import Path
from common.utils import BASE_DIR

FILE_LATEST_FILE = BASE_DIR / "latest" / "file_latest.json"
FILE_LATEST_FILE.parent.mkdir(parents=True, exist_ok=True)
FILE_SHARE_TTL_SECONDS = 10 * 60


def is_file_record_expired(record, now=None):
    """Return whether a shared-file record is no longer valid."""
    if not isinstance(record, dict):
        return True

    try:
        updated_at = float(record.get("updated_at"))
    except (TypeError, ValueError):
        return True

    current_time = time.time() if now is None else now
    return current_time - updated_at >= FILE_SHARE_TTL_SECONDS

class FileLatestTracker:
    def __init__(self):
        self.data = self._load()   # 现在 data 是一个 list

    def _load(self):
        """从磁盘加载文件列表，兼容旧版单对象格式"""
        if not os.path.exists(FILE_LATEST_FILE):
            return []

        with open(FILE_LATEST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 旧格式没有 updated_at 时，用文件本身的修改时间迁移。这样时间戳稳定，
        # 不会因为每次读取都补成当前时间而让陈旧记录永久续期。
        fallback_updated_at = os.path.getmtime(FILE_LATEST_FILE)

        # 兼容旧版：如果存的是单个字典，转成列表
        if isinstance(data, dict):
            # 旧数据可能缺少 port / updated_at，补全后放入列表
            item = {
                "file_id": data.get("file_id"),
                "path": data.get("path"),
                "name": data.get("name"),
                "size": data.get("size", 0),
                "source": data.get("source"),
                "ip": data.get("ip"),
                "port": data.get("port"),
                "updated_at": data.get("updated_at", fallback_updated_at)
            }
            return [item] if item["file_id"] else []

        if not isinstance(data, list):
            return []

        # 已经是列表，确保每个条目字段完整
        normalized = []
        for item in data:
            if not isinstance(item, dict):
                continue
            item.setdefault("file_id", None)
            item.setdefault("path", None)
            item.setdefault("name", None)
            item.setdefault("size", 0)
            item.setdefault("source", None)
            item.setdefault("ip", None)
            item.setdefault("port", None)
            item.setdefault("updated_at", fallback_updated_at)
            normalized.append(item)
        return normalized

    def _save(self):
        with open(FILE_LATEST_FILE, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    def upsert_file(self, file_id, path, name, size, source, ip, port, save=True):
        """
        插入或更新一条文件记录（根据 file_id 去重）
        """
        if not file_id:
            raise ValueError("file_id cannot be empty")

        now = time.time()
        self.purge_expired(now=now, save=False)
        # 查找是否已存在该 file_id
        for item in self.data:
            if item["file_id"] == file_id:
                item.update({
                    "path": path,
                    "name": name,
                    "size": size,
                    "source": source,
                    "ip": ip,
                    "port": port,
                    "updated_at": now
                })
                if save:
                    self._save()
                return

        # 不存在则追加
        self.data.append({
            "file_id": file_id,
            "path": path,
            "name": name,
            "size": size,
            "source": source,
            "ip": ip,
            "port": port,
            "updated_at": now
        })
        if save:
            self._save()

    def purge_expired(self, now=None, save=True):
        """移除超过共享期限或缺少有效时间戳的文件记录。"""
        active = [
            item for item in self.data
            if not is_file_record_expired(item, now=now)
        ]
        removed_count = len(self.data) - len(active)
        if removed_count:
            self.data = active
            if save:
                self._save()
        return removed_count

    def get_all_files(self):
        """返回所有仍在共享期限内的文件记录副本。"""
        self.data = self._load()
        self.purge_expired()
        return [item.copy() for item in self.data]

    def get_file_by_id(self, file_id):
        """根据 file_id 查找单条记录，未找到返回 None"""
        self.data = self._load()
        self.purge_expired()
        for item in self.data:
            if item["file_id"] == file_id:
                return item.copy()
        return None

    def get_latest(self):
        """
        返回最新更新的一条记录（兼容旧版单文件调用）
        如果没有记录返回 None
        """
        self.data = self._load()
        self.purge_expired()
        if not self.data:
            return None
        # 按 updated_at 倒序取第一条
        latest = max(self.data, key=lambda x: x.get("updated_at", 0))
        return latest.copy()

    def remove_file(self, file_id):
        """根据 file_id 删除记录"""
        before = len(self.data)
        self.data = [item for item in self.data if item["file_id"] != file_id]
        if len(self.data) != before:
            self._save()
            return True
        return False

    def clear(self):
        """清空所有记录"""
        self.data = []
        self._save()

    def is_remote_file(self, file_id=None):
        """
        判断指定文件是否为远程文件。
        若未传 file_id，则判断最新一条记录。
        """
        if file_id:
            item = self.get_file_by_id(file_id)
        else:
            item = self.get_latest()
        if not item:
            return False
        return not item.get("path") or not os.path.isfile(item["path"])
