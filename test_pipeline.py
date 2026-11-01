import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import collect
import build

TODAY = dt.date(2026, 11, 1)


def record(**fields):
    return dict(recrutPblntSn=1, instNm='기관', recrutPbancTtl='채용',
                pbancBgngYmd='20261001', pbancEndYmd='20261130',
                srcUrl='https://example.org/notice', ongoingYn='Y', **fields)


class PipelineTests(unittest.TestCase):
    def test_invalid_dates(self):
        for value in [None, '', '20260230', '2026-13-01', 'not-a-date']:
            self.assertIsNone(collect.date_of(value))

    def test_start_end_and_status(self):
        for changes in [{'pbancEndYmd':'20261031'}, {'pbancBgngYmd':'20261102'},
                        {'ongoingYn':'N'}, {'pbancEndYmd':None}]:
            r=record();r.update(changes)
            self.assertEqual(collect.normalize([r],TODAY),[])
        r=record();r['pbancEndYmd']='20261101'
        self.assertEqual(len(collect.normalize([r],TODAY)),1)

    def test_explicit_classification_only(self):
        r=record(hireTypeNmLst='무기계약직',acbgCondNmLst='학력무관',recrutSeNm='신입+경력')
        r['recrutPbancTtl']='공무직 채용'
        j=collect.normalize([r],TODAY)[0]
        self.assertEqual(j['tags'],['공무직','무기계약직','학력무관'])
        self.assertNotIn('경력무관',j['tags'])
        r['recrutSeNm']='경력무관'
        self.assertIn('경력무관',collect.normalize([r],TODAY)[0]['tags'])

    def test_unknown_not_inferred_from_title(self):
        r=record();r['recrutPbancTtl']='학력무관 경력무관 신입 채용'
        j=collect.normalize([r],TODAY)[0]
        self.assertEqual(j['education'],'');self.assertEqual(j['career'],'')
        self.assertEqual(j['tags'],[])

    def test_unsafe_links(self):
        for url in ['javascript:alert(1)','http://example.org','https://user:password@example.org',
                    'https://example.org/?serviceKey=secret','https://example.org/\nfoo']:
            self.assertIsNone(collect.safe_url(url))

    def test_only_public_fields(self):
        r=record(serviceKey='sensitive',internal='private')
        j=collect.normalize([r],TODAY)[0]
        self.assertNotIn('serviceKey',j);self.assertNotIn('internal',j)

    def test_detail_id_must_match(self):
        with patch('collect.request',return_value={'result':{'recrutPblntSn':2}}):
            with self.assertRaises(collect.ApiError):collect.fetch_detail(1)

    def test_gateway_error_never_leaks_secret_or_response(self):
        response=MagicMock();response.__enter__.return_value=response
        opener=MagicMock();opener.open.return_value=response
        with patch.dict('os.environ',{'ALIO_API_KEY':'test-secret','ALIO_BASE_URL':collect.BASE}), \
             patch('collect.build_opener',return_value=opener),patch('collect.time.sleep'), \
             patch('collect.json.load',return_value={'resultCode':'5','resultMsg':'test-secret'}):
            with self.assertRaises(collect.ApiError) as ctx:collect.fetch_page(1)
            self.assertNotIn('test-secret',str(ctx.exception));self.assertIn('5',str(ctx.exception))
            self.assertEqual(opener.open.call_count,3)

    def test_failure_preserves_existing_feed(self):
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'jobs.json';target.write_text('existing')
            with patch('collect.ROOT',Path(temp)),patch('sys.argv',['collect.py']), \
                 patch('collect.collect',side_effect=collect.ApiError('upstream unavailable')):
                with self.assertRaises(SystemExit) as ctx:collect.main()
                self.assertEqual(ctx.exception.code,1)
                self.assertEqual(target.read_text(),'existing')

    def test_incomplete_pagination_fails(self):
        with patch('collect.fetch_page',side_effect=[{'result':[record()], 'totalCount':2},
                                                   {'result':[], 'totalCount':2}]):
            with self.assertRaises(collect.ApiError):collect.collect()

    def test_collect_checks_details_and_provenance(self):
        r=record();r['pbancEndYmd']='20991231'
        for public in [False,True]:
            with patch('collect.fetch_page',return_value={'result':[r],'totalCount':1}), \
                 patch('collect.fetch_detail',return_value=r) as detail:
                feed=json.loads(collect.collect(public))
                self.assertEqual(len(feed['jobs']),1)
                self.assertEqual(feed['authenticated_api_verified'],not public)
                detail.assert_called_once_with('1',public)

    def test_credential_reflection_refuses_publication(self):
        r=record();r['pbancEndYmd']='20991231';r['recrutPbancTtl']='sensitive-secret'
        with patch.dict('os.environ',{'ALIO_API_KEY':'sensitive-secret'}), \
             patch('collect.fetch_page',return_value={'result':[r],'totalCount':1}), \
             patch('collect.fetch_detail',return_value=r):
            with self.assertRaises(collect.ApiError):collect.collect()

    def test_build_has_only_allowlisted_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            out=build.build(Path(temp)/'site')
            self.assertEqual({p.name for p in out.iterdir()},set(build.PUBLIC)|{'.nojekyll'})
            self.assertNotIn('collect.py',{p.name for p in out.iterdir()})


if __name__ == '__main__':
    unittest.main()
