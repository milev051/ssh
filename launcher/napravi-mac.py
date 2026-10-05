#!/usr/bin/env python3
"""Napravi macOS aplikaciju sa trenutnom verzijom lokalnog panela."""
from pathlib import Path
import plistlib
import shutil
import subprocess

root = Path(__file__).resolve().parents[1]
app = root / 'SSH UI - Mac.app'
subprocess.run(['osacompile', '-o', str(app), str(root / 'launcher' / 'mac.applescript')], check=True)
resources = app / 'Contents' / 'Resources'
shutil.copy2(root / 'launcher' / 'pokreni.sh', resources / 'pokreni.sh')
(resources / 'prototip').mkdir(exist_ok=True)
for name in ('server.py', 'index.html', 'askpass', 'askpass.cmd', 'askpass.py'):
    shutil.copy2(root / 'prototip' / name, resources / 'prototip' / name)
info_path = app / 'Contents' / 'Info.plist'
with info_path.open('rb') as stream:
    info = plistlib.load(stream)
info.update(CFBundleIdentifier='local.ssh-ui.launcher', CFBundleName='SSH UI - Mac',
            CFBundleDisplayName='SSH UI - Mac', LSUIElement=True)
with info_path.open('wb') as stream:
    plistlib.dump(info, stream)
subprocess.run(['codesign', '--force', '--deep', '--sign', '-', str(app)], check=True)
print(f'Aplikacija je napravljena: {app}')
