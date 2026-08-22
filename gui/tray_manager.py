"""Tray and desktop-window orchestration for SyncClipboard."""

import logging
import queue
import sys
import threading

from PIL import Image

from common.utils import (
    BASE_DIR,
    clear_tk_root,
    post_to_main_thread_no_wait,
    process_ui_queue,
    request_tk_shutdown,
    set_tk_root,
    show_message,
)
from gui.clipboard_handler import ClipboardHandler
from gui.config_manager import ConfigManager
from gui.file_handler import FileHandler
from gui.file_watcher_handler import FileWatcherHandler
from gui.main_window import create_main_window
from gui.service_manager import ServiceManager
from gui.ui_backend import create_root

logger = logging.getLogger("gui")


class TrayManager:
    """Coordinate the tray, modern window, and child services."""

    def __init__(self):
        self.config = ConfigManager()
        self.config.load_state()

        # Create Tk only when the application is actually started. Importing this
        # module remains safe for tests, multiprocessing children, and tooling.
        self.root, self.uses_customtkinter = create_root(self.config.appearance_mode)
        self.root.withdraw()
        set_tk_root(self.root)
        self.root.after(0, process_ui_queue)

        self.services = ServiceManager(self.config)
        self.file_handler = FileHandler(self.config)
        self.clipboard_handler = ClipboardHandler(self.config, self)
        self.watcher = FileWatcherHandler(self.clipboard_handler, self.config)
        from gui.tray_menu import TrayMenu

        self.menu_builder = TrayMenu(self)

        self.window = None
        self.icon = None
        self._service_busy = False
        self._quitting = False
        self._state_lock = threading.Lock()
        self._operation_queue = queue.Queue()
        self._operation_thread = threading.Thread(
            target=self._process_operation_queue,
            name="service-control",
            daemon=True,
        )
        self._operation_thread.start()

    @staticmethod
    def _process_alive(process):
        if process is None:
            return False
        try:
            return process.is_alive()
        except (AssertionError, ValueError):
            return False

    def get_service_state(self):
        """Return persisted intent and observed process health separately."""
        with self._state_lock:
            busy = self._service_busy or self._quitting
        return {
            "server_enabled": bool(self.config.server_running),
            "client_enabled": bool(self.config.client_running),
            "server_alive": self._process_alive(self.services.server_process),
            "client_alive": self._process_alive(self.services.client_process),
            "busy": busy,
        }

    def request_service_state(self, service, enabled):
        """Start or stop one service on the serialized background worker."""
        if service not in {"server", "client"}:
            raise ValueError(f"未知服务: {service}")

        def action():
            if service == "server":
                (self.services.start_server if enabled else self.services.stop_server)()
            else:
                (self.services.start_client if enabled else self.services.stop_client)()

        return self._dispatch_service_action(action)

    def restart_services_async(self):
        return self._dispatch_service_action(self.services.restart_services)

    def restart_client_async(self):
        def action():
            if not self.config.client_running:
                return
            if self.services.stop_client(preserve_intent=True):
                self.services.start_client()

        return self._dispatch_service_action(action)

    def _dispatch_service_action(self, action):
        with self._state_lock:
            if self._service_busy or self._quitting:
                return False
            self._service_busy = True
            self._operation_queue.put((action, False))

        self.refresh_ui()
        return True

    def _process_operation_queue(self):
        """Execute accepted service actions and shutdown strictly in FIFO order."""
        while True:
            action, is_shutdown = self._operation_queue.get()
            try:
                action()
            except Exception:
                logger.exception("%s失败", "退出操作" if is_shutdown else "服务操作")
            finally:
                if not is_shutdown:
                    with self._state_lock:
                        if not self._quitting:
                            self._service_busy = False
                    post_to_main_thread_no_wait(self.refresh_ui)
                self._operation_queue.task_done()
            if is_shutdown:
                return

    def refresh_ui(self):
        """Refresh all status surfaces after a service transition."""
        if threading.current_thread() is not threading.main_thread():
            post_to_main_thread_no_wait(self.refresh_ui)
            return
        if self.window is not None:
            try:
                self.window.refresh_status()
            except Exception:
                logger.exception("刷新主窗口失败")
        try:
            self.update_icon()
        except Exception:
            logger.exception("刷新托盘图标失败")
        if self.icon is not None:
            try:
                self.icon.update_menu()
            except Exception:
                logger.debug("刷新托盘菜单失败", exc_info=True)

    def _load_icon_image(self):
        state = self.get_service_state()
        active = state["server_alive"] or state["client_alive"]
        icon_name = "icon-active.png" if active else "icon-stop.png"
        icon_path = BASE_DIR / "gui" / "icon" / icon_name
        if icon_path.exists():
            with Image.open(icon_path) as source:
                return source.convert("RGBA").copy()
        return Image.new("RGBA", (64, 64), "#2563EB" if active else "#64748B")

    def update_icon(self):
        if self.icon is not None:
            self.icon.icon = self._load_icon_image()

    def show_main_window(self, icon=None, item=None):
        if self.window is not None:
            post_to_main_thread_no_wait(self.window.show)

    def hide_main_window(self):
        if self.window is not None:
            self.window.hide()

    def on_left_click(self, icon=None, item=None):
        """Compatibility callback; the tray's default item opens the window."""
        self.show_main_window(icon, item)

    def fetch_shared_file(self, icon=None, item=None):
        threading.Thread(
            target=self.file_handler.fetch_file_with_progress,
            name="fetch-shared-file",
            daemon=True,
        ).start()

    def quit_app(self, icon=None, item=None):
        """Stop processes off the UI thread, preserving enabled-state intent."""
        with self._state_lock:
            if self._quitting:
                return
            self._quitting = True
            self._service_busy = True

        self.refresh_ui()

        def shutdown():
            try:
                keep_server = bool(self.config.server_running)
                keep_client = bool(self.config.client_running)
                self.services.stop_server(preserve_intent=True)
                self.services.stop_client(preserve_intent=True)
                self.config.server_running = keep_server
                self.config.client_running = keep_client
                self.config.save_state()
            except Exception:
                logger.exception("退出时停止服务失败")
            finally:
                tray_icon = icon or self.icon
                if tray_icon is not None:
                    try:
                        tray_icon.stop()
                    except Exception:
                        logger.debug("停止托盘图标失败", exc_info=True)
                request_tk_shutdown(self.root)

        self._operation_queue.put((shutdown, True))

    def run(self):
        """Start services, tray integration, and the Tk main loop."""
        import pystray

        if not self.config.load_client_config():
            logger.error("客户端配置加载失败，界面未启动")
            try:
                show_message("配置加载失败", "无法读取客户端配置，请检查 config/client_config.json")
            finally:
                clear_tk_root(self.root)
                self.root.destroy()
            return

        self.window = create_main_window(
            self.root,
            self,
            use_customtkinter=self.uses_customtkinter,
        )

        restore_server = bool(self.config.server_running)
        restore_client = bool(self.config.client_running)
        logger.info("状态恢复: server=%s, client=%s", restore_server, restore_client)
        if restore_server:
            self.services.start_server()
        if restore_client:
            self.services.start_client()

        self.watcher.start()
        self.icon = pystray.Icon(
            "SyncClipboard",
            self._load_icon_image(),
            "SyncClipboard",
            self.menu_builder.create(),
        )
        if hasattr(self.icon, "run_detached"):
            self.icon.run_detached()
        else:
            threading.Thread(target=self.icon.run, name="tray-icon", daemon=True).start()

        self.refresh_ui()
        if "--minimized" not in sys.argv:
            self.window.show()

        try:
            self.root.mainloop()
        finally:
            self.watcher.stop()
            clear_tk_root(self.root)
            try:
                self.root.destroy()
            except Exception:
                pass
