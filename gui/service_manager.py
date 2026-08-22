import time
import logging
import multiprocessing
from server.run import main as server_main
from client.run import main as client_main

logger = logging.getLogger("gui")

class ServiceManager:
    """服务管理器（服务器和客户端的启停）"""
    def __init__(self, config_manager):
        self.config = config_manager
        self.server_process = None
        self.client_process = None

    @property
    def server_running(self):
        return self.config.server_running

    @server_running.setter
    def server_running(self, value):
        self.config.server_running = value
        self.config.save_state()

    @property
    def client_running(self):
        return self.config.client_running

    @client_running.setter
    def client_running(self, value):
        self.config.client_running = value
        self.config.save_state()

    def start_server(self):
        """启动服务器"""
        logger.info(f"尝试启动服务器，当前状态: running={self.server_running}")
        if self.server_process and self.server_process.is_alive():
            self.server_running = True
            return True
        if self.server_process:
            try:
                self.server_process.close()
            except (AttributeError, ValueError):
                pass
            self.server_process = None

        self.server_running = True
        try:
            self.server_process = multiprocessing.Process(target=server_main, daemon=True)
            self.server_process.start()
            logger.info("服务器已启动")
            return True
        except Exception as e:
            logger.error(f"服务器启动失败: {e}")
            try:
                self.server_process.close()
            except (AttributeError, ValueError):
                pass
            self.server_process = None
            return False

    def stop_server(self, preserve_intent=False):
        """停止服务器"""
        stopped = True
        if self.server_process and self.server_process.is_alive():
            self.server_process.terminate()
            self.server_process.join(timeout=5)
            if self.server_process.is_alive():
                self.server_process.kill()
                self.server_process.join(timeout=5)
            if not self.server_process.is_alive():
                try:
                    self.server_process.close()
                except (AttributeError, ValueError):
                    pass
                self.server_process = None
            else:
                logger.error("服务器进程未能在超时内停止")
                stopped = False
        elif self.server_process:
            try:
                self.server_process.close()
            except (AttributeError, ValueError):
                pass
            self.server_process = None
        if not preserve_intent:
            self.server_running = False
        logger.info("服务器已停止" if stopped else "服务器停止失败")
        return stopped

    def toggle_server(self):
        """切换服务器状态"""
        if self.server_running:
            self.stop_server()
        else:
            self.start_server()

    def start_client(self):
        """启动客户端"""
        logger.info(f"尝试启动客户端，当前状态: running={self.client_running}")
        if self.client_process and self.client_process.is_alive():
            self.client_running = True
            return True
        if self.client_process:
            try:
                self.client_process.close()
            except (AttributeError, ValueError):
                pass
            self.client_process = None

        self.client_running = True
        try:
            self.client_process = multiprocessing.Process(target=client_main, daemon=True)
            self.client_process.start()
            logger.info("客户端已启动")
            return True
        except Exception as e:
            logger.error(f"客户端启动失败: {e}")
            try:
                self.client_process.close()
            except (AttributeError, ValueError):
                pass
            self.client_process = None
            return False

    def stop_client(self, preserve_intent=False):
        """停止客户端"""
        stopped = True
        if self.client_process and self.client_process.is_alive():
            self.client_process.terminate()
            self.client_process.join(timeout=5)
            if self.client_process.is_alive():
                self.client_process.kill()
                self.client_process.join(timeout=5)
            if not self.client_process.is_alive():
                try:
                    self.client_process.close()
                except (AttributeError, ValueError):
                    pass
                self.client_process = None
            else:
                logger.error("客户端进程未能在超时内停止")
                stopped = False
        elif self.client_process:
            try:
                self.client_process.close()
            except (AttributeError, ValueError):
                pass
            self.client_process = None
        if not preserve_intent:
            self.client_running = False
        logger.info("客户端已停止" if stopped else "客户端停止失败")
        return stopped

    def toggle_client(self):
        """切换客户端状态"""
        if self.client_running:
            self.stop_client()
        else:
            self.start_client()

    def restart_services(self):
        """仅重启用户已启用的服务。"""
        logger.info("正在重启服务...")
        restart_server = self.server_running
        restart_client = self.client_running
        server_stopped = True
        client_stopped = True
        if restart_server:
            server_stopped = self.stop_server(preserve_intent=True)
        if restart_client:
            client_stopped = self.stop_client(preserve_intent=True)
        if restart_server or restart_client:
            time.sleep(1)
        if restart_server and server_stopped:
            self.start_server()
        if restart_client and client_stopped:
            self.start_client()
