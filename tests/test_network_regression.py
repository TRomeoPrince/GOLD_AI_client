"""Regression checks for interrupted AZT requests; no network or broker is contacted."""
import unittest
from unittest.mock import patch
import httpx
from client.api import GoldAIServer, ServerUnavailable
from client.models import ClientProfile

class NetworkRegressionTests(unittest.TestCase):
    def setUp(self):
        self.api = GoldAIServer(ClientProfile(server_url="https://example.invalid"))

    def test_closed_without_response_is_recoverable(self):
        with patch("client.api.httpx.request", side_effect=httpx.RemoteProtocolError("Server disconnected without sending a response.")):
            with self.assertRaises(ServerUnavailable):
                self.api.request("GET", "/v1/azt/overview")

    def test_timeout_is_recoverable(self):
        with patch("client.api.httpx.request", side_effect=httpx.ReadTimeout("timeout")):
            with self.assertRaises(ServerUnavailable):
                self.api.request("GET", "/v1/azt/overview")

    def test_server_500_is_recoverable(self):
        response = httpx.Response(502, request=httpx.Request("GET", "https://example.invalid/v1/azt/overview"))
        with patch("client.api.httpx.request", return_value=response):
            with self.assertRaises(ServerUnavailable):
                self.api.request("GET", "/v1/azt/overview")

if __name__ == "__main__":
    unittest.main()
