import sys
import os
import json
import winreg
import socket
import logging
import tempfile
import threading
from pathlib import Path
from common.utils import BASE_DIR, get_default_server_host

logger = logging.getLogger("gui")

class ConfigManager:
    """配置管理器"""
    _CONFIG_LOCK = threading.RLock()
    # 配置文件路径常量
    CLIENT_CONFIG = BASE_DIR / "config" / "client_config.json"
    SERVER_CONFIG = BASE_DIR / "config" / "server_config.json"
    STATE_FILE = BASE_DIR / "config" / "gui_state.json"
    TEXT_LATEST_FILE = BASE_DIR / "latest" / "text_latest.json"
    FILE_LATEST_FILE = BASE_DIR / "latest" / "file_latest.json"
    def __init__(self):
        self.server_host = None
        self.server_port = None
        self.key = None
        self.local_name = socket.gethostname() # 直接使用电脑名称
        self.file_server_port = None
        self.save_path = str(Path.home() / "Downloads")
        self.server_running = False
        self.client_running = False
        self.server_local_name = "Server"
        self.appearance_mode = "System"
        self._state_data = {}
        self._client_config_data = {}
        self._server_config_data = {}
        self._config_lock = ConfigManager._CONFIG_LOCK

        # 确保必要的目录存在
        ConfigManager.CLIENT_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        ConfigManager.TEXT_LATEST_FILE.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _read_json_object(path):
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(f"{path.name} 必须是 JSON 对象")
        return data

    @staticmethod
    def _atomic_write_json(path, data):
        """Write JSON in the same directory, then atomically replace the target."""
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(
                mode='w',
                encoding='utf-8',
                dir=path.parent,
                prefix=f'.{path.name}.',
                suffix='.tmp',
                delete=False,
            ) as f:
                temp_name = f.name
                json.dump(data, f, ensure_ascii=False, indent=4)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_name, path)
        except Exception:
            if temp_name:
                try:
                    Path(temp_name).unlink(missing_ok=True)
                except OSError:
                    pass
            raise

    def load_state(self):
        """加载服务运行状态"""
        if ConfigManager.STATE_FILE.exists():
            try:
                with open(ConfigManager.STATE_FILE, 'r', encoding='utf-8') as f:
                    s = json.load(f)
                if not isinstance(s, dict):
                    raise ValueError("GUI 状态文件必须是 JSON 对象")
                self._state_data = dict(s)
                self.server_running = s.get('server_running', False)
                self.client_running = s.get('client_running', False)
                appearance_mode = s.get('appearance_mode', 'System')
                self.appearance_mode = (
                    appearance_mode if appearance_mode in {'System', 'Light', 'Dark'} else 'System'
                )
            except Exception as e:
                logger.error(f"加载服务运行状态失败: {e}")

    def save_state(self):
        """保存服务运行状态"""
        with self._config_lock:
            try:
                state = dict(self._state_data)
                if ConfigManager.STATE_FILE.exists():
                    try:
                        state.update(self._read_json_object(ConfigManager.STATE_FILE))
                    except Exception as e:
                        logger.warning(f"重新读取 GUI 状态失败，使用内存副本: {e}")
                state.update({
                    'server_running': self.server_running,
                    'client_running': self.client_running,
                    'appearance_mode': self.appearance_mode
                })
                self._atomic_write_json(ConfigManager.STATE_FILE, state)
                self._state_data = state
                return True
            except Exception as e:
                logger.error(f"保存服务运行状态失败: {e}")
                return False

    def load_client_config(self):
        """加载客户端配置"""
        config_file = ConfigManager.CLIENT_CONFIG

        # 1. 如果配置文件不存在，创建默认配置
        if not config_file.exists():
            logger.info("客户端配置文件不存在，正在创建默认配置...")
            default_config = {
                "server_host": get_default_server_host(),
                "server_port": 8000,
                "key": "123456",
                "local_name": self.local_name,
                "file_server_port": 8899,
                "save_path": str(Path.home() / "Downloads")
            }
            try:
                with open(config_file, 'w', encoding='utf-8') as f:
                    json.dump(default_config, f, ensure_ascii=False, indent=4)
                logger.info(f"默认配置文件已创建，电脑名称: {default_config['local_name']}")
            except Exception as e:
                logger.error(f"创建默认配置文件失败: {e}")
                return False

        # 2. 读取配置文件
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            if not isinstance(config, dict):
                raise ValueError("客户端配置文件必须是 JSON 对象")
        except Exception as e:
            logger.error(f"读取配置文件失败: {e}")
            return False

        # 3. 处理电脑名称：如果是默认值 "PC-01"，则替换为真实电脑名称
        need_save = False
        if config.get("local_name") == "PC-01":
            logger.info(f"检测到默认电脑名称 'PC-01'，正在替换为真实电脑名称: {self.local_name}")
            config["local_name"] = self.local_name
            need_save = True

        if config.get("server_host") == "127.0.0.1":
            logger.info(f"检测到默认服务器地址 '127.0.0.1'，正在替换为真实服务器地址")
            config["server_host"] = get_default_server_host()
            need_save = True

        # 4. 检查并补充缺失的字段（兼容旧版本配置文件）
        default_fields = {
            "server_host": "127.0.0.1",
            "server_port": 8000,
            "key": "",
            "local_name": self.local_name,
            "file_server_port": 8899,
            "save_path": str(Path.home() / "Downloads")
        }

        for field, default_value in default_fields.items():
            if field not in config:
                logger.warning(f"配置文件缺少字段 '{field}'，使用默认值: {default_value}")
                config[field] = default_value
                need_save = True

        # 5. 如果有修改，保存配置文件
        if need_save:
            try:
                with open(config_file, 'w', encoding='utf-8') as f:
                    json.dump(config, f, ensure_ascii=False, indent=4)
                logger.info("配置文件已更新")
            except Exception as e:
                logger.error(f"保存配置文件失败: {e}")

        # 6. 赋值给实例变量
        self.server_host = config.get("server_host")
        self.server_port = config.get("server_port")
        self.key = config.get("key", "")
        self.local_name = config.get("local_name")
        self.file_server_port = config.get("file_server_port")
        self.save_path = config.get("save_path", str(Path.home() / "Downloads"))
        self._client_config_data = dict(config)

        logger.info(f"读取客户端配置 | 服务器={self.server_host}:{self.server_port} | 客户端={self.local_name}")
        return True

    def save_client_config(self):
        """保存客户端配置"""
        with self._config_lock:
            return self._save_client_config_locked()

    def _save_client_config_locked(self):
        try:
            config = dict(self._client_config_data)
            if ConfigManager.CLIENT_CONFIG.exists():
                try:
                    config.update(self._read_json_object(ConfigManager.CLIENT_CONFIG))
                except Exception as e:
                    logger.warning(f"重新读取客户端配置失败，使用内存副本: {e}")
            config.update({
                "server_host": self.server_host,
                "server_port": self.server_port,
                "key": self.key,
                "local_name": self.local_name,
                "file_server_port": self.file_server_port,
                "save_path": self.save_path
            })
            self._atomic_write_json(ConfigManager.CLIENT_CONFIG, config)
            self._client_config_data = config
            logger.info(f"客户端配置已保存 | 电脑名称: {self.local_name}")
            return True
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
            return False

    def update_client_config(self, values):
        """Atomically update all UI-managed client fields in memory and on disk."""
        allowed_fields = {
            "server_host",
            "server_port",
            "key",
            "local_name",
            "file_server_port",
            "save_path",
        }
        unknown = set(values) - allowed_fields
        if unknown:
            raise ValueError(f"未知客户端配置字段: {', '.join(sorted(unknown))}")

        with self._config_lock:
            previous = {key: getattr(self, key) for key in values}
            for key, value in values.items():
                setattr(self, key, value)
            if self._save_client_config_locked():
                return True
            for key, value in previous.items():
                setattr(self, key, value)
            return False

    def load_server_config(self):
        """加载服务器配置（自动创建默认配置）"""
        config_file = ConfigManager.SERVER_CONFIG

        # 1. 如果配置文件不存在，创建默认配置
        if not config_file.exists():
            logger.info("服务器配置文件不存在，正在创建默认配置...")
            default_config = {
                "key": "123456",
                "port": 8000,
                "local_name": self.local_name
            }
            try:
                with open(config_file, 'w', encoding='utf-8') as f:
                    json.dump(default_config, f, ensure_ascii=False, indent=4)
                logger.info(f"默认服务器配置文件已创建，端口: {default_config['port']}")
            except Exception as e:
                logger.error(f"创建默认服务器配置文件失败: {e}")
                return False

        # 2. 读取配置文件
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            if not isinstance(config, dict):
                raise ValueError("服务器配置文件必须是 JSON 对象")
        except Exception as e:
            logger.error(f"读取服务器配置文件失败: {e}")
            return False
        # 3. 设置默认名字
        need_save = False
        if config.get("local_name") == "Server":
            logger.info(f"检测到默认服务器名称 'Server'，正在替换为真实电脑名称: {self.local_name}")
            config["local_name"] = self.local_name
            need_save = True

        # 4. 检查并补充缺失的字段
        default_fields = {
            "key": "123456",
            "port": 8000,
            "local_name": self.local_name
        }

        for field, default_value in default_fields.items():
            if field not in config:
                logger.warning(f"服务器配置文件缺少字段 '{field}'，使用默认值: {default_value}")
                config[field] = default_value
                need_save = True

        # 5. 如果有修改，保存配置文件
        if need_save:
            try:
                with open(config_file, 'w', encoding='utf-8') as f:
                    json.dump(config, f, ensure_ascii=False, indent=4)
                logger.info("服务器配置文件已更新")
            except Exception as e:
                logger.error(f"保存服务器配置文件失败: {e}")

        # 5. 赋值给实例变量
        self.server_port = config.get("port")
        self.key = config.get("key", "")
        self.local_name = config.get("local_name", "Server")
        self.save_path = config.get("save_path", str(Path.home() / "Downloads"))
        self._server_config_data = dict(config)

        logger.info(f"读取服务器配置 | 端口={self.server_port} | 保存路径={self.save_path} | 服务器名称={self.local_name}")
        return True

    def save_server_config(self):
        """保存服务器配置"""
        with self._config_lock:
            try:
                config = dict(self._server_config_data)
                if ConfigManager.SERVER_CONFIG.exists():
                    try:
                        config.update(self._read_json_object(ConfigManager.SERVER_CONFIG))
                    except Exception as e:
                        logger.warning(f"重新读取服务器配置失败，使用内存副本: {e}")
                config.update({
                    "port": self.server_port,
                    "key": self.key,
                    "local_name": getattr(self, 'local_name', "Server"),
                    "save_path": self.save_path,
                })
                self._atomic_write_json(ConfigManager.SERVER_CONFIG, config)
                self._server_config_data = config
                logger.info(f"服务器配置已保存 | 端口: {self.server_port} | 保存路径: {self.save_path}")
                return True
            except Exception as e:
                logger.error(f"保存服务器配置失败: {e}")
                return False

    def is_autostart_enabled(self):
        """检查是否已设置开机启动"""
        try:
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
                winreg.QueryValueEx(key, "SyncClipboardTray")
                return True
        except FileNotFoundError:
            return False
        except OSError as e:
            logger.error(f"读取开机启动状态失败: {e}")
            return False

    def toggle_autostart(self, enabled):
        """切换开机启动"""
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        try:
            if enabled:
                # 开启
                if getattr(sys, "frozen", False):
                    cmd = f'"{sys.executable}" --minimized'
                else:
                    cmd = f'"{sys.executable}" -m gui.run --minimized'
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                    winreg.SetValueEx(key, "SyncClipboardTray", 0, winreg.REG_SZ, cmd)
                logger.info("开机启动已启用")
            else:
                # 关闭
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                    winreg.DeleteValue(key, "SyncClipboardTray")
                logger.info("开机启动已禁用")
            return True
        except Exception as e:
            logger.error(f"开机启动操作失败: {e}")
            return False
