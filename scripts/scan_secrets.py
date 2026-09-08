"""Scan the candidate Git tree with pinned Gitleaks, excluding local artifacts."""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'ghcr.io/gitleaks/gitleaks:v8.30.1'


def scan():
    files = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard'], cwd=ROOT, text=True).splitlines()
    with tempfile.TemporaryDirectory(prefix='leadpro-secret-scan-') as temporary:
        destination = Path(temporary)
        for name in files:
            if Path(name).name.startswith('CODEX_') or not (ROOT / name).is_file():
                continue
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        return subprocess.run(['docker', 'run', '--rm', '--network', 'none', '-v', str(destination) + ':/src:ro',
                               IMAGE, 'dir', '/src', '--redact', '--no-banner', '--verbose'], check=True)


if __name__ == '__main__':
    scan()
