import unittest
from unittest.mock import Mock

from steam_skin_ops.profit.clients.steam import SteamClient


class TestSteamLoginCheck(unittest.TestCase):
    def test_profile_redirect_means_logged_in(self):
        client = SteamClient("session", "secure")
        response = Mock()
        response.status_code = 302
        response.headers = {
            "Location": "https://steamcommunity.com/profiles/76561198000000001/"
        }
        client.session.get = Mock(return_value=response)

        self.assertTrue(client.check_login())
        client.session.get.assert_called_once_with(
            "https://steamcommunity.com/my/",
            timeout=10,
            allow_redirects=False,
        )

    def test_login_redirect_means_logged_out(self):
        client = SteamClient("session", "secure")
        response = Mock()
        response.status_code = 302
        response.headers = {
            "Location": "https://steamcommunity.com/login/home/?goto=%2Fmy%2F"
        }
        client.session.get = Mock(return_value=response)

        self.assertFalse(client.check_login())


if __name__ == "__main__":
    unittest.main()
