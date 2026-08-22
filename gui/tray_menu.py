"""System tray menu for the desktop client."""

import os

from pystray import Menu, MenuItem

from common.utils import BASE_DIR


class TrayMenu:
    def __init__(self, tray_manager):
        self.manager = tray_manager

    def create(self):
        return Menu(
            MenuItem("打开 SyncClipboard", self.manager.show_main_window, default=True),
            MenuItem("获取共享文件", self.manager.fetch_shared_file),
            Menu.SEPARATOR,
            MenuItem(
                "同步客户端",
                self._toggle_client,
                checked=lambda item: self.manager.get_service_state()["client_enabled"],
                enabled=self._service_controls_enabled,
            ),
            MenuItem(
                "本机服务器",
                self._toggle_server,
                checked=lambda item: self.manager.get_service_state()["server_enabled"],
                enabled=self._service_controls_enabled,
            ),
            MenuItem(
                "重启已启用服务",
                self._restart_services,
                enabled=self._service_controls_enabled,
            ),
            Menu.SEPARATOR,
            MenuItem(
                "开机启动",
                self._toggle_autostart,
                checked=lambda item: self.manager.config.is_autostart_enabled(),
            ),
            MenuItem("打开客户端配置", self._edit_client_config),
            MenuItem("打开服务器配置", self._edit_server_config),
            Menu.SEPARATOR,
            MenuItem("退出", self.manager.quit_app),
        )

    def _service_controls_enabled(self, item):
        return not self.manager.get_service_state()["busy"]

    def _toggle_autostart(self, icon=None, item=None):
        current = self.manager.config.is_autostart_enabled()
        self.manager.config.toggle_autostart(not current)
        if icon is not None:
            icon.update_menu()

    def _toggle_server(self, icon=None, item=None):
        state = self.manager.get_service_state()
        self.manager.request_service_state("server", not state["server_enabled"])

    def _toggle_client(self, icon=None, item=None):
        state = self.manager.get_service_state()
        self.manager.request_service_state("client", not state["client_enabled"])

    @staticmethod
    def _edit_server_config(icon=None, item=None):
        config_path = BASE_DIR / "config" / "server_config.json"
        if config_path.exists():
            os.startfile(config_path)

    @staticmethod
    def _edit_client_config(icon=None, item=None):
        config_path = BASE_DIR / "config" / "client_config.json"
        if config_path.exists():
            os.startfile(config_path)

    def _restart_services(self, icon=None, item=None):
        self.manager.restart_services_async()
