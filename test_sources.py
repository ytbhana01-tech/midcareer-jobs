import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from collectors.common import KST, SourceError, OfficialHTTP, canonical_url, normalize, closing, classify, sanitize_serialized
from collectors.nara import NaraCollector, parse_page
from collectors.busan import BusanCollector, parse_feed
from collect_all import merge,run,legacy_snapshot

FIXTURES=Path(__file__).parent/'tests'/'fixtures'
NOW=dt.datetime(2026,11,1,12,tzinfo=KST)
REVIEW={'spec_url':'https://www.data.go.kr/data/15156780/openapi.do',
        'rights_url':'https://agency.go.kr/test-license','reviewed_at':'2026-11-01',
        'redistribution_allowed':True,'spec_verified':True}
NARA={'enabled':True,'endpoint':'https://apis.data.go.kr/synthetic-contract',
      'original_hosts':['agency.go.kr'],'format':'json','key_parameter':'serviceKey',
      'page_parameter':'pageNo','size_parameter':'numOfRows','success_path':'response.header.resultCode',
      'success_codes':['00'],'total_path':'response.body.totalCount','items_path':'response.body.items.item',
      'fields':{'notice_id':'notice','org':'agency','title':'heading','deadline':'closes',
                'source_url':'original','type':'hire','education':'school'},'review':REVIEW}
BUSAN={'enabled':True,'endpoint':'https://www.busan.go.kr/synthetic-supported-feed','format':'rss',
       'original_hosts':['www.busan.go.kr'],'items_path':'channel/item',
       'namespaces':{'job':'urn:synthetic-job-contract','atom':'http://www.w3.org/2005/Atom'},
       'fields':{'notice_id':'guid','title':'title','org':'job:agency','deadline':'job:deadline',
                 'type':'job:type','source_url':'link'},'next_path':"channel/atom:link[@rel='next']",'review':REVIEW}


def row(ident='7',url='https://agency.go.kr/notice/7',**extra):
    return {'notice_id':ident,'org':'기관','title':'채용','deadline':'2026-11-02','source_url':url,**extra}


def job(source='alio',ident='7',url='https://agency.go.kr/notice/7',**extra):
    return normalize([row(ident,url,**extra)],source,source.upper(),NOW)[0]


def page(rows,total):
    return json.dumps({'response':{'header':{'resultCode':'00'},'body':{'items':{'item':rows},'totalCount':total}}}).encode()


