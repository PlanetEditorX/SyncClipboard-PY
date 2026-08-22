import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from client.file_server import FileServer
from client.main_menu import SyncClient
from server.api import flask_app
from server.core.item_builder import build_text_item
from server.core.text_tracker import TextTracker


class TestTextSyncLoopPrevention(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.text_latest_file = Path(self.temp_dir.name) / "text_latest.json"
        self.latest_patcher = patch(
            'server.core.text_tracker.TEXT_LATEST_FILE',
            self.text_latest_file,
        )
        self.latest_patcher.start()

    def tearDown(self):
        self.latest_patcher.stop()
        self.temp_dir.cleanup()

    def _make_client(self, local_name="client-b"):
        file_server = FileServer(local_name=local_name, key="secret")
        sync_client = SyncClient(
            {
                "server_host": "127.0.0.1",
                "server_port": 8000,
                "key": "secret",
                "local_name": local_name,
            },
            file_server,
        )
        return file_server, sync_client

    @patch('client.main_menu.pyperclip.copy')
    def test_remote_push_updates_sync_client_state_and_is_not_reuploaded(self, mock_copy):
        file_server, sync_client = self._make_client()
        remote_item = build_text_item(
            "hello",
            "client-a",
            timestamp="2026-08-23T10:00:00",
        )

        response = file_server.app.test_client().post(
            "/update/current_latest",
            json={
                "key": "secret",
                "type": "text",
                "latest_global": remote_item,
            },
        )

        self.assertEqual(response.status_code, 200)
        mock_copy.assert_called_once_with("hello")
        self.assertEqual(sync_client.last_remote_id, remote_item["id"])
        self.assertEqual(sync_client.last_text, "hello")

        with patch.object(sync_client, 'safe_paste', return_value="hello"):
            self.assertIsNone(sync_client._get_local_text_to_push())

    def test_server_ignores_same_content_returned_by_another_client(self):
        tracker = TextTracker()
        tracker.update(build_text_item("hello", "client-a"))

        with (
            patch.object(flask_app, 'KEY', "secret"),
            patch.object(flask_app, 'tracker', tracker),
            patch.object(flask_app, 'copy_text_to_clipboard') as mock_copy,
            patch.object(flask_app, 'notify_clients') as mock_notify,
        ):
            response = flask_app.app.test_client().post(
                "/text_sync",
                json={
                    "key": "secret",
                    "content": "hello",
                    "source": "client-b",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ignored")
        mock_copy.assert_not_called()
        mock_notify.assert_not_called()

    def test_text_item_id_is_stable_for_retries(self):
        first = build_text_item(
            "hello",
            "client-a",
            timestamp="2026-08-23T10:00:00",
        )
        retry = build_text_item(
            "hello",
            "client-a",
            timestamp="2026-08-23T10:05:00",
        )

        self.assertEqual(first["id"], retry["id"])
        self.assertNotEqual(first["timestamp"], retry["timestamp"])


if __name__ == '__main__':
    unittest.main()
