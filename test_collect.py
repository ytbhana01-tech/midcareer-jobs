import datetime as dt
import unittest
from collect import normalize, date_of

class CollectTests(unittest.TestCase):
    def test_date_formats(self):
        self.assertEqual(date_of("2026-12-01"), dt.date(2026,12,1))
        self.assertEqual(date_of("20261201"), dt.date(2026,12,1))
    def test_filter_and_dedupe(self):
        record = {"id":"1","org":"기관","title":"채용","deadline":"2026-12-01","source_url":"https://example.org/notice"}
        self.assertEqual(len(normalize([record,record], dt.date(2026,11,1))),1)
        self.assertEqual(len(normalize([record], dt.date(2026,12,2))),0)
    def test_insecure_url_rejected(self):
        record = {"id":"1","org":"기관","title":"채용","deadline":"2026-12-01","source_url":"javascript:alert(1)"}
        self.assertEqual(normalize([record], dt.date(2026,11,1)),[])

if __name__ == "__main__":
    unittest.main()
