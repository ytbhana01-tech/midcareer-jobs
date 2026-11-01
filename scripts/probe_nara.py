"""Review the official public detail route without credentials."""
import re
import time
from urllib.request import urlopen, Request
from urllib.error import HTTPError
cases=[
('robots','https://www.gojobs.go.kr/robots.txt',None),
('get','https://www.gojobs.go.kr/apmView.do?menuNo=401&empmnsn=289736&searchJobsecode=020&flag=U',None),
('get-minimal','https://www.gojobs.go.kr/apmView.do?empmnsn=289736',None),
('post','https://www.gojobs.go.kr/apmView.do',b'menuNo=401&empmnsn=289736&searchJobsecode=020&flag=U'),
('bai','https://www.bai.go.kr/bai/notice/notification/detail?tabId=tab03&brdId=BAK_0003&postNo=1160',None)]
for label,url,data in cases:
    try:
        with urlopen(Request(url,data=data,headers={'User-Agent':'MidcareerJobsBot/1.0'}),timeout=20) as r:
            text=r.read(2_000_000).decode('utf-8',errors='replace')
            print(label,r.status,'matched:', '감사교육원 기간제근로자(조리원) 신규채용' in text,'title:',re.findall('<title>(.*?)</title>',text,re.S),text if label=='robots' else '')
    except Exception as error:print(label,type(error).__name__,getattr(error,'code',None))
    time.sleep(1)
