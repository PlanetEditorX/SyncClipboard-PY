# item_builder.py
import os
import hashlib
from datetime import datetime

def generate_stable_id(item):
    """
    新的稳定 ID，忽略 timestamp，同一内容+来源只生成一个 ID
    """
    s = f'{item["type"]}|{item.get("content","")}|{item.get("path","")}|{item["source"]}'
    return hashlib.md5(s.encode('utf-8')).hexdigest()

def build_text_item(text, source, pasted=False, timestamp=None):
    """
    构建一个剪贴板文本条目字典
    :param text: 文本内容
    :param source: 来源标识（如 "PC", "iPhone" 等）
    :param pasted: 是否已粘贴
    :param timestamp: 时间戳，不传则自动生成 ISO 格式
    :return: 符合缓存结构的 item 字典
    """
    if timestamp is None:
        timestamp = datetime.now().isoformat()

    item = {
        "id": generate_stable_id({
            "type": "text",
            "content": text,
            "source": source
        }),
        "type": "text",
        "content": text,
        "timestamp": timestamp,
        "source": source,
        "pasted": pasted
    }
    return item

def build_file_item(file_paths, source, pasted=False):
    """根据文件路径列表构建文件条目（仅元数据）"""
    files_info = []
    for path in file_paths:
        if os.path.isfile(path):
            stat = os.stat(path)
            files_info.append({
                "path": path,
                "name": os.path.basename(path),
                "size": stat.st_size
            })
    if not files_info:
        return None

    # 生成唯一 id：基于所有文件的路径+大小+来源
    id_str = "".join([f"{f['path']}{f['size']}" for f in files_info]) + source
    item_id = hashlib.md5(id_str.encode()).hexdigest()
    return {
        "id": item_id,
        "type": "file",
        "content": files_info,          # 文件元数据列表
        "timestamp": datetime.now().isoformat(),
        "source": source,
        "pasted": False
    }
