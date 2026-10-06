import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from app.config import ConfigurationError, PROJECT_ROOT, Settings, get_settings, load_environment


class SettingsTests(unittest.TestCase):
    def test_local_defaults_and_paths(self):
        settings = Settings.from_environment({})
        self.assertEqual(settings.callback_url, "http://localhost:5173/auth/discogs/callback")
        self.assertFalse(settings.cookie_secure)
        self.assertEqual(settings.auth_db_path, PROJECT_ROOT / "data/auth.sqlite3")
        self.assertEqual(settings.cache_db_path, PROJECT_ROOT / "data/cache.sqlite3")

    def test_hosted_urls_drive_cors_callback_and_cookie_security(self):
        settings = Settings.from_environment({"FRONTEND_URL": "https://dside.example/"})
        self.assertEqual(settings.callback_url, "https://dside.example/auth/discogs/callback")
        self.assertEqual(settings.cors_allowed_origins, ("https://dside.example",))
        self.assertEqual(settings.trusted_origins, frozenset({"https://dside.example"}))
        self.assertTrue(settings.cookie_secure)

    def test_cors_origins_are_explicit_and_do_not_expand_trusted_write_origins(self):
        settings = Settings.from_environment({
            "CORS_ALLOWED_ORIGINS": "https://reader.example, http://localhost:5173,https://reader.example",
        })
        self.assertEqual(settings.cors_allowed_origins, ("https://reader.example", "http://localhost:5173"))
        self.assertNotIn("https://reader.example", settings.trusted_origins)
        for invalid in ("*", "https://*.example", "https://reader.example/path", "https://reader.example,", ""):
            with self.subTest(invalid=invalid), self.assertRaises(ConfigurationError):
                    Settings.from_environment({"CORS_ALLOWED_ORIGINS": invalid})

    def test_origins_are_normalized_to_browser_format(self):
        settings = Settings.from_environment({"FRONTEND_URL": "https://Dside.Example:443/"})
        self.assertEqual(settings.frontend_url, "https://dside.example")
        self.assertEqual(settings.cors_allowed_origins, ("https://dside.example",))

    def test_invalid_url_settings_fail_without_echoing_credentials(self):
        for url in ("http://public.example", "https://user:secret@example.com", "https://example.com?key=secret",
                    "https://example.com#secret", "https://example.com:99999", "https://[invalid", "javascript:secret",
                    "https://example .com", "https://example.com\n"):
            for name in ("FRONTEND_URL", "DISCOGS_CALLBACK_URL"):
                with self.subTest(url=url, name=name), self.assertRaises(ConfigurationError) as caught:
                    Settings.from_environment({name: url})
                self.assertNotIn("secret", str(caught.exception))

    def test_session_durations_are_positive_integers(self):
        settings = Settings.from_environment({"AUTH_PENDING_TTL_SECONDS": "120", "AUTH_SESSION_TTL_SECONDS": "3600"})
        self.assertEqual(settings.pending_ttl_seconds, 120)
        self.assertEqual(settings.session_ttl_seconds, 3600)
        for name in ("AUTH_PENDING_TTL_SECONDS", "AUTH_SESSION_TTL_SECONDS", "CACHE_CLEANUP_INTERVAL_SECONDS",
                     "RELEASE_CACHE_MAX_ENTRIES", "RELEASE_CACHE_TTL_SECONDS", "MAX_CONCURRENT_SEARCHES"):
            for invalid in ("0", "-1", "1.5", "invalid"):
                with self.subTest(name=name, invalid=invalid), self.assertRaises(ConfigurationError):
                    Settings.from_environment({name: invalid})

    def test_invalid_encryption_key_and_insecure_cookie_override(self):
        with self.assertRaises(ConfigurationError) as caught:
            Settings.from_environment({"AUTH_ENCRYPTION_KEY": "secret-invalid-key"})
        self.assertNotIn("secret-invalid-key", str(caught.exception))
        for env in ({"COOKIE_SECURE": "invalid"},
                    {"FRONTEND_URL": "https://dside.example", "COOKIE_SECURE": "false"}):
            with self.assertRaises(ConfigurationError):
                Settings.from_environment(env)

    def test_secrets_are_not_in_settings_repr(self):
        key = Fernet.generate_key().decode()
        settings = Settings.from_environment({"DISCOGS_CONSUMER_KEY": "test-consumer-key",
            "DISCOGS_CONSUMER_SECRET": "test-consumer-secret", "AUTH_ENCRYPTION_KEY": key})
        settings.require_auth_configuration()
        for secret in (key, "test-consumer-key", "test-consumer-secret"):
            self.assertNotIn(secret, repr(settings))

    def test_dotenv_loading_preserves_environment_and_does_not_edit_file(self):
        self.addCleanup(get_settings.cache_clear)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            content = "FRONTEND_URL=http://localhost:5555\nAUTH_SESSION_TTL_SECONDS=1234\n"
            path.write_text(content)
            with patch("app.config.PROJECT_ROOT", Path(directory)), patch.dict(os.environ,
                {"FRONTEND_URL": "https://hosted.example"}, clear=True):
                load_environment()
                settings = get_settings()
                self.assertEqual(settings.frontend_url, "https://hosted.example")
                self.assertEqual(settings.session_ttl_seconds, 1234)
                self.assertEqual(path.read_text(), content)


if __name__ == "__main__":
    unittest.main()
