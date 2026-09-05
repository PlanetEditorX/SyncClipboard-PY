import unittest
from unittest.mock import patch
from server.api.flask_app import app, KEY, clients

class TestSSRFPrevention(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def tearDown(self):
        clients.clear()

    @patch('server.api.flask_app.get_api_key')
    def test_ssrf_untrusted_url(self, mock_get_api_key):
        mock_get_api_key.return_value = KEY

        # Test with an untrusted IP
        response = self.app.put('/upload_file_to_download?redirect=http://evil.com/upload?filename=test.txt')
        self.assertEqual(response.status_code, 403)
        self.assertIn('不信任的重定向地址', response.get_json()['message'])

    @patch('server.api.flask_app.secure_save_path')
    @patch('server.api.flask_app.get_api_key')
    def test_ssrf_trusted_localhost(self, mock_get_api_key, mock_secure_save_path):
        mock_get_api_key.return_value = KEY
        mock_secure_save_path.return_value = None # to prevent writing file, return 400

        # Test with localhost (trusted)
        response = self.app.put(
            '/upload_file_to_download?redirect=http://127.0.0.1:8080/upload?filename=test.txt',
            data=b"test data"
        )
        self.assertNotEqual(response.status_code, 403)

    @patch('server.api.flask_app.secure_save_path')
    @patch('server.api.flask_app.get_api_key')
    def test_ssrf_trusted_client(self, mock_get_api_key, mock_secure_save_path):
        mock_get_api_key.return_value = KEY
        mock_secure_save_path.return_value = None

        # Add a mock client to the clients list
        clients.append({"ip": "192.168.1.100"})

        # Test with registered client IP (trusted)
        response = self.app.put(
            '/upload_file_to_download?redirect=http://192.168.1.100:8080/upload?filename=test.txt',
            data=b"test data"
        )
        # Should not be rejected due to SSRF
        self.assertNotEqual(response.status_code, 403)

    @patch('server.api.flask_app.get_api_key')
    def test_ssrf_invalid_url(self, mock_get_api_key):
        mock_get_api_key.return_value = KEY

        # Test with an invalid URL without hostname
        response = self.app.put('/upload_file_to_download?redirect=invalid-url')
        self.assertEqual(response.status_code, 400)
        self.assertIn('无效的 redirect_url', response.get_json()['message'])

if __name__ == '__main__':
    unittest.main()
