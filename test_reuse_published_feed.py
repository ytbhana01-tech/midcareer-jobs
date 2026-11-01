import copy
import datetime as dt
import unittest
from scripts.reuse_published_feed import validate_feed

class ReusePublishedFeedTests(unittest.TestCase):
    def setUp(self):
        self.now=dt.datetime(2026,11,2,tzinfo=dt.timezone.utc)
        self.feed={'source':'multi-source','updated_at':'2026-11-01T22:01:31+09:00',
          'jobs':[{'id':'alio:1'},{'id':'nara:1'}],
          'sources':{'alio':{'status':'ok','updated_at':'2026-11-01T21:42:07+09:00'},
                     'nara':{'status':'ok','updated_at':'2026-11-01T22:01:31+09:00','mode':'official-api','originals_verified':True}}}
    def test_reuse_preserves_original_data_and_times(self):
        before=copy.deepcopy(self.feed)
        validate_feed(self.feed,self.now)
        self.assertEqual(self.feed,before)
    def test_unverified_and_future_snapshots_are_rejected(self):
        for changes in ({'originals_verified':False},{'status':'unavailable'},{'updated_at':'2026-11-03T12:00:00+09:00'}):
            feed=copy.deepcopy(self.feed);feed['sources']['nara'].update(changes)
            with self.assertRaises(ValueError):validate_feed(feed,self.now)
        self.feed['jobs'].append({'id':'nara:1'})
        with self.assertRaises(ValueError):validate_feed(self.feed,self.now)

if __name__=='__main__':unittest.main()
