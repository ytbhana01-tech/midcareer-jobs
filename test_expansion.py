import datetime as dt
import unittest

from collect_all import published_snapshots, run
from collectors.common import KST, SourceError, normalize
from scripts.audit_sources import audit

NOW=dt.datetime(2026,11,1,22,tzinfo=KST)


def job(source,ident='1',**values):
    row=dict(notice_id=ident,title='시설관리 기간제 채용',org='기관',
             start='2026-10-30',deadline='2026-11-05',source_url='https://agency.go.kr/view?id='+ident)
    row.update(values)
    return normalize([row],source,source,NOW)[0]


class ExpansionTests(unittest.TestCase):
    def test_cache_loss_retains_nara_primary_data_and_own_timestamp(self):
        old_time='2026-11-01T20:00:00+09:00'
        previous={'source':'multi-source','jobs':[job('alio'),job('nara','2')],
                  'sources':{s:{'status':'ok','updated_at':old_time,'mode':'official-api',
                                'originals_verified':True} for s in ('alio','nara')}}
        def fail():raise SourceError('Offline')
        feed,snapshots=run({'nara':{'enabled':True}},previous,{},dict(alio=fail,nara=fail),NOW)
        self.assertEqual(len(feed['jobs']),2)
        self.assertEqual(feed['sources']['nara']['status'],'cached')
        self.assertEqual(snapshots['nara']['updated_at'],old_time)
        self.assertEqual(feed['sources']['alio']['updated_at'],old_time)

    def test_recovery_does_not_invent_missing_source_evidence(self):
        feed={'source':'multi-source','jobs':[job('alio')],
              'sources':{'nara':{'status':'unavailable','updated_at':None}}}
        self.assertEqual(published_snapshots(feed),{})

    def test_existing_cache_has_priority_over_published_fallback(self):
        old_time='2026-11-01T20:00:00+09:00'
        previous={'source':'multi-source','jobs':[job('nara')],
                  'sources':{'nara':{'status':'ok','updated_at':old_time}}}
        cache={'nara':{'jobs':[job('nara','2')],'updated_at':NOW.isoformat()}}
        def fail():raise SourceError('Offline')
        _,snapshots=run({'nara':{'enabled':True}},previous,cache,dict(alio=fail,nara=fail),NOW)
        self.assertEqual(snapshots['nara'],cache['nara'])

    def test_audit_counts_url_overlap_but_not_same_title(self):
        baseline={'jobs':[job('nara')]}
        candidates={'pen':[job('pen'),job('pen','2'),job('pen','3',deadline='2026-11-02')]}
        candidates['pen'][2]['deadline']='2026-10-31'
        result=audit(baseline,candidates,NOW)['candidates']['pen']
        self.assertEqual(result['additional_unique'],1)
        self.assertEqual(result['overlap_with_baseline'],1)
        self.assertEqual(result['expired_or_invalid'],1)
        self.assertEqual(result['new_notice_ids'],['pen:2'])

    def test_audit_same_board_url_with_different_evidence_stays_separate(self):
        result=audit({'jobs':[job('nara')]},{'pen':[job('pen',title='다른 채용')]},NOW)
        self.assertEqual(result['candidates']['pen']['additional_unique'],1)

    def test_bridging_existing_groups_is_not_negative_new_notice_count(self):
        first=job('nara','1',agency_id='official',announcement_number='2026-1')
        second=job('nara','2')
        bridge=job('pen','2',agency_id='official',announcement_number='2026-1')
        result=audit({'jobs':[first,second]},{'pen':[bridge]},NOW)['candidates']['pen']
        self.assertEqual(result['additional_unique'],0)
        self.assertEqual(result['overlap_with_baseline'],1)
        self.assertEqual(result['net_feed_change'],-1)


if __name__=='__main__':unittest.main()
