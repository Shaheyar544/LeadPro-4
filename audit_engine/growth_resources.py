"""Small same-origin resource probes, never a second HTML crawling pipeline.

Every hop is normalized, DNS checked and pinned. No cookies, credentials,
proxy inheritance, decompression, external sitemap fetches or unbounded XML.
"""
import asyncio
import fnmatch
import re
from urllib.parse import urlsplit, urljoin, quote
import xml.etree.ElementTree as ET

import aiohttp
from url_safety import normalize_url, resolve_public, _PinnedResolver, UnsafeURL

BYTE_CAP = 512 * 1024
TIMEOUT = 6
USER_AGENT = 'LeadEngine'


def origin(url):
    p = urlsplit(normalize_url(url))
    return p.scheme, p.netloc


async def probe(url, base, *, body=False, upgrade=False):
    async def request():
        current = normalize_url(url)
        for hop in range(4):
            p = urlsplit(current)
            allowed = origin(current) == origin(base)
            if upgrade:
                allowed = p.hostname == urlsplit(base).hostname and p.scheme in {'http', 'https'}
            if not allowed:
                raise UnsafeURL('Cross-origin resource')
            addresses = await resolve_public(p.hostname, 443 if p.scheme == 'https' else 80)
            connector = aiohttp.TCPConnector(resolver=_PinnedResolver(p.hostname, addresses), use_dns_cache=False,
                                             limit=1, force_close=True, ssl=True)
            async with aiohttp.ClientSession(connector=connector, trust_env=False, cookie_jar=aiohttp.DummyCookieJar(),
                    auto_decompress=False, timeout=aiohttp.ClientTimeout(total=TIMEOUT, connect=3)) as session:
                async with session.request('GET' if body else 'HEAD', current, allow_redirects=False,
                        headers={'User-Agent': 'LeadEngine/1.0 (public website audit)', 'Accept-Encoding': 'identity'}) as response:
                    if response.status in {301, 302, 303, 307, 308}:
                        if hop == 3 or not response.headers.get('Location'):
                            return dict(status='unknown', reason='redirect_limit')
                        current = normalize_url(urljoin(current, response.headers['Location']))
                        continue
                    code = response.status
                    state = 'blocked' if code in {401, 403, 429} else 'observed' if 200 <= code < 300 or code in {404, 410} else 'unknown'
                    result = dict(status=state, http_status=code, url=current, redirects=hop,
                                  x_robots_tag=response.headers.get('X-Robots-Tag', '')[:500])
                    if body and state == 'observed' and 200 <= code < 300:
                        if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                            return dict(status='unknown', reason='encoded_resource')
                        if response.content_length is not None and response.content_length > BYTE_CAP:
                            return dict(status='unknown', reason='resource_limit')
                        data = bytearray()
                        async for chunk in response.content.iter_chunked(16384):
                            if len(data) + len(chunk) > BYTE_CAP:
                                return dict(status='unknown', reason='resource_limit')
                            data.extend(chunk)
                        result['body'] = data.decode('utf-8', errors='replace')
                    return result
    try:
        return await asyncio.wait_for(request(), TIMEOUT)
    except (UnsafeURL, ValueError, OSError, aiohttp.ClientError, asyncio.TimeoutError):
        return dict(status='unknown', reason='resource_unavailable')


def rep_path(value):
    """RFC 9309 comparison: decode ASCII unreserved only; preserve reserved octets."""
    value = quote(value, safe="/%!$&'()+,;=:@?*~.-_$")
    def replace(match):
        n = int(match[1], 16)
        return chr(n) if chr(n).isascii() and (chr(n).isalnum() or chr(n) in '-._~') else '%' + match[1].upper()
    return re.sub(r'%([0-9a-fA-F]{2})', replace, value)


class Robots:
    def __init__(self, text):
        self.groups, self.sitemaps = [], []
        self.valid = len(text.splitlines()) <= 10000 and '\ufffd' not in text and not re.search(r'<\s*(?:html|!doctype)', text, re.I)
        agents, rules, directives_seen = [], [], False
        for line in text.splitlines()[:10000]:
            key, sep, value = line.partition('#')[0].partition(':')
            if not sep:
                continue
            key, value = key.strip().lstrip('\ufeff').lower(), value.strip()
            if key == 'sitemap':
                self.sitemaps.append(value)
            elif key == 'user-agent':
                if directives_seen:
                    self.groups.append((agents, rules)); agents, rules, directives_seen = [], [], False
                agents.append(value.casefold())
            elif key in {'allow', 'disallow'} and agents:
                directives_seen = True
                if value:
                    if len(value) > 2048:
                        self.valid = False
                    rules.append((key, rep_path(value)))
        if agents:
            self.groups.append((agents, rules))

    def allowed(self, url, agent=USER_AGENT):
        if not self.valid:
            return False
        matches = [(len(a), rules) for agents, rules in self.groups for a in agents
                   if a != '*' and a in agent.casefold()]
        if matches:
            longest = max(n for n, _ in matches)
            rules = [r for n, group in matches if n == longest for r in group]
        else:
            rules = [r for agents, group in self.groups if '*' in agents for r in group]
        p = urlsplit(url)
        path = rep_path(p.path + ('?' + p.query if p.query else ''))
        hits = []
        for kind, rule in rules:
            terminal = rule.endswith('$')
            raw = rule[:-1] if terminal else rule
            # fnmatch's translation uses atomic groups for wildcard segments;
            # adversarial rules cannot trigger regex backtracking explosions.
            pattern = raw.replace('[', '[[]').replace('?', '[?]') + ('' if terminal else '*')
            if fnmatch.fnmatchcase(path, pattern):
                hits.append((len(raw.replace('*', '').encode('utf-8')), kind == 'allow'))
        return max(hits)[1] if hits else True


