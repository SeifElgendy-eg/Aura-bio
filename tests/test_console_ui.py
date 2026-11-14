import hashlib
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which('node') is None, reason='Node is optional')
def test_console_ui():
    result = subprocess.run(['node', 'tests/test_console_ui.cjs'], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_local_web_silhouette():
    original = ROOT / 'web/static/images/human-silhouette.svg'
    assert hashlib.sha256(original.read_bytes()).hexdigest() == 'd0e37b1a7b06c9db1e4c822c3b5189f3d9da4335cd2c543d04ec2e255ed49f9e'
    ns = {'s': 'http://www.w3.org/2000/svg'}
    source_path = ET.parse(original).getroot().find('.//s:path', ns).attrib['d']
    body = ET.parse(ROOT / 'web/static/images/body-systems.svg').getroot()
    clip_path = body.find('.//s:path[@id="human-outline"]', ns)
    assert clip_path.attrib['d'] == source_path
    assert clip_path.attrib['transform'] == 'translate(41.500029,630.92312)'
    parts = [e for e in body.iter() if 'data-lane' in e.attrib]
    assert {e.attrib['data-lane'] for e in parts} == {'neuro', 'immune', 'cardio', 'metab', 'bone', 'habitat'}
    assert all(e.attrib['role'] == 'button' and e.attrib['tabindex'] == '0' for e in parts)
    for e in body.iter():
        assert e.tag.split('}')[-1] not in {'script', 'image', 'foreignObject'}
        assert not any(k.startswith('on') for k in e.attrib)
        assert all(v.startswith('#') for k, v in e.attrib.items() if k.endswith('href'))
