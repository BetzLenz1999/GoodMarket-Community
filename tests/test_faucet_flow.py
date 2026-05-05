import unittest
from unittest.mock import patch

from flask import Flask

from routes import routes


class FakeWeb3:
    class HTTPProvider:
        def __init__(self, *_args, **_kwargs):
            pass

    def __init__(self, _provider):
        self.provider = _provider

    @staticmethod
    def to_checksum_address(addr):
        return addr


class FaucetFlowTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "test-secret"
        self.app.register_blueprint(routes)
        self.client = self.app.test_client()

    def _auth_session(self, wallet="0x1111111111111111111111111111111111111111"):
        with self.client.session_transaction() as sess:
            sess["verified"] = True
            sess["wallet"] = wallet

    @patch("routes.Web3", new=FakeWeb3)
    @patch("routes._execute_onchain_faucet_topup")
    def test_onchain_endpoint_success(self, mock_onchain):
        self._auth_session()
        mock_onchain.return_value = {
            "success": True,
            "status": "onchain_sent",
            "tx_hash": "0xabc",
        }
        resp = self.client.post(
            "/api/faucet/onchain",
            json={"wallet": "0x1111111111111111111111111111111111111111"},
        )
        body = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(body["success"])
        self.assertEqual(body["status"], "onchain_sent")
        self.assertEqual(body["tx_hash"], "0xabc")
        self.assertTrue(body["attempted_onchain"])

    @patch("routes.Web3", new=FakeWeb3)
    @patch("routes._execute_onchain_faucet_topup")
    def test_onchain_endpoint_not_configured(self, mock_onchain):
        self._auth_session()
        mock_onchain.return_value = {
            "success": False,
            "status": "onchain_failed",
            "reason": "not_configured",
            "error": "On-chain faucet not configured (missing TOPWALLET_KEY)",
        }
        resp = self.client.post(
            "/api/faucet/onchain",
            json={"wallet": "0x1111111111111111111111111111111111111111"},
        )
        body = resp.get_json()
        self.assertEqual(resp.status_code, 503)
        self.assertFalse(body["success"])
        self.assertEqual(body["reason"], "not_configured")

    @patch("routes.Web3", new=FakeWeb3)
    @patch("routes._has_recent_refill")
    @patch("routes._get_gas_status")
    def test_case1_enough_celo_no_topup(self, mock_get_gas, mock_recent):
        self._auth_session()
        mock_recent.return_value = (False, 0)
        mock_get_gas.return_value = {
            "balance_wei": "2000000000000000",
            "balance_celo": 0.002,
            "estimated_gas": 220000,
            "gas_price_wei": "1000000000",
            "required_gas_wei": "1000000000000000",
            "required_gas_celo": 0.001,
            "gas_ready": True,
        }

        resp = self.client.post("/api/faucet/gas", json={"wallet": "0x1111111111111111111111111111111111111111"})
        body = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(body["gas_ready"])
        self.assertFalse(body["attempted_api"])
        self.assertFalse(body["attempted_onchain"])
        self.assertEqual(body["terminal_status"], "gas_ready")

    @patch("routes.urllib.request.urlopen")
    @patch("routes.Web3", new=FakeWeb3)
    @patch("routes._poll_balance_increase")
    @patch("routes._has_recent_refill")
    @patch("routes._get_gas_status")
    def test_case2_zero_celo_api_success(self, mock_get_gas, mock_recent, mock_poll, mock_urlopen):
        self._auth_session()
        mock_recent.return_value = (False, 0)
        mock_get_gas.side_effect = [
            {
                "balance_wei": "0",
                "balance_celo": 0.0,
                "estimated_gas": 220000,
                "gas_price_wei": "1000000000",
                "required_gas_wei": "1000000000000000",
                "required_gas_celo": 0.001,
                "gas_ready": False,
            },
            {
                "balance_wei": "2000000000000000",
                "balance_celo": 0.002,
                "estimated_gas": 220000,
                "gas_price_wei": "1000000000",
                "required_gas_wei": "1000000000000000",
                "required_gas_celo": 0.001,
                "gas_ready": True,
            },
        ]
        mock_poll.return_value = (2000000000000000, True)

        class _Resp:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return b'{"ok":1,"txHash":"0xapi"}'
        mock_urlopen.return_value = _Resp()

        resp = self.client.post("/api/faucet/gas", json={"wallet": "0x1111111111111111111111111111111111111111"})
        body = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(body["topup_source"], "api")
        self.assertTrue(body["attempted_api"])
        self.assertFalse(body["attempted_onchain"])
        self.assertEqual(body["terminal_status"], "gas_ready")

    @patch("routes._execute_onchain_faucet_topup")
    @patch("routes.urllib.request.urlopen")
    @patch("routes.Web3", new=FakeWeb3)
    @patch("routes._get_gas_status")
    @patch("routes._has_recent_refill")
    def test_case3_api_fail_triggers_onchain_success(
        self, mock_recent, mock_get_gas, mock_urlopen, mock_onchain
    ):
        self._auth_session()
        mock_recent.return_value = (False, 0)
        mock_get_gas.side_effect = [
            {
                "balance_wei": "0", "balance_celo": 0.0, "estimated_gas": 220000, "gas_price_wei": "1000000000",
                "required_gas_wei": "1000000000000000", "required_gas_celo": 0.001, "gas_ready": False,
            },
            {
                "balance_wei": "2000000000000000", "balance_celo": 0.002, "estimated_gas": 220000, "gas_price_wei": "1000000000",
                "required_gas_wei": "1000000000000000", "required_gas_celo": 0.001, "gas_ready": True,
            },
        ]
        mock_urlopen.side_effect = Exception("api down")
        mock_onchain.return_value = {
            "success": True,
            "status": "onchain_sent",
            "tx_hash": "0xfallback",
        }

        resp = self.client.post("/api/faucet/gas", json={"wallet": "0x1111111111111111111111111111111111111111"})
        body = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(body["attempted_api"])
        self.assertTrue(body["attempted_onchain"])
        self.assertEqual(body["topup_source"], "onchain")
        self.assertTrue(body["gas_ready"])
        self.assertEqual(body["terminal_status"], "gas_ready")
        self.assertEqual(body["api_error"], "api down")
        self.assertEqual(body["diagnostics"]["fallback_reason"], "api_failed")
        self.assertEqual(body["onchain_result"]["tx_hash"], "0xfallback")

    @patch("routes.Web3", new=FakeWeb3)
    @patch("routes._has_recent_refill")
    @patch("routes._get_gas_status")
    def test_case4_recent_refill_branch(self, mock_get_gas, mock_recent):
        self._auth_session()
        mock_recent.return_value = (True, 42)
        mock_get_gas.return_value = {
            "balance_wei": "0", "balance_celo": 0.0, "estimated_gas": 220000, "gas_price_wei": "1000000000",
            "required_gas_wei": "1000000000000000", "required_gas_celo": 0.001, "gas_ready": False,
        }

        resp = self.client.post("/api/faucet/gas", json={"wallet": "0x1111111111111111111111111111111111111111"})
        body = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(body["terminal_status"], "recent_refill")
        self.assertFalse(body["attempted_api"])
        self.assertFalse(body["attempted_onchain"])

    @patch("routes._execute_onchain_faucet_topup")
    @patch("routes.Web3", new=FakeWeb3)
    @patch("routes._has_recent_refill")
    @patch("routes._get_gas_status")
    @patch("routes.urllib.request.urlopen")
    def test_case5_missing_games_key_returns_not_configured(
        self, mock_urlopen, mock_get_gas, mock_recent, mock_onchain
    ):
        self._auth_session()
        mock_recent.return_value = (False, 0)
        mock_get_gas.side_effect = [
            {
                "balance_wei": "0", "balance_celo": 0.0, "estimated_gas": 220000, "gas_price_wei": "1000000000",
                "required_gas_wei": "1000000000000000", "required_gas_celo": 0.001, "gas_ready": False,
            },
            {
                "balance_wei": "0", "balance_celo": 0.0, "estimated_gas": 220000, "gas_price_wei": "1000000000",
                "required_gas_wei": "1000000000000000", "required_gas_celo": 0.001, "gas_ready": False,
            },
        ]
        mock_urlopen.side_effect = Exception("api down")
        mock_onchain.return_value = {
            "success": False,
            "status": "onchain_failed",
            "reason": "not_configured",
            "error": "On-chain faucet not configured (missing TOPWALLET_KEY)",
        }

        resp = self.client.post("/api/faucet/gas", json={"wallet": "0x1111111111111111111111111111111111111111"})
        body = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(body["attempted_api"])
        self.assertTrue(body["attempted_onchain"])
        self.assertFalse(body["gas_ready"])
        self.assertEqual(body["terminal_status"], "not_configured")
        self.assertEqual(body["diagnostics"]["fallback_reason"], "api_failed")
        self.assertEqual(body["onchain_result"]["reason"], "not_configured")

    @patch("routes._execute_onchain_faucet_topup")
    @patch("routes.urllib.request.urlopen")
    @patch("routes.Web3", new=FakeWeb3)
    @patch("routes._has_recent_refill")
    @patch("routes._get_gas_status")
    def test_case6_force_onchain_skips_api_and_uses_onchain(
        self, mock_get_gas, mock_recent, mock_urlopen, mock_onchain
    ):
        self._auth_session()
        mock_recent.return_value = (False, 0)
        mock_get_gas.side_effect = [
            {
                "balance_wei": "0", "balance_celo": 0.0, "estimated_gas": 220000, "gas_price_wei": "1000000000",
                "required_gas_wei": "1000000000000000", "required_gas_celo": 0.001, "gas_ready": False,
            },
            {
                "balance_wei": "1500000000000000", "balance_celo": 0.0015, "estimated_gas": 220000, "gas_price_wei": "1000000000",
                "required_gas_wei": "1000000000000000", "required_gas_celo": 0.001, "gas_ready": True,
            },
        ]
        mock_onchain.return_value = {
            "success": True,
            "status": "onchain_sent",
            "tx_hash": "0xforce",
        }

        resp = self.client.post(
            "/api/faucet/gas",
            json={"wallet": "0x1111111111111111111111111111111111111111", "force_onchain": True},
        )
        body = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(body["attempted_api"])
        self.assertTrue(body["attempted_onchain"])
        self.assertEqual(body["topup_source"], "onchain")
        self.assertTrue(body["gas_ready"])
        self.assertTrue(body["debug"]["force_onchain"])
        self.assertEqual(body["onchain_attempts"], 1)
        self.assertEqual(mock_urlopen.call_count, 0)

    @patch("routes._poll_balance_increase")
    @patch("routes.urllib.request.urlopen")
    @patch("routes.Web3", new=FakeWeb3)
    @patch("routes._has_recent_refill")
    @patch("routes._get_gas_status")
    def test_case7_force_onchain_string_false_does_not_force(
        self, mock_get_gas, mock_recent, mock_urlopen, mock_poll
    ):
        mock_poll.return_value = (2000000000000000, True)
        self._auth_session()
        mock_recent.return_value = (False, 0)
        mock_get_gas.side_effect = [
            {
                "balance_wei": "0",
                "balance_celo": 0.0,
                "estimated_gas": 220000,
                "gas_price_wei": "1000000000",
                "required_gas_wei": "1000000000000000",
                "required_gas_celo": 0.001,
                "gas_ready": False,
            },
            {
                "balance_wei": "2000000000000000",
                "balance_celo": 0.002,
                "estimated_gas": 220000,
                "gas_price_wei": "1000000000",
                "required_gas_wei": "1000000000000000",
                "required_gas_celo": 0.001,
                "gas_ready": True,
            },
        ]

        class _Resp:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return b'{"ok":1,"txHash":"0xapi"}'
        mock_urlopen.return_value = _Resp()

        resp = self.client.post(
            "/api/faucet/gas",
            json={"wallet": "0x1111111111111111111111111111111111111111", "force_onchain": "false"},
        )
        body = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(body["attempted_api"])
        self.assertFalse(body["attempted_onchain"])
        self.assertEqual(body["topup_source"], "api")
        self.assertFalse(body["debug"]["force_onchain"])

    @patch("routes.Web3", new=FakeWeb3)
    @patch("routes._get_xdc_gas_status")
    def test_case8_xdc_faucet_returns_ready_without_topup(self, mock_get_xdc_gas):
        self._auth_session()
        mock_get_xdc_gas.return_value = {
            "balance_wei": "4000000000000000",
            "balance_xdc": 0.004,
            "estimated_gas": 220000,
            "gas_price_wei": "1000000000",
            "required_gas_wei": "3000000000000000",
            "required_gas_xdc": 0.003,
            "required_gas_celo": 0.003,
            "gas_ready": True,
        }

        resp = self.client.post("/api/xdc/faucet/gas", json={"wallet": "0x1111111111111111111111111111111111111111"})
        body = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(body["success"])
        self.assertTrue(body["gas_ready"])
        self.assertFalse(body["topped_up"])
        self.assertEqual(body["terminal_status"], "gas_ready")

    @patch("routes._execute_onchain_xdc_faucet_topup")
    @patch("routes.urllib.request.urlopen")
    @patch("routes.Web3", new=FakeWeb3)
    @patch("routes._poll_balance_increase")
    @patch("routes._has_recent_refill")
    @patch("routes._get_xdc_gas_status")
    def test_case9_xdc_faucet_api_success_then_gas_ready(
        self, mock_get_xdc_gas, mock_recent, mock_poll, mock_urlopen, _mock_onchain
    ):
        self._auth_session()
        mock_recent.return_value = (False, 0)
        mock_get_xdc_gas.side_effect = [
            {
                "balance_wei": "0",
                "balance_xdc": 0.0,
                "estimated_gas": 220000,
                "gas_price_wei": "1000000000",
                "required_gas_wei": "3000000000000000",
                "required_gas_xdc": 0.003,
                "required_gas_celo": 0.003,
                "gas_ready": False,
            },
            {
                "balance_wei": "4000000000000000",
                "balance_xdc": 0.004,
                "estimated_gas": 220000,
                "gas_price_wei": "1000000000",
                "required_gas_wei": "3000000000000000",
                "required_gas_xdc": 0.003,
                "required_gas_celo": 0.003,
                "gas_ready": True,
            },
        ]
        mock_poll.return_value = (4000000000000000, True)

        class _Resp:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return b'{"ok":1,"txHash":"0xapi-xdc"}'
        mock_urlopen.return_value = _Resp()

        resp = self.client.post("/api/xdc/faucet/gas", json={"wallet": "0x1111111111111111111111111111111111111111"})
        body = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(body["success"])
        self.assertTrue(body["gas_ready"])
        self.assertTrue(body["topped_up"])
        self.assertEqual(body["topup_source"], "api")

    @patch("routes.Web3", new=FakeWeb3)
    @patch("routes._has_recent_refill")
    @patch("routes._get_gas_status")
    def test_cooldown_enforced_even_with_force_onchain(self, mock_get_gas, mock_recent):
        """Test that cooldown is strictly enforced regardless of force_onchain flag."""
        self._auth_session()
        mock_recent.return_value = (True, 30)  # Recent refill with 30s cooldown
        mock_get_gas.return_value = {
            "balance_wei": "0", "balance_celo": 0.0, "estimated_gas": 220000, "gas_price_wei": "1000000000",
            "required_gas_wei": "1000000000000000", "required_gas_celo": 0.001, "gas_ready": False,
        }

        # Try with force_onchain=true - should STILL be blocked by cooldown
        resp = self.client.post(
            "/api/faucet/gas",
            json={"wallet": "0x1111111111111111111111111111111111111111", "force_onchain": True},
        )
        body = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(body["terminal_status"], "recent_refill")
        self.assertFalse(body["attempted_api"])
        self.assertFalse(body["attempted_onchain"])
        self.assertTrue(body["debug"]["force_onchain_blocked"])

    @patch("routes.Web3", new=FakeWeb3)
    @patch("routes._has_recent_refill")
    @patch("routes._get_gas_status")
    def test_force_onchain_rate_limit_exceeded(self, mock_get_gas, mock_recent):
        """Test that force_onchain calls are rate-limited to prevent spam."""
        self._auth_session()
        wallet = "0x1111111111111111111111111111111111111111"
        
        # Setup: no recent refill, gas needs top-up
        mock_recent.return_value = (False, 0)
        mock_get_gas.return_value = {
            "balance_wei": "0", "balance_celo": 0.0, "estimated_gas": 220000, "gas_price_wei": "1000000000",
            "required_gas_wei": "1000000000000000", "required_gas_celo": 0.001, "gas_ready": False,
        }

        # Make force_onchain requests up to the limit
        # Default limit is 2 per hour (FAUCET_FORCE_ONCHAIN_MAX_PER_HOUR=2)
        for i in range(2):
            with patch("routes._execute_onchain_faucet_topup") as mock_onchain:
                mock_onchain.return_value = {
                    "success": True,
                    "status": "onchain_sent",
                    "tx_hash": f"0xfaucet{i}",
                }
                resp = self.client.post(
                    "/api/faucet/gas",
                    json={"wallet": wallet, "force_onchain": True},
                )
                body = resp.get_json()
                self.assertEqual(resp.status_code, 200)
                self.assertTrue(body.get("attempted_onchain"))

        # Third force_onchain attempt should be rate-limited
        resp = self.client.post(
            "/api/faucet/gas",
            json={"wallet": wallet, "force_onchain": True},
        )
        body = resp.get_json()
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(body["status"], "force_onchain_rate_limited")
        self.assertIn("retry_after", body["reason"])


if __name__ == "__main__":
    unittest.main()
