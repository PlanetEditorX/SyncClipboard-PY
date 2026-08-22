import os
import json
import time
import logging
import threading
import pyperclip
import requests
from threading import Thread
from urllib.parse import unquote
from common.utils import BASE_DIR
from common.notification import show_notification
from server.core.file_latest import (
    FILE_SHARE_TTL_SECONDS,
    is_file_record_expired,
)
from server.core.text_tracker import TextTracker
from flask import Flask, jsonify, send_file, after_this_request, request

FILE_LATEST_FILE = BASE_DIR / "latest" / "file_latest.json"
FILE_LATEST_FILE.parent.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("client")

def get_api_key():
    return request.headers.get("key", "")

def get_files_latest_file():
    """读取最新文件数据，如果文件不存在或无效则返回 None"""
    if not FILE_LATEST_FILE.exists():
        return []
    try:
        with open(FILE_LATEST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except (json.JSONDecodeError, AttributeError):
        return None

class FileServer:
    """客户端网络服务"""
    def __init__(self, port=8899, center_host="127.0.0.1", center_port=8000, local_name="PC-01", key="123456", save_path="./uploads"):
        self.port = port
        self.center_host = center_host
        self.center_port = center_port
        self.shared_files = {}
        self.shared_file_registered_at = {}
        self._shared_files_lock = threading.RLock()
        self.app = Flask(__name__)
        # 关闭 Flask 默认访问日志
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        self._register_routes()
        # 全局锁，避免同时读写剪贴板
        self.clipboard_lock = threading.Lock()
        self.last_remote_id = None
        self._last_remote_content = None
        self.last_text = ""
        self.KEY = str(key)
        self.local_name = local_name
        self.save_path = save_path
        self.tracker = TextTracker()
        # 添加运行状态和服务器引用
        self.running = False
        self._server_thread = None
        self._flask_server = None

    def _register_routes(self):
        @self.app.route("/ping", methods=["GET"])
        def ping():
            return jsonify({
                "status": "ok",
                "service": "file_server"
            })

        @self.app.route("/files", methods=["GET"])
        def files():
            client_ip = request.remote_addr
            logger.info(f"获取文件下载列表 - 请求来自: {client_ip}")
            self._purge_expired_files()
            with self._shared_files_lock:
                shared_files = self.shared_files.copy()
            return jsonify({
                "count": len(shared_files),
                "files": shared_files
            })

        @self.app.route("/update/current_latest", methods=["POST"])
        def update_client_latest():
            data = request.get_json()
            if not data:
                return jsonify({"status": "error", "message": "无效的请求数据"}), 400
            if data.get("key") != self.KEY:
                return jsonify({"status": "error", "message": "密钥错误"}), 403
            client_ip = request.remote_addr
            if data.get("type") == "text":
                logger.info(f"更新文字列表 - 请求来自: {client_ip}")
                latest = data.get("latest_global")
                if latest and latest.get("source") != self.local_name:
                    if latest["id"] != self.last_remote_id:
                        # 更新到文件
                        if self.tracker.is_duplicate(latest["id"]):
                            return jsonify({"status": "duplicate", "message": "重复内容"}), 200
                        # 更新剪贴板
                        with self.clipboard_lock:
                            pyperclip.copy(latest["content"])
                        # 更新记录（同时注册 ID、更新客户端最新和全局最新）
                        self.tracker.update(latest)
                        self.last_remote_id = latest["id"]
                        self._last_remote_content = latest["content"]
                        self.last_text = latest["content"]
                        logging.info(f"更新剪贴板: {latest['content'][:50]} (来自 {latest['source']})")
            else:
                logger.info(f"更新文件列表 - 请求来自: {client_ip}")
                latest = data.get("latest_global") or []
                if isinstance(latest, dict):
                    latest = [latest]
                if not isinstance(latest, list):
                    latest = []
                latest = [
                    item for item in latest
                    if not is_file_record_expired(item)
                ]
                # 获取本地已存储的文件
                file_latest = get_files_latest_file()
                if latest == file_latest:
                    logger.info(f"文件未变化，跳过写入")
                else:
                    # 只有当 file_id 不一致时才写入
                    file_latest = latest
                    with open(FILE_LATEST_FILE, "w", encoding="utf-8") as f:
                        json.dump(file_latest, f, ensure_ascii=False, indent=2)
                    logger.info("file_latest文件已更新")
            return jsonify({
                "status": "ok",
            })

        @self.app.route('/upload_file', methods=['PUT'])
        def upload_file():
            """上传文件到电脑"""
            key = get_api_key()
            if key != self.KEY:
                return jsonify({"status": "error", "message": "密钥错误"}), 403

            # 从 URL 参数获取文件名，例如 ?filename=my%20file.txt
            encoded_filename = request.args.get('filename', 'uploaded_file')
            filename = unquote(encoded_filename)  # 解码 %20 为空格

            # 安全处理文件名：去除空字符，替换反斜杠，提取最后一部分作为纯文件名
            filename = filename.replace('\x00', '')
            filename = filename.replace('\\', '/')
            filename = filename.split('/')[-1]
            if not filename or filename in ('.', '..'):
                filename = 'uploaded_file'

            file_data = None
            try:
                file_data = request.get_data(cache=False, as_text=False)
            except Exception as e:
                logger.error(f"读取原始二进制数据时出错: {e}")

            if not file_data:
                return jsonify({"status": "error", "message": "未收到文件"}), 400

            # 保存到文件
            save_file_path = os.path.join(self.save_path, filename)
            with open(save_file_path, 'wb') as f:
                f.write(file_data)

            logging.info(f"手机上传文件已保存: {save_file_path}")
            source = unquote(request.headers.get("source", ""))
            msg = f"来源：{source}\n文件：{filename}\n保存：{save_file_path}"
            show_notification("手机文件已保存", msg)
            return jsonify({"status": "ok", "message": "文件上传成功","path": save_file_path}), 200

        @self.app.route("/clear/file_latest", methods=["GET"])
        def clear_file_latest():
            key = get_api_key()
            if key != self.KEY:
                return jsonify({"status": "error", "message": "密钥错误"}), 403
            client_ip = request.remote_addr
            logger.info(f"清空文件列表 - 请求来自: {client_ip}")
            with open(FILE_LATEST_FILE, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)
            logger.info("file_latest文件已清空")
            return jsonify({
                "status": "ok",
            })

        @self.app.route("/check/<file_id>", methods=["GET"])
        def check_files(file_id):
            client_ip = request.remote_addr
            logger.info(f"检测文件状态 - 请求来自: {client_ip}")

            path = self.get_file_path(file_id)
            if not path:
                return jsonify({"status": "error", "message": "file_id不存在"}), 404

            if not os.path.isfile(path):
                return jsonify({"status": "error", "message": "文件不存在"}), 404

            logger.info("文件正常: %s -> %s", file_id, path)
            return jsonify({"status": "ok", "message": "文件正常"}), 200

        @self.app.route("/file/<file_id>", methods=["GET"])
        def download_file(file_id):
            client_ip = request.remote_addr
            source = request.headers.get("source", "未知设备")
            logger.info(f"获取文件下载 - 请求来自: {unquote(request.headers.get('source', ''))}({client_ip})")

            path = self.get_file_path(file_id)
            if not path:
                return jsonify({"status": "error", "message": "file_id不存在"}), 404

            if not os.path.isfile(path):
                return jsonify({"status": "error", "message": "文件不存在"}), 404

            logger.info("文件下载请求: %s -> %s", file_id, path)

            # 注册一个后置回调：文件发送完成后取消共享
            @after_this_request
            def after_download(response):
                # 取消本机共享
                self.unregister_file(file_id)
                return response

            return send_file(path, as_attachment=True)

    def register_file(self, file_id, path):
        """
        注册共享文件
        Parameters
        ----------
        file_id : str
            文件唯一ID
        path : str
            本地文件路径
        """
        with self._shared_files_lock:
            self.shared_files[file_id] = path
            self.shared_file_registered_at[file_id] = time.time()
        logger.info("注册共享文件: %s -> %s", file_id, path)

    def unregister_file(self, file_id):
        """
        取消共享
        """
        with self._shared_files_lock:
            path = self.shared_files.pop(file_id, None)
            self.shared_file_registered_at.pop(file_id, None)
        if path is not None:
            logger.info("取消共享文件: %s -> %s", file_id, path)

    def clear_files(self):
        """
        清空共享列表
        """
        with self._shared_files_lock:
            self.shared_files.clear()
            self.shared_file_registered_at.clear()
        logger.info("共享文件列表已清空")

    def _purge_expired_files(self, now=None):
        """从本机文件服务中移除已超过共享期限的文件。"""
        current_time = time.time() if now is None else now
        with self._shared_files_lock:
            expired_ids = [
                file_id
                for file_id, registered_at in self.shared_file_registered_at.items()
                if current_time - registered_at >= FILE_SHARE_TTL_SECONDS
            ]
            for file_id in expired_ids:
                path = self.shared_files.pop(file_id, None)
                self.shared_file_registered_at.pop(file_id, None)
                logger.info("共享文件已过期: %s -> %s", file_id, path)
        return len(expired_ids)

    def get_file_path(self, file_id):
        """
        获取文件路径
        """
        self._purge_expired_files()
        with self._shared_files_lock:
            return self.shared_files.get(file_id)

    def start(self):
        """启动文件服务器"""
        if self.running:
            logger.warning("文件服务器已在运行中")
            return

        self.running = True

        def run():
            logger.info("文件服务启动: 0.0.0.0:%s", self.port)
            try:
                # 使用 Werkzeug 服务器（Flask 内置）
                from werkzeug.serving import make_server
                self._flask_server = make_server('0.0.0.0', self.port, self.app, threaded=True)
                self._flask_server.serve_forever()
            except Exception as e:
                if self.running:  # 只在非主动停止时记录错误
                    logger.error(f"文件服务器异常: {e}")

        self._server_thread = Thread(target=run, daemon=True)
        self._server_thread.start()
        logger.info("文件服务器线程已启动")

    def stop(self):
        """停止文件服务器"""
        if not self.running:
            logger.warning("文件服务器未在运行")
            return

        logger.info("正在停止文件服务器...")
        self.running = False

        # 关闭 Werkzeug 服务器
        if self._flask_server:
            try:
                self._flask_server.shutdown()
                logger.info("Flask 服务器已关闭")
            except Exception as e:
                logger.error(f"关闭 Flask 服务器时出错: {e}")

        # 等待线程结束
        if self._server_thread and self._server_thread.is_alive():
            self._server_thread.join(timeout=5)
            if self._server_thread.is_alive():
                logger.warning("文件服务器线程未能在5秒内停止")

        logger.info("文件服务器已停止")
