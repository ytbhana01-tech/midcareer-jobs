"""부산광역시 supported RSS/Atom adapter. No HTML board scraping or guessed feed URL."""
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit, urljoin, urlencode
from collectors.common import OfficialHTTP, SourceError, normalize, reviewed
from collectors.nara import parse_page


def parse_feed(data, config):
    try:
        if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
            raise SourceError('DTD/entity XML refused')
        root=ET.fromstring(data)
        namespaces=config.get('namespaces',{})
        entries=root.findall(config['items_path'],namespaces)
        if root.tag.split('}')[-1] not in ('rss','feed','RDF'):
            raise SourceError('Unsupported official feed structure')
        rows=[]
        for entry in entries:
            row={}
            for key,field in config['fields'].items():
                if not field:continue
                # Feed contract can use an explicit attribute (e.g. Atom link@href).
                path,sep,attr=field.rpartition('@')
                if not sep:path=field
                node=entry.find(path,namespaces)
                row[key]=(node.get(attr) if sep else ''.join(node.itertext()).strip()) if node is not None else None
            rows.append(row)
        next_url=None
        path=config.get('next_path')
        if path:
            node=root.find(path,namespaces)
            if node is not None:next_url=node.get('href') or node.text
        return rows,next_url
    except (ET.ParseError,KeyError,TypeError,UnicodeError,SyntaxError):
        raise SourceError('Malformed official 부산시 feed') from None


class BusanCollector:
    source_id='busan'
    source_name='부산광역시'

    def __init__(self,config,http=None):
        self.config=config
        self.http=http or OfficialHTTP(['www.busan.go.kr',*config.get('original_hosts',[])],config.get('min_interval',2))

    def collect(self):
        c=self.config
        reviewed(c)
        if c.get('fields',{}).get('deadline') in ('pubDate','published','updated'):
            raise SourceError('Publication timestamps cannot substitute for application deadlines')
        if c.get('format')=='json':
            return self.collect_json()
        if c.get('format') not in ('rss','atom'):
            raise SourceError('Only officially supported 부산시 feeds are enabled by this adapter')
        records=[];url=c['endpoint'];seen=set()
        for page in range(100):
            if url in seen or urlsplit(url).hostname!='www.busan.go.kr':
                raise SourceError('Invalid/looping 부산시 feed pagination')
            seen.add(url)
            if not self.http.allowed(url):raise SourceError('부산시 robots policy disallows feed access')
            rows,next_url=parse_feed(self.http.get(url),c)
            records.extend(rows)
            if not next_url:break
            url=urljoin(url,next_url)
        else:raise SourceError('부산시 pagination limit exceeded')
        # Never use pubDate as an application deadline, or assume a posting date
        # is an application start date. Only explicitly mapped source fields qualify.
        jobs=normalize(records,self.source_id,self.source_name)
        return [job for job in jobs if self.http.original(job['source_url'])]

    def collect_json(self):
        """Supported official JSON API only; endpoint/schema remain review-gated."""
        c=self.config
        required=('page_parameter','size_parameter','success_path','success_codes','total_path','items_path')
        if not all(c.get(k) for k in required) or urlsplit(c['endpoint']).hostname!='www.busan.go.kr' or urlsplit(c['endpoint']).query:
            raise SourceError('Verified 부산시 JSON API contract required')
        if not self.http.allowed(c['endpoint']):
            raise SourceError('부산시 robots policy disallows API access')
        rows=[];expected=None
        for page in range(1,101):
            params={**c.get('params',{}),c['page_parameter']:page,c['size_parameter']:100}
            items,total=parse_page(self.http.get(c['endpoint']+'?'+urlencode(params)),c)
            if expected is None:expected=total
            if total!=expected:raise SourceError('부산시 API pagination total changed')
            rows.extend(items)
            if len(rows)>=total:
                if len(rows)!=total:raise SourceError('부산시 API pagination count mismatch')
                break
            if not items:raise SourceError('Incomplete 부산시 API pagination')
        else:raise SourceError('부산시 API pagination limit exceeded')
        ids=[str(r.get('notice_id') or '') for r in rows]
        if len(ids)!=len(set(ids)) or not all(ids):raise SourceError('Duplicate/missing 부산시 API notice IDs')
        jobs=normalize(rows,self.source_id,self.source_name)
        return [j for j in jobs if self.http.original(j['source_url'])]
