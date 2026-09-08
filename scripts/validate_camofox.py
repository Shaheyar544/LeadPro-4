"""Run inside the worker container: private browser contract and safety smoke."""
import asyncio
import json
import socket
from pathlib import Path
from browser.base import BrowserError
from engine_config import EngineConfig


async def main():
    browser = EngineConfig().browser()
    session = await browser.open_session()
    try:
        assert (await browser.health()).available
        for url in ('http://127.0.0.1/', 'http://postgres:5432/', 'http://redis:6379/',
                    'http://api:8000/admin', 'http://169.254.169.254/latest/meta-data/',
                    'http://host.docker.internal/', 'file:///var/run/docker.sock'):
            try:
                await browser.open_page(session, url)
            except BrowserError as error:
                assert error.code == 'unsafe_navigation'
            else:
                raise AssertionError('Unsafe target accepted')
        page = await browser.open_page(session, 'https://example.com/')
        assert 'Example Domain' in await browser.evaluate(page, 'document.title')
        assert (await browser.evaluate(page, 'location.href')).startswith('https://example.com')
        await browser.close_page(page)
    finally:
        await browser.close_session(session)
        await browser.shutdown()
    assert not session.pages
    print(json.dumps({'open': True, 'evaluate': True, 'close': True, 'ssrf_direct_targets': 'rejected'}))


if __name__ == '__main__':
    asyncio.run(main())
