from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from shorts import cli, upload


class _FakeCreds:
    def __init__(self, *, valid: bool, expired: bool = False, refresh_token: str | None = None, payload: str = '{"token":"abc"}') -> None:
        self.valid = valid
        self.expired = expired
        self.refresh_token = refresh_token
        self._payload = payload

    def to_json(self) -> str:
        return self._payload


class _FakeFlow:
    def __init__(self, credentials: _FakeCreds) -> None:
        self.credentials = credentials
        self.authorization_response = None

    def fetch_token(self, *, authorization_response: str) -> None:
        self.authorization_response = authorization_response


class TestYouTubeAuth(unittest.TestCase):
    def _write_client_secret(self, root: Path) -> Path:
        path = root / "client_secret.json"
        path.write_text(
            json.dumps(
                {
                    "installed": {
                        "client_id": "client-id",
                        "client_secret": "client-secret",
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": ["http://localhost"],
                    }
                }
            ),
            encoding="utf-8",
        )
        return path

    def _config(self, client_secret_file: Path, token_file: Path):
        return SimpleNamespace(
            youtube=SimpleNamespace(
                client_secret_file=str(client_secret_file),
                token_file=str(token_file),
            )
        )

    def test_cli_youtube_auth_command_delegates(self) -> None:
        with mock.patch("shorts.cli.upload.youtube_authenticate", return_value=(Path("/tmp/token.json"), "created")) as auth:
            rc = cli.main(
                [
                    "youtube",
                    "auth",
                    "--config",
                    "ENV",
                    "--authorization-response",
                    "http://localhost/?state=s&code=c",
                ]
            )
        self.assertEqual(rc, 0)
        auth.assert_called_once()

    def test_youtube_auth_writes_token_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            client_secret = self._write_client_secret(root)
            token_file = root / "token.json"
            config = self._config(client_secret, token_file)
            fake_flow = _FakeFlow(_FakeCreds(valid=True, payload='{"refresh_token":"r"}'))
            with mock.patch("shorts.upload._load_credentials", return_value=None):
                with mock.patch("shorts.upload._build_manual_flow", return_value=(fake_flow, "https://accounts.google.com/o/oauth2/auth?x=1", "state123")):
                    token_path, mode = upload.youtube_authenticate(
                        config,
                        authorization_response="http://localhost/?state=state123&code=abc123",
                    )
            self.assertEqual(token_path, token_file)
            self.assertEqual(mode, "created")
            self.assertTrue(token_file.exists())
            self.assertIn("refresh_token", token_file.read_text(encoding="utf-8"))
            file_mode = stat.S_IMODE(token_file.stat().st_mode)
            self.assertEqual(file_mode, 0o600)
            self.assertEqual(fake_flow.authorization_response, "http://localhost/?state=state123&code=abc123")

    def test_youtube_auth_noops_when_valid_token_exists(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            client_secret = self._write_client_secret(root)
            token_file = root / "token.json"
            config = self._config(client_secret, token_file)
            creds = _FakeCreds(valid=True)
            with mock.patch("shorts.upload._load_credentials", return_value=creds):
                with mock.patch("shorts.upload._build_manual_flow") as build_flow:
                    token_path, mode = upload.youtube_authenticate(config)
            self.assertEqual(token_path, token_file)
            self.assertEqual(mode, "existing")
            build_flow.assert_not_called()

    def test_youtube_auth_rejects_state_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            client_secret = self._write_client_secret(root)
            token_file = root / "token.json"
            config = self._config(client_secret, token_file)
            fake_flow = _FakeFlow(_FakeCreds(valid=True))
            with mock.patch("shorts.upload._load_credentials", return_value=None):
                with mock.patch("shorts.upload._build_manual_flow", return_value=(fake_flow, "https://accounts.google.com/o/oauth2/auth?x=1", "expected-state")):
                    with self.assertRaisesRegex(RuntimeError, "state mismatch"):
                        upload.youtube_authenticate(
                            config,
                            authorization_response="http://localhost/?state=wrong&code=abc123",
                        )
            self.assertFalse(token_file.exists())

    def test_get_youtube_client_requires_explicit_auth_when_token_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            client_secret = self._write_client_secret(root)
            token_file = root / "token.json"
            config = self._config(client_secret, token_file)
            with mock.patch("shorts.upload._load_credentials", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "python -m shorts youtube auth --config ENV"):
                    upload.get_youtube_client(config)

    def test_get_youtube_client_refresh_failure_raises_reauth(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            client_secret = self._write_client_secret(root)
            token_file = root / "token.json"
            config = self._config(client_secret, token_file)
            creds = _FakeCreds(valid=False, expired=True, refresh_token="refresh")
            with mock.patch("shorts.upload._load_credentials", return_value=creds):
                with mock.patch("shorts.upload._refresh_credentials", side_effect=RuntimeError("bad refresh")):
                    with self.assertRaisesRegex(RuntimeError, "youtube auth --config ENV"):
                        upload.get_youtube_client(config)
