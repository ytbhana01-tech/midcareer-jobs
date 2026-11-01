"""Bounded Actions-only contract probe; never persist credentials or request URLs."""
import datetime as dt
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlencode, unquote
from urllib.request import Request, build_opener
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from collect import NoRedirect
from collectors.common import sanitize_serialized

out=Path('nara-validation');out.mkdir(exist_ok=True)
key=os.environ.get('NARA_API_KEY','').strip()
if not key:raise SystemExit('NARA_API_KEY is not available to this workflow')
key=unquote(key)
summary=[]
for sort in ('desc','내림차순'):
    params={'serviceKey':key,'pageNo':1,'numOfRows':2,'Pblanc_ty':'e04','Instt_se':'','Sort_order':sort,'Begin_de':(dt.date.today()-dt.timedelta(days=30)).isoformat(),'End_de':dt.date.today().isoformat()}
    try:
        request=Request('https://apis.data.go.kr/1760000/PblJobService/getList?'+urlencode(params),headers={'User-Agent':'MidcareerJobsBot/1.0'})
        with build_opener(NoRedirect()).open(request,timeout=40) as r:body=r.read(2_000_000);status=r.status
    except HTTPError as e:body=e.read(100_000);status=e.code
    except Exception:summary.append({'sort':sort,'transport_error':True});continue
    if key.encode() in body or os.environ['NARA_API_KEY'].encode() in body:raise SystemExit('Credential reflection refused')
    try:
        root=ET.fromstring(body)
        summary.append({'sort':sort,'http_status':status,'root':root.tag,'code':root.findtext('.//resultCode') or root.findtext('.//returnReasonCode'),'total':root.findtext('.//totalCount')})
        if root.find('.//items/item') is not None:
            (out/'list.xml').write_text(sanitize_serialized({'xml':body.decode('utf-8')}))
            idx=root.findtext('.//items/item/idx')
            time.sleep(1)
            with build_opener(NoRedirect()).open('https://apis.data.go.kr/1760000/PblJobService/getItem?'+urlencode({'serviceKey':key,'idx':idx}),timeout=40) as r:detail=r.read(2_000_000)
            if key.encode() in detail:raise SystemExit('Credential reflection refused')
            (out/'detail.xml').write_text(sanitize_serialized({'xml':detail.decode('utf-8')}))
            print('sample',sort,(out/'list.xml').read_text(),(out/'detail.xml').read_text())
    except ET.ParseError:summary.append({'non_xml_response':True})
    time.sleep(1)
(out/'summary.json').write_text(sanitize_serialized(summary))
print(json.dumps(summary,ensure_ascii=False))

for sample in ('list.xml','detail.xml'):
    if (out/sample).exists():print(sample, (out/sample).read_text())
