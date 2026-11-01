"""나라일터 adapter for dataset 15156780. Mapping MUST come from reviewed official docs.

No endpoint or vendor field names are guessed. Disabled until the official contract,
permission and credential have been confirmed. JSON/XML envelope paths are configurable.
"""
import datetime as dt
import html
import re
import time
from html.parser import HTMLParser
import json
import os
import xml.etree.ElementTree as ET
from urllib.parse import urlencode, urlsplit, unquote
from collectors.common import OfficialHTTP, SourceError, normalize, reviewed, KST, canonical_url, closing


def at(value, path):
    for part in (path or '').split('.'):
        if not part:
            continue
        if not isinstance(value,dict) or part not in value:
            raise SourceError('Unexpected official API schema')
        value=value[part]
    return value


def xml_value(node):
    children=list(node)
    if not children:
        return node.text or ''
    result={}
    for child in children:
        key=child.tag.split('}')[-1]
        value=xml_value(child)
        if key in result:
            if not isinstance(result[key],list):result[key]=[result[key]]
            result[key].append(value)
        else:result[key]=value
    return result


def parse_page(data, config):
    try:
        if config['format']=='json':
            payload=json.loads(data)
        elif config['format']=='xml':
            if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
                raise SourceError('DTD/entity XML refused')
            root=ET.fromstring(data)
            payload={root.tag.split('}')[-1]:xml_value(root)}
        else:
            raise SourceError('Unsupported official API format')
        if str(at(payload,config['success_path'])) not in config['success_codes']:
            raise SourceError('Official API rejected request')
        total=int(at(payload,config['total_path']))
        try:
            items=at(payload,config['items_path'])
        except SourceError:
            # The official XML service emits <items/> when there are no rows.
            if total != 0:raise
            items=[]
        if isinstance(items,dict):items=[items]
        if items in ('',None) and total==0:items=[]
        if not isinstance(items,list) or total<0:
            raise SourceError('Invalid API page metadata')
        rows=[]
        for item in items:
            if not isinstance(item,dict):
                raise SourceError('Malformed API record')
            # Optional absent fields remain absent; required fields fail normalization.
            rows.append({key:item.get(field) for key,field in config['fields'].items() if field})
        return rows,total
    except (ValueError,TypeError,KeyError,ET.ParseError,UnicodeError):
        raise SourceError('Malformed official API response') from None


