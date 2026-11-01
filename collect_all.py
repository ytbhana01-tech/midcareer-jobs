"""Source-isolated collection, snapshot retention, cross-source deduplication and publication."""
import argparse
import datetime as dt
import json
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit
import collect as alio
from collectors.common import KST, OfficialHTTP, SourceError, canonical_url, normalize, sanitize_serialized
from collectors.nara import NaraCollector
from collectors.busan import BusanCollector

ROOT=Path(__file__).resolve().parent
SOURCE_NAMES={'alio':'ALIO · 공공기관 경영정보 공개시스템','nara':'나라일터 · 인사혁신처','busan':'부산광역시'}


def current(job,now):
    day=now.astimezone(KST).date().isoformat()
    deadline=alio.date_of(job.get('deadline'))
    if not deadline or deadline.isoformat()<day:return False
    for key in ('opens_at','closes_at'):
        if job.get(key):
            try:
                stamp=dt.datetime.fromisoformat(job[key])
                if stamp.tzinfo is None:return False
                if key=='opens_at' and stamp>now:return False
                if key=='closes_at' and stamp<now:return False
            except (ValueError,TypeError):return False
    start=alio.date_of(job.get('start'))
    if job.get('start') and not start:return False
    return not start or start.isoformat()<=day


def merge(jobs,now=None):
    now=now or dt.datetime.now(KST)
    candidates=[j for j in jobs if current(j,now) and canonical_url(j.get('source_url'))]
    # Union duplicate groups so a bridging record cannot leave transitive duplicates.
    parents=list(range(len(candidates)))
    def find(i):
        while parents[i]!=i:
            parents[i]=parents[parents[i]];i=parents[i]
        return i
    seen={}
    for i,j in enumerate(candidates):
        # Some institutions reuse a generic recruitment landing URL for many
        # distinct notices. A shared URL alone is not proof of duplication.
        evidence=tuple(' '.join(unicodedata.normalize('NFKC',str(j.get(k) or '')).split())
                       for k in ('org','title','start','deadline'))
        keys=[('url',canonical_url(j['source_url']),evidence),('source',j['source_id'],j['notice_id'])]
        if canonical_url(j.get('agency_url')):
            keys.append(('url',canonical_url(j['agency_url']),evidence))
        if j.get('agency_id') and j.get('announcement_number'):
            keys.append(('announcement',j['agency_id'],j['announcement_number']))
        for key in keys:
            if key in seen:parents[find(i)]=find(seen[key])
            else:seen[key]=i
    groups={}
    for i,j in enumerate(candidates):groups.setdefault(find(i),[]).append(j)
    result=[]
    for group in groups.values():
        # Preserve one source's evidence as a whole; never combine qualifications
        # from distinct records to invent broader eligibility.
        primary=dict(group[0])
        primary['attributions']=[{key:j[key] for key in ('source_id','source_name','notice_id','source_url','collected_at')}
                                 for j in group]
        result.append(primary)
    return sorted(result,key=lambda j:(j['deadline'],j['id']))


def collect_alio():
    try:
        feed=json.loads(alio.collect(False))
    except alio.ApiError:
        feed=json.loads(alio.collect(True))
    now=dt.datetime.fromisoformat(feed['updated_at'])
    records=normalize(feed['jobs'],'alio',SOURCE_NAMES['alio'],now)
    # Check originals without sending the ALIO key to any destination. The source
    # snapshot is retained on unknown transport failure; known missing originals
    # and robots-disallowed originals are excluded on a successful source update.
    hosts={urlsplit(j['source_url']).hostname for j in records}
    http=OfficialHTTP(hosts)
    verified=[j for j in records if http.original(j['source_url'])]
    return {'jobs':verified,'updated_at':feed['updated_at'],'mode':feed['source'],'originals_verified':True}


def collect_nara(config):
    collector=NaraCollector(config)
    jobs=collector.collect()
    return {'jobs':jobs,'updated_at':dt.datetime.now(KST).isoformat(timespec='seconds'),
            'mode':'official-api','originals_verified':True,'stats':collector.stats,
            'coverage':'최근 '+str(config['lookback_days'])+'일 등록 공고'}


