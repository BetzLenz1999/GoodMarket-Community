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
        # Reset module-level faucet rate-limit / cooldown state so tests
        # don't leak counters into each other (force_onchain attempts and
        # recent-refill timestamps are wallet-keyed in-memory dicts).
        import routes as _routes_mod
        with _routes_mod._faucet_lock:
            _routes_mod._force_onchain_attempts.clear()
            _routes_mod._faucet_recent_refill.clear()
            _routes_mod._faucet_api_pending.clear()
            _routes_mod._minipay_cusd_recent_refill.clear()

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
        self.assertIn("Retry after", body["reason"])
        self.assertIn("force_onchain_rate_limit_retry_after_seconds", body)

    @patch("routes.Web3", new=FakeWeb3)
    @patch("routes._has_recent_refill")
    @patch("routes._get_xdc_gas_status")
    def test_xdc_cooldown_enforced_even_with_force_onchain(self, mock_get_xdc_gas, mock_recent):
        """XDC parity: cooldown is strictly enforced regardless of force_onchain flag."""
        wallet = "0x2222222222222222222222222222222222222222"
        self._auth_session(wallet)
        mock_recent.return_value = (True, 30)  # Recent refill with 30s cooldown
        mock_get_xdc_gas.return_value = {
            "balance_wei": "0", "balance_xdc": 0.0, "estimated_gas": 220000, "gas_price_wei": "1000000000",
            "required_gas_wei": "3000000000000000", "required_gas_xdc": 0.003,
            "required_gas_celo": 0.003, "gas_ready": False,
        }

        # Try with force_onchain=true - should STILL be blocked by cooldown
        resp = self.client.post(
            "/api/xdc/faucet/gas",
            json={"wallet": wallet, "force_onchain": True},
        )
        body = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(body["terminal_status"], "recent_refill")
        self.assertFalse(body["topped_up"])
        self.assertFalse(body["gas_ready"])
        self.assertTrue(body["debug"]["force_onchain_blocked"])
        self.assertEqual(body["debug"]["cooldown_reason"], "recent_refill")

    @patch("routes.Web3", new=FakeWeb3)
    @patch("routes._has_recent_refill")
    @patch("routes._get_xdc_gas_status")
    def test_xdc_force_onchain_rate_limit_exceeded(self, mock_get_xdc_gas, mock_recent):
        """XDC parity: force_onchain calls are rate-limited to prevent TOPWALLET_KEY drain."""
        wallet = "0x3333333333333333333333333333333333333333"
        self._auth_session(wallet)
        mock_recent.return_value = (False, 0)
        mock_get_xdc_gas.return_value = {
            "balance_wei": "0", "balance_xdc": 0.0, "estimated_gas": 220000, "gas_price_wei": "1000000000",
            "required_gas_wei": "3000000000000000", "required_gas_xdc": 0.003,
            "required_gas_celo": 0.003, "gas_ready": False,
        }

        # Make force_onchain requests up to the limit (default 2/hour).
        for i in range(2):
            with patch("routes._execute_onchain_xdc_faucet_topup") as mock_onchain:
                mock_onchain.return_value = {
                    "success": True,
                    "status": "onchain_sent",
                    "tx_hash": f"0xxdcfaucet{i}",
                }
                resp = self.client.post(
                    "/api/xdc/faucet/gas",
                    json={"wallet": wallet, "force_onchain": True},
                )
                self.assertEqual(resp.status_code, 200)

        # Third force_onchain attempt should be rate-limited
        resp = self.client.post(
            "/api/xdc/faucet/gas",
            json={"wallet": wallet, "force_onchain": True},
        )
        body = resp.get_json()
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(body["status"], "force_onchain_rate_limited")
        self.assertIn("Retry after", body["reason"])
        self.assertIn("force_onchain_rate_limit_retry_after_seconds", body)
        self.assertEqual(body["force_onchain_max_per_hour"], 2)

    @patch("routes.Web3", new=FakeWeb3)
    @patch("routes._execute_minipay_cusd_faucet_transfer")
    @patch("routes._get_minipay_stablecoin_balances")
    def test_minipay_stablecoin_faucet_sends_cusd_when_below_threshold(
        self, mock_balances, mock_transfer
    ):
        self._auth_session()
        mock_balances.side_effect = [
            {
                "balances": {"cusd": {"balance": 0.0}, "usdt": {"balance": 0.0}, "usdc": {"balance": 0.0}},
                "total_usd": 0.0,
                "total_usd_exact": "0",
                "stable_ready": False,
                "required_usd": 0.05,
            },
            {
                "balances": {"cusd": {"balance": 0.05}, "usdt": {"balance": 0.0}, "usdc": {"balance": 0.0}},
                "total_usd": 0.05,
                "total_usd_exact": "0.05",
                "stable_ready": True,
                "required_usd": 0.05,
            },
        ]
        import routes as _routes_mod
        mock_transfer.return_value = {
            "success": True,
            "status": "cusd_sent",
            "tx_hash": "0xcusd",
            "amount_cusd": float(_routes_mod.MINIPAY_CUSD_FAUCET_AMOUNT),
        }

        resp = self.client.post(
            "/api/minipay/stablecoin-faucet",
            json={"wallet": "0x1111111111111111111111111111111111111111"},
        )
        body = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(body["success"])
        self.assertEqual(body["status"], "cusd_sent")
        self.assertEqual(body["topup_source"], "topwallet_key_cusd")
        self.assertEqual(body["tx_hash"], "0xcusd")
        mock_transfer.assert_called_once()
        self.assertEqual(mock_transfer.call_args.args[2], _routes_mod.MINIPAY_CUSD_FAUCET_AMOUNT)
        self.assertEqual(body["faucet_amount_cusd"], float(_routes_mod.MINIPAY_CUSD_FAUCET_AMOUNT))

    @patch("routes.Web3", new=FakeWeb3)
    @patch("routes._execute_minipay_cusd_faucet_transfer")
    @patch("routes._get_minipay_stablecoin_balances")
    def test_minipay_stablecoin_faucet_skips_when_stable_ready(
        self, mock_balances, mock_transfer
    ):
        self._auth_session()
        mock_balances.return_value = {
            "balances": {"cusd": {"balance": 0.07}, "usdt": {"balance": 0.0}, "usdc": {"balance": 0.0}},
            "total_usd": 0.07,
            "total_usd_exact": "0.07",
            "stable_ready": True,
            "required_usd": 0.05,
        }

        resp = self.client.post(
            "/api/minipay/stablecoin-faucet",
            json={"wallet": "0x1111111111111111111111111111111111111111"},
        )
        body = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(body["success"])
        self.assertEqual(body["status"], "stable_ready")
        self.assertFalse(body["topped_up"])
        mock_transfer.assert_not_called()

    @patch("routes.Web3", new=FakeWeb3)
    @patch("routes._execute_minipay_cusd_faucet_transfer")
    @patch("routes._get_minipay_stablecoin_balances")
    def test_minipay_stablecoin_faucet_respects_cooldown(
        self, mock_balances, mock_transfer
    ):
        self._auth_session()
        wallet = "0x1111111111111111111111111111111111111111"
        mock_balances.return_value = {
            "balances": {"cusd": {"balance": 0.0}, "usdt": {"balance": 0.0}, "usdc": {"balance": 0.0}},
            "total_usd": 0.0,
            "total_usd_exact": "0",
            "stable_ready": False,
            "required_usd": 0.05,
        }
        import routes as _routes_mod
        _routes_mod._record_minipay_cusd_refill(wallet, "0xold", _routes_mod.MINIPAY_CUSD_FAUCET_AMOUNT)

        resp = self.client.post(
            "/api/minipay/stablecoin-faucet",
            json={"wallet": wallet},
        )
        body = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(body["success"])
        self.assertEqual(body["status"], "recent_refill")
        self.assertFalse(body["topped_up"])
        self.assertIn("recent_refill_cooldown_seconds", body)
        mock_transfer.assert_not_called()

    @patch("routes.Web3", new=FakeWeb3)
    @patch("routes._execute_minipay_cusd_faucet_transfer")
    @patch("routes._get_minipay_stablecoin_balances")
    def test_minipay_stablecoin_faucet_blocks_when_pending(
        self, mock_balances, mock_transfer
    ):
        self._auth_session()
        wallet = "0x1111111111111111111111111111111111111111"
        mock_balances.return_value = {
            "balances": {"cusd": {"balance": 0.0}, "usdt": {"balance": 0.0}, "usdc": {"balance": 0.0}},
            "total_usd": 0.0,
            "total_usd_exact": "0",
            "stable_ready": False,
            "required_usd": 0.05,
        }
        import routes as _routes_mod
        _routes_mod._set_minipay_cusd_pending(wallet)
        try:
            resp = self.client.post(
                "/api/minipay/stablecoin-faucet",
                json={"wallet": wallet},
            )
        finally:
            _routes_mod._clear_minipay_cusd_pending(wallet)
        body = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(body["success"])
        self.assertEqual(body["status"], "pending_refill")
        self.assertFalse(body["topped_up"])
        self.assertIn("pending_refill_seconds", body)
        mock_transfer.assert_not_called()

    @patch("routes.Web3", new=FakeWeb3)
    @patch("routes._execute_minipay_cusd_faucet_transfer")
    @patch("routes._get_minipay_cusd_refill_from_db")
    @patch("routes._get_minipay_stablecoin_balances")
    def test_minipay_stablecoin_faucet_respects_persisted_cooldown_after_balance_spent(
        self, mock_balances, mock_db_refill, mock_transfer
    ):
        self._auth_session()
        wallet = "0x1111111111111111111111111111111111111111"
        mock_balances.return_value = {
            "balances": {"cusd": {"balance": 0.0}, "usdt": {"balance": 0.0}, "usdc": {"balance": 0.0}},
            "total_usd": 0.0,
            "total_usd_exact": "0",
            "stable_ready": False,
            "required_usd": 0.05,
        }
        import routes as _routes_mod
        refill_at = _routes_mod.datetime.now(_routes_mod.timezone.utc)
        mock_db_refill.return_value = {
            "timestamp": refill_at.timestamp(),
            "last_refill_at": refill_at.isoformat(),
            "tx_hash": "0xdbold",
            "amount_cusd": str(_routes_mod.MINIPAY_CUSD_FAUCET_AMOUNT),
            "source": "database",
        }

        resp = self.client.post(
            "/api/minipay/stablecoin-faucet",
            json={"wallet": wallet},
        )
        body = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(body["success"])
        self.assertEqual(body["status"], "recent_refill")
        self.assertFalse(body["topped_up"])
        self.assertEqual(body["recent_refill"]["source"], "database")
        mock_transfer.assert_not_called()

    @patch("routes.Web3", new=FakeWeb3)
    @patch("routes._execute_minipay_cusd_faucet_transfer")
    @patch("routes._get_minipay_stablecoin_balances")
    def test_minipay_stablecoin_faucet_surfaces_signer_insufficient_cusd(
        self, mock_balances, mock_transfer
    ):
        self._auth_session()
        mock_balances.return_value = {
            "balances": {"cusd": {"balance": 0.0}, "usdt": {"balance": 0.0}, "usdc": {"balance": 0.0}},
            "total_usd": 0.0,
            "total_usd_exact": "0",
            "stable_ready": False,
            "required_usd": 0.05,
        }
        mock_transfer.return_value = {
            "success": False,
            "status": "cusd_faucet_failed",
            "reason": "signer_insufficient_cusd",
            "error": "MiniPay cUSD faucet signer has insufficient cUSD",
        }

        resp = self.client.post(
            "/api/minipay/stablecoin-faucet",
            json={"wallet": "0x1111111111111111111111111111111111111111"},
        )
        body = resp.get_json()
        self.assertEqual(resp.status_code, 502)
        self.assertFalse(body["success"])
        self.assertEqual(body["status"], "cusd_faucet_failed")
        self.assertEqual(body["reason"], "signer_insufficient_cusd")

    # ── GoodDollar 48h cooldown (drainage protection) ──────────────────
    # The cooldown is checked BEFORE the in-memory `_has_recent_refill`
    # cooldown, blocks both API and force_onchain paths, and surfaces a
    # 429 response so the frontend banner can explain the situation.
    @patch("routes.Web3", new=FakeWeb3)
    @patch("routes._has_recent_gooddollar_celo_refill")
    @patch("routes._has_recent_refill")
    @patch("routes._get_gas_status")
    def test_gooddollar_48h_cooldown_blocks_api_path(
        self, mock_get_gas, mock_recent, mock_gd_recent
    ):
        self._auth_session()
        mock_recent.return_value = (False, 0)
        mock_gd_recent.return_value = (
            True,
            3600,
            {
                "timestamp": 1700000000.0,
                "last_refill_at": "2024-01-01T00:00:00+00:00",
                "tx_hash": "0xprev",
                "source": "api",
            },
        )
        mock_get_gas.return_value = {
            "balance_wei": "0", "balance_celo": 0.0, "estimated_gas": 220000, "gas_price_wei": "1000000000",
            "required_gas_wei": "1000000000000000", "required_gas_celo": 0.001, "gas_ready": False,
        }

        resp = self.client.post(
            "/api/faucet/gas",
            json={"wallet": "0x1111111111111111111111111111111111111111"},
        )
        body = resp.get_json()
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(body["terminal_status"], "gooddollar_cooldown")
        self.assertEqual(body["status"], "gooddollar_cooldown")
        self.assertFalse(body["attempted_api"])
        self.assertFalse(body["attempted_onchain"])
        self.assertEqual(body["gooddollar_cooldown_remaining_seconds"], 3600)
        self.assertIn("gas_coverage_message", body)
        self.assertIn("3 days", body["gas_coverage_message"])

    @patch("routes.Web3", new=FakeWeb3)
    @patch("routes._has_recent_gooddollar_celo_refill")
    @patch("routes._has_recent_refill")
    @patch("routes._get_gas_status")
    def test_gooddollar_48h_cooldown_blocks_force_onchain_path(
        self, mock_get_gas, mock_recent, mock_gd_recent
    ):
        self._auth_session()
        mock_recent.return_value = (False, 0)
        mock_gd_recent.return_value = (
            True,
            7200,
            {
                "timestamp": 1700000000.0,
                "last_refill_at": "2024-01-01T00:00:00+00:00",
                "tx_hash": "0xprev",
                "source": "onchain",
            },
        )
        mock_get_gas.return_value = {
            "balance_wei": "0", "balance_celo": 0.0, "estimated_gas": 220000, "gas_price_wei": "1000000000",
            "required_gas_wei": "1000000000000000", "required_gas_celo": 0.001, "gas_ready": False,
        }

        resp = self.client.post(
            "/api/faucet/gas",
            json={"wallet": "0x1111111111111111111111111111111111111111", "force_onchain": True},
        )
        body = resp.get_json()
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(body["terminal_status"], "gooddollar_cooldown")
        self.assertFalse(body["attempted_api"])
        self.assertFalse(body["attempted_onchain"])
        self.assertTrue(body["debug"]["force_onchain_blocked"])

    @patch("routes.Web3", new=FakeWeb3)
    @patch("routes._has_recent_gooddollar_celo_refill")
    def test_gooddollar_48h_cooldown_blocks_direct_onchain_endpoint(
        self, mock_gd_recent
    ):
        self._auth_session()
        mock_gd_recent.return_value = (
            True,
            5400,
            {
                "timestamp": 1700000000.0,
                "last_refill_at": "2024-01-01T00:00:00+00:00",
                "tx_hash": "0xprev",
                "source": "api",
            },
        )

        resp = self.client.post(
            "/api/faucet/onchain",
            json={"wallet": "0x1111111111111111111111111111111111111111"},
        )
        body = resp.get_json()
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(body["status"], "gooddollar_cooldown")
        self.assertFalse(body["attempted_onchain"])
        self.assertIn("gas_coverage_message", body)


    # ── Helpers below: the WalletConnect-faucet-UX patch ──────────────────
    # When a GoodWallet user connects via WalletConnect URI/QR they often
    # share a wallet address that the GoodDollar Faucet contract has
    # already topped up within its 48h window. We added a `canTop(address)`
    # preflight + revert-reason decoding so the on-chain fallback surfaces
    # the contract cooldown cleanly instead of producing the misleading
    # "Gas top-up did not arrive in time" error after burning gas on a tx
    # that just reverts.
    @patch("routes.Web3", new=FakeWeb3)
    @patch("routes._has_recent_gooddollar_celo_refill")
    @patch("routes._has_recent_refill")
    @patch("routes._get_gas_status")
    @patch("routes.urllib.request.urlopen")
    @patch("routes._execute_onchain_faucet_topup")
    def test_walletconnect_onchain_cooldown_returns_gooddollar_cooldown(
        self,
        mock_onchain,
        mock_urlopen,
        mock_get_gas,
        mock_recent,
        mock_gd_recent,
    ):
        """Server surfaces gooddollar_cooldown when on-chain fallback reports it."""
        self._auth_session()
        mock_recent.return_value = (False, 0)
        # No prior DB-tracked GoodDollar refill yet — the preflight only
        # discovers the cooldown inside the on-chain helper via canTop().
        mock_gd_recent.return_value = (False, 0, None)
        mock_get_gas.return_value = {
            "balance_wei": "0", "balance_celo": 0.0, "estimated_gas": 220000,
            "gas_price_wei": "1000000000",
            "required_gas_wei": "1000000000000000", "required_gas_celo": 0.001,
            "gas_ready": False,
        }
        mock_urlopen.side_effect = Exception("api down")
        # On-chain helper detects the contract cooldown (either via canTop=False
        # or a decoded revert reason) and returns the new gooddollar_cooldown
        # reason instead of the generic onchain_failed.
        mock_onchain.return_value = {
            "success": False,
            "status": "gooddollar_cooldown",
            "reason": "gooddollar_cooldown",
            "error": "GoodDollar faucet declined this wallet — 48h cooldown.",
            "can_top": False,
            "attempted_tx": False,
        }

        resp = self.client.post(
            "/api/faucet/gas",
            json={"wallet": "0x1111111111111111111111111111111111111111"},
        )
        body = resp.get_json()
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(body["status"], "gooddollar_cooldown")
        self.assertFalse(body["success"])
        self.assertFalse(body.get("topped_up", True))
        self.assertFalse(body.get("wallet_action_required", True))
        self.assertIn("GoodDollar", body["reason"])
        # Only one on-chain attempt should be made — retrying does not help.
        self.assertEqual(mock_onchain.call_count, 1)

    def test_can_top_preflight_handles_false_and_unknown(self):
        """`_check_gooddollar_faucet_can_top` returns False, True, or None."""
        import routes as _routes_mod

        class _Eth:
            def __init__(self, result):
                self._result = result

            def call(self, _tx):
                if isinstance(self._result, Exception):
                    raise self._result
                return self._result

        class _W3:
            def __init__(self, result):
                self.eth = _Eth(result)

        # False — 32 zero bytes.
        can, err = _routes_mod._check_gooddollar_faucet_can_top(
            _W3(b"\x00" * 32),
            "0x4F93Fa058b03953C851eFaA2e4FC5C34afDFAb84",
            "0x1111111111111111111111111111111111111111",
        )
        self.assertEqual(can, False)
        self.assertIsNone(err)

        # True — non-zero byte present.
        can, err = _routes_mod._check_gooddollar_faucet_can_top(
            _W3(b"\x00" * 31 + b"\x01"),
            "0x4F93Fa058b03953C851eFaA2e4FC5C34afDFAb84",
            "0x1111111111111111111111111111111111111111",
        )
        self.assertEqual(can, True)
        self.assertIsNone(err)

        # Unknown — exception during eth_call (e.g. RPC blip / missing fn).
        can, err = _routes_mod._check_gooddollar_faucet_can_top(
            _W3(RuntimeError("boom")),
            "0x4F93Fa058b03953C851eFaA2e4FC5C34afDFAb84",
            "0x1111111111111111111111111111111111111111",
        )
        self.assertIsNone(can)
        self.assertIn("boom", err)

    def test_faucet_cooldown_error_heuristic(self):
        """Revert-reason strings from the GoodDollar Faucet contract are matched."""
        import routes as _routes_mod
        self.assertTrue(_routes_mod._looks_like_faucet_cooldown_error(
            "execution reverted: Cooldown"))
        self.assertTrue(_routes_mod._looks_like_faucet_cooldown_error(
            "Wallet already topped within the cooldown period"))
        self.assertTrue(_routes_mod._looks_like_faucet_cooldown_error(
            "VM Exception: too soon to top wallet"))
        self.assertFalse(_routes_mod._looks_like_faucet_cooldown_error(
            "execution reverted: insufficient balance"))
        self.assertFalse(_routes_mod._looks_like_faucet_cooldown_error(""))
        self.assertFalse(_routes_mod._looks_like_faucet_cooldown_error(None))

    def test_faucet_success_response_includes_wallet_action_required_flag(self):
        """Faucet responses tell the frontend no wallet signature is required."""
        self._auth_session()
        with patch("routes.Web3", new=FakeWeb3), \
             patch("routes._has_recent_refill", return_value=(False, 0)), \
             patch("routes._get_gas_status", return_value={
                 "balance_wei": "2000000000000000",
                 "balance_celo": 0.002,
                 "estimated_gas": 220000,
                 "gas_price_wei": "1000000000",
                 "required_gas_wei": "1000000000000000",
                 "required_gas_celo": 0.001,
                 "gas_ready": True,
             }):
            resp = self.client.post(
                "/api/faucet/gas",
                json={"wallet": "0x1111111111111111111111111111111111111111"},
            )
        body = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        # The frontend uses this flag to render "no wallet approval needed"
        # copy specifically for WalletConnect users.
        self.assertIn("wallet_action_required", body)
        self.assertFalse(body["wallet_action_required"])


if __name__ == "__main__":
    unittest.main()
