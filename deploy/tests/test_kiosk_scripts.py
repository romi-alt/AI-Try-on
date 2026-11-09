"""The kiosk launcher and policy installer, run for real in dry-run / temporary-directory mode."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

KIOSK = Path(__file__).resolve().parents[1] / "kiosk"
URL = "https://mirror.shop.example/"
BASH = shutil.which("bash")  # absolute, so a test can empty PATH and still start the shell


def run(script: str, *args, env=None, check=False):
    base = {"PATH": os.environ["PATH"], "HOME": "/nonexistent"}
    return subprocess.run(
        [BASH, str(KIOSK / script), *args],
        env={**base, **(env or {})},
        capture_output=True,
        text=True,
        check=check,
    )


@pytest.mark.parametrize("script", ["start-kiosk.sh", "install-policy.sh"])
def test_scripts_have_valid_shell_syntax_and_are_executable(script):
    assert subprocess.run(["bash", "-n", str(KIOSK / script)]).returncode == 0
    assert os.access(KIOSK / script, os.X_OK)


def test_dry_run_prints_a_kiosk_command_with_the_url_and_a_private_profile(tmp_path):
    r = run(
        "start-kiosk.sh",
        "--once",
        env={"KIOSK_DRY_RUN": "1", "KIOSK_URL": URL, "KIOSK_PROFILE": str(tmp_path / "p")},
    )
    assert r.returncode == 0, r.stderr
    out = r.stdout.strip()
    assert "--kiosk" in out and out.endswith(URL)
    assert f"--user-data-dir={tmp_path / 'p'}" in out
    for flag in (
        "--noerrdialogs",
        "--disable-session-crashed-bubble",
        "--disable-infobars",
        "--no-first-run",
    ):
        assert flag in out
    assert (
        "--use-fake-ui-for-media-stream" not in out
    )  # the camera is allowed by policy, never by a test flag


def test_the_loop_mode_dry_run_exits_instead_of_looping_forever():
    r = run("start-kiosk.sh", env={"KIOSK_DRY_RUN": "1", "KIOSK_URL": URL})
    assert r.returncode == 0 and "--kiosk" in r.stdout


def test_a_missing_url_is_a_clear_failure():
    r = run("start-kiosk.sh", "--once", env={"KIOSK_DRY_RUN": "1"})
    assert r.returncode != 0 and "KIOSK_URL" in r.stderr


def test_settings_are_read_from_the_config_file(tmp_path):
    cfg = tmp_path / "kiosk.env"
    cfg.write_text(f"KIOSK_URL={URL}\n")
    r = run("start-kiosk.sh", "--once", env={"KIOSK_DRY_RUN": "1", "KIOSK_ENV": str(cfg)})
    assert r.returncode == 0 and r.stdout.strip().endswith(URL)


def test_a_crash_flag_in_the_profile_is_cleared_so_no_restore_bubble_greets_the_next_shopper(tmp_path):
    prefs = tmp_path / "Default" / "Preferences"
    prefs.parent.mkdir()
    prefs.write_text('{"profile":{"exited_cleanly":false,"exit_type":"Crashed"}}')
    run(
        "start-kiosk.sh",
        "--once",
        env={"KIOSK_DRY_RUN": "1", "KIOSK_URL": URL, "KIOSK_PROFILE": str(tmp_path)},
        check=True,
    )
    assert json.loads(prefs.read_text()) == {"profile": {"exited_cleanly": True, "exit_type": "Normal"}}


def test_without_chrome_installed_it_says_so(tmp_path):
    r = run("start-kiosk.sh", "--once", env={"KIOSK_URL": URL, "PATH": str(tmp_path)})
    assert r.returncode != 0 and "Chrome or Chromium" in r.stderr


# --- the policy -----------------------------------------------------------------------------------


def install(tmp_path, url=URL):
    return run("install-policy.sh", env={"KIOSK_URL": url, "POLICY_DIR": str(tmp_path / "managed")})


def test_the_policy_allows_the_camera_for_the_mirrors_origin_only(tmp_path):
    r = install(tmp_path, "https://mirror.shop.example/try-on?x=1")
    assert r.returncode == 0, r.stderr
    policy = json.loads((tmp_path / "managed" / "elevariq-kiosk.json").read_text())
    assert policy["VideoCaptureAllowed"] is True
    assert policy["VideoCaptureAllowedUrls"] == ["https://mirror.shop.example"]  # origin, not the page
    assert policy["AudioCaptureAllowed"] is False and policy["AudioCaptureAllowedUrls"] == []
    assert policy["HomepageLocation"] == "https://mirror.shop.example/try-on?x=1"
    assert "__" not in json.dumps(policy)  # every placeholder was filled


def test_the_policy_closes_everything_a_shopper_should_not_meet(tmp_path):
    install(tmp_path)
    p = json.loads((tmp_path / "managed" / "elevariq-kiosk.json").read_text())
    assert p["DeveloperToolsAvailability"] == 2 and p["IncognitoModeAvailability"] == 1
    assert p["ExtensionInstallBlocklist"] == ["*"] and p["BrowserSignin"] == 0
    assert p["PasswordManagerEnabled"] is False and p["TranslateEnabled"] is False
    assert p["PrintingEnabled"] is False and p["DownloadRestrictions"] == 3
    assert p["DefaultGeolocationSetting"] == 2 and p["DefaultNotificationsSetting"] == 2


def test_the_policy_refuses_plain_http_and_a_missing_url(tmp_path):
    assert install(tmp_path, "http://mirror.shop.example/").returncode != 0
    assert run("install-policy.sh", env={"POLICY_DIR": str(tmp_path)}).returncode != 0
    assert not (tmp_path / "managed").exists()


def test_the_policy_template_is_valid_json_with_the_placeholders_the_installer_fills():
    text = (KIOSK / "chrome-policy.json").read_text()
    json.loads(text)
    assert "__KIOSK_ORIGIN__" in text and "__KIOSK_URL__" in text


def test_the_autostart_entries_point_at_the_launcher():
    assert "start-kiosk.sh" in (KIOSK / "elevariq-kiosk.desktop").read_text()
    assert "start-kiosk.sh" in (KIOSK / "elevariq-kiosk.service").read_text()
    assert "Restart=always" in (KIOSK / "elevariq-kiosk.service").read_text()
