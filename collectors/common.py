"""Shared source validation. No guessed eligibility, dates, or URLs."""
import datetime as dt
import html
import ipaddress
import json
import os
import re
import time
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from urllib.request import Request, build_opener
from urllib.error import HTTPError
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo
from collect import ApiError, NoRedirect, safe_url, date_of

KST = ZoneInfo('Asia/Seoul')
USER_AGENT = 'MidcareerJobsBot/1.0'


class SourceError(RuntimeError):
    """Only fixed, credential-free messages may cross the source boundary."""


def timestamp():
    return dt.datetime.now(KST).isoformat(timespec='seconds')


def closing(value):
    value = str(value or '').strip()
    date = date_of(value)
    if date:
        return date.isoformat(), None
    try:
        stamp = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=KST)
        stamp = stamp.astimezone(KST)
        return stamp.date().isoformat(), stamp.isoformat()
    except ValueError:
        return None, None


def canonical_url(value):
    url = safe_url(value)
    if not url:
        return None
    p = urlsplit(url)
    try:
        port = p.port
    except ValueError:
        return None
    host = p.hostname.lower().rstrip('.')
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    if '.' not in host or host.endswith(('.localhost', '.local', '.internal')):
        return None
    parsed_query=parse_qsl(p.query,keep_blank_values=True)
    if any(re.search(r'(servicekey|api.?key|password|secret|token|auth)',k,re.I) for k,v in parsed_query):
        return None
    query = [(k, v) for k, v in parsed_query
             if not k.lower().startswith('utm_') and k.lower() not in ('fbclid', 'gclid')]
    return urlunsplit(('https', host+(f':{port}' if port not in (None,443) else ''), p.path or '/', urlencode(sorted(query)), ''))


def classify(title, employment):
    evidence = employment or ''
    result = []
    for label in ('공무직', '무기계약직', '기간제'):
        if label in evidence or (label in title and not re.search(label+r'\s*(?:제외|아님)', title)):
            result.append(label)
    return result or (['기타'] if evidence else [])


def normalize(rows, source_id, source_name, now=None):
    now = now or dt.datetime.now(KST)
    if now.tzinfo is None:
        raise SourceError('Timezone-aware collection time required')
    now = now.astimezone(KST)
    jobs, ids = [], set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        ident = str(row.get('notice_id') or row.get('id') or '').strip()
        url = canonical_url(row.get('source_url'))
        deadline, exact = closing(row.get('deadline'))
        start, start_exact = closing(row.get('start'))
        if (not ident or not url or not row.get('title') or not row.get('org') or not deadline
                or deadline < now.date().isoformat()
                or (exact and dt.datetime.fromisoformat(exact) < now)
                or (row.get('start') and not start)
                or (start and start > now.date().isoformat())
                or (start_exact and dt.datetime.fromisoformat(start_exact) > now)
                or row.get('accepting') is False):
            continue
        if ident in ids:
            raise SourceError('Duplicate source notice IDs; incomplete page snapshot')
        ids.add(ident)
        # Publish a narrow allowlist, never copy arbitrary source fields.
        job = {key: str(row.get(key) or '').strip() for key in (
            'title','org','region','type','education','career','qualifications','procedure','preference',
            'agency_id','announcement_number')}
        types = classify(job['title'], job['type'])
        tags = [x for x in types if x != '기타']
        if job['career'].replace(' ', '') == '경력무관':
            tags.append('경력무관')
        if '학력무관' in [x.strip() for x in job['education'].split(',')]:
            tags.append('학력무관')
        job.update(id=f'{source_id}:{ident}', notice_id=ident, source_id=source_id,
                   source_name=source_name, source_url=url, deadline=deadline, closes_at=exact,
                   start=start, opens_at=start_exact, tags=tags, employment_types=types,
                   collected_at=now.isoformat(timespec='seconds'))
        jobs.append(job)
    return jobs


def sanitize_serialized(data):
    text = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
    names = {'ALIO_API_KEY','NARA_API_KEY','DATA_GO_KR_API_KEY','GH_TOKEN','GITHUB_TOKEN'}
    names.update(name for name in os.environ if re.search(r'(?:API_KEY|PASSWORD|SECRET|TOKEN)$',name))
    for name in names:
        value = os.environ.get(name)
        if value and (value in text or urlencode({'x':value})[2:] in text):
            raise SourceError('Credential reflection detected; publication refused')
    return text


class OfficialHTTP:
    """HTTPS only, explicit hosts, robots fail-closed, serial per-host rate limiting."""
    def __init__(self, hosts, min_interval=1.0):
        self.hosts = set(hosts)
        self.min_interval = max(1.0, float(min_interval))
        self.last = {}
        self.robots = {}

    def get(self, url, max_bytes=5_000_000):
        clean = safe_url(url)
        if not clean or urlsplit(clean).hostname not in self.hosts:
            raise SourceError('Unapproved request destination')
        host = urlsplit(clean).hostname
        delay = self.min_interval - (time.monotonic()-self.last.get(host,0))
        if delay > 0:
            time.sleep(delay)
        self.last[host] = time.monotonic()
        try:
            request = Request(clean,headers={'User-Agent':USER_AGENT,'Accept':'application/json, application/xml, text/xml, text/html'})
            with build_opener(NoRedirect()).open(request,timeout=30) as response:
                data = response.read(max_bytes+1)
                if response.status != 200 or len(data)>max_bytes:
                    raise SourceError('Invalid or oversized source response')
                return data
        except HTTPError as error:
            if error.code in (404,410):
                raise SourceError('Original not found') from None
            raise SourceError('Official source HTTP request failed') from None
        except (ApiError, OSError, ValueError):
            raise SourceError('Official source transport failed') from None

    def allowed(self, url):
        p = urlsplit(url)
        origin = f'{p.scheme}://{p.netloc}'
        if origin not in self.robots:
            robot = RobotFileParser()
            try:
                data = self.get(origin+'/robots.txt',max_bytes=500_000)
                robot.parse(data.decode('utf-8').splitlines())
            except SourceError as error:
                if str(error)=='Original not found':
                    robot.parse([])  # Standard robots 404: no access rules; terms gate still applies.
                else:
                    raise
            delay = robot.crawl_delay(USER_AGENT) or robot.crawl_delay('*')
            if delay:
                self.min_interval=max(self.min_interval,float(delay))
            self.robots[origin]=robot
        return self.robots[origin].can_fetch(USER_AGENT,url)

    def original(self, url):
        # A known HTTP 404/410 or robots denial excludes the announcement. Unknown
        # transport failures fail this source update, preserving its previous snapshot.
        if not self.allowed(url):
            return False
        try:
            body=self.get(url)
        except SourceError as error:
            if str(error)=='Original not found':
                return False
            raise
        return bool(body.strip())


def reviewed(config):
    required=('spec_url','rights_url','reviewed_at','redistribution_allowed','spec_verified')
    if not config.get('enabled') or not all(config.get('review',{}).get(k) for k in required):
        raise SourceError('Source disabled pending official specification and republication review')
    if any(config.get('review',{}).get(k) is not True for k in ('redistribution_allowed','spec_verified')):
        raise SourceError('Explicit official permission review required')
    fields=config.get('fields',{})
    if not all(isinstance(fields.get(k),str) and fields[k] for k in ('notice_id','title','org','deadline','source_url')):
        raise SourceError('Verified required source field mapping missing')
    if not config.get('endpoint') or not config.get('fields') or not config.get('original_hosts'):
        raise SourceError('Verified endpoint, field mapping, and original hosts required')
