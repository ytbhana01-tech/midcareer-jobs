"""Build an allowlisted static artifact; never copy server code or environment files."""
from pathlib import Path
import json
import shutil

ROOT = Path(__file__).resolve().parent
PUBLIC = ('index.html', 'styles.css', 'app.js', 'jobs.json')


def build(destination=None):
    destination = Path(destination) if destination else ROOT / 'dist'
    feed = json.loads((ROOT / 'jobs.json').read_text(encoding='utf-8'))
    if not isinstance(feed.get('jobs'), list):
        raise ValueError('Invalid public feed')
    destination.mkdir(parents=True, exist_ok=True)
    for existing in destination.iterdir():
        if existing.is_dir():
            shutil.rmtree(existing)
        else:
            existing.unlink()
    for name in PUBLIC:
        shutil.copyfile(ROOT / name, destination / name)
    (destination / '.nojekyll').touch()
    print(f'Built {len(PUBLIC)} public assets; {len(feed["jobs"])} listings')
    return destination


if __name__ == '__main__':
    build()
