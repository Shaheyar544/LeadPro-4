"""Local Compose backup/restore using binary pipes (safe on Windows and Linux)."""
import argparse
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ['docker', 'compose', '--env-file', str(ROOT / '.local-integration/stack.env'),
        '-f', str(ROOT / 'compose.production.yaml'), 'exec', '-T', 'postgres']


def backup(path):
    # 'xb' refuses to overwrite a prior backup.
    with Path(path).open('xb') as stream:
        subprocess.run(BASE + ['pg_dump', '-U', 'leadpro', '-d', 'leadpro', '--format=custom'], stdout=stream, check=True)


def restore(path, database):
    if not re.fullmatch(r'phase4a2_restore_[a-z0-9_]+', database):
        raise ValueError('Restore requires a new phase4a2_restore_* database')
    # createdb fails if the destination exists; never overwrite a populated DB.
    subprocess.run(BASE + ['createdb', '-U', 'leadpro', database], check=True)
    with Path(path).open('rb') as stream:
        subprocess.run(BASE + ['pg_restore', '-U', 'leadpro', '-d', database,
                              '--exit-on-error', '--no-owner', '--no-privileges'], stdin=stream, check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['backup', 'restore'])
    parser.add_argument('file', type=Path)
    parser.add_argument('--database')
    args = parser.parse_args()
    if args.operation == 'backup':
        backup(args.file)
    else:
        restore(args.file, args.database or '')