def legacy_snapshot(feed):
    rows=[j for j in feed.get('jobs',[]) if j.get('source_id','alio')=='alio']
    if not rows:return None
    when=feed.get('updated_at')
    try:now=dt.datetime.fromisoformat(when)
    except (TypeError,ValueError):return None
    if now.tzinfo is None:return None
    # Migration preserves the original timestamp and makes the unverified-original
    # legacy state explicit instead of inventing a recent verification time.
    return {'jobs':normalize(rows,'alio',SOURCE_NAMES['alio'],now),
            'updated_at':when,'mode':feed.get('source','alio-public-preview'),'originals_verified':False}


def run(config,previous,cache,collectors,now=None):
    now=now or dt.datetime.now(KST)
    if now.tzinfo is None:raise SourceError('Timezone-aware collection time required')
    snapshots=dict(cache)
    if 'alio' not in snapshots:
        seed=legacy_snapshot(previous)
        if seed:snapshots['alio']=seed
    statuses={};all_jobs=[]
    for source,name in SOURCE_NAMES.items():
        enabled=source=='alio' or config.get(source,{}).get('enabled',False)
        old=snapshots.get(source)
        if not enabled:
            statuses[source]={'name':name,'status':'disabled','count':0,
                              'reason':'공식 명세·이용조건 확인 및 활성화 대기'}
            continue
        try:
            fresh=collectors[source]()
            if isinstance(fresh,list):
                fresh={'jobs':fresh,'updated_at':now.isoformat(timespec='seconds'),
                       'mode':'official-api' if source=='nara' or config.get(source,{}).get('format')=='json' else 'official-feed','originals_verified':True}
            if not isinstance(fresh,dict) or not isinstance(fresh.get('jobs'),list):
                raise SourceError('Malformed source snapshot')
            # Per-source snapshot is committed only after a successful full run.
            sanitize_serialized(fresh)
            snapshots[source]=fresh;chosen=fresh;status='ok'
        except Exception:
            chosen=old;status='cached' if old else 'unavailable'
        jobs=[j for j in (chosen or {}).get('jobs',[]) if current(j,now)]
        all_jobs.extend(jobs)
        statuses[source]={'name':name,'status':status,'count':len(jobs),
                          'updated_at':(chosen or {}).get('updated_at'),
                          'mode':(chosen or {}).get('mode'),
                          'originals_verified':bool((chosen or {}).get('originals_verified'))}
        if (chosen or {}).get('coverage'):statuses[source]['coverage']=chosen['coverage']
        if (chosen or {}).get('stats'):statuses[source]['stats']=chosen['stats']
        if status!='ok':statuses[source]['reason']='수집 실패 또는 검증 대기 · 이전 검증 시각의 데이터 유지'
    times=[s.get('updated_at') for s in statuses.values() if s.get('updated_at')]
    updated=max(times,key=lambda t:dt.datetime.fromisoformat(t)) if times else None
    feed={'source':'multi-source','generated_at':now.isoformat(timespec='seconds'),
          'updated_at':updated,'sources':statuses,'jobs':merge(all_jobs,now)}
    sanitize_serialized(feed)
    return feed,snapshots


def load(path,default):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:return default
    except (ValueError,OSError):raise SourceError('Invalid saved collector state; publication refused') from None


def atomic(path,text):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.tmp')
    temporary.write_text(text,encoding='utf-8');temporary.replace(path)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--cached-only',action='store_true',help='Build from saved snapshots without network access')
    args=parser.parse_args()
    try:
        config=load(ROOT/'sources.json',{})
        previous=load(ROOT/'jobs.json',{})
        cache_path=ROOT/'.collector-cache'/'source-feeds.json'
        cache=load(cache_path,{})
        def cached():raise SourceError('Offline snapshot validation')
        runners={'alio':collect_alio,'nara':lambda:collect_nara(config.get('nara',{})),
                 'busan':BusanCollector(config.get('busan',{})).collect}
        if args.cached_only:runners={name:cached for name in SOURCE_NAMES}
        feed,snapshots=run(config,previous,cache,runners)
        if not feed['jobs'] and not any(s['status']=='ok' for s in feed['sources'].values()):
            raise SourceError('No usable source snapshot; existing feed preserved')
        serialized=sanitize_serialized(feed)
        saved=sanitize_serialized(snapshots)
        atomic(cache_path,saved)
        atomic(ROOT/'jobs.json',serialized)
        print(json.dumps({'published':len(feed['jobs']),'sources':{
            key:{'status':value['status'],'count':value['count']} for key,value in feed['sources'].items()}}))
    except SourceError as error:
        parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()
