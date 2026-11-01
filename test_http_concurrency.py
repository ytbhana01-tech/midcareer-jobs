"""Concurrency preserves origin request intervals and one robots-policy load."""
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch
from collectors.common import OfficialHTTP

class HTTPConcurrencyTests(unittest.TestCase):
    def test_parallel_responses_do_not_burst_request_starts(self):
        http=OfficialHTTP(['agency.go.kr'])
        # A shorter test clock interval exercises the same limiter; production
        # configuration is clamped to at least one second by the constructor.
        self.assertGreaterEqual(http.min_interval,1)
        http.min_interval=.04
        starts=[];active=0;maximum=0;guard=threading.Lock()
        class Response:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,size):return b'ok'
        def open_request(*args,**kwargs):
            nonlocal active,maximum
            with guard:
                starts.append(time.monotonic());active+=1;maximum=max(maximum,active)
            time.sleep(.15)  # Slow response, without holding the dispatch lock.
            with guard:active-=1
            return Response()
        opener=Mock();opener.open.side_effect=open_request
        with patch('collectors.common.build_opener',return_value=opener),ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(list(pool.map(http.get,['https://agency.go.kr/'+str(n) for n in range(6)])),[b'ok']*6)
        self.assertGreater(maximum,1)
        self.assertTrue(all(b-a>=.03 for a,b in zip(starts,starts[1:])),starts)

    def test_concurrent_originals_share_one_robots_fetch(self):
        http=OfficialHTTP(['agency.go.kr'])
        calls=[]
        def robots(*args,**kwargs):
            calls.append(args[0]);time.sleep(.03)
            return b'User-agent: *\nDisallow: /private\nCrawl-delay: 2\n'
        with patch.object(http,'get',side_effect=robots),ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(list(pool.map(http.allowed,['https://agency.go.kr/public']*8)),[True]*8)
        self.assertEqual(calls,['https://agency.go.kr/robots.txt'])
        self.assertEqual(http.min_interval,2)
        self.assertFalse(http.allowed('https://agency.go.kr/private'))

if __name__=='__main__':unittest.main()
