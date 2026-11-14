import subprocess
from pathlib import Path


def test_notification_ui():
    root = Path(__file__).resolve().parents[1]
    subprocess.run(["node", "tests/test_notifications_ui.cjs"], cwd=root, check=True)
