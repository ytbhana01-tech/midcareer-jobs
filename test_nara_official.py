"""Real API contract regression tests; fixtures retrieved in Actions on 2026-11-01."""
import copy
import datetime as dt
import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock, patch
from collectors.common import KST, SourceError, normalize
from collectors.nara import NaraCollector, plain, original_url
from collect_all import merge

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
