"""Website SSO session and bounded requests. Credentials stay in memory."""
from html.parser import HTMLParser
import hashlib
import re
import time
from urllib.parse import urlparse

import requests

BASE = 'https://database.ourtaiko.org'
SSO = 'https://sso.ourtaiko.org'


class APIError(RuntimeError):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(f'HTTP {status}: {code}')


class Forms(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.forms, self.current = [], None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form':
            self.current = {}
            self.forms.append(self.current)
        elif tag == 'input' and self.current is not None and attrs.get('name'):
            self.current[attrs['name']] = attrs.get('value', '')

    def handle_endtag(self, tag):
        if tag == 'form':
            self.current = None


class Client:
    def __init__(self, interval=1.7, proxy=None):
        self.session = requests.Session()
        self.session.headers['User-Agent'] = 'TaikoCoverUploader/1.0'
        if proxy:
            self.session.proxies.update(http=proxy, https=proxy)
        self.interval, self.last_write = max(1.7, interval), 0
        self.csrf = ''

    def request(self, method, url, **kwargs):
        # A retrying PUT is safe: the endpoint replaces with the same content.
        for attempt in range(4):
            if method != 'GET':
                time.sleep(max(0, self.interval - (time.monotonic() - self.last_write)))
                self.last_write = time.monotonic()
            for value in kwargs.get('files', {}).values():
                value[1].seek(0)
            try:
                response = self.session.request(method, url, timeout=(15, 90), **kwargs)
            except requests.RequestException:
                if attempt == 3:
                    raise APIError(0, 'NETWORK_ERROR') from None
                time.sleep(2 ** attempt)
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < 3:
                    retry = response.headers.get('Retry-After', '')
                    time.sleep(min(120, max(65, int(retry))) if retry.isdigit() else 65)
                    continue
            return response
        raise AssertionError('unreachable')

    @staticmethod
    def json(response):
        try:
            data = response.json()
        except ValueError:
            raise APIError(response.status_code, 'NON_JSON_RESPONSE') from None
        if response.status_code >= 400:
            code = str(data.get('code', 'REQUEST_FAILED'))
            raise APIError(response.status_code, code if re.fullmatch('[A-Z0-9_]+', code) else 'REQUEST_FAILED')
        return data

    def login(self, username, password):
        page = self.request('GET', BASE + '/api/v1/auth/sso/login?returnTo=%2F')
        if urlparse(page.url).netloc != urlparse(SSO).netloc or urlparse(page.url).path != '/login/':
            raise APIError(page.status_code, 'SSO_LOGIN_FORM_MISSING')
        form = next((f for f in Forms(page.text).forms if 'password' in f), None)
        if form is None or not form.get('csrfmiddlewaretoken'):
            raise APIError(page.status_code, 'SSO_LOGIN_FORM_MISSING')
        form.update(username=username, password=password)
        page = self.request('POST', page.url, data=form, headers={'Origin': SSO, 'Referer': page.url})
        form.clear()
        # Some accounts must grant Database its normal OpenID/profile scopes once.
        if urlparse(page.url).netloc == urlparse(SSO).netloc and urlparse(page.url).path == '/o/authorize/':
            form = next((f for f in Forms(page.text).forms if 'client_id' in f), None)
            if not form or form['client_id'] != 'OurTaikoDatabase':
                raise APIError(page.status_code, 'SSO_CONSENT_FORM_INVALID')
            form['allow'] = 'true'
            page = self.request('POST', page.url, data=form, headers={'Origin': SSO, 'Referer': page.url})
        me = self.json(self.request('GET', BASE + '/api/v1/me'))
        if not me.get('user') or not me.get('csrfToken'):
            raise APIError(401, 'LOGIN_FAILED')
        self.csrf = me['csrfToken']
        return me['user']

    def chart(self, cid):
        return self.json(self.request('GET', BASE + '/api/v1/charts/' + cid))

    def put_cover(self, cid, path):
        # Some maintained .png files contain JPEG bytes. The API requires the
        # multipart filename extension to match the actual format; keep bytes intact.
        from PIL import Image
        with Image.open(path) as image:
            extension = {'PNG': '.png', 'JPEG': '.jpg', 'WEBP': '.webp'}[image.format]
        upload_name = path.stem + extension
        with path.open('rb') as stream:
            response = self.request('PUT', BASE + '/api/v1/charts/' + cid + '/cover',
                                    headers={'Origin': BASE, 'X-CSRF-Token': self.csrf},
                                    files={'cover': (upload_name, stream)})
        result = self.json(response)
        digest = result.get('coverHash', '')
        if not re.fullmatch('[0-9a-f]{64}', digest):
            raise APIError(200, 'COVER_HASH_MISSING')
        if self.chart(cid).get('coverHash') != digest:
            raise APIError(200, 'COVER_VERIFY_FAILED')
        return digest

    def verify_download(self, cid, expected):
        response = self.request('GET', BASE + '/api/v1/charts/' + cid + '/cover')
        if response.status_code != 200 or hashlib.sha256(response.content).hexdigest() != expected:
            raise APIError(response.status_code, 'COVER_DOWNLOAD_VERIFY_FAILED')

    def close(self):
        try:
            if self.csrf:
                self.request('POST', BASE + '/api/v1/auth/logout', headers={'Origin': BASE, 'X-CSRF-Token': self.csrf})
        except APIError:
            pass  # A failed logout must not hide the durable upload results.
        finally:
            self.session.close()
