from pathlib import Path
import unittest
import tempfile
import json
import os
from unittest.mock import patch
from server.core.file_latest import FileLatestTracker

class TestFileLatestTracker(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_file = Path(self.temp_dir.name) / "file_latest.json"

        # We need to mock the FILE_LATEST_FILE constant in server.core.file_latest
        self.patcher = patch('server.core.file_latest.FILE_LATEST_FILE', self.temp_file)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.temp_dir.cleanup()

    def test_load_legacy_dict_format(self):
        # Create a legacy format json file
        old_data = {
            "file_id": "test_id_123",
            "path": "/some/path/file.txt",
            "name": "file.txt",
            "size": 1024,
            "source": "remote",
            "ip": "192.168.1.100"
            # port and updated_at are missing
        }
        with open(self.temp_file, "w", encoding="utf-8") as f:
            json.dump(old_data, f)

        tracker = FileLatestTracker()

        self.assertEqual(len(tracker.data), 1)
        item = tracker.data[0]

        self.assertEqual(item["file_id"], "test_id_123")
        self.assertEqual(item["path"], "/some/path/file.txt")
        self.assertEqual(item["name"], "file.txt")
        self.assertEqual(item["size"], 1024)
        self.assertEqual(item["source"], "remote")
        self.assertEqual(item["ip"], "192.168.1.100")
        self.assertIsNone(item["port"])
        self.assertIsNotNone(item["updated_at"])

    def test_load_legacy_dict_format_missing_file_id(self):
        old_data = {
            "path": "/some/path/file.txt",
            "name": "file.txt"
        }
        with open(self.temp_file, "w", encoding="utf-8") as f:
            json.dump(old_data, f)

        tracker = FileLatestTracker()
        self.assertEqual(tracker.data, [])

    def test_load_non_existent(self):
        tracker = FileLatestTracker()
        self.assertEqual(tracker.data, [])

    @patch('time.time', return_value=1234567890.0)
    def test_load_list_format(self, mock_time):
        list_data = [
            {
                "file_id": "test_id_1",
                "path": "/path/1.txt",
                "name": "1.txt",
                "size": 100,
                "source": "remote",
                "ip": "1.2.3.4",
                "port": 8080,
                "updated_at": 1000000000.0
            },
            {
                "file_id": "test_id_2"
            }
        ]
        with open(self.temp_file, "w", encoding="utf-8") as f:
            json.dump(list_data, f)

        tracker = FileLatestTracker()
        self.assertEqual(len(tracker.data), 2)

        item1 = tracker.data[0]
        self.assertEqual(item1["file_id"], "test_id_1")
        self.assertEqual(item1["path"], "/path/1.txt")
        self.assertEqual(item1["name"], "1.txt")
        self.assertEqual(item1["size"], 100)
        self.assertEqual(item1["source"], "remote")
        self.assertEqual(item1["ip"], "1.2.3.4")
        self.assertEqual(item1["port"], 8080)
        self.assertEqual(item1["updated_at"], 1000000000.0)

        item2 = tracker.data[1]
        self.assertEqual(item2["file_id"], "test_id_2")
        self.assertIsNone(item2["path"])
        self.assertIsNone(item2["name"])
        self.assertEqual(item2["size"], 0)
        self.assertIsNone(item2["source"])
        self.assertIsNone(item2["ip"])
        self.assertIsNone(item2["port"])
        self.assertEqual(item2["updated_at"], 1234567890.0)

    @patch('time.time', return_value=1234567890.0)
    def test_upsert_file_insert(self, mock_time):
        tracker = FileLatestTracker()
        tracker.upsert_file("id1", "/p/1.txt", "1.txt", 10, "local", "1.1.1.1", 1234)

        self.assertEqual(len(tracker.data), 1)
        item = tracker.data[0]
        self.assertEqual(item["file_id"], "id1")
        self.assertEqual(item["path"], "/p/1.txt")
        self.assertEqual(item["name"], "1.txt")
        self.assertEqual(item["size"], 10)
        self.assertEqual(item["source"], "local")
        self.assertEqual(item["ip"], "1.1.1.1")
        self.assertEqual(item["port"], 1234)
        self.assertEqual(item["updated_at"], 1234567890.0)

        # Check saved to disk
        with open(self.temp_file, "r", encoding="utf-8") as f:
            disk_data = json.load(f)
            self.assertEqual(len(disk_data), 1)
            self.assertEqual(disk_data[0]["file_id"], "id1")

    @patch('time.time', return_value=1234567890.0)
    def test_upsert_file_update(self, mock_time):
        tracker = FileLatestTracker()
        tracker.upsert_file("id1", "/p/1.txt", "1.txt", 10, "local", "1.1.1.1", 1234)

        mock_time.return_value = 1234567891.0
        tracker.upsert_file("id1", "/p/2.txt", "2.txt", 20, "remote", "2.2.2.2", 4321)

        self.assertEqual(len(tracker.data), 1)
        item = tracker.data[0]
        self.assertEqual(item["file_id"], "id1")
        self.assertEqual(item["path"], "/p/2.txt")
        self.assertEqual(item["name"], "2.txt")
        self.assertEqual(item["size"], 20)
        self.assertEqual(item["source"], "remote")
        self.assertEqual(item["ip"], "2.2.2.2")
        self.assertEqual(item["port"], 4321)
        self.assertEqual(item["updated_at"], 1234567891.0)

    def test_upsert_file_empty_id(self):
        tracker = FileLatestTracker()
        with self.assertRaises(ValueError):
            tracker.upsert_file("", "/p/1.txt", "1.txt", 10, "local", "1.1.1.1", 1234)

    def test_get_all_files(self):
        tracker = FileLatestTracker()
        tracker.upsert_file("id1", "/p/1.txt", "1.txt", 10, "local", "1.1.1.1", 1234)
        tracker.upsert_file("id2", "/p/2.txt", "2.txt", 20, "local", "1.1.1.1", 1234)

        files = tracker.get_all_files()
        self.assertEqual(len(files), 2)
        # Modifying returned copy should not affect tracker
        files.clear()
        self.assertEqual(len(tracker.data), 2)

    def test_get_file_by_id(self):
        tracker = FileLatestTracker()
        tracker.upsert_file("id1", "/p/1.txt", "1.txt", 10, "local", "1.1.1.1", 1234)

        item = tracker.get_file_by_id("id1")
        self.assertIsNotNone(item)
        self.assertEqual(item["file_id"], "id1")

        # Modify copy should not affect tracker
        item["file_id"] = "modified"
        self.assertEqual(tracker.data[0]["file_id"], "id1")

        self.assertIsNone(tracker.get_file_by_id("missing"))

    def test_get_latest(self):
        tracker = FileLatestTracker()
        self.assertIsNone(tracker.get_latest())

        with patch('time.time', return_value=100.0):
            tracker.upsert_file("id1", "/p/1.txt", "1.txt", 10, "local", "1.1.1.1", 1234)

        with patch('time.time', return_value=300.0):
            tracker.upsert_file("id3", "/p/3.txt", "3.txt", 30, "local", "1.1.1.1", 1234)

        with patch('time.time', return_value=200.0):
            tracker.upsert_file("id2", "/p/2.txt", "2.txt", 20, "local", "1.1.1.1", 1234)

        latest = tracker.get_latest()
        self.assertEqual(latest["file_id"], "id3")

        # Modify copy should not affect tracker
        latest["file_id"] = "modified"
        self.assertEqual(tracker.data[1]["file_id"], "id3")

    def test_remove_file(self):
        tracker = FileLatestTracker()
        tracker.upsert_file("id1", "/p/1.txt", "1.txt", 10, "local", "1.1.1.1", 1234)
        tracker.upsert_file("id2", "/p/2.txt", "2.txt", 20, "local", "1.1.1.1", 1234)

        # Remove missing
        self.assertFalse(tracker.remove_file("missing"))
        self.assertEqual(len(tracker.data), 2)

        # Remove existing
        self.assertTrue(tracker.remove_file("id1"))
        self.assertEqual(len(tracker.data), 1)
        self.assertEqual(tracker.data[0]["file_id"], "id2")

        # Check saved
        with open(self.temp_file, "r", encoding="utf-8") as f:
            disk_data = json.load(f)
            self.assertEqual(len(disk_data), 1)

    def test_clear(self):
        tracker = FileLatestTracker()
        tracker.upsert_file("id1", "/p/1.txt", "1.txt", 10, "local", "1.1.1.1", 1234)
        tracker.clear()

        self.assertEqual(len(tracker.data), 0)

        with open(self.temp_file, "r", encoding="utf-8") as f:
            disk_data = json.load(f)
            self.assertEqual(len(disk_data), 0)

    @patch('os.path.isfile')
    def test_is_remote_file(self, mock_isfile):
        tracker = FileLatestTracker()
        self.assertFalse(tracker.is_remote_file())

        # Test 1: path exists locally -> local file
        mock_isfile.return_value = True
        tracker.upsert_file("id1", "/path/exists.txt", "exists.txt", 10, "local", "1.1.1.1", 1234)
        self.assertFalse(tracker.is_remote_file("id1"))
        self.assertFalse(tracker.is_remote_file()) # tests get_latest

        # Test 2: path does not exist locally -> remote file
        mock_isfile.return_value = False
        tracker.upsert_file("id2", "/path/missing.txt", "missing.txt", 10, "remote", "1.1.1.1", 1234)
        self.assertTrue(tracker.is_remote_file("id2"))
        self.assertTrue(tracker.is_remote_file()) # id2 is now latest

        # Test 3: no path -> remote file
        tracker.upsert_file("id3", None, "no_path.txt", 10, "remote", "1.1.1.1", 1234)
        self.assertTrue(tracker.is_remote_file("id3"))

if __name__ == '__main__':
    unittest.main()
