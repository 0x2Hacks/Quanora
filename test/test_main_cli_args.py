import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)


def test_resume_mode_flag_is_removed() -> None:
    result = subprocess.run(
        [sys.executable, "main.py", "--resume-mode", "summary"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        raise AssertionError("Expected main.py to reject the removed --resume-mode flag.")
    combined = f"{result.stdout}\n{result.stderr}"
    if "unrecognized arguments: --resume-mode summary" not in combined:
        raise AssertionError(f"Expected argparse unknown-flag error, got: {combined}")


def test_version_does_not_validate_config(tmp_path) -> None:
    bad_settings = tmp_path / "settings.json"
    bad_settings.write_text("{", encoding="utf-8")
    env = os.environ.copy()
    env["CHAINPEER_SETTINGS_PATH"] = str(bad_settings)

    result = subprocess.run(
        [sys.executable, "main.py", "--version"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise AssertionError(f"Expected --version to succeed, got: {result.stderr}")
    if "chainpeer " not in result.stdout:
        raise AssertionError(f"Expected version output, got: {result.stdout}")


def main() -> int:
    test_resume_mode_flag_is_removed()
    with tempfile.TemporaryDirectory() as temp_dir:
        test_version_does_not_validate_config(Path(temp_dir))
    print("Main CLI arg tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
