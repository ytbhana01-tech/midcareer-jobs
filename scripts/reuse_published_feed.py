"""Reuse the verified public feed for a design-only release without restamping it."""
import datetime as dt
import json
import sys
from pathlib import Path
from urllib.request import Request, build_opener
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from collect import NoRedirect

URL='https://ytbhana01-tech.github.io/midcareer-jobs/jobs.json'
ROOT=Path(__file__).resolve().parents[1]


def validate_feed(feed,now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    if feed.get('source')!='multi-source' or not isinstance(feed.get('jobs'),list) or not feed['jobs']:
        raise ValueError('A published multi-source feed is required')
    ids=[j.get('id') for j in feed['jobs']]
    if not all(isinstance(i,str) and i for i in ids) or len(ids)!=len(set(ids)):
        raise ValueError('Invalid published notice IDs')
    for source in ('alio','nara'):
        metadata=feed['sources'][source]
        if metadata['status'] not in ('ok','cached'):
            raise ValueError('A verified source snapshot is required')
        stamp=dt.datetime.fromisoformat(metadata['updated_at'])
        if stamp.tzinfo is None or stamp>now+dt.timedelta(minutes=5):
            raise ValueError('Invalid source collection timestamp')
    nara=feed['sources']['nara']
    if nara['mode']!='official-api' or nara['originals_verified'] is not True:
        raise ValueError('Verified Nara data is required')


def main():
    request=Request(URL,headers={'Cache-Control':'no-cache','Accept':'application/json'})
    with build_opener(NoRedirect()).open(request,timeout=40) as response:
        data=response.read(20_000_001)
        if response.status!=200 or len(data)>20_000_000:raise ValueError('Invalid public response')
    feed=json.loads(data)
    validate_feed(feed)
    temporary=ROOT/'jobs.json.tmp'
    temporary.write_bytes(data)
    temporary.replace(ROOT/'jobs.json')
    print(json.dumps({'reused_notices':len(feed['jobs']),'original_updated_at':feed['updated_at']},ensure_ascii=False))


if __name__=='__main__':
    try:main()
    except Exception:raise SystemExit('Published feed could not be verified; deployment stopped') from None
