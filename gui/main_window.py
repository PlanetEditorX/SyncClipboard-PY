"""Modern desktop control panel for SyncClipboard."""

import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from common.utils import BASE_DIR, show_message
from gui.ui_backend import ctk, set_appearance_mode


FONT = "Microsoft YaHei UI"
BG = ("#F4F7FB", "#080D18")
CARD = ("#FFFFFF", "#111827")
CARD_ALT = ("#F8FAFC", "#172033")
BORDER = ("#E2E8F0", "#263248")
TEXT = ("#132033", "#F8FAFC")
MUTED = ("#64748B", "#93A4BC")
ACCENT = "#3B82F6"
ACCENT_HOVER = "#2563EB"
SUCCESS = "#22C55E"
WARNING = "#F59E0B"
DANGER = "#EF4444"


def validate_client_settings(
    server_host,
    server_port,
    local_name,
    file_server_port,
    key,
    save_path,
):
    """Validate and normalize settings independently from Tk widgets."""
    host = str(server_host or "").strip()
    name = str(local_name or "").strip()
    secret = str(key or "")
    directory = str(save_path or "").strip()

    if not host:
        raise ValueError("请输入服务器地址")
    if not name:
        raise ValueError("请输入本机名称")
    if not secret.strip():
        raise ValueError("请输入共享密钥")
    if not directory:
        raise ValueError("请选择文件保存目录")

    try:
        server_port_value = int(server_port)
        file_port_value = int(file_server_port)
    except (TypeError, ValueError) as exc:
        raise ValueError("端口必须是数字") from exc

    if not 1 <= server_port_value <= 65535:
        raise ValueError("服务器端口必须在 1 到 65535 之间")
    if not 1 <= file_port_value <= 65535:
        raise ValueError("文件服务端口必须在 1 到 65535 之间")

    return {
        "server_host": host,
        "server_port": server_port_value,
        "local_name": name,
        "file_server_port": file_port_value,
        "key": secret,
        "save_path": directory,
    }


def create_main_window(root, manager, use_customtkinter=True):
    if use_customtkinter and ctk is not None:
        return ModernMainWindow(root, manager)
    return FallbackMainWindow(root, manager)


