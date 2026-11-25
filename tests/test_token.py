import base64
import hashlib
import subprocess
import unittest
from unittest import mock

import refresh


def electron_encrypt(plaintext: str, password: str) -> str:
    key = hashlib.pbkdf2_hmac("sha1", password.encode(), b"saltysalt", 1003, 16)
    cipher = subprocess.run(
        ["openssl", "enc", "-aes-128-cbc", "-K", key.hex(), "-iv", (b" " * 16).hex()],
        input=plaintext.encode(),
        capture_output=True,
        check=True,
    ).stdout
    return refresh.ENCRYPTED_PREFIX + base64.b64encode(b"v10" + cipher).decode()


class DecryptTest(unittest.TestCase):
    def test_round_trips_electron_safe_storage(self):
        stored = electron_encrypt("header.payload.signature", "pw")
        self.assertEqual(refresh.decrypt_safe_storage(stored, "pw"), "header.payload.signature")

    def test_wrong_password_fails_loudly(self):
        stored = electron_encrypt("header.payload.signature", "pw")
        with self.assertRaises(RuntimeError):
            refresh.decrypt_safe_storage(stored, "other")

    def test_unknown_blob_version_fails_loudly(self):
        stored = refresh.ENCRYPTED_PREFIX + base64.b64encode(b"v99xxxx").decode()
        with self.assertRaisesRegex(RuntimeError, "v99"):
            refresh.decrypt_safe_storage(stored, "pw")


class KeychainTest(unittest.TestCase):
    def setUp(self):
        refresh.keychain_password.cache_clear()
        self.addCleanup(refresh.keychain_password.cache_clear)

    def test_keychain_is_read_once_per_process(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd[0])
            return subprocess.CompletedProcess(cmd, 0, stdout="pw\n", stderr="")

        with mock.patch.object(refresh.subprocess, "run", fake_run), mock.patch.object(refresh.sys, "platform", "darwin"):
            self.assertEqual(refresh.keychain_password(), "pw")
            self.assertEqual(refresh.keychain_password(), "pw")
        self.assertEqual(calls, ["security"])

    def test_denied_keychain_is_retried_next_time(self):
        results = iter([
            subprocess.CompletedProcess([], 1, stdout="", stderr="denied"),
            subprocess.CompletedProcess([], 0, stdout="pw\n", stderr=""),
        ])
        with mock.patch.object(refresh.subprocess, "run", lambda cmd, **kw: next(results)), mock.patch.object(refresh.sys, "platform", "darwin"):
            with self.assertRaisesRegex(RuntimeError, "denied"):
                refresh.keychain_password()
            self.assertEqual(refresh.keychain_password(), "pw")


if __name__ == "__main__":
    unittest.main()
