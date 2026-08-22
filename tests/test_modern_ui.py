import importlib
import json
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from gui.config_manager import ConfigManager
from gui.main_window import ModernMainWindow, validate_client_settings
from gui.service_manager import ServiceManager


class TestClientSettingsValidation(unittest.TestCase):
    def test_valid_settings_are_trimmed_and_ports_are_normalized(self):
        result = validate_client_settings(
            " 192.0.2.10 ", "8000", " Office-PC ", "8899", " secret ", " D:/Downloads "
        )

        self.assertEqual(result["server_host"], "192.0.2.10")
        self.assertEqual(result["server_port"], 8000)
        self.assertEqual(result["file_server_port"], 8899)
        self.assertEqual(result["local_name"], "Office-PC")

    def test_key_keeps_intentional_surrounding_spaces(self):
        result = validate_client_settings(
            "host", "8000", "PC", "8899", " secret with spaces ", "D:/Downloads"
        )
        self.assertEqual(result["key"], " secret with spaces ")

    def test_invalid_port_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "服务器端口"):
            validate_client_settings("host", "70000", "PC", "8899", "key", "D:/Downloads")

    def test_empty_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "共享密钥"):
            validate_client_settings("host", "8000", "PC", "8899", "  ", "D:/Downloads")


class TestModernUiCompatibility(unittest.TestCase):
    def test_failed_settings_save_rolls_back_runtime_values(self):
        config = SimpleNamespace(
            server_host="old-host",
            server_port=8000,
            local_name="Old-PC",
            file_server_port=8899,
            key="old-key",
            save_path="D:/Old",
            update_client_config=MagicMock(return_value=False),
        )
        window = ModernMainWindow.__new__(ModernMainWindow)
        window.config = config
        window.manager = MagicMock()
        window.settings_message = MagicMock()
        window.server_host_entry = MagicMock(get=MagicMock(return_value="new-host"))
        window.server_port_entry = MagicMock(get=MagicMock(return_value="9000"))
        window.local_name_entry = MagicMock(get=MagicMock(return_value="New-PC"))
        window.file_port_entry = MagicMock(get=MagicMock(return_value="9999"))
        window.key_entry = MagicMock(get=MagicMock(return_value="new-key"))
        window.save_path_entry = MagicMock(get=MagicMock(return_value="D:/New"))

        window.save_settings()

        self.assertEqual(config.server_host, "old-host")
        self.assertEqual(config.server_port, 8000)
        self.assertEqual(config.local_name, "Old-PC")
        self.assertEqual(config.key, "old-key")

    def test_importing_tray_manager_does_not_create_a_root_window(self):
        module = importlib.import_module("gui.tray_manager")
        self.assertFalse(hasattr(module, "root"))

    def test_build_script_is_import_safe_and_uses_onedir(self):
        build = importlib.import_module("release.build")
        command = build.build_command(Path("C:/preview/customtkinter"))

        self.assertIn("--onedir", command)
        self.assertNotIn("--onefile", command)
        self.assertIn("--add-data", command)
        self.assertTrue(any(value.endswith("customtkinter") for value in command))

    def test_build_assets_keep_templates_separate_from_runtime_config(self):
        build = importlib.import_module("release.build")
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            project = temp / "project"
            release_dir = project / "release"
            app_dir = release_dir / "dist" / "SyncClipboard"
            (project / "config" / "example").mkdir(parents=True)
            (project / "config" / "example" / "client_config.json").write_text("{}", encoding="utf-8")
            (project / "gui" / "icon").mkdir(parents=True)
            app_dir.mkdir(parents=True)
            (app_dir / "SyncClipboard.exe").write_bytes(b"preview")

            with (
                patch.object(build, "PROJECT_ROOT", project),
                patch.object(build, "RELEASE_DIR", release_dir),
                patch.object(build, "APP_DIR", app_dir),
            ):
                build.copy_runtime_assets()

            self.assertTrue((app_dir / "config" / "example" / "client_config.json").exists())
            self.assertFalse((app_dir / "config" / "client_config.json").exists())

    def test_ui_shutdown_releases_waiting_worker(self):
        from common import utils

        root = MagicMock()
        errors = []
        started = threading.Event()
        utils.clear_tk_root()
        utils.set_tk_root(root)

        def worker():
            started.set()
            try:
                utils.post_to_main_thread(lambda: None)
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        self.assertTrue(started.wait(timeout=1))
        utils.request_tk_shutdown(root)
        thread.join(timeout=1)
        utils.clear_tk_root(root)

        self.assertFalse(thread.is_alive())
        self.assertTrue(any(isinstance(error, RuntimeError) for error in errors))

    def test_state_and_client_config_preserve_unknown_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            state_file = temp / "config" / "gui_state.json"
            client_file = temp / "config" / "client_config.json"
            server_file = temp / "config" / "server_config.json"
            latest_file = temp / "latest" / "text_latest.json"
            state_file.parent.mkdir(parents=True)
            client_file.parent.mkdir(parents=True, exist_ok=True)

            state_file.write_text(
                json.dumps({"server_running": False, "client_running": True, "future_flag": 7}),
                encoding="utf-8",
            )
            client_file.write_text(
                json.dumps(
                    {
                        "server_host": "192.0.2.10",
                        "server_port": 8000,
                        "key": "secret",
                        "local_name": "Office-PC",
                        "file_server_port": 8899,
                        "save_path": str(temp),
                        "future_option": {"enabled": True},
                    }
                ),
                encoding="utf-8",
            )
            server_file.write_text(
                json.dumps(
                    {
                        "host": "0.0.0.0",
                        "port": 8000,
                        "key": "secret",
                        "local_name": "Office-Server",
                        "future_server_option": True,
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch.object(ConfigManager, "STATE_FILE", state_file),
                patch.object(ConfigManager, "CLIENT_CONFIG", client_file),
                patch.object(ConfigManager, "SERVER_CONFIG", server_file),
                patch.object(ConfigManager, "TEXT_LATEST_FILE", latest_file),
                patch.object(ConfigManager, "FILE_LATEST_FILE", temp / "latest" / "file_latest.json"),
            ):
                manager = ConfigManager()
                manager.load_state()
                external_state = json.loads(state_file.read_text(encoding="utf-8"))
                external_state["added_while_running"] = "state-value"
                state_file.write_text(json.dumps(external_state), encoding="utf-8")
                manager.appearance_mode = "Dark"
                manager.save_state()

                self.assertTrue(manager.load_client_config())
                externally_edited = json.loads(client_file.read_text(encoding="utf-8"))
                externally_edited["added_while_running"] = "preserve-me"
                client_file.write_text(json.dumps(externally_edited), encoding="utf-8")
                manager.server_port = 9000
                self.assertTrue(manager.save_client_config())
                persisted_client = client_file.read_text(encoding="utf-8")
                failed_update = {
                    "server_host": manager.server_host,
                    "server_port": 9200,
                    "local_name": manager.local_name,
                    "file_server_port": manager.file_server_port,
                    "key": manager.key,
                    "save_path": manager.save_path,
                }
                with patch("gui.config_manager.os.replace", side_effect=OSError("disk busy")):
                    self.assertFalse(manager.update_client_config(failed_update))
                self.assertEqual(client_file.read_text(encoding="utf-8"), persisted_client)
                self.assertEqual(list(client_file.parent.glob(".client_config.json.*.tmp")), [])
                self.assertEqual(manager.server_port, 9000)
                self.assertTrue(manager.load_server_config())
                external_server = json.loads(server_file.read_text(encoding="utf-8"))
                external_server["added_while_running"] = "server-value"
                server_file.write_text(json.dumps(external_server), encoding="utf-8")
                manager.server_port = 9100
                self.assertTrue(manager.save_server_config())

            state = json.loads(state_file.read_text(encoding="utf-8"))
            client = json.loads(client_file.read_text(encoding="utf-8"))
            server = json.loads(server_file.read_text(encoding="utf-8"))
            self.assertEqual(state["future_flag"], 7)
            self.assertEqual(state["added_while_running"], "state-value")
            self.assertEqual(state["appearance_mode"], "Dark")
            self.assertEqual(client["future_option"], {"enabled": True})
            self.assertEqual(client["added_while_running"], "preserve-me")
            self.assertEqual(client["server_port"], 9000)
            self.assertEqual(server["host"], "0.0.0.0")
            self.assertTrue(server["future_server_option"])
            self.assertEqual(server["added_while_running"], "server-value")
            self.assertEqual(server["port"], 9100)

    def test_restart_only_restarts_enabled_services(self):
        config = MagicMock(server_running=False, client_running=True)
        manager = ServiceManager(config)
        manager.stop_server = MagicMock()
        manager.start_server = MagicMock()
        manager.stop_client = MagicMock()
        manager.start_client = MagicMock()

        with patch("gui.service_manager.time.sleep"):
            manager.restart_services()

        manager.stop_server.assert_not_called()
        manager.start_server.assert_not_called()
        manager.stop_client.assert_called_once_with(preserve_intent=True)
        manager.start_client.assert_called_once_with()

    def test_start_failure_preserves_enabled_intent(self):
        config = SimpleNamespace(
            server_running=False,
            client_running=False,
            save_state=MagicMock(return_value=True),
        )
        manager = ServiceManager(config)
        process = MagicMock()
        process.start.side_effect = OSError("spawn failed")

        with patch("gui.service_manager.multiprocessing.Process", return_value=process):
            self.assertFalse(manager.start_client())

        self.assertTrue(config.client_running)
        self.assertIsNone(manager.client_process)

    def test_shutdown_runs_after_an_accepted_service_action(self):
        from gui.tray_manager import TrayManager

        order = []
        config = SimpleNamespace(
            server_running=False,
            client_running=False,
            save_state=lambda: order.append("save"),
        )

        class Services:
            server_process = None
            client_process = None

            def start_client(self):
                order.append("start-client")
                config.client_running = True

            def stop_client(self, preserve_intent=False):
                order.append("stop-client")
                if not preserve_intent:
                    config.client_running = False

            def stop_server(self, preserve_intent=False):
                order.append("stop-server")
                if not preserve_intent:
                    config.server_running = False

        manager = TrayManager.__new__(TrayManager)
        manager.config = config
        manager.services = Services()
        manager.root = MagicMock()
        manager.window = None
        manager.icon = None
        manager._service_busy = False
        manager._quitting = False
        manager._state_lock = threading.Lock()
        manager._operation_queue = queue.Queue()
        manager._operation_thread = threading.Thread(
            target=manager._process_operation_queue,
            daemon=True,
        )
        manager._operation_thread.start()

        posted = []
        with (
            patch("gui.tray_manager.post_to_main_thread_no_wait", side_effect=lambda func, *args: posted.append(func)),
            patch("gui.tray_manager.request_tk_shutdown") as request_shutdown,
        ):
            self.assertTrue(manager.request_service_state("client", True))
            manager.quit_app()
            manager._operation_thread.join(timeout=2)

        self.assertFalse(manager._operation_thread.is_alive())
        self.assertEqual(order[:3], ["start-client", "stop-server", "stop-client"])
        self.assertTrue(config.client_running)
        request_shutdown.assert_called_once_with(manager.root)


if __name__ == "__main__":
    unittest.main()
