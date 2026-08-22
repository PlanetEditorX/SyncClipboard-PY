"""GUI backend selection without import-time window creation."""

import logging
import tkinter as tk
from tkinter import ttk

logger = logging.getLogger("gui")

try:
    import customtkinter as ctk
except (ImportError, OSError) as exc:
    ctk = None
    logger.warning("CustomTkinter 不可用，将使用基础界面: %s", exc)


def create_root(appearance_mode="System"):
    """Create the single Tk root in the main process, with a safe ttk fallback."""
    if appearance_mode not in {"System", "Light", "Dark"}:
        appearance_mode = "System"
    if ctk is not None:
        root = None
        try:
            ctk.set_appearance_mode(appearance_mode)
            ctk.set_default_color_theme("blue")
            root = ctk.CTk()
            return root, True
        except (tk.TclError, OSError, FileNotFoundError) as exc:
            logger.exception("CustomTkinter 初始化失败，降级为 ttk: %s", exc)
            if root is not None:
                try:
                    root.destroy()
                except Exception:
                    pass

    root = tk.Tk()
    try:
        ttk.Style(root).theme_use("clam")
    except tk.TclError:
        pass
    return root, False


def set_appearance_mode(mode):
    if ctk is not None:
        ctk.set_appearance_mode(mode)
