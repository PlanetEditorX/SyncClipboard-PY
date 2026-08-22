import os
import logging
import requests
import threading
import tkinter as tk
from tkinter import filedialog
from gui.download_dialog import DownloadProgressDialog
from common.utils import post_to_main_thread, show_message, copy_files_to_clipboard, parse_filename_from_cd, get_tk_root

logger = logging.getLogger("gui")

class FileHandler:
    """文件下载处理器"""
    def __init__(self, config_manager):
        self.config = config_manager

    def _run_in_worker_thread(self, func, *args, **kwargs):
        """如果当前在主线程，则将阻塞操作移到后台线程执行。"""
        if threading.current_thread() is threading.main_thread():
            thread = threading.Thread(target=func, args=args, kwargs=kwargs, daemon=True)
            thread.start()
            return thread
        return func(*args, **kwargs)

    def _run_in_main_thread(self, func, *args, **kwargs):
        """
        在主线程执行 func 并同步返回结果。
        若当前已是主线程则直接执行，否则用 after 调度并等待。
        """
        root = get_tk_root()
        if root is None:
            logger.error("Tk 根窗口未初始化")
            return None
        if threading.current_thread() is threading.main_thread():
            return func(*args, **kwargs)

        result = [None]
        event = threading.Event()
        def wrapper():
            result[0] = func(*args, **kwargs)
            event.set()
        root.after(0, wrapper)
        event.wait()
        return result[0]

    def _get_dialog_parent(self):
        root = get_tk_root()
        if root is None:
            return None
        try:
            if getattr(root, 'state', lambda: '')() == 'withdrawn':
                root.update_idletasks()
                screen_w = root.winfo_screenwidth()
                screen_h = root.winfo_screenheight()
                root.geometry(f"+{screen_w//2}+{screen_h//2}")
        except Exception as e:
            logger.warning(f"获取或设置对话框父级窗口状态出错: {e}")
        return root

    def _ask_save_path(self, filename):
        """弹出保存对话框（线程安全）"""
        def _ask():
            parent = self._get_dialog_parent()
            file_path = filedialog.asksaveasfilename(
                title="保存文件",
                initialdir=self.config.save_path,
                initialfile=filename,
                defaultextension="",
                filetypes=[("所有文件", "*.*")],
                parent=parent
            )
            if file_path:
                self.config.save_path = os.path.dirname(file_path)
                self.config.save_client_config()
            return file_path
        return post_to_main_thread(_ask)

    def _ask_save_directory(self):
        """弹出目录选择对话框（线程安全）"""
        def _ask():
            parent = self._get_dialog_parent()
            dir_path = filedialog.askdirectory(
                title="选择保存文件夹",
                initialdir=self.config.save_path,
                parent=parent
            )
            if dir_path:
                self.config.save_path = dir_path
                self.config.save_client_config()
            return dir_path
        return post_to_main_thread(_ask)

    def _save_file_stream(self, response, filename):
        """流式接收文件并写入磁盘"""
        file_path = self._ask_save_path(filename)
        if not file_path:
            logger.info("用户取消保存文件")
            response.close()
            return

        progress = post_to_main_thread(DownloadProgressDialog, "下载进度")

        try:
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            last_percentage = -1

            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        if progress.is_cancelled():
                            logger.info("用户取消下载")
                            f.close()
                            try:
                                os.remove(file_path)
                            except OSError as e:
                                logger.warning(f"清理下载文件失败: {e}", exc_info=True)
                            show_message("已取消", "文件下载已取消")
                            return

                        f.write(chunk)
                        downloaded += len(chunk)

                        if total_size > 0:
                            percentage = int(downloaded / total_size * 100)
                            if percentage != last_percentage:
                                downloaded_mb = downloaded / (1024 * 1024)
                                total_mb = total_size / (1024 * 1024)
                                progress.update_progress(percentage, downloaded_mb, total_mb)
                                last_percentage = percentage

            progress.update_progress(100, downloaded/(1024*1024), downloaded/(1024*1024))
            progress.close()

            logger.info(f"文件已保存: {file_path} ({downloaded} 字节)")

            if copy_files_to_clipboard([file_path]):
                logger.info(f"保存成功文件已保存至:\n{file_path}")
            else:
                logger.info(f"文件保存至:\n{file_path}失败")

        except Exception as e:
            progress.close()
            logger.error(f"保存文件失败: {e}")
            show_message("保存失败", f"无法保存文件: {e}")
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except OSError as e:
                logger.warning(f"清理下载文件失败: {e}", exc_info=True)
        finally:
            response.close()

    def _download_from_url(self, download_url, filename, save_path=None, progress_dialog=None):
        """
        从URL下载文件。
        若提供 progress_dialog 则复用该对话框，下载完成后只调用 reset()，
        最后由外部调用 close()。
        """
        if save_path is None:
            file_path = self._ask_save_path(filename)
            if not file_path:
                return False
        else:
            file_path = os.path.join(save_path, filename)
            base, ext = os.path.splitext(file_path)
            counter = 1
            while os.path.exists(file_path):
                file_path = f"{base} ({counter}){ext}"
                counter += 1

        # 决定进度对话框：外部传入则复用，否则自己创建
        own_dialog = False
        if progress_dialog is None:
            progress_dialog = post_to_main_thread(DownloadProgressDialog, "下载进度")
            own_dialog = True

        # 准备下载
        progress_dialog.reset(filename, 0)
        try:
            with requests.get(download_url, stream=True, timeout=30) as r:
                r.raise_for_status()
                total_size = int(r.headers.get('content-length', 0))
                downloaded = 0
                last_percentage = -1

                with open(file_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            if progress_dialog.is_cancelled():
                                f.close()
                                try:
                                    os.remove(file_path)
                                except OSError as e:
                                    logger.warning(f"清理下载文件失败: {e}", exc_info=True)
                                show_message("已取消", "文件下载已取消")
                                return False

                            f.write(chunk)
                            downloaded += len(chunk)

                            if total_size > 0:
                                percentage = int(downloaded / total_size * 100)
                                if percentage != last_percentage:
                                    downloaded_mb = downloaded / (1024 * 1024)
                                    total_mb = total_size / (1024 * 1024)
                                    progress_dialog.update_progress(percentage, downloaded_mb, total_mb)
                                    last_percentage = percentage

            progress_dialog.update_progress(100, downloaded/(1024*1024), downloaded/(1024*1024))
            logger.info(f"文件从URL下载成功: {file_path}")
            if copy_files_to_clipboard([file_path]):
                logger.info(f"保存成功,文件已保存至:\n{file_path}")
            else:
                logger.info(f"文件保存至:\n{file_path}失败")
            return True
        except Exception as e:
            logger.error(f"从URL下载文件失败: {e}")
            show_message("下载失败", f"下载失败: {e}")
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except OSError as e:
                logger.warning(f"清理下载文件失败: {e}", exc_info=True)
            return False
        finally:
            if own_dialog:
                progress_dialog.close()

    def _clear_latest_file(self, host, port):
        """
        通知服务器清理latest_file
        """
        try:
            clear_url = f"http://{host}:{port}/latest/clear"
            resp = requests.get(clear_url, timeout=3)
            if resp.status_code == 200:
                logger.info(f"成功通知中心服务器清理 latest_file")
            else:
                logger.warning(f"通知中心服务器返回非200: {resp.status_code}")
        except Exception as e:
            logger.error(f"通知中心服务器清理失败: {e}")

    def fetch_file_with_progress(self, suggested_filename="downloaded_file"):
        """
        点击通知后下载所有待拉取文件
        （兼容旧版单文件流 / 单文件下载链接 / 新版文件列表）
        """
        if threading.current_thread() is threading.main_thread():
            threading.Thread(target=self.fetch_file_with_progress,
                             args=(suggested_filename,),
                             daemon=True).start()
            return

        logger.info("开始拉取服务器文件...")
        server_host = self.config.server_host
        server_port = self.config.server_port
        url = f"http://{server_host}:{server_port}/request_file"
        try:
            resp = requests.post(
                url,
                headers={"key": self.config.key},
                json={"source": self.config.local_name},
                timeout=10,
                stream=True
            )
        except Exception as e:
            logger.error(f"请求服务器失败: {e}")
            show_message("请求失败", f"无法连接服务器: {e}")
            return

        if resp.status_code != 200:
            show_message("请求失败", f"HTTP {resp.status_code}")
            return

        content_type = resp.headers.get("Content-Type", "")
        # 1. 处理直接文件流
        if "application/octet-stream" in content_type or "attachment" in content_type:
            filename = parse_filename_from_cd(
                resp.headers.get("Content-Disposition", "")
            ) or suggested_filename
            self._save_file_stream(resp, filename)
            return

        # 2. 解析 JSON 响应
        try:
            data = resp.json()
        except Exception as e:
            logger.error(f"解析服务器响应失败: {e}")
            show_message("错误", "服务器响应格式异常")
            return

        # 2.1 单文件下载链接
        if data.get("status") == "download" and data.get("type") == "file":
            download_url = data.get("download_url")
            name = data.get("name", suggested_filename)
            if download_url:
                self._download_from_url(download_url, name)
            return

        # 多文件列表
        if data.get("type") == "file_list":
            files = data.get("files", [])
            if not files:
                return

            save_dir = post_to_main_thread(self._ask_save_directory)  # 已在主线程执行对话框
            if not save_dir:
                return

            # 在主线程创建进度条
            progress_dialog = post_to_main_thread(DownloadProgressDialog, "下载进度")
            all_completed = True
            try:
                for idx, file in enumerate(files, 1):
                    if progress_dialog.is_cancelled():
                        all_completed = False
                        break
                    name = file.get("name", f"file_{idx}")
                    total = len(files)
                    download_url = file.get("download_url")
                    if not download_url:
                        logger.warning(f"文件 {name} 无下载地址，跳过")
                        continue
                    logger.info(f"({idx}/{total}) 下载: {name}")
                    success = self._download_from_url(download_url, name,
                                                    save_path=save_dir,
                                                    progress_dialog=progress_dialog)
                    if not success:
                        if progress_dialog.is_cancelled():
                            all_completed = False
                        else:
                            all_completed = False
                        break
            finally:
                progress_dialog.close()

            if all_completed and not progress_dialog.is_cancelled():
                show_message("下载完成", f"已处理 {total} 个文件\n保存至：{save_dir}")
                self._clear_latest_file(server_host, server_port)
            return