class NaraCollector:
    source_id='nara'
    source_name='나라일터 · 인사혁신처'

    def __init__(self,config,http=None):
        self.config=config
        self.http=http or OfficialHTTP(['apis.data.go.kr',*config.get('original_hosts',[])],config.get('min_interval',1))

    def collect(self):
        c=self.config
        reviewed(c)
        if c.get('contract')=='pbljob-v1':
            return self.collect_official()
        required=('format','key_parameter','page_parameter','size_parameter','success_path','success_codes','total_path','items_path')
        if not all(c.get(k) for k in required):
            raise SourceError('Verified API envelope and parameter mapping required')
        if urlsplit(c['endpoint']).hostname!='apis.data.go.kr' or urlsplit(c['endpoint']).query:
            raise SourceError('Unapproved 나라일터 API endpoint')
        key=os.environ.get('NARA_API_KEY')
        if not key:
            raise SourceError('NARA_API_KEY missing; source not activated')
        if not self.http.allowed(c['endpoint']):
            raise SourceError('Official robots policy disallows API access')
        records=[];expected=None
        for page in range(1,101):
            params={**c.get('params',{}),c['key_parameter']:key,c['page_parameter']:page,c['size_parameter']:100}
            data=self.http.get(c['endpoint']+'?'+urlencode(params),allow_credentials=True)
            rows,total=parse_page(data,c)
            if expected is None:expected=total
            if total!=expected:
                raise SourceError('API pagination total changed')
            records.extend(rows)
            if len(records)>=total:
                if len(records)!=total:raise SourceError('API pagination count mismatch')
                break
            if not rows:raise SourceError('Incomplete API pagination')
        else:raise SourceError('API pagination limit exceeded')
        identifiers=[str(r.get('notice_id') or '') for r in records]
        if len(set(identifiers))!=len(identifiers) or not all(identifiers):
            raise SourceError('Duplicate/missing API notice IDs')
        jobs=normalize(records,self.source_id,self.source_name)
        return [job for job in jobs if self.http.original(job['source_url'])]

    def api(self, operation, params):
        # Access is authorized by this exact reviewed API contract. The API
        # gateway returns NO_OPENAPI_SERVICE_ERROR for /robots.txt (HTTP 400);
        # website robots rules remain mandatory for the public originals.
        key=unquote(os.environ.get('NARA_API_KEY','').strip())
        if not key:raise SourceError('NARA_API_KEY missing; source not activated')
        endpoint='https://apis.data.go.kr/1760000/PblJobService/'+operation
        for attempt in range(3):
            try:
                data=self.http.get(endpoint+'?'+urlencode({**params,'serviceKey':key}),allow_credentials=True)
                break
            except SourceError:
                if attempt==2:raise
                time.sleep(2**attempt)
        if key.encode() in data:raise SourceError('Credential reflection detected')
        try:
            if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
                raise SourceError('DTD/entity XML refused')
            root=ET.fromstring(data)
            if root.tag!='response' or root.findtext('header/resultCode')!='00':
                raise SourceError('Official Nara API rejected request')
            return root,data
        except ET.ParseError:raise SourceError('Malformed official Nara XML') from None

    def collect_official(self):
        c=self.config
        if c['endpoint']!='https://apis.data.go.kr/1760000/PblJobService/getList':
            raise SourceError('Unapproved official Nara contract endpoint')
        now=dt.datetime.now(KST)
        days=int(c['lookback_days'])
        if not 1<=days<=365:raise SourceError('Invalid Nara collection window')
        params={'Pblanc_ty':'','Instt_se':'','Sort_order':'desc',
                'Begin_de':(now.date()-dt.timedelta(days=days)).isoformat(),
                'End_de':now.date().isoformat(),'numOfRows':100}
        records=[];expected=None;seen=set()
        self.stats={'listed':0,'expired_or_invalid':0,'details':0,'missing_original':0,'published':0}
        for page in range(1,501):
            root,data=self.api('getList',{**params,'pageNo':page})
            rows,total=parse_page(data,c)
            if expected is None:expected=total
            if total!=expected:raise SourceError('Nara API pagination changed; retry collection')
            # Verify the service honored paging rather than repeating page one.
            if root.findtext('body/pageNo')!=str(page):raise SourceError('Nara page number mismatch')
            for row in rows:
                ident=str(row.get('notice_id') or '').strip()
                if not ident or ident in seen:raise SourceError('Duplicate/missing Nara notice ID')
                seen.add(ident)
            records.extend(rows)
            if len(records)>=total:
                if len(records)!=total:raise SourceError('Nara pagination count mismatch')
                break
            if not rows:raise SourceError('Incomplete Nara pagination')
        else:raise SourceError('Nara pagination limit exceeded')
        self.stats['listed']=len(records)
        print('Nara API listing pages verified: '+str(len(records)),flush=True)
        jobs=[]
        for row in records:
            deadline,_=closing(row.get('deadline'))
            if not deadline or deadline<now.date().isoformat():
                self.stats['expired_or_invalid']+=1;continue
            ident=str(row['notice_id'])
            if not re.fullmatch(r'[0-9]+',ident):raise SourceError('Invalid Nara notice ID')
            root,_=self.api('getItem',{'idx':ident})
            node=root.find('body/item')
            if node is None:raise SourceError('Missing Nara detail')
            detail=xml_value(node)
            # Historical API records can reuse an idx across notice types.
            # An idx match alone does not establish that this is the same job.
            for key,field in [('notice_id','idx'),('title','title'),('org','insttname'),('deadline','enddate')]:
                if plain(row.get(key))!=plain(detail.get(field)):
                    raise SourceError('Nara list/detail identity mismatch')
            self.stats['details']+=1
            if self.stats['details']%50==0:print('Nara details verified: '+str(self.stats['details']),flush=True)
            row.update(title=plain(row['title']),org=plain(row['org']),
                       description=plain(detail.get('contents')),region=plain(detail.get('areaname')))
            candidate=html.unescape(html.unescape(str(detail.get('link01') or '').strip()))
            if candidate and '://' not in candidate and not candidate.startswith(('/',':')):candidate='https://'+candidate
            row['agency_url']=canonical_url(candidate)
            # regdate is a publication date, never an application opening date.
            row['published_date']=closing(detail.get('regdate'))[0]
            # begindate is undocumented and live samples disagree with the
            # explicit application period in contents; do not invent a start.
            row['start']=None
            template=c.get('original_url_template')
            if template:
                row['source_url']=template.format(notice_id=ident)
            else:
                row['source_url']=next((url for field in ('link01','link02','link03')
                    if (url:=original_url(detail.get(field),c['original_hosts']))),None)
            normalized=normalize([row],self.source_id,self.source_name,now)
            if not normalized:continue
            for attempt in range(3):
                try:
                    available=self.http.original(normalized[0]['source_url'],expected_text=row['title'])
                    break
                except SourceError:
                    if attempt==2:raise
                    time.sleep(2**attempt)
            if available:jobs.extend(normalized)
            else:self.stats['missing_original']+=1
        self.stats['published']=len(jobs)
        return jobs


class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.parts=[];self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):self.hidden+=1
        if tag in ('p','br','div','li','tr'):self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style'):self.hidden=max(0,self.hidden-1)
        if tag in ('p','div','li','tr'):self.parts.append('\n')
    def handle_data(self,data):
        if not self.hidden:self.parts.append(data)


def plain(value):
    value=str(value or '')
    # The official API double-encodes markup/entities in some fields.
    for _ in range(2):value=html.unescape(value)
    parser=TextOnly();parser.feed(value)
    return '\n'.join(' '.join(line.split()) for line in ''.join(parser.parts).splitlines() if line.strip())


def original_url(value,hosts):
    value=html.unescape(html.unescape(str(value or '').strip()))
    if value and '://' not in value and not value.startswith(('/',':')):
        value='https://'+value
    url=canonical_url(value)
    return url if url and urlsplit(url).hostname in hosts else None
