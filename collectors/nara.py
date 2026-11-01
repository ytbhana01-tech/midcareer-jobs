"""나라일터 adapter for dataset 15156780. Mapping MUST come from reviewed official docs.

No endpoint or vendor field names are guessed. Disabled until the official contract,
permission and credential have been confirmed. JSON/XML envelope paths are configurable.
"""
import json
import os
import xml.etree.ElementTree as ET
from urllib.parse import urlencode, urlsplit
from collectors.common import OfficialHTTP, SourceError, normalize, reviewed


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
        items=at(payload,config['items_path'])
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
            data=self.http.get(c['endpoint']+'?'+urlencode(params))
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
