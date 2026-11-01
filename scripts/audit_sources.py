"""Compare verified candidate feeds with a frozen production baseline, offline.

Run: python -m scripts.audit_sources baseline.json --candidate candidate.json
Candidates use the normalized jobs.json schema. This tool does not certify rights
or successful collection and never modifies a published feed.
"""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

from collect_all import current, merge
from collectors.common import KST, canonical_url, sanitize_serialized


def audit(baseline, candidates, now):
    base=[j for j in baseline['jobs'] if current(j,now) and canonical_url(j.get('source_url'))]
    base_count=len(merge(base,now))
    report={'as_of':now.isoformat(), 'baseline_current':base_count,
            'baseline_sources':baseline.get('sources',{}), 'candidates':{}}
    for source,rows in candidates.items():
        eligible=[j for j in rows if current(j,now) and canonical_url(j.get('source_url'))]
        groups=merge(eligible,now)
        combined=merge(base+eligible,now)
        base_ids={(j['source_id'],j['notice_id']) for j in base}
        new_groups=[j for j in combined if not any(
            (a['source_id'],a['notice_id']) in base_ids for a in j['attributions'])]
        matched_ids={(a['source_id'],a['notice_id']) for j in combined
                     if any((a['source_id'],a['notice_id']) in base_ids for a in j['attributions'])
                     for a in j['attributions']}
        overlapping=sum(any((a['source_id'],a['notice_id']) in matched_ids
                            for a in j['attributions']) for j in groups)
        report['candidates'][source]={'input':len(rows), 'expired_or_invalid':len(rows)-len(eligible),
            'current_unique':len(groups),'within_source_duplicates':len(eligible)-len(groups),
            'additional_unique':len(new_groups),'overlap_with_baseline':overlapping,
            'net_feed_change':len(combined)-base_count,
            'new_notice_ids':[j['id'] for j in new_groups]}
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline',type=Path)
    parser.add_argument('--candidate',type=Path,action='append',default=[])
    parser.add_argument('--as-of',help='Timezone-aware ISO timestamp; default current KST')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    now=dt.datetime.fromisoformat(args.as_of) if args.as_of else dt.datetime.now(KST)
    if now.tzinfo is None:parser.error('--as-of must include timezone')
    data=args.baseline.read_bytes()
    candidates={}
    for path in args.candidate:
        feed=json.loads(path.read_text())
        for row in feed['jobs']:candidates.setdefault(row['source_id'],[]).append(row)
    report=audit(json.loads(data),candidates,now)
    report['baseline_sha256']=hashlib.sha256(data).hexdigest()
    serialized=sanitize_serialized(report)
    if args.output:args.output.write_text(serialized,encoding='utf-8')
    print(serialized,end='')


if __name__=='__main__':main()
