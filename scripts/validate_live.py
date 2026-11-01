"""Fail a pre-merge validation unless the current run collected real Nara jobs."""
import json
import sys
from pathlib import Path

feed=json.loads(Path('jobs.json').read_text())
sources=feed['sources']
nara=sources['nara']
allow_cached='--allow-cached' in sys.argv
assert nara['status'] in (('ok','cached') if allow_cached else ('ok',)), 'Nara collection did not succeed'
assert nara['mode']=='official-api' and nara['originals_verified'], 'Nara verification incomplete'
if not allow_cached:assert nara['count']>0, 'No publishable Nara records'
assert sources['alio']['count']>0, 'Existing ALIO data was not preserved'
ids=[j['id'] for j in feed['jobs']]
assert len(ids)==len(set(ids)), 'Duplicate public IDs'
if nara['count']:assert any(j.get('description') for j in feed['jobs'] if j['source_id']=='nara'), 'Nara detail content missing'
summary={'updated_at':feed['updated_at'],'total':len(ids),'sources':sources}
Path('live-validation.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(summary,ensure_ascii=False))
