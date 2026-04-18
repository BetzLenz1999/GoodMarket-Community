import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def _install_import_stubs():
    """Install lightweight module stubs so routes.py can be imported in CI-lite envs."""
    if "flask" not in sys.modules:
        flask = types.ModuleType("flask")

        class _Blueprint:
            def __init__(self, *args, **kwargs):
                pass

            def route(self, *args, **kwargs):
                def _decorator(func):
                    return func
                return _decorator

        flask.Blueprint = _Blueprint
        flask.render_template = lambda *args, **kwargs: None
        flask.request = types.SimpleNamespace(get_json=lambda: {}, args={})
        flask.jsonify = lambda *args, **kwargs: {}
        flask.session = {}
        flask.redirect = lambda *args, **kwargs: None
        flask.url_for = lambda *args, **kwargs: ""
        flask.make_response = lambda *args, **kwargs: None
        sys.modules["flask"] = flask

    if "analytics_service" not in sys.modules:
        analytics_service = types.ModuleType("analytics_service")
        analytics_service.analytics = types.SimpleNamespace(
            track_verification_attempt=lambda *args, **kwargs: None,
            track_user_session=lambda *args, **kwargs: None,
            track_page_view=lambda *args, **kwargs: None,
            get_dashboard_stats=lambda *args, **kwargs: {},
            get_global_analytics=lambda *args, **kwargs: {},
        )
        sys.modules["analytics_service"] = analytics_service

    if "supabase_client" not in sys.modules:
        supabase_client = types.ModuleType("supabase_client")
        supabase_client.get_supabase_client = lambda: None
        supabase_client.safe_supabase_operation = (
            lambda fn, fallback_result=None, operation_name=None: fn()
        )
        supabase_client.supabase_logger = None
        supabase_client.log_admin_action = lambda *args, **kwargs: None
        sys.modules["supabase_client"] = supabase_client

    if "notifications_service" not in sys.modules:
        notifications_service = types.ModuleType("notifications_service")

        class _NotificationService:
            pass

        notifications_service.NotificationService = _NotificationService
        sys.modules["notifications_service"] = notifications_service

    if "web3" not in sys.modules:
        web3 = types.ModuleType("web3")

        class _Web3:
            @staticmethod
            def is_address(_value):
                return True

            @staticmethod
            def to_checksum_address(value):
                return value

        web3.Web3 = _Web3
        sys.modules["web3"] = web3

    if "blockchain" not in sys.modules:
        blockchain = types.ModuleType("blockchain")
        blockchain.has_recent_ubi_claim = lambda *_args, **_kwargs: False
        blockchain.GOODDOLLAR_CONTRACTS = {}
        blockchain.is_identity_verified = lambda _wallet: {"verified": False}
        sys.modules["blockchain"] = blockchain


_install_import_stubs()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import routes  # noqa: E402


class _FakeTable:
    def __init__(self, should_fail_on_rich_payload=True):
        self.should_fail_on_rich_payload = should_fail_on_rich_payload
        self.upsert_payloads = []

    def upsert(self, payload, on_conflict=None):
        self.upsert_payloads.append(payload)
        if self.should_fail_on_rich_payload and "login_method" in payload:
            raise Exception("column user_data.login_method does not exist")
        return self

    def execute(self):
        return types.SimpleNamespace(data=[{"ok": True}])


class _FakeSupabase:
    def __init__(self, table_obj):
        self._table = table_obj

    def table(self, _name):
        return self._table


class TurnkeyUserDataSyncTests(unittest.TestCase):
    def test_upsert_user_wallet_record_falls_back_to_wallet_only(self):
        fake_table = _FakeTable(should_fail_on_rich_payload=True)
        fake_supabase = _FakeSupabase(fake_table)

        with patch("supabase_client.get_supabase_client", lambda: fake_supabase):
            def _safe(callable_fn, fallback_result=None, operation_name=None):
                try:
                    return callable_fn()
                except Exception:
                    return fallback_result

            with patch.object(routes, "safe_supabase_operation", _safe):
                ok = routes._upsert_user_wallet_record(
                    "0x1234567890123456789012345678901234567890",
                    login_method="turnkey",
                    extra_fields={"turnkey_suborg_id": "suborg_1", "turnkey_sign_with": "0xabc"},
                )

        self.assertTrue(ok)
        self.assertEqual(len(fake_table.upsert_payloads), 2)
        self.assertEqual(fake_table.upsert_payloads[0]["login_method"], "turnkey")
        self.assertEqual(
            fake_table.upsert_payloads[1],
            {"wallet_address": "0x1234567890123456789012345678901234567890"},
        )

    def test_sync_user_verification_tracking_records_unverified(self):
        calls = {"record_unverified_visit": 0, "log_verification_attempt": 0}

        class _FakeLogger:
            def record_unverified_visit(self, wallet_address):
                calls["record_unverified_visit"] += 1

            def log_verification_attempt(self, wallet_address, success, face_verified=False):
                calls["log_verification_attempt"] += 1

        fake_blockchain = types.SimpleNamespace(
            is_identity_verified=lambda _wallet: {"verified": False}
        )

        with patch.object(routes, "supabase_logger", _FakeLogger()):
            with patch.dict(sys.modules, {"blockchain": fake_blockchain}):
                routes._sync_user_verification_tracking(
                    "0x1234567890123456789012345678901234567890"
                )

        self.assertEqual(calls["record_unverified_visit"], 1)
        self.assertEqual(calls["log_verification_attempt"], 0)

    def test_sync_user_verification_tracking_marks_verified(self):
        calls = {"record_unverified_visit": 0, "log_verification_attempt": 0}

        class _FakeLogger:
            def record_unverified_visit(self, wallet_address):
                calls["record_unverified_visit"] += 1

            def log_verification_attempt(self, wallet_address, success, face_verified=False):
                calls["log_verification_attempt"] += 1
                self.assertTrue(success)
                self.assertTrue(face_verified)

            # unittest assertions from outer class are not available here
            def assertTrue(self, value):
                if not value:
                    raise AssertionError("Expected truthy value")

        fake_blockchain = types.SimpleNamespace(
            is_identity_verified=lambda _wallet: {"verified": True}
        )

        with patch.object(routes, "supabase_logger", _FakeLogger()):
            with patch.dict(sys.modules, {"blockchain": fake_blockchain}):
                routes._sync_user_verification_tracking(
                    "0x1234567890123456789012345678901234567890"
                )

        self.assertEqual(calls["record_unverified_visit"], 0)
        self.assertEqual(calls["log_verification_attempt"], 1)


if __name__ == "__main__":
    unittest.main()