class ParserTests(unittest.TestCase):
    def test_nara_fixture_does_not_invent_deadlines(self):
        rows,total=parse_page((FIXTURES/'nara-contract.json').read_bytes(),NARA)
        self.assertEqual(total,2)
        jobs=normalize(rows,'nara','나라일터',NOW)
        self.assertEqual(len(jobs),1);self.assertEqual(jobs[0]['id'],'nara:7')
        self.assertEqual(jobs[0]['closes_at'],'2026-11-01T17:00:00+09:00')
        self.assertIn('기간제',jobs[0]['tags']);self.assertEqual(jobs[0]['career'],'')

    def test_nara_xml_and_singleton(self):
        c={**NARA,'format':'xml'}
        xml=b'<response><header><resultCode>00</resultCode></header><body><totalCount>1</totalCount><items><item><notice>7</notice></item></items></body></response>'
        rows,total=parse_page(xml,c);self.assertEqual(total,1);self.assertEqual(rows[0]['notice_id'],'7')

    def test_nara_empty_and_malformed_response(self):
        self.assertEqual(parse_page(page([],0),NARA),([],0))
        for data in [b'broken',b'{}',page('invalid',2),page([None],1),page([], -1)]:
            with self.assertRaises(SourceError):parse_page(data,NARA)
        with self.assertRaises(SourceError):parse_page(b'<!DOCTYPE x><x/>',{**NARA,'format':'xml'})

    def test_busan_fixture_never_uses_publication_date_as_deadline(self):
        rows,next_url=parse_feed((FIXTURES/'busan-contract.xml').read_bytes(),BUSAN)
        self.assertTrue(next_url.endswith('page=2'))
        jobs=normalize(rows,'busan','부산광역시',NOW)
        self.assertEqual(len(jobs),1);self.assertEqual(jobs[0]['deadline'],'2026-11-01')
        self.assertIsNone(jobs[0]['start']);self.assertIn('공무직',jobs[0]['tags'])

    def test_atom_attribute_and_bad_feeds(self):
        c={**BUSAN,'format':'atom','items_path':'a:entry','namespaces':{'a':'http://www.w3.org/2005/Atom'},
           'fields':{'source_url':'a:link@href','title':'a:title'},'next_path':None}
        rows,_=parse_feed(b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Job</title><link href="https://www.busan.go.kr/7"/></entry></feed>',c)
        self.assertEqual(rows[0]['source_url'],'https://www.busan.go.kr/7')
        for data in [b'<html/>',b'<!DOCTYPE x><rss/>',b'not xml']:
            with self.assertRaises(SourceError):parse_feed(data,BUSAN)

    def test_timezone_and_exact_deadline(self):
        rows=[row(deadline='2026-11-01T03:00:00Z')]
        self.assertEqual(len(normalize(rows,'nara','나라일터',NOW)),1)
        self.assertEqual(normalize(rows,'nara','나라일터',NOW+dt.timedelta(seconds=1)),[])
        self.assertEqual(closing('2026-11-01T23:59:00')[1],'2026-11-01T23:59:00+09:00')
        self.assertEqual(normalize([row(deadline='2026-02-30')],'nara','나라일터',NOW),[])
        self.assertEqual(normalize([row(start='2026-11-02')],'nara','나라일터',NOW),[])
        self.assertEqual(normalize([row(start='broken')],'nara','나라일터',NOW),[])

    def test_classification_keeps_unknown_and_categories(self):
        self.assertEqual(classify('일반채용',''),[])
        self.assertEqual(classify('채용','정규직'),['기타'])
        self.assertEqual(classify('기간제 모집','기간제'),['기간제'])
        self.assertEqual(classify('채용','무기계약직'),['무기계약직'])
        self.assertNotIn('경력무관',normalize([row(career='신입+경력')],'nara','나라일터',NOW)[0]['tags'])


class CollectionTests(unittest.TestCase):
    def nara_http(self, pages):
        h=Mock();h.allowed.return_value=True;h.original.return_value=True;h.get.side_effect=pages
        return h

    def test_pagination(self):
        rows=[{'notice':'1'},{'notice':'2'}]
        http=self.nara_http([page(rows[:1],2),page(rows[1:],2)])
        with patch.dict('os.environ',{'NARA_API_KEY':'synthetic-test-key'}):
            result=NaraCollector(NARA,http).collect()
        self.assertEqual(http.get.call_count,2)
        self.assertEqual(result,[])  # No closing dates or URLs were invented.

    def test_bad_pagination_preserves_snapshot(self):
        cases=[[page([{'notice':'1'}],2),page([],2)],
               [page([{'notice':'1'}],2),page([{'notice':'1'}],2)],
               [page([{'notice':'1'}],2),page([{'notice':'2'}],3)]]
        for pages in cases:
            with patch.dict('os.environ',{'NARA_API_KEY':'synthetic-test-key'}):
                with self.assertRaises(SourceError):NaraCollector(NARA,self.nara_http(pages)).collect()

    def test_review_and_key_gates_before_network(self):
        http=Mock()
        for config in [{**NARA,'enabled':False},{**NARA,'review':{}},{**NARA,'original_hosts':[]}]:
            with self.assertRaises(SourceError):NaraCollector(config,http).collect()
        with patch.dict('os.environ',{},clear=True):
            with self.assertRaises(SourceError):NaraCollector(NARA,http).collect()
        http.get.assert_not_called()
        with self.assertRaises(SourceError):BusanCollector({**BUSAN,'format':'html'},http).collect()
        http.get.assert_not_called()

    def test_busan_pagination_and_robots(self):
        data=(FIXTURES/'busan-contract.xml').read_bytes()
        second=b'<rss><channel/></rss>'
        h=Mock();h.allowed.return_value=True;h.original.return_value=True;h.get.side_effect=[data,second]
        with patch('collectors.busan.normalize',return_value=[{'source_url':'https://www.busan.go.kr/notice/7'}]):
            self.assertEqual(len(BusanCollector(BUSAN,h).collect()),1)
        self.assertEqual(h.get.call_count,2)
        h=Mock();h.allowed.return_value=False
        with self.assertRaises(SourceError):BusanCollector(BUSAN,h).collect()
        h.get.assert_not_called()

    def test_busan_pagination_loop_and_external_link_refused(self):
        data=(FIXTURES/'busan-contract.xml').read_bytes()
        h=Mock();h.allowed.return_value=True;h.get.return_value=data
        with self.assertRaises(SourceError):BusanCollector(BUSAN,h).collect()
        h.get.return_value=data.replace(b'https://www.busan.go.kr/supported-feed?page=2',b'https://evil.invalid/feed')
        with self.assertRaises(SourceError):BusanCollector(BUSAN,h).collect()

    def test_busan_supported_json_api(self):
        config={**NARA,'endpoint':'https://www.busan.go.kr/synthetic-api','original_hosts':['www.busan.go.kr']}
        http=self.nara_http([page([{'notice':'7'}],1)])
        self.assertEqual(BusanCollector(config,http).collect(),[])
        self.assertEqual(http.get.call_count,1)

    def test_known_missing_original_excluded_unknown_transport_fails_source(self):
        http=OfficialHTTP(['agency.go.kr'])
        with patch.object(http,'allowed',return_value=False):
            self.assertFalse(http.original('https://agency.go.kr/7'))
        with patch.object(http,'allowed',return_value=True),patch.object(http,'get',side_effect=SourceError('Original not found')):
            self.assertFalse(http.original('https://agency.go.kr/7'))
        with patch.object(http,'allowed',return_value=True),patch.object(http,'get',side_effect=SourceError('Official source transport failed')):
            with self.assertRaises(SourceError):http.original('https://agency.go.kr/7')

    def test_unapproved_destinations_and_encoded_secrets_refused(self):
        self.assertIsNone(canonical_url('https://agency.go.kr/7?service%4Bey=synthetic'))
        http=OfficialHTTP(['www.busan.go.kr'])
        for url in ['https://evil.invalid/api','http://www.busan.go.kr/api']:
            with self.assertRaises(SourceError):http.get(url)

    def test_rate_limit_applies_before_request(self):
        http=OfficialHTTP(['agency.go.kr'],min_interval=2)
        http.last['agency.go.kr']=9
        response=Mock();response.status=200;response.read.return_value=b'ok'
        opener=Mock();opener.open.return_value.__enter__=Mock(return_value=response)
        opener.open.return_value.__exit__=Mock(return_value=False)
        with patch('collectors.common.time.monotonic',return_value=10),patch('collectors.common.time.sleep') as sleep, \
             patch('collectors.common.build_opener',return_value=opener):
            self.assertEqual(http.get('https://agency.go.kr/notice'),'ok'.encode())
            sleep.assert_called_once_with(1)

    def test_robots_disallow_and_crawl_delay(self):
        http=OfficialHTTP(['agency.go.kr'])
        with patch.object(http,'get',return_value=b'User-agent: *\nDisallow: /private\nCrawl-delay: 5\n'):
            self.assertFalse(http.allowed('https://agency.go.kr/private/7'))
            self.assertTrue(http.allowed('https://agency.go.kr/public/7'))
            self.assertEqual(http.min_interval,5)


class MergeTests(unittest.TestCase):
    def test_same_numeric_ids_do_not_collide(self):
        jobs=[job('alio'),job('nara',url='https://agency.go.kr/other/7')]
        self.assertEqual(len(merge(jobs,NOW)),2)

    def test_generic_landing_url_does_not_drop_different_announcements(self):
        a=job('alio',ident='1',title='첫 번째 공고')
        b=job('alio',ident='2',title='다른 공고')
        self.assertEqual(len(merge([a,b],NOW)),2)
        self.assertEqual(canonical_url('https://agency.go.kr:8443/notice'),
                         'https://agency.go.kr:8443/notice')

    def test_canonical_duplicates_and_provenance(self):
        jobs=[job('alio',url='https://agency.go.kr/n?id=7&utm_source=a#frag'),
              job('nara',url='https://AGENCY.go.kr:443/n?id=7')]
        merged=merge(jobs,NOW)
        self.assertEqual(len(merged),1)
        self.assertEqual({a['source_id'] for a in merged[0]['attributions']},{'alio','nara'})

    def test_agency_notice_number_and_transitive_duplicates(self):
        a=job('alio',agency_id='official-code',announcement_number='2026-7')
        b=job('nara',url='https://agency.go.kr/other/7',agency_id='official-code',announcement_number='2026-7')
        c=job('busan',url=b['source_url'])
        self.assertEqual(len(merge([a,b,c],NOW)),1)
        self.assertEqual(len(merge([a,job('nara',url=b['source_url'],agency_id='other-code',announcement_number='2026-7')],NOW)),2)

    def test_expiry_and_unsafe_url(self):
        a=job();a['deadline']='2026-10-31'
        b=job('nara');b['source_url']='https://127.0.0.1/notice'
        self.assertEqual(merge([a,b],NOW),[])

    def test_source_failure_never_loses_other_source_and_timestamp(self):
        old={'jobs':[job()],'updated_at':NOW.isoformat(),'mode':'alio-public-preview','originals_verified':True}
        new=[job('nara',url='https://agency.go.kr/nara/7')]
        feed,cache=run({'nara':{'enabled':True}},{},{'alio':old},
                       {'alio':Mock(side_effect=RuntimeError('must not log secret')),'nara':lambda:new},NOW+dt.timedelta(hours=1))
        self.assertEqual(len(feed['jobs']),2)
        self.assertEqual(feed['sources']['alio']['status'],'cached')
        self.assertEqual(feed['sources']['alio']['updated_at'],old['updated_at'])
        self.assertNotIn('must not log',json.dumps(feed))
        self.assertEqual(cache['alio'],old)

    def test_successful_empty_source_clears_only_that_source(self):
        old={'jobs':[job()],'updated_at':NOW.isoformat()}
        feed,_=run({'nara':{'enabled':True}},{},{'alio':old},
                   {'alio':Mock(side_effect=SourceError('unavailable')),'nara':lambda:[]},NOW)
        self.assertEqual(len(feed['jobs']),1);self.assertEqual(feed['sources']['nara']['count'],0)
        self.assertEqual(feed['sources']['nara']['status'],'ok')

    def test_legacy_migration_preserves_time_and_does_not_claim_original_check(self):
        previous={'jobs':[row(id='7')],'updated_at':NOW.isoformat(),'source':'alio-public-preview'}
        feed,_=run({},previous,{}, {'alio':Mock(side_effect=SourceError('unavailable'))},NOW)
        self.assertEqual(len(feed['jobs']),1);self.assertEqual(feed['updated_at'],NOW.isoformat())
        self.assertFalse(feed['sources']['alio']['originals_verified'])
        self.assertEqual(feed['sources']['nara']['status'],'disabled')

    def test_failed_new_sources_keep_their_independent_snapshots(self):
        snapshots={source:{'jobs':[job(source,url=f'https://agency.go.kr/{source}/7')],
                           'updated_at':NOW.isoformat(),'mode':'official-api'} for source in ('alio','nara','busan')}
        runners={source:Mock(side_effect=SourceError('offline')) for source in snapshots}
        runners['alio']=lambda:snapshots['alio']
        feed,_=run({'nara':{'enabled':True},'busan':{'enabled':True}},{},snapshots,runners,NOW)
        self.assertEqual(len(feed['jobs']),3)
        self.assertEqual(feed['sources']['alio']['status'],'ok')
        self.assertEqual(feed['sources']['nara']['status'],'cached')
        self.assertEqual(feed['sources']['busan']['status'],'cached')

    def test_no_secret_can_be_serialized(self):
        with patch.dict('os.environ',{'NARA_API_KEY':'synthetic-test-key'}):
            with self.assertRaises(SourceError):sanitize_serialized({'title':'synthetic-test-key'})


if __name__=='__main__':unittest.main()
