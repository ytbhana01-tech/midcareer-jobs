"""Collect ALIO listings on the server; publish only allowlisted, normalized fields."""
import argparse
import datetime as dt
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
BASE = 'https://opendata.alio.go.kr'


def date_of(value):
    value = str(value or '').strip()
    for fmt in ('%Y-%m-%d', '%Y%m%d'):
        try:
            return dt.datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def safe_url(value):
    value = str(value or '').strip()
    try:
        p = urlsplit(value)
        if (p.scheme == 'https' and p.hostname and not p.username and not p.password
                and not re.search(r'[\x00-\x20]', value)
                and not re.search(r'(servicekey|api[_-]?key|token|authorization)=', p.query, re.I)):
            return value
    except ValueError:
        pass
    return None


def text(value):
    return str(value).strip() if value is not None else ''


def normalize(records, today=None):
    today = today or dt.datetime.now(ZoneInfo('Asia/Seoul')).date()
    result, seen = [], set()
    for r in records:
        if not isinstance(r, dict):
            continue
        ident = text(r.get('recrutPblntSn', r.get('id')))
        deadline = date_of(r.get('pbancEndYmd', r.get('deadline')))
        start = date_of(r.get('pbancBgngYmd', r.get('start')))
        url = safe_url(r.get('srcUrl', r.get('source_url')))
        title = text(r.get('recrutPbancTtl', r.get('title')))
        org = text(r.get('instNm', r.get('org')))
        if (not ident or ident in seen or not deadline or deadline < today or not url
                or not title or not org or r.get('ongoingYn') == 'N'
                or (start and start > today)):
            continue
        hire = text(r.get('hireTypeNmLst', r.get('type')))
        education = text(r.get('acbgCondNmLst', r.get('education')))
        career = text(r.get('recrutSeNm', r.get('career')))
        qualifications = text(r.get('aplyQlfcCn', r.get('qualifications')))
        # Classify only explicit source labels. 신입+경력 is NOT 경력무관.
        tags = []
        if '공무직' in title or '공무직' in hire:
            tags.append('공무직')
        if '무기계약직' in hire:
            tags.append('무기계약직')
        if career.replace(' ', '') == '경력무관':
            tags.append('경력무관')
        if '학력무관' in [v.strip() for v in education.split(',')]:
            tags.append('학력무관')
        result.append(dict(id=ident, title=title, org=org,
                           region=text(r.get('workRgnNmLst', r.get('region'))),
                           type=hire, education=education, career=career, tags=tags,
                           start=start.isoformat() if start else None,
                           deadline=deadline.isoformat(), source_url=url,
                           qualifications=qualifications,
                           procedure=text(r.get('scrnprcdrMthdExpln', r.get('procedure'))),
                           preference=text(r.get('prefCondCn', r.get('preference')))))
        seen.add(ident)
    return sorted(result, key=lambda r: (r['deadline'], r['id']))