class ModernMainWindow:
    """Single-page CustomTkinter dashboard."""

    APPEARANCE_LABELS = {
        "System": "跟随系统",
        "Light": "浅色",
        "Dark": "深色",
    }
    APPEARANCE_MODES = {value: key for key, value in APPEARANCE_LABELS.items()}

    def __init__(self, root, manager):
        self.root = root
        self.manager = manager
        self.config = manager.config
        self._centered = False
        self._secret_visible = False
        self._refresh_job = None
        self._window_icon = None

        self.root.title("SyncClipboard")
        self._configure_window_size()
        self.root.configure(fg_color=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        self._set_window_icon()
        self._build()
        self.load_settings()
        self.refresh_status()

    def _configure_window_size(self):
        screen_width = max(self.root.winfo_screenwidth(), 1)
        screen_height = max(self.root.winfo_screenheight(), 1)
        width = min(screen_width, max(720, min(1000, int(screen_width * 0.88))))
        height = min(screen_height, max(520, min(760, int(screen_height * 0.86))))
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(min(width, 780), min(height, 560))

    def _set_window_icon(self):
        try:
            icon_path = BASE_DIR / "gui" / "icon" / "icon-active.png"
            if icon_path.exists():
                self._window_icon = tk.PhotoImage(file=str(icon_path))
                self.root.iconphoto(False, self._window_icon)
        except Exception:
            pass

    def _build(self):
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=1)

        self._build_header()
        self.body = ctk.CTkScrollableFrame(
            self.root,
            fg_color=BG,
            corner_radius=0,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=ACCENT,
        )
        self.body.grid(row=1, column=0, sticky="nsew")
        self.body.grid_columnconfigure((0, 1), weight=1, uniform="content")

        self._build_welcome()
        self._build_service_cards()
        self._build_quick_actions()
        self._build_settings()
        self._build_footer()

    def _build_header(self):
        header = ctk.CTkFrame(self.root, height=92, corner_radius=0, fg_color=CARD)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.grid_columnconfigure(1, weight=1)

        badge = ctk.CTkLabel(
            header,
            text="SC",
            width=48,
            height=48,
            corner_radius=14,
            fg_color=ACCENT,
            text_color="#FFFFFF",
            font=(FONT, 17, "bold"),
        )
        badge.grid(row=0, column=0, rowspan=2, padx=(28, 14), pady=22)

        ctk.CTkLabel(
            header,
            text="SyncClipboard",
            text_color=TEXT,
            font=(FONT, 22, "bold"),
            anchor="w",
        ).grid(row=0, column=1, sticky="sw", pady=(20, 0))
        ctk.CTkLabel(
            header,
            text="跨设备剪贴板同步中心",
            text_color=MUTED,
            font=(FONT, 12),
            anchor="w",
        ).grid(row=1, column=1, sticky="nw", pady=(0, 20))

        self.appearance_selector = ctk.CTkSegmentedButton(
            header,
            values=list(self.APPEARANCE_MODES),
            command=self._change_appearance,
            selected_color=ACCENT,
            selected_hover_color=ACCENT_HOVER,
            font=(FONT, 11),
            height=34,
        )
        self.appearance_selector.grid(row=0, column=2, rowspan=2, padx=28, pady=28)

    def _build_welcome(self):
        hero = ctk.CTkFrame(
            self.body,
            fg_color=("#EAF2FF", "#0D2245"),
            border_width=1,
            border_color=("#CFE0FF", "#1E4B86"),
            corner_radius=18,
        )
        hero.grid(row=0, column=0, columnspan=2, sticky="ew", padx=24, pady=(22, 14))
        hero.grid_columnconfigure(0, weight=1)

        self.welcome_title = ctk.CTkLabel(
            hero,
            text="设备同步已准备就绪",
            text_color=TEXT,
            font=(FONT, 21, "bold"),
            anchor="w",
        )
        self.welcome_title.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 4))
        self.welcome_detail = ctk.CTkLabel(
            hero,
            text="正在读取服务状态…",
            text_color=MUTED,
            font=(FONT, 12),
            anchor="w",
        )
        self.welcome_detail.grid(row=1, column=0, sticky="ew", padx=24, pady=(0, 20))
        self.overall_status = ctk.CTkLabel(
            hero,
            text="检查中",
            width=92,
            height=32,
            corner_radius=16,
            fg_color=WARNING,
            text_color="#FFFFFF",
            font=(FONT, 11, "bold"),
        )
        self.overall_status.grid(row=0, column=1, rowspan=2, padx=24)

    def _build_service_cards(self):
        self.server_card = self._service_card(
            column=0,
            title="本机服务器",
            description="为局域网设备中转剪贴板内容",
            badge="S",
            command=self._toggle_server,
        )
        self.client_card = self._service_card(
            column=1,
            title="同步客户端",
            description="监听并同步本机剪贴板变化",
            badge="C",
            command=self._toggle_client,
        )

    def _service_card(self, column, title, description, badge, command):
        card = ctk.CTkFrame(
            self.body,
            fg_color=CARD,
            border_width=1,
            border_color=BORDER,
            corner_radius=18,
            height=158,
        )
        card.grid(
            row=1,
            column=column,
            sticky="nsew",
            padx=(24, 7) if column == 0 else (7, 24),
            pady=7,
        )
        card.grid_propagate(False)
        card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            card,
            text=badge,
            width=42,
            height=42,
            corner_radius=12,
            fg_color=CARD_ALT,
            text_color=ACCENT,
            font=(FONT, 16, "bold"),
        ).grid(row=0, column=0, padx=(20, 12), pady=(20, 5))
        ctk.CTkLabel(
            card,
            text=title,
            text_color=TEXT,
            font=(FONT, 16, "bold"),
            anchor="w",
        ).grid(row=0, column=1, sticky="w", pady=(20, 5))
        switch = ctk.CTkSwitch(
            card,
            text="",
            width=48,
            command=command,
            progress_color=ACCENT,
        )
        switch.grid(row=0, column=2, padx=20, pady=(20, 5))

        ctk.CTkLabel(
            card,
            text=description,
            text_color=MUTED,
            font=(FONT, 11),
            anchor="w",
        ).grid(row=1, column=0, columnspan=3, sticky="ew", padx=20, pady=(3, 12))
        status = ctk.CTkLabel(
            card,
            text="已停止",
            height=28,
            corner_radius=14,
            fg_color=CARD_ALT,
            text_color=MUTED,
            font=(FONT, 10, "bold"),
        )
        status.grid(row=2, column=0, columnspan=3, sticky="w", padx=20, pady=(0, 18))
        return {"frame": card, "switch": switch, "status": status}

    def _build_quick_actions(self):
        panel = ctk.CTkFrame(
            self.body,
            fg_color=CARD,
            border_width=1,
            border_color=BORDER,
            corner_radius=18,
        )
        panel.grid(row=2, column=0, columnspan=2, sticky="ew", padx=24, pady=7)
        panel.grid_columnconfigure((0, 1, 2), weight=1, uniform="actions")

        ctk.CTkLabel(
            panel,
            text="快速操作",
            text_color=TEXT,
            font=(FONT, 15, "bold"),
            anchor="w",
        ).grid(row=0, column=0, columnspan=3, sticky="ew", padx=20, pady=(18, 12))

        self.fetch_button = self._action_button(
            panel, 0, "获取共享文件", self._fetch_file, primary=True
        )
        self.restart_button = self._action_button(
            panel, 1, "重启已启用服务", self._restart_services
        )
        self.folder_button = self._action_button(
            panel, 2, "打开下载目录", self._open_download_folder
        )

    def _action_button(self, parent, column, text, command, primary=False):
        button = ctk.CTkButton(
            parent,
            text=text,
            command=command,
            height=42,
            corner_radius=12,
            font=(FONT, 12, "bold"),
            fg_color=ACCENT if primary else CARD_ALT,
            hover_color=ACCENT_HOVER if primary else BORDER,
            text_color="#FFFFFF" if primary else TEXT,
            border_width=0 if primary else 1,
            border_color=BORDER,
        )
        button.grid(
            row=1,
            column=column,
            sticky="ew",
            padx=(20, 6) if column == 0 else ((6, 20) if column == 2 else 6),
            pady=(0, 20),
        )
        return button

    def _build_settings(self):
        panel = ctk.CTkFrame(
            self.body,
            fg_color=CARD,
            border_width=1,
            border_color=BORDER,
            corner_radius=18,
        )
        panel.grid(row=3, column=0, columnspan=2, sticky="ew", padx=24, pady=7)
        panel.grid_columnconfigure((0, 1), weight=1, uniform="settings")

        ctk.CTkLabel(
            panel,
            text="连接设置",
            text_color=TEXT,
            font=(FONT, 17, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=22, pady=(20, 2))
        ctk.CTkLabel(
            panel,
            text="保存后，正在运行的客户端会自动重启并应用配置",
            text_color=MUTED,
            font=(FONT, 11),
            anchor="e",
        ).grid(row=0, column=1, sticky="ew", padx=22, pady=(20, 2))

        self.server_host_entry = self._field(panel, 1, 0, "服务器地址", "例如 192.168.1.10")
        self.server_port_entry = self._field(panel, 1, 1, "服务器端口", "8000")
        self.local_name_entry = self._field(panel, 2, 0, "本机名称", "用于识别此设备")
        self.file_port_entry = self._field(panel, 2, 1, "文件服务端口", "8899")
        self.key_entry = self._field(panel, 3, 0, "共享密钥", "访问服务器所需密钥", show="•")

        secret_toggle = ctk.CTkButton(
            panel,
            text="显示密钥",
            command=self._toggle_secret,
            width=100,
            height=36,
            corner_radius=10,
            fg_color=CARD_ALT,
            hover_color=BORDER,
            text_color=TEXT,
            border_width=1,
            border_color=BORDER,
            font=(FONT, 10),
        )
        secret_toggle.grid(row=4, column=0, sticky="w", padx=22, pady=(0, 12))
        self.secret_toggle = secret_toggle

        directory = ctk.CTkFrame(panel, fg_color="transparent")
        directory.grid(row=3, column=1, rowspan=2, sticky="nsew", padx=22, pady=(10, 12))
        directory.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            directory,
            text="文件保存目录",
            text_color=MUTED,
            font=(FONT, 10),
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        self.save_path_entry = ctk.CTkEntry(
            directory,
            height=40,
            corner_radius=10,
            border_color=BORDER,
            fg_color=CARD_ALT,
            text_color=TEXT,
            font=(FONT, 11),
        )
        self.save_path_entry.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(
            directory,
            text="选择",
            command=self._choose_directory,
            width=72,
            height=40,
            corner_radius=10,
            fg_color=CARD_ALT,
            hover_color=BORDER,
            text_color=TEXT,
            border_width=1,
            border_color=BORDER,
            font=(FONT, 11),
        ).grid(row=1, column=1)

        preference = ctk.CTkFrame(panel, fg_color=CARD_ALT, corner_radius=12)
        preference.grid(row=5, column=0, columnspan=2, sticky="ew", padx=22, pady=(2, 14))
        preference.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            preference,
            text="开机后自动在后台启动",
            text_color=TEXT,
            font=(FONT, 11, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=16, pady=14)
        self.autostart_switch = ctk.CTkSwitch(
            preference,
            text="",
            width=48,
            progress_color=ACCENT,
            command=self._toggle_autostart,
        )
        self.autostart_switch.grid(row=0, column=1, padx=16)

        buttons = ctk.CTkFrame(panel, fg_color="transparent")
        buttons.grid(row=6, column=0, columnspan=2, sticky="ew", padx=22, pady=(0, 22))
        buttons.grid_columnconfigure(0, weight=1)
        self.settings_message = ctk.CTkLabel(
            buttons,
            text="",
            text_color=MUTED,
            font=(FONT, 10),
            anchor="w",
        )
        self.settings_message.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(
            buttons,
            text="打开高级配置",
            command=self._open_config_folder,
            width=120,
            height=40,
            corner_radius=10,
            fg_color=CARD_ALT,
            hover_color=BORDER,
            text_color=TEXT,
            border_width=1,
            border_color=BORDER,
            font=(FONT, 11),
        ).grid(row=0, column=1, padx=(8, 8))
        self.save_button = ctk.CTkButton(
            buttons,
            text="保存并应用",
            command=self.save_settings,
            width=130,
            height=40,
            corner_radius=10,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            font=(FONT, 11, "bold"),
        )
        self.save_button.grid(row=0, column=2)

    def _field(self, parent, row, column, label, placeholder, show=None):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=row, column=column, sticky="nsew", padx=22, pady=10)
        frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            frame,
            text=label,
            text_color=MUTED,
            font=(FONT, 10),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 6))
        entry = ctk.CTkEntry(
            frame,
            placeholder_text=placeholder,
            show=show,
            height=40,
            corner_radius=10,
            border_color=BORDER,
            fg_color=CARD_ALT,
            text_color=TEXT,
            font=(FONT, 11),
        )
        entry.grid(row=1, column=0, sticky="ew")
        return entry

    def _build_footer(self):
        ctk.CTkLabel(
            self.body,
            text="关闭窗口后应用仍会在系统托盘中运行",
            text_color=MUTED,
            font=(FONT, 10),
        ).grid(row=4, column=0, columnspan=2, pady=(10, 24))

    @staticmethod
    def _set_entry(entry, value):
        entry.delete(0, "end")
        entry.insert(0, "" if value is None else str(value))

    def load_settings(self):
        self._set_entry(self.server_host_entry, self.config.server_host)
        self._set_entry(self.server_port_entry, self.config.server_port)
        self._set_entry(self.local_name_entry, self.config.local_name)
        self._set_entry(self.file_port_entry, self.config.file_server_port)
        self._set_entry(self.key_entry, self.config.key)
        self._set_entry(self.save_path_entry, self.config.save_path)

        mode = getattr(self.config, "appearance_mode", "System")
        self.appearance_selector.set(self.APPEARANCE_LABELS.get(mode, "跟随系统"))
        if self.config.is_autostart_enabled():
            self.autostart_switch.select()
        else:
            self.autostart_switch.deselect()

    def save_settings(self):
        try:
            values = validate_client_settings(
                self.server_host_entry.get(),
                self.server_port_entry.get(),
                self.local_name_entry.get(),
                self.file_port_entry.get(),
                self.key_entry.get(),
                self.save_path_entry.get(),
            )
        except ValueError as exc:
            self.settings_message.configure(text=str(exc), text_color=DANGER)
            return

        if not self.config.update_client_config(values):
            self.settings_message.configure(text="配置保存失败，请查看日志", text_color=DANGER)
            return

        self.settings_message.configure(text="配置已保存", text_color=SUCCESS)
        self.welcome_detail.configure(
            text=f"连接到 {values['server_host']}:{values['server_port']} · 设备 {values['local_name']}"
        )
        if self.manager.get_service_state()["client_enabled"]:
            if self.manager.restart_client_async():
                self.settings_message.configure(text="配置已保存，正在重启客户端…", text_color=WARNING)
            else:
                self.settings_message.configure(
                    text="配置已保存；服务正忙，请稍后手动重启客户端",
                    text_color=WARNING,
                )

    def refresh_status(self):
        if self._refresh_job is not None:
            try:
                self.root.after_cancel(self._refresh_job)
            except Exception:
                pass
            self._refresh_job = None
        state = self.manager.get_service_state()
        self._render_service(self.server_card, state["server_enabled"], state["server_alive"], state["busy"])
        self._render_service(self.client_card, state["client_enabled"], state["client_alive"], state["busy"])
        control_state = "disabled" if state["busy"] else "normal"
        self.restart_button.configure(state=control_state)
        self.save_button.configure(state=control_state)

        unhealthy = []
        if state["server_enabled"] != state["server_alive"]:
            unhealthy.append(
                "服务器进程未运行" if state["server_enabled"] else "服务器进程未能停止"
            )
        if state["client_enabled"] != state["client_alive"]:
            unhealthy.append(
                "客户端进程未运行" if state["client_enabled"] else "客户端进程未能停止"
            )
        healthy = state["client_alive"] or state["server_alive"]
        if state["busy"]:
            self.overall_status.configure(text="处理中", fg_color=WARNING)
            self.welcome_title.configure(text="正在更新服务状态")
        elif unhealthy:
            self.overall_status.configure(text="需检查", fg_color=DANGER)
            self.welcome_title.configure(text="、".join(unhealthy))
        elif healthy:
            self.overall_status.configure(text="运行中", fg_color=SUCCESS)
            self.welcome_title.configure(text="设备同步已准备就绪")
        else:
            self.overall_status.configure(text="已暂停", fg_color=MUTED)
            self.welcome_title.configure(text="同步服务当前已暂停")

        self.welcome_detail.configure(
            text=f"连接到 {self.config.server_host}:{self.config.server_port} · 设备 {self.config.local_name}"
        )
        if not state["busy"] and self.settings_message.cget("text") == "配置已保存，正在重启客户端…":
            if state["client_alive"]:
                self.settings_message.configure(text="配置已应用", text_color=SUCCESS)
            else:
                self.settings_message.configure(
                    text="配置已保存，但客户端启动失败",
                    text_color=DANGER,
                )
        self._refresh_job = self.root.after(1000, self.refresh_status)

    @staticmethod
    def _render_service(card, enabled, alive, busy):
        switch = card["switch"]
        status = card["status"]
        if enabled:
            switch.select()
        else:
            switch.deselect()
        switch.configure(state="disabled" if busy else "normal")

        if busy:
            status.configure(text="正在更新…", fg_color=WARNING, text_color="#FFFFFF")
        elif enabled and alive:
            status.configure(text="  运行正常  ", fg_color=SUCCESS, text_color="#FFFFFF")
        elif enabled:
            status.configure(text="  已启用 · 进程未运行  ", fg_color=DANGER, text_color="#FFFFFF")
        elif alive:
            status.configure(text="  已关闭 · 进程未能停止  ", fg_color=DANGER, text_color="#FFFFFF")
        else:
            status.configure(text="  已停止  ", fg_color=CARD_ALT, text_color=MUTED)

    def show(self):
        if not self._centered:
            self._center_window()
            self._centered = True
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide(self):
        self.root.withdraw()

    def _center_window(self):
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = max((self.root.winfo_screenwidth() - width) // 2, 0)
        y = max((self.root.winfo_screenheight() - height) // 2, 0)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _toggle_server(self):
        desired = bool(self.server_card["switch"].get())
        if not self.manager.request_service_state("server", desired):
            self.refresh_status()

    def _toggle_client(self):
        desired = bool(self.client_card["switch"].get())
        if not self.manager.request_service_state("client", desired):
            self.refresh_status()

    def _restart_services(self):
        if not self.manager.restart_services_async():
            self.settings_message.configure(text="服务正忙，请稍后再试", text_color=WARNING)

    def _fetch_file(self):
        threading.Thread(
            target=self.manager.file_handler.fetch_file_with_progress,
            daemon=True,
        ).start()

    def _open_download_folder(self):
        path = Path(self.save_path_entry.get() or self.config.save_path)
        try:
            path.mkdir(parents=True, exist_ok=True)
            os.startfile(path)
        except Exception as exc:
            show_message("无法打开目录", str(exc))

    def _open_config_folder(self):
        config_dir = BASE_DIR / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(config_dir)

    def _choose_directory(self):
        selected = filedialog.askdirectory(
            parent=self.root,
            initialdir=self.save_path_entry.get() or self.config.save_path,
            title="选择文件保存目录",
        )
        if selected:
            self._set_entry(self.save_path_entry, selected)

    def _toggle_secret(self):
        self._secret_visible = not self._secret_visible
        self.key_entry.configure(show="" if self._secret_visible else "•")
        self.secret_toggle.configure(text="隐藏密钥" if self._secret_visible else "显示密钥")

    def _toggle_autostart(self):
        desired = bool(self.autostart_switch.get())
        if not self.config.toggle_autostart(desired):
            if desired:
                self.autostart_switch.deselect()
            else:
                self.autostart_switch.select()
            self.settings_message.configure(text="开机启动设置失败", text_color=DANGER)
        else:
            self.settings_message.configure(
                text="已开启开机后台启动" if desired else "已关闭开机启动",
                text_color=SUCCESS,
            )

    def _change_appearance(self, label):
        mode = self.APPEARANCE_MODES.get(label, "System")
        set_appearance_mode(mode)
        self.config.appearance_mode = mode
        if not self.config.save_state():
            self.settings_message.configure(text="外观偏好保存失败", text_color=DANGER)


class FallbackMainWindow:
    """Functional ttk fallback for source environments without CustomTkinter."""

    def __init__(self, root, manager):
        self.root = root
        self.manager = manager
        self._refresh_job = None
        self.root.title("SyncClipboard")
        self.root.geometry("620x420")
        self.root.protocol("WM_DELETE_WINDOW", self.hide)

        frame = ttk.Frame(root, padding=24)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="SyncClipboard", font=(FONT, 22, "bold")).pack(anchor="w")
        ttk.Label(frame, text="跨设备剪贴板同步中心").pack(anchor="w", pady=(0, 20))
        self.status = ttk.Label(frame, text="正在读取状态…", font=(FONT, 11))
        self.status.pack(anchor="w", pady=(0, 18))
        ttk.Button(frame, text="切换同步客户端", command=self._toggle_client).pack(fill="x", pady=5)
        ttk.Button(frame, text="切换本机服务器", command=self._toggle_server).pack(fill="x", pady=5)
        ttk.Button(frame, text="获取共享文件", command=self._fetch_file).pack(fill="x", pady=5)
        ttk.Button(frame, text="打开配置目录", command=self._open_config).pack(fill="x", pady=5)
        ttk.Button(frame, text="隐藏到托盘", command=self.hide).pack(fill="x", pady=(18, 5))
        self.refresh_status()

    def refresh_status(self):
        if self._refresh_job is not None:
            try:
                self.root.after_cancel(self._refresh_job)
            except Exception:
                pass
        state = self.manager.get_service_state()
        self.status.configure(
            text=(
                f"客户端：{'运行中' if state['client_alive'] else '已停止'}    "
                f"服务器：{'运行中' if state['server_alive'] else '已停止'}"
            )
        )
        self._refresh_job = self.root.after(1000, self.refresh_status)

    def show(self):
        self.root.deiconify()
        self.root.lift()

    def hide(self):
        self.root.withdraw()

    def _toggle_client(self):
        state = self.manager.get_service_state()
        self.manager.request_service_state("client", not state["client_enabled"])

    def _toggle_server(self):
        state = self.manager.get_service_state()
        self.manager.request_service_state("server", not state["server_enabled"])

    def _fetch_file(self):
        threading.Thread(target=self.manager.file_handler.fetch_file_with_progress, daemon=True).start()

    @staticmethod
    def _open_config():
        os.startfile(BASE_DIR / "config")
