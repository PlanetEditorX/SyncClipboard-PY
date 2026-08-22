import json
import logging
import threading
from datetime import datetime, timedelta
from common.utils import SAFE_POST
from common.notification import show_notification, show_notification_with_click
from server.core.file_latest import is_file_record_expired

logger = logging.getLogger("gui")


class ClipboardHandler:
    """剪贴板更新处理器"""
    def __init__(self, config_manager, tray_manager_ref=None):
        self.config = config_manager
        self.tray_manager = tray_manager_ref
        self.last_global_id = None

    def handle_client_latest(self):
        """处理文本剪贴板更新"""
        try:
            if not self.config.TEXT_LATEST_FILE.exists():
                return

            with open(self.config.TEXT_LATEST_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)

            latest = data.get('latest_global')
            if not latest:
                return

            current_id = latest.get('id')
            source = latest.get('source')

            if current_id and current_id != self.last_global_id and source != self.config.local_name:
                # 时间判断：超过10分钟不显示
                timestamp_str = latest.get('timestamp')
                if timestamp_str:
                    try:
                        record_time = datetime.fromisoformat(timestamp_str)
                        if datetime.now() - record_time > timedelta(minutes=10):
                            logger.info(f"剪贴板记录已过期（超过10分钟），跳过弹窗: {timestamp_str}")
                            return
                    except Exception as e:
                        logger.warning(f"解析时间戳失败: {timestamp_str}, 错误: {e}")

                self.last_global_id = current_id
                source = latest.get('source', '未知来源')
                content = latest.get('content', '')
                ctype = latest.get('type', 'text')
                title = "✂️ 剪贴板更新"

                if ctype == 'text':
                    preview = content[:60] + ('…' if len(content) > 60 else '')
                    msg = f"来源：{source}\n内容：{preview}"
                else:
                    msg = f"来源：{source}\n类型：{ctype}"

                show_notification(title, msg)
        except Exception:
            logger.exception("处理剪贴板变化失败")

    def handle_file_latest(self):
        """处理文件剪贴板更新"""
        try:
            if not self.config.FILE_LATEST_FILE.exists():
                return

            with open(self.config.FILE_LATEST_FILE, 'r', encoding='utf-8') as f:
                file_list = json.load(f)

            if isinstance(file_list, dict):
                file_list = [file_list]
            if not isinstance(file_list, list):
                return

            name_list = []
            msg = ""
            for file in file_list:
                if not isinstance(file, dict):
                    continue
                if is_file_record_expired(file):
                    logger.info(
                        "文件记录已过期，跳过通知: %s",
                        file.get('file_id')
                    )
                    continue
                file_id = file.get('file_id')
                if not file_id:
                    return

                source = file.get('source', '未知来源')
                if file_id and source != self.config.local_name and self.tray_manager:
                    name = file.get('name', '未知文件')
                    if name not in name_list:
                        name_list.append(name)
                        if msg == "":
                            msg += f"来源：{source}\n文件：{name}"
                        else:
                            msg += f"\n文件：{name}"
            if name_list and msg:
                def download_callback():
                    threading.Thread(
                        target=self.tray_manager.file_handler.fetch_file_with_progress,
                        daemon=True
                    ).start()

                show_notification_with_click(
                    "检测到文件发布, 点击保存。",
                    msg,
                    download_callback
                )
        except Exception as e:
            logger.error(f"处理文件变化失败: {e}")

    def notify_server_if_running(self, changed_type):
        """如果服务器在运行，通知服务器"""
        if self.config.server_running:
            import requests
            try:
                resp = SAFE_POST(
                    f"http://127.0.0.1:{self.config.server_port}/internal/notify_clients",
                    json={"changed_type": changed_type},
                    timeout=60
                )
                if resp is not None and resp.status_code == 200:
                    logger.info("通知服务器成功")
                else:
                    logger.warning(f"通知服务器失败: {resp.status_code}")
            except Exception:
                logger.exception("客户端通知内部服务器异常")
