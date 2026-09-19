"""Build and verify a single-file Windows release, then package it as a ZIP."""
import os
from pathlib import Path
import subprocess
import sys
import zipfile
from version import __version__

ROOT = Path(__file__).resolve().parent


def main():
    os.chdir(ROOT)
    subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], check=True)
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QIcon
    from PIL import Image
    app = QApplication([])
    icon = QIcon(str(ROOT / 'assets' / 'pysnip.svg'))
    png = ROOT / 'assets' / 'pysnip-build.png'
    if not icon.pixmap(256, 256).save(str(png)):
        raise RuntimeError('Could not render the application icon')
    with Image.open(png) as image:
        image.save(ROOT / 'assets' / 'pysnip.ico', sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    subprocess.run([
        sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onefile', '--windowed',
        '--workpath', 'build-release',
        '--name', 'PySnip', '--icon', 'assets/pysnip.ico',
        '--add-data', 'assets/pysnip.svg:assets',
        '--add-data', 'ocr_bridge.ps1:.',
        '--hidden-import', 'PySide6.QtSvg', 'main.py',
    ], check=True, env={**os.environ, 'PATH': os.pathsep.join([
        str(Path(sys.executable).parent),
        str(Path(os.environ['SystemRoot']) / 'System32'),
        os.environ['SystemRoot'],
    ])})
    report = ROOT / 'dist' / 'verification.json'
    subprocess.run([str(ROOT / 'dist' / 'PySnip.exe'), '--self-test', str(report)], check=True, timeout=90)
    import json
    if not json.loads(report.read_text(encoding='utf-8')).get('ok'):
        raise RuntimeError('Frozen executable verification failed')
    archive = ROOT / 'dist' / f'PySnip-{__version__}-Windows-x64.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        bundle.write(ROOT / 'dist' / 'PySnip.exe', 'PySnip/PySnip.exe')
        bundle.write(ROOT / 'README.md', 'PySnip/README.md')
    print(f'Release: {archive} ({archive.stat().st_size / 1024**2:.1f} MiB)')


if __name__ == '__main__':
    main()
