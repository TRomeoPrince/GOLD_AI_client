"""Friends trial tests never create a real task or uninstall anything."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from client import friends_trial


class FriendsTrialTest(unittest.TestCase):
    def setUp(self):
        self.patcher = patch.object(friends_trial, "is_friends_edition", return_value=True)
        self.patcher.start()
        friends_trial._last_schedule_attempt = None
        self.addCleanup(self.patcher.stop)
        self.start = datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc)
        self.end = self.start + timedelta(days=14)
        self.sub = {
            "plan_code": "DISTRIBUTOR_TRIAL",
            "access_kind": "DISTRIBUTOR_TRIAL",
            "starts_utc": self.start.isoformat(),
            "expires_utc": self.end.isoformat(),
        }

    def test_only_owner_returned_exact_fourteen_days_can_schedule(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "lease.json"
            calls = []
            registrar = lambda: calls.append(True) or True
            invalid = dict(self.sub, expires_utc=(self.start + timedelta(days=30)).isoformat())
            self.assertFalse(friends_trial.observe_subscription(invalid, path=path, registrar=registrar, now=self.start))
            self.assertFalse(path.exists())
            self.assertFalse(friends_trial.observe_subscription(dict(self.sub, access_kind="PAID"), path=path, registrar=registrar, now=self.start))
            self.assertFalse(calls)
            self.assertTrue(friends_trial.observe_subscription(self.sub, path=path, registrar=registrar, now=self.start))
            self.assertEqual(len(calls), 1)
            self.assertTrue(friends_trial.observe_subscription(self.sub, path=path, registrar=registrar, now=self.start))
            self.assertEqual(len(calls), 1)

    def test_first_expiry_is_not_extended_by_later_overview(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "lease.json"
            self.assertTrue(friends_trial.observe_subscription(self.sub, path=path, registrar=lambda: True, now=self.start))
            later = dict(self.sub, starts_utc=(self.start + timedelta(days=1)).isoformat(),
                         expires_utc=(self.end + timedelta(days=1)).isoformat())
            self.assertTrue(friends_trial.observe_subscription(later, path=path, registrar=lambda: True, now=self.start))
            self.assertEqual(friends_trial._read_lease(path)["expires_utc"], self.end.isoformat())
            self.assertFalse(friends_trial.local_trial_expired(path=path, now=self.end - timedelta(seconds=1)))
            self.assertTrue(friends_trial.local_trial_expired(path=path, now=self.end))


    def test_execution_is_permitted_only_by_active_fourteen_day_owner_lease(self):
        active = {"allowed": True, "subscription": self.sub}
        self.assertTrue(friends_trial.friends_trial_authorized(active))
        self.assertFalse(friends_trial.friends_trial_authorized({"allowed": False, "subscription": self.sub}))
        self.assertFalse(friends_trial.friends_trial_authorized({"allowed": True,
            "subscription": dict(self.sub, expires_utc=(self.start + timedelta(days=30)).isoformat())}))
        self.assertFalse(friends_trial.friends_trial_authorized({"allowed": True,
            "subscription": dict(self.sub, access_kind="PAID")}))

    def test_invalid_and_missing_lease_never_launch_cleanup(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "lease.json"
            with patch.object(friends_trial, "local_trial_expired", return_value=False), patch.object(
                    friends_trial, "_launch_powershell") as launched:
                self.assertEqual(friends_trial.run_expiry_guard(), 0)
                launched.assert_not_called()
            path.write_text("{corrupt", encoding="utf-8")
            self.assertIsNone(friends_trial._read_lease(path))

    def test_register_failure_keeps_lease_for_retry(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "lease.json"
            self.assertFalse(friends_trial.observe_subscription(self.sub, path=path, registrar=lambda: False, now=self.start))
            self.assertIsNotNone(friends_trial._read_lease(path))
            self.assertFalse(friends_trial._read_lease(path)["scheduler_registered"])
            self.assertTrue(friends_trial.observe_subscription(self.sub, path=path,
                registrar=lambda: True, now=self.start + timedelta(minutes=6)))
            self.assertTrue(friends_trial._read_lease(path)["scheduler_registered"])


if __name__ == "__main__":
    unittest.main()