class ApiError(RuntimeError):
    """Safe error: never contains request URLs, keys, or response bodies."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ApiError('ALIO redirect refused; credentials withheld')


def request(path, params, public=False):
    base = os.environ.get('ALIO_BASE_URL', BASE).rstrip('/')
    if base != BASE:
        raise ApiError('ALIO_BASE_URL must be https://opendata.alio.go.kr')
    if not public:
        if not os.environ.get('ALIO_API_KEY'):
            raise ApiError('ALIO_API_KEY is required')
        params = {**params, 'serviceKey': os.environ['ALIO_API_KEY']}
    encoded = urlencode(params)
    req = (Request(base + path, data=encoded.encode()) if public else
           Request(base + path + '?' + encoded, method='POST'))
    req.add_header('Accept', 'application/json')
    if not public:
        req.add_header('Content-Type', 'application/json')
    for attempt in range(3):
        try:
            with build_opener(NoRedirect()).open(req, timeout=30) as response:
                payload = json.load(response)
            if not isinstance(payload, dict):
                raise ApiError('Unexpected ALIO response structure')
            body = payload.get('data', payload) if public else payload
            if not isinstance(body, dict):
                raise ApiError('Unexpected ALIO response structure')
            code = str(body.get('resultCode', ''))
            if code not in ('200', '00', '0'):
                # Only expose known codes, never echo untrusted messages or query data.
                if code == '5':
                    raise ApiError('ALIO SERVICETIMEOUT_ERROR (5)')
                raise ApiError('ALIO rejected request (response code withheld)')
            return body
        except Exception as error:
            reason = str(error) if isinstance(error, ApiError) else 'ALIO transport/JSON error; credentials withheld'
            if attempt == 2:
                raise ApiError(reason) from None
            time.sleep(2 ** attempt)


def fetch_page(page, public=False):
    path = '/new/odaApiMng/recrutInquiryAjaxList.do' if public else '/new/v1/recruit/list.do'
    return request(path, dict(pageNo=page, numOfRows=100, ongoingYn='Y'), public)


def fetch_detail(ident, public=False):
    path = '/new/odaApiMng/recrutInquiryAjaxDetail.do' if public else '/new/v1/recruit/detail.do'
    body = request(path, {'sn': ident}, public)
    result = body.get('result')
    if not isinstance(result, dict) or str(result.get('recrutPblntSn')) != str(ident):
        raise ApiError('Unexpected ALIO detail identity/structure')
    return result


def collect(public=False):
    records, page, total = [], 1, None
    while page <= 100:
        payload = fetch_page(page, public)
        rows = payload.get('result')
        if not isinstance(rows, list):
            raise ApiError('Unexpected ALIO listing structure; feed preserved')
        if total is None:
            try:
                total = int(payload['totalCount'])
            except (KeyError, TypeError, ValueError):
                raise ApiError('Missing ALIO totalCount; feed preserved') from None
        records.extend(rows)
        if len(records) >= total:
            break
        if not rows:
            raise ApiError('Incomplete ALIO pagination; feed preserved')
        page += 1
    else:
        raise ApiError('ALIO pagination limit exceeded; feed preserved')
    if len({str(r.get('recrutPblntSn')) for r in records}) < total:
        raise ApiError('ALIO pagination changed or duplicated; retry collection')
    candidates = normalize(records)
    # Check every published record against the detail endpoint; publish atomically.
    with ThreadPoolExecutor(max_workers=4) as pool:
        details = list(pool.map(lambda r: fetch_detail(r['id'], public), candidates))
    jobs = normalize(details)
    now = dt.datetime.now(ZoneInfo('Asia/Seoul')).isoformat(timespec='seconds')
    feed = dict(updated_at=now, source='alio-public-preview' if public else 'alio-api',
                authenticated_api_verified=not public, total_fetched=len(records), jobs=jobs)
    serialized = json.dumps(feed, ensure_ascii=False, indent=2) + '\n'
    # Fail closed if a source ever reflects credentials in a public field.
    for name in ('ALIO_API_KEY', 'GH_TOKEN', 'GITHUB_TOKEN'):
        secret = os.environ.get(name)
        if secret and (secret in serialized or urlencode({'x': secret})[2:] in serialized):
            raise ApiError('Credential reflection detected; feed preserved')
    return serialized


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--public-preview', action='store_true',
                        help='Explicit public-query preview; never claims authenticated API success')
    args = parser.parse_args()
    try:
        serialized = collect(args.public_preview)
        temporary = ROOT / 'jobs.json.tmp'
        temporary.write_text(serialized, encoding='utf-8')
        temporary.replace(ROOT / 'jobs.json')
        feed = json.loads(serialized)
        print(f"Published {len(feed['jobs'])} verified-detail listings ({feed['source']})")
    except ApiError as error:
        parser.exit(1, str(error) + '; existing feed preserved\n')


if __name__ == '__main__':
    main()
