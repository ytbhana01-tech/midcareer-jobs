"""Real API contract regression tests; fixtures retrieved in Actions on 2026-11-01."""
import copy
import datetime as dt
import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock, patch
from collectors.common import KST, SourceError, OfficialHTTP, normalize
from collectors.nara import NaraCollector, plain, original_url
from collect_all import merge, collect_alio

ROOT=Path(__file__).parent
NOW=dt.datetime(2026,11,1,12,tzinfo=KST)

class Clock(dt.datetime):
    @classmethod
    def now(cls,tz=None):return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

class OfficialNaraTests(unittest.TestCase):
    def setUp(self):
        self.config=json.loads((ROOT/'sources.json').read_text())['nara']
        self.list=ET.parse(ROOT/'tests/fixtures/nara-live-list.xml').getroot()
        self.list.find('body/totalCount').text='2'
        self.list.findall('body/items/item')[1].find('enddate').text='20261031'
        self.detail=(ROOT/'tests/fixtures/nara-live-detail.xml').read_bytes()
        self.http=Mock();self.http.original.return_value=True

    def collect(self,details=None):
        self.http.get.side_effect=[ET.tostring(self.list),self.detail if details is None else details]
        collector=NaraCollector(self.config,self.http)
        with patch.dict('os.environ',{'NARA_API_KEY':'synthetic-key'}),patch('collectors.nara.dt.datetime',Clock):
            jobs=collector.collect()
        return jobs,collector.stats

    def test_live_list_detail_normalization_and_original_validation(self):
        jobs,stats=self.collect()
        self.assertEqual(len(jobs),1)
        job=jobs[0]
        self.assertEqual(job['id'],'nara:289736')
        self.assertEqual(job['deadline'],'2026-11-09')
        self.assertIsNone(job['start'])
        self.assertEqual(job['region'],'경기')
        self.assertEqual(job['published_date'],'2026-10-26')
        self.assertIn('기간제',job['tags'])
        self.assertNotIn('경력무관',job['tags'])
        self.assertIn('원서접수기간',job['description'])
        self.assertNotIn('&amp;',job['agency_url'])
        self.http.original.assert_called_once_with(job['source_url'],expected_text=job['title'])
        self.assertEqual(stats['expired_or_invalid'],1)
        # API authorization uses the reviewed API contract, not the gateway's
        # /robots.txt route, which returns NO_OPENAPI_SERVICE_ERROR (400).
        self.http.allowed.assert_not_called()
        for call in self.http.get.call_args_list:self.assertTrue(call.kwargs['allow_credentials'])

    def test_list_detail_mismatch_and_api_error_refuse_publication(self):
        for value in ('<idx>999</idx>','<title>Different job</title>','<insttname>Different agency</insttname>','<enddate>20261110</enddate>'):
            root=ET.fromstring(self.detail)
            replacement=ET.fromstring(value)
            root.find('body/item/'+replacement.tag).text=replacement.text
            with self.assertRaises(SourceError):self.collect(ET.tostring(root))
        self.http.get.side_effect=None
        self.http.get.return_value=b'<response><header><resultCode>30</resultCode></header></response>'
        with patch.dict('os.environ',{'NARA_API_KEY':'synthetic-key'}):
            with self.assertRaises(SourceError):NaraCollector(self.config,self.http).collect()

    def test_one_inconsistent_record_does_not_remove_other_verified_jobs(self):
        item=copy.deepcopy(self.list.findall('body/items/item')[0])
        item.find('idx').text='999999'
        self.list.find('body/items').append(item)
        self.list.find('body/totalCount').text='3'
        self.http.get.side_effect=[ET.tostring(self.list),self.detail,self.detail]
        collector=NaraCollector(self.config,self.http)
        with patch.dict('os.environ',{'NARA_API_KEY':'synthetic-key'}),patch('collectors.nara.dt.datetime',Clock):
            result=collector.collect()
        self.assertEqual([j['id'] for j in result],['nara:289736'])
        self.assertEqual(collector.stats['detail_mismatch'],1)
        self.assertEqual(collector.stats['published'],1)

    def test_credential_reflection_and_original_failure_fail_closed(self):
        with self.assertRaises(SourceError):self.collect(self.detail.replace(b'NORMAL SERVICE.',b'synthetic-key'))
        self.http.original.side_effect=SourceError('Official source transport failed')
        with patch('collectors.nara.time.sleep'):
            with self.assertRaises(SourceError):self.collect()

    def test_api_paging_is_checked(self):
        self.list.find('body/pageNo').text='2'
        with self.assertRaises(SourceError):self.collect()
        self.list.find('body/pageNo').text='1'
        items=self.list.find('body/items')
        items[1].find('idx').text=items[0].findtext('idx')
        with self.assertRaises(SourceError):self.collect()

    def test_plain_text_discards_executable_markup_and_keeps_readable_lines(self):
        text=plain('&lt;p&gt;지원 조건&lt;/p&gt;&lt;script&gt;alert(1)&lt;/script&gt;&lt;p&gt;접수&lt;/p&gt;')
        self.assertEqual(text,'지원 조건\n접수')
        self.assertIsNone(original_url('http://www.gojobs.go.kr/old',['www.gojobs.go.kr']))
        self.assertIsNone(original_url('https://other.example/notice',['www.gojobs.go.kr']))
        self.assertEqual(original_url('www.gojobs.go.kr/x?a=1&amp;amp;b=2',['www.gojobs.go.kr']),'https://www.gojobs.go.kr/x?a=1&b=2')

    def test_original_200_must_contain_the_expected_notice(self):
        http=OfficialHTTP(['www.gojobs.go.kr'])
        with patch.object(http,'allowed',return_value=True),patch.object(http,'get',return_value=b'<html><h1>Different notice</h1></html>'):
            with self.assertRaises(SourceError):http.original('https://www.gojobs.go.kr/test',expected_text='Expected notice')
        with patch.object(http,'allowed',return_value=True),patch.object(http,'get',return_value=b'<html><h1>Expected &amp; notice</h1></html>'):
            self.assertTrue(http.original('https://www.gojobs.go.kr/test',expected_text='Expected & notice'))

    def test_literal_title_angles_and_undocumented_begin_date(self):
        title='공무직 <조리원> 채용'
        self.list.findall('body/items/item')[0].find('title').text=title
        detail=ET.fromstring(self.detail)
        detail.find('body/item/title').text=title
        detail.find('body/item/begindate').text='20261105'
        jobs,_=self.collect(ET.tostring(detail))
        self.assertEqual(jobs[0]['title'],title)
        self.assertIsNone(jobs[0]['start'])
        http=OfficialHTTP(['www.gojobs.go.kr'])
        with patch.object(http,'allowed',return_value=True),patch.object(http,'get',return_value='<h1>공무직 &lt;조리원&gt; 채용</h1>'.encode()):
            self.assertTrue(http.original('https://www.gojobs.go.kr/test',expected_text=title))

    def test_alio_keeps_the_existing_list_detail_fallback_without_extra_crawling(self):
        record={'id':'7','title':'공무직 채용','org':'기관','deadline':'2026-11-09',
                'source_url':'https://agency.go.kr/notice/7'}
        feed={'jobs':[record],'updated_at':NOW.isoformat(),'source':'alio-public-preview'}
        import collect
        with patch('collect_all.alio.collect',side_effect=[collect.ApiError('API unavailable'),json.dumps(feed)] ) as collector:
            snapshot=collect_alio()
        self.assertEqual([c.args[0] for c in collector.call_args_list],[False,True])
        self.assertEqual(snapshot['jobs'][0]['id'],'alio:7')
        self.assertEqual(snapshot['jobs'][0]['source_url'],record['source_url'])
        self.assertFalse(snapshot['originals_verified'])

    def test_verified_agency_alias_deduplicates_and_keeps_attribution(self):
        nara=self.collect()[0][0]
        alio=copy.deepcopy(nara)
        alio.update(id='alio:289736',source_id='alio',source_name='ALIO',source_url=nara['agency_url'])
        result=merge([alio,nara],NOW)
        self.assertEqual(len(result),1)
        self.assertEqual({a['source_id'] for a in result[0]['attributions']},{'alio','nara'})
        nara['title']+=' 별도 모집'
        self.assertEqual(len(merge([alio,nara],NOW)),2)

if __name__=='__main__':unittest.main()
