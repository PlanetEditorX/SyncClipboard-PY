import logging
import threading
import tkinter as tk
from tkinter import ttk
from common.utils import post_to_main_thread, get_tk_root, post_to_main_thread_no_wait, BASE_DIR
from gui.ui_backend import create_root, ctk

import ctypes

logger = logging.getLogger("gui")


class DownloadProgressDialog:
    """下载进度对话框（支持复用，线程安全）"""
    def __init__(self, title="下载进度", master=None):
        self._owns_master = False
        # 如果调用者没有提供 master，则使用已注册的全局根窗口
        if master is None:
            master = get_tk_root()
            if master is None:
                logger.warning("No Tk root registered. Creating a temporary root.")
                master, self._use_customtkinter = create_root()
                self._owns_master = True
                master.withdraw()
            else:
                self._use_customtkinter = ctk is not None and isinstance(master, ctk.CTk)
        else:
            self._use_customtkinter = ctk is not None and isinstance(master, ctk.CTk)
        self.master = master

        if self._use_customtkinter:
            self.window = ctk.CTkToplevel(master)
        else:
            self.window = tk.Toplevel(master)

        self.window.withdraw()
        if hasattr(self.window, 'transient'):
            try:
                if getattr(master, 'state', lambda: '')() != 'withdrawn':
                    self.window.transient(master)
            except Exception as e:
                logger.warning(f"无法设置 transient: {e}", exc_info=True)

        self.window.title(title)
        self.window.resizable(False, False)
        try:
            icon_path = BASE_DIR / "gui" / "icon" / "icon-active.png"
            if icon_path.exists():
                self.window.iconphoto(False, tk.PhotoImage(file=str(icon_path)))
        except Exception as e:
            logger.warning(f"加载图标失败: {e}", exc_info=True)

        if self._use_customtkinter:
            try:
                self.window.configure(fg_color=("#F4F7FB", "#080D18"))
            except Exception as e:
                logger.warning(f"配置窗口前景色失败: {e}", exc_info=True)
        else:
            try:
                self.window.configure(bg="#f7f7f7")
            except Exception as e:
                logger.warning(f"配置窗口背景色失败: {e}", exc_info=True)

        if self._use_customtkinter:
            self.container = ctk.CTkFrame(self.window, fg_color=("#F4F7FB", "#080D18"))
        else:
            self.container = tk.Frame(self.window, bg="#f7f7f7")
        self.container.grid(row=0, column=0, sticky='nsew')
        self.container.grid_columnconfigure(0, weight=1)
        try:
            self.window.grid_rowconfigure(0, weight=1)
        except Exception as e:
            logger.warning(f"配置行权重失败: {e}", exc_info=True)

        if self._use_customtkinter:
            self.label = ctk.CTkLabel(self.container, text="正在下载文件...", font=("微软雅黑", 15, "bold"), anchor='w')
        else:
            self.label = tk.Label(self.container, text="正在下载文件...", font=("微软雅黑", 15, "bold"), bg="#f7f7f7", anchor='w')
        self.label.grid(row=0, column=0, padx=20, pady=(20, 10), sticky='ew')

        self.progress_var = tk.DoubleVar()
        if self._use_customtkinter:
            self.progress_bar = ctk.CTkProgressBar(self.container, mode='determinate')
            self._use_ctk_progress = True
        else:
            style = ttk.Style()
            style.theme_use('clam')
            style.configure("TProgressbar", thickness=20)
            self.progress_bar = ttk.Progressbar(
                self.container, variable=self.progress_var, maximum=100,
                mode='determinate', style="TProgressbar"
            )
            self._use_ctk_progress = False
        self.progress_bar.grid(row=1, column=0, padx=20, pady=5, sticky='ew')

        if self._use_customtkinter:
            self.detail_label = ctk.CTkLabel(self.container, text="准备下载...", font=("微软雅黑", 11), anchor='w')
        else:
            self.detail_label = tk.Label(self.container, text="准备下载...", font=("微软雅黑", 11), bg="#f7f7f7", anchor='w')
        self.detail_label.grid(row=2, column=0, padx=20, pady=(5, 15), sticky='ew')

        if self._use_customtkinter:
            self.cancel_button = ctk.CTkButton(
                self.container, text="取消下载", command=self.cancel,
                width=120, height=32, corner_radius=8
            )
        else:
            self.cancel_button = tk.Button(
                self.container, text="取消下载", command=self.cancel,
                font=("微软雅黑", 10), width=12, height=1,
                bg="#f0f0f0", relief=tk.RAISED, cursor="hand2"
            )
        self.cancel_button.grid(row=3, column=0, padx=20, pady=(0, 20), sticky='e')

        self.window.protocol("WM_DELETE_WINDOW", self.cancel)
        self.cancelled = False
        self._running = True   # 控件初始化完毕即标记为运行中

        try:
            self.window.attributes("-alpha", 0)
            self.window.deiconify()
            self.window.after(100, self._show_centered)
        except Exception as e:
            logger.warning(f"显示窗口并居中时失败: {e}", exc_info=True)

    def _show_centered(self):
        self._center_window()

        self.window.attributes("-alpha", 1)

        self.window.lift()
        self.window.focus_force()

    def _center_window(self):
        try:
            self.window.update_idletasks()
            width = self.window.winfo_width()
            height = self.window.winfo_height()
            if width <= 1 or height <= 1:
                width = self.window.winfo_reqwidth()
                height = self.window.winfo_reqheight()
                if width <= 1 or height <= 1:
                    self.window.after(50, self._center_window)
                    return
            try:
                user32 = ctypes.windll.user32
                MONITOR_DEFAULTTONEAREST = 2
                hwnd = self.window.winfo_id()
                hmon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
                class RECT(ctypes.Structure):
                    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
                class MONITORINFO(ctypes.Structure):
                    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", RECT),
                                ("rcWork", RECT), ("dwFlags", ctypes.c_ulong)]

                mi = MONITORINFO()
                mi.cbSize = ctypes.sizeof(MONITORINFO)
                if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                    left = mi.rcWork.left
                    top = mi.rcWork.top
                    right = mi.rcWork.right
                    bottom = mi.rcWork.bottom
                    screen_w = right - left
                    screen_h = bottom - top
                    x = left + max((screen_w - width) // 2, 0)
                    y = top + max((screen_h - height) // 2, 0)
                    self.window.geometry(f"+{x}+{y}")
                    return
            except Exception as e:
                logger.warning(f"使用 user32 获取多显示器位置失败: {e}", exc_info=True)
            screen_w = self.window.winfo_screenwidth()
            screen_h = self.window.winfo_screenheight()
            x = max((screen_w - width) // 2, 0)
            y = max((screen_h - height) // 2, 0)
            self.window.geometry(f"+{x}+{y}")
        except Exception as e:
            logger.warning(f"窗口居中失败: {e}", exc_info=True)

    def _set_progress_value(self, percentage):
        if getattr(self, '_use_ctk_progress', False):
            self.progress_bar.set(percentage / 100.0)
        else:
            self.progress_var.set(percentage)

    def reset(self, filename, total_size=0):
        def _update():
            if not self.window.winfo_exists():
                return
            self.label.configure(text=f"正在下载：{filename}")
            self._set_progress_value(0)
            self.detail_label.configure(text="准备下载...")
            self.window.update_idletasks()

        post_to_main_thread_no_wait(_update)

    def update_progress(self, percentage, downloaded_mb, total_mb):
        """更新进度（线程安全，异步，不阻塞下载线程）"""
        def _update():
            if not self.window.winfo_exists():
                return
            self._set_progress_value(percentage)
            if total_mb > 0:
                self.detail_label.configure(
                    text=f"下载进度：{percentage}% ({downloaded_mb:.1f} MB / {total_mb:.1f} MB)"
                )
            else:
                self.detail_label.configure(
                    text=f"已下载：{downloaded_mb:.1f} MB"
                )
            # 强制刷新
            self.window.update_idletasks()

        # 异步投递，不等待
        post_to_main_thread_no_wait(_update)

    def cancel(self):
        """取消下载"""
        self.cancelled = True
        self._running = False
        def _destroy():
            try:
                if self.window.winfo_exists():
                    self.window.destroy()
                if self._owns_master and self.master.winfo_exists():
                    self.master.destroy()
            except Exception as e:
                logger.warning(f"取消下载销毁窗口失败: {e}", exc_info=True)
        post_to_main_thread(_destroy)

    def close(self):
        """关闭对话框"""
        self._running = False
        def _destroy():
            try:
                if self.window.winfo_exists():
                    self.window.destroy()
                if self._owns_master and self.master.winfo_exists():
                    self.master.destroy()
            except Exception as e:
                logger.warning(f"关闭对话框销毁窗口失败: {e}", exc_info=True)
        post_to_main_thread(_destroy)

    def is_cancelled(self):
        return self.cancelled
