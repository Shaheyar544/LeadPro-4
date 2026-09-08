"""Five controlled site classes. No provider calls or live domains."""
from copy import deepcopy

BASE = 'https://growth-business.test/'


def facts(kind='strong', url=BASE):
    service = '/service' in url
    title = 'Oak Plumbing Repair in Austin' if service else 'Contact Oak Plumbing Austin' if '/contact' in url else 'Oak Plumbing Austin'
    headings = [dict(level=1, text=title), dict(level=2, text='Plumbing services'), dict(level=2, text='Customer testimonials')]
    links = [dict(href=BASE + 'contact', text='Contact', navigation=True),
             dict(href=BASE + 'services/repair', text='Plumbing repair', navigation=True, service_context=True),
             dict(href=BASE + 'locations/austin', text='Austin office', navigation=True)]
    g = dict(version='digital_growth_crawl_v1', title=title, descriptions=[title + ': Local plumbing repairs with clear service details.'],
        robots_meta=[], canonicals=[url], viewport='width=device-width', headings=headings, headings_complete=True,
        schema=dict(entities=[dict(types=['Plumber'], name='Oak Plumbing', url=BASE,
            address=dict(streetAddress='12 Oak Street', addressLocality='Austin', addressRegion='TX'),
            phone='+15125550199', areas=['Austin'], geo_present=False, hours_present=True)],
            microdata_types=[], invalid_json_count=0, script_count=1, complete=True),
        images=dict(count=2, missing_alt=0, empty_alt=1, dimensions_missing=0, lazy=1), mixed_content=0,
        visible_words=120, paragraphs=3, section_count=2, faq=True, video=False,
        addresses=['12 Oak Street Austin TX'], links=links, links_complete=True, body_complete=True,
        service_area_context=True, supporting_detail=True, h1_body_overlap=True, testimonials=True)
    f = dict(url=url, title=title, ready_state='complete', complete=True, viewport='width=device-width',
        body_available=True, text_length=1000, link_count=len(links), limits_reached=False,
        links=links, forms=[], ctas=[dict(text='Contact us', href=BASE + 'contact')], resources=[], iframes=[], tracking={}, generator='',
        contacts=[dict(type='phone', kind='tel', value='+15125550199'), dict(type='email', kind='mailto', value='office@growth-business.test')], growth=g)
    if kind == 'technical':
        g.update(title='', descriptions=[], canonicals=[], viewport='', mixed_content=2)
        g['schema'].update(entities=[], invalid_json_count=1)
        g['images']['missing_alt'] = 2
        f['title'] = ''
    elif kind == 'on_page':
        g.update(title='Home', supporting_detail=False, h1_body_overlap=False)
        f['title'] = 'Home'
    elif kind == 'local':
        g.update(addresses=[], service_area_context=False, testimonials=False)
        g['links'] = links[:2]
        g['schema'].update(entities=[])
    elif kind == 'blocked':
        f.update(blocked=True, complete=False, ready_state='loading')
        g.update(body_complete=False, headings_complete=False)
    return deepcopy(f)


class FixtureResources:
    def __init__(self, base, *, denied=False):
        from audit_engine.growth_resources import Robots
        self.base, self.robots = base, Robots('User-agent: *\nDisallow: /private')
        self.robot_result = dict(status='observed', http_status=200)
        self.denied = denied
        self.calls = []

    async def initialize(self):
        self.calls.append('robots')

    def allowed(self, url):
        from audit_engine.growth_resources import origin
        return not self.denied and origin(url) == origin(self.base) and self.robots.allowed(url)

    async def sitemap(self):
        return dict(status='present', url=self.base + 'sitemap.xml', sampled_url_count=3)

    async def head(self, url, **kwargs):
        self.calls.append(url)
        return dict(status='observed', http_status=200, url=url.replace('http:', 'https:'), redirects=int(url.startswith('http:')))

    async def links(self, urls, cap):
        return [dict(status='observed', url=u, http_status=404 if '/broken' in u else 200) for u in sorted(set(urls))[:cap]]