def sitemap_document(text, base):
    if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
        return dict(status='unknown', reason='unsafe_xml')
    try:
        root = ET.fromstring(text)
    except (ET.ParseError, ValueError):
        return dict(status='unknown', reason='invalid_xml')
    kind = root.tag.rsplit('}', 1)[-1]
    if kind not in {'urlset', 'sitemapindex'}:
        return dict(status='unknown', reason='unsupported_xml')
    urls, rejected = [], 0
    for element in root.iter():
        if element.tag.rsplit('}', 1)[-1] == 'loc':
            try:
                value = normalize_url((element.text or '').strip())
                if origin(value) != origin(base):
                    raise UnsafeURL('External sitemap URL')
                urls.append(value)
            except UnsafeURL:
                rejected += 1
            if len(urls) + rejected >= 500:
                break
    return dict(status='present', kind=kind, urls=list(dict.fromkeys(urls)), external_rejected=rejected,
                limited=len(urls) + rejected >= 500)


class Resources:
    def __init__(self, base, fetch=probe):
        self.base, self.fetch, self.robots = base, fetch, None
        self.robot_result = dict(status='unknown')
        self.cache = {}
        self.blocked = False

    async def initialize(self):
        if urlsplit(self.base).scheme == 'http':
            # Establish an observed same-host HTTPS upgrade before choosing the
            # robots origin. Robots itself still never follows across origins.
            upgraded = await self.fetch(self.base, self.base, upgrade=True)
            if upgraded.get('status') == 'observed' and upgraded.get('url', '').startswith('https://'):
                if urlsplit(upgraded['url']).hostname == urlsplit(self.base).hostname:
                    self.base = normalize_url(upgraded['url'])
                    self.cache[self.base] = upgraded
        url = urljoin(self.base, '/robots.txt')
        self.robot_result = await self.fetch(url, self.base, body=True)
        if self.robot_result.get('http_status') in {404, 410}:
            self.robots = Robots('')
        elif self.robot_result.get('status') == 'observed' and 'body' in self.robot_result:
            parsed = Robots(self.robot_result['body'])
            self.robots = parsed if parsed.valid else None

    def allowed(self, url):
        return self.robots is not None and origin(url) == origin(self.base) and self.robots.allowed(url)

    async def head(self, url, *, upgrade=False):
        if self.blocked:
            return dict(status='unknown', reason='resource_access_blocked')
        if not upgrade and not self.allowed(url):
            return dict(status='unknown', reason='robots_not_allowed_or_unavailable')
        if url not in self.cache:
            self.cache[url] = await self.fetch(url, self.base, upgrade=upgrade)
            if self.cache[url].get('status') == 'blocked':
                self.blocked = True
        return self.cache[url]

    async def sitemap(self):
        candidates = self.robots.sitemaps[:2] if self.robots else []
        candidates = list(dict.fromkeys([*candidates, urljoin(self.base, '/sitemap.xml')]))[:3]
        observations, discovered = [], []
        for url in candidates:
            try:
                if not self.allowed(url):
                    continue
                result = await self.fetch(url, self.base, body=True)
                if result.get('status') == 'blocked':
                    self.blocked = True
                    return dict(status='unknown', reason='sitemap_access_blocked')
                if result.get('http_status') in {404, 410}:
                    observations.append(dict(status='absent', url=url)); continue
                parsed = sitemap_document(result['body'], self.base) if result.get('body') else dict(status='unknown')
                if parsed['status'] == 'present':
                    discovered += parsed['urls']
                    if parsed['kind'] == 'sitemapindex':
                        # At most two children; no recursive index traversal.
                        for child in parsed['urls'][:2]:
                            if self.allowed(child):
                                fetched = await self.fetch(child, self.base, body=True)
                                if fetched.get('status') == 'blocked':
                                    self.blocked = True
                                    break
                                nested = sitemap_document(fetched.get('body', ''), self.base)
                                if nested.get('kind') == 'urlset':
                                    discovered += nested['urls']
                    return dict(status='present', url=url, sampled_url_count=min(len(discovered), 500),
                                kind=parsed['kind'], limited=parsed['limited'] or len(discovered) > 500, external_rejected=parsed['external_rejected'])
                observations.append(dict(status='unknown', url=url))
            except UnsafeURL:
                observations.append(dict(status='unknown'))
        state = 'absent' if observations and all(o['status'] == 'absent' for o in observations) else 'unknown'
        return dict(status=state, checked=[o.get('url') for o in observations if o.get('url')], scope='Checked same-origin sitemap locations only')

    async def links(self, urls, cap):
        semaphore = asyncio.Semaphore(2)
        async def check(url):
            async with semaphore:
                return dict(url=url, **{k: v for k, v in (await self.head(url)).items() if k != 'url'})
        # Total supplemental link work is time-bounded too; preserve completed results.
        tasks = [asyncio.create_task(check(url)) for url in sorted(set(urls))[:cap]]
        if not tasks:
            return []
        try:
            done, _ = await asyncio.wait(tasks, timeout=30)
            return sorted([task.result() for task in done], key=lambda row: row['url'])
        finally:
            pending = [task for task in tasks if not task.done()]
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
