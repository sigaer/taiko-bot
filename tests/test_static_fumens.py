"""Authorization, publication ordering, URL/path allowlist and fail-closed reads."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Barrier

import httpx
from PIL import Image
import pytest

from taiko_bot import static_fumens as schema
from taiko_bot.offline import static_fumens as publisher

BASE = 'https://static.example.test/approved/fumens'
NOW = 1800000000


@pytest.fixture
def assets(tmp_path):
    root, publication = tmp_path/'runtime', tmp_path/'published'
    (root/'songs').mkdir(parents=True)
    folder = root/'assets/fumens/Oni'
    folder.mkdir(parents=True)
    source = folder/'1.png'
    with Image.new('RGB', (16, 24), 'red') as image:
        image.save(source)
    sha = schema.digest(source.read_bytes())
    policy = dict(schema=1, scope='public-static-fumen', base_url=BASE, valid_until=NOW+86400,
                  grants=[dict(difficulty='Oni', song_id='1', sha256=sha, public=True,
                               authorization_ref='test-owned synthetic image')])
    def save_policy():
        publisher.atomic_write(root/'songs'/schema.POLICY, schema.canonical(policy))
    save_policy()
    calls = []
    def server(request):
        assert request.method == 'GET'
        calls.append(request)
        path = publication/'sha256'/request.url.path.rsplit('/', 1)[1]
        return httpx.Response(200, headers={'Content-Type': 'image/png'}, content=path.read_bytes())
    client = httpx.Client(transport=httpx.MockTransport(server), follow_redirects=False)
    yield root, publication, source, policy, save_policy, client, calls
    client.close()


def publish(assets, **kwargs):
    root, publication, _, _, _, client, _ = assets
    return publisher.publish(root, publication, BASE, client, now=NOW, **kwargs)


def test_resources_verified_before_atomic_manifest_and_repeat_url_is_stable(assets):
    root, publication, _, policy, _, client, calls = assets
    manifest = root/'songs'/schema.MANIFEST
    def verify(request):
        assert not manifest.exists(), 'reference switched before resource verification'
        path = publication/'sha256'/request.url.path.rsplit('/', 1)[1]
        return httpx.Response(200, headers={'Content-Type': 'image/png'}, content=path.read_bytes())
    with httpx.Client(transport=httpx.MockTransport(verify)) as checker:
        publisher.publish(root, publication, BASE, checker, now=NOW)
    first = json.loads(manifest.read_text())
    publish(assets)
    second = json.loads(manifest.read_text())
    assert first['entries'] == second['entries']
    assert first['resource_version'] == second['resource_version']
    row = second['entries'][0]
    assert row['sha256'] in row['url'] and row['resource_version'] == row['sha256']
    assert (row['width'], row['height']) == (16, 24)
    assert calls and all(call.url.scheme == 'https' for call in calls)


def test_verified_lookup_never_reads_source_png_and_keeps_immutable_entries(assets, monkeypatch):
    root, _, source, _, _, _, _ = assets
    publish(assets)
    source.unlink()
    store = schema.StaticFumenStore()
    entry = store.lookup(root, BASE, 'Oni', '1', now=NOW+1)
    assert entry is not None
    def forbidden(*args, **kwargs):
        raise AssertionError('hot lookup opened remote connection')
    monkeypatch.setattr(httpx.Client, 'send', forbidden)
    assert store.lookup(root, BASE, 'Oni', '1', now=NOW+2) is entry
    with pytest.raises(AttributeError):
        entry.url = 'changed'


@pytest.mark.parametrize('kind', ['missing', 'hash_changed', 'corrupt', 'https_404', 'https_bytes', 'https_redirect', 'https_type'])
def test_bad_resources_never_enter_manifest(assets, kind):
    root, publication, source, policy, save_policy, client, _ = assets
    if kind == 'missing':
        source.unlink()
    elif kind == 'hash_changed':
        source.write_bytes(b'changed')
    elif kind == 'corrupt':
        source.write_bytes(b'not a PNG file')
        policy['grants'][0]['sha256'] = schema.digest(source.read_bytes())
        save_policy()
    if kind.startswith('https_'):
        def server(request):
            if kind == 'https_404':
                return httpx.Response(404)
            if kind == 'https_redirect':
                return httpx.Response(302, headers={'Location': 'https://evil.test/image'})
            if kind == 'https_type':
                return httpx.Response(200, headers={'Content-Type': 'text/html'}, content=source.read_bytes())
            return httpx.Response(200, headers={'Content-Type': 'image/png'}, content=b'wrong')
        client = httpx.Client(transport=httpx.MockTransport(server))
    try:
        result = publisher.publish(root, publication, BASE, client, now=NOW)
    finally:
        if kind.startswith('https_'):
            client.close()
    assert result['published'] == 0 and result['rejected'] == ['Oni/1']
    assert schema.StaticFumenStore().lookup(root, BASE, 'Oni', '1', now=NOW+1) is None


@pytest.mark.parametrize('field,value', [('public', False), ('authorization_ref', ''), ('sha256', 'bad')])
def test_unauthorized_policy_never_copies_image(assets, field, value):
    root, publication, _, policy, save_policy, _, _ = assets
    policy['grants'][0][field] = value
    save_policy()
    with pytest.raises(ValueError):
        publish(assets)
    assert not publication.exists()
    assert not (root/'songs'/schema.MANIFEST).exists()


@pytest.mark.parametrize('url', ['http://static.example.test/approved', 'https://evil.test/approved',
    'https://static.example.test/approved/../secret', 'https://static.example.test/approved/%2e%2e/secret',
    'https://user:pass@static.example.test/approved', 'https://static.example.test/approved?q=x',
    'https://static.example.test/approved#x', 'https://static.example.test:99999/approved'])
def test_manifest_cannot_escape_configured_url_prefix(assets, url):
    root, _, _, _, _, _, _ = assets
    publish(assets)
    path = root/'songs'/schema.MANIFEST
    payload = json.loads(path.read_text())
    payload['entries'][0]['url'] = url
    payload['resource_version'] = schema.digest(schema.canonical(dict(policy_sha256=payload['policy_sha256'], entries=payload['entries'])))
    publisher.atomic_write(path, schema.canonical(payload))
    assert schema.StaticFumenStore().lookup(root, BASE, 'Oni', '1', now=NOW+1) is None


@pytest.mark.parametrize('target', ['songs', 'policy', 'manifest', 'source'])
def test_symlink_paths_are_rejected(assets, tmp_path, target):
    root, _, source, _, _, _, _ = assets
    if target != 'source':
        publish(assets)
    path = {'songs': root/'songs', 'policy': root/'songs'/schema.POLICY,
            'manifest': root/'songs'/schema.MANIFEST, 'source': source}[target]
    moved = tmp_path/('moved-'+target)
    path.rename(moved)
    path.symlink_to(moved, target_is_directory=target == 'songs')
    if target == 'source':
        assert publish(assets)['published'] == 0
    else:
        assert schema.StaticFumenStore().lookup(root, BASE, 'Oni', '1', now=NOW+1) is None


def test_expiry_revocation_corruption_all_fail_closed_and_recover(assets):
    root, _, _, policy, save_policy, _, _ = assets
    publish(assets)
    store = schema.StaticFumenStore()
    assert store.lookup(root, BASE, 'Oni', '1', now=NOW+1)
    assert store.lookup(root, BASE, 'Oni', '1', now=NOW+301) is None
    publish(assets)
    original_grants = policy['grants']
    policy['grants'] = []
    save_policy()
    assert store.lookup(root, BASE, 'Oni', '1', now=NOW+2) is None
    policy['grants'] = original_grants
    save_policy()
    publish(assets)
    assert store.lookup(root, BASE, 'Oni', '1', now=NOW+3)
    (root/'songs'/schema.MANIFEST).write_text('{broken')
    assert store.lookup(root, BASE, 'Oni', '1', now=NOW+4) is None
    publish(assets)
    assert store.lookup(root, BASE, 'Oni', '1', now=NOW+5)


def test_atomic_manifest_failure_preserves_previous_generation(assets, monkeypatch):
    root, _, _, _, _, _, _ = assets
    publish(assets)
    path = root/'songs'/schema.MANIFEST
    previous = schema.digest(path.read_bytes())
    original = publisher.atomic_write
    def fail(path, data):
        if path.name == schema.MANIFEST:
            raise OSError('publication unavailable')
        return original(path, data)
    monkeypatch.setattr(publisher, 'atomic_write', fail)
    with pytest.raises(OSError):
        publish(assets)
    assert schema.digest(path.read_bytes()) == previous


def test_30s_verification_hashes_unchanged_bytes_without_rebuilding(assets, monkeypatch):
    root, _, _, _, _, _, _ = assets
    publish(assets)
    store = schema.StaticFumenStore()
    entry = store.lookup(root, BASE, 'Oni', '1', now=NOW+1)
    def forbidden(*args, **kwargs):
        raise AssertionError('unchanged verified metadata was reparsed')
    monkeypatch.setattr(schema.json, 'loads', forbidden)
    assert store.lookup(root, BASE, 'Oni', '1', now=NOW+32) is entry
    assert store.loads == 1
    # Expiration still fails closed even when every byte stays identical.
    monkeypatch.undo()
    assert store.lookup(root, BASE, 'Oni', '1', now=NOW+301) is None


def test_excessive_json_nesting_fails_closed_and_recovers(assets):
    root, _, _, _, _, _, _ = assets
    publish(assets)
    store = schema.StaticFumenStore()
    assert store.lookup(root, BASE, 'Oni', '1', now=NOW+1)
    publisher.atomic_write(root/'songs'/schema.MANIFEST, b'['*1500+b'0'+b']'*1500)
    assert store.lookup(root, BASE, 'Oni', '1', now=NOW+2) is None
    publish(assets)
    assert store.lookup(root, BASE, 'Oni', '1', now=NOW+3)


def test_concurrent_readers_load_one_manifest(assets):
    root, _, _, _, _, _, _ = assets
    publish(assets)
    store, barrier = schema.StaticFumenStore(), Barrier(8)
    def read(_):
        barrier.wait(timeout=10)
        return store.lookup(root, BASE, 'Oni', '1', now=NOW+1)
    with ThreadPoolExecutor(max_workers=8) as executor:
        entries = list(executor.map(read, range(8)))
    assert all(entry is entries[0] for entry in entries) and entries[0] is not None
    assert store.loads == 1


def test_atomic_manifest_switch_with_concurrent_readers(assets):
    root, _, _, policy, save_policy, _, _ = assets
    # Two valid generations with the same rights policy: a full manifest and a
    # verified subset. Readers may see either generation, never partial bytes.
    policy['grants'].append(dict(policy['grants'][0], song_id='2'))
    save_policy()
    publish(assets)
    path = root/'songs'/schema.MANIFEST
    first = json.loads(path.read_text())
    second = json.loads(path.read_text())
    second['entries'].append(dict(second['entries'][0], song_id='2'))
    second['resource_version'] = schema.digest(schema.canonical(dict(
        policy_sha256=second['policy_sha256'], entries=second['entries'])))
    versions = [schema.canonical(payload) for payload in (first, second)]
    store, barrier = schema.StaticFumenStore(), Barrier(5)
    old = store.lookup(root, BASE, 'Oni', '1', now=NOW+1)
    def writer():
        barrier.wait(timeout=10)
        for index in range(30):
            publisher.atomic_write(path, versions[index % 2])
    def reader():
        barrier.wait(timeout=10)
        for _ in range(60):
            entry = store.lookup(root, BASE, 'Oni', '1', now=NOW+2)
            # Signature changes during a read intentionally fail closed.
            assert entry is None or entry == old
            payload = json.loads(path.read_bytes())
            assert payload['resource_version'] in (first['resource_version'], second['resource_version'])
    with ThreadPoolExecutor(max_workers=5) as executor:
        jobs = [executor.submit(writer)] + [executor.submit(reader) for _ in range(4)]
        for job in jobs:
            job.result(timeout=15)
    assert store.lookup(root, BASE, 'Oni', '2', now=NOW+3) is not None
    assert old.song_id == '1' and old.url == first['entries'][0]['url']


def test_real_isolated_https_publication_and_repeat_fetch(assets, tmp_path):
    from datetime import datetime, timedelta, timezone
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import ipaddress
    import ssl
    from threading import Thread
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    root, publication, source, policy, save_policy, _, _ = assets
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'isolated static test')])
    stamp = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(private.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(stamp-timedelta(minutes=1))
        .not_valid_after(stamp+timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
        .sign(private, hashes.SHA256()))
    cert_path, key_path = tmp_path/'server.crt', tmp_path/'server.key'
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()))
    seen = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            filename = self.path.rsplit('/', 1)[1]
            assert filename == policy['grants'][0]['sha256']+'.png'
            data = (publication/'sha256'/filename).read_bytes()
            seen.append(self.path)
            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        def log_message(self, *args):
            pass
    server = HTTPServer(('127.0.0.1', 0), Handler)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert_path, key_path)
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f'https://127.0.0.1:{server.server_port}/approved/fumens'
    policy['base_url'] = base
    save_policy()
    try:
        verify = ssl.create_default_context(cafile=str(cert_path))
        with httpx.Client(verify=verify, trust_env=False, timeout=3) as client:
            result = publisher.publish(root, publication, base, client, now=NOW)
            assert result['published'] == 1
            entry = schema.StaticFumenStore().lookup(root, base, 'Oni', '1', now=NOW+1)
            source.unlink()
            for _ in range(2):
                response = client.get(entry.url)
                assert response.status_code == 200 and schema.digest(response.content) == entry.sha256
        assert len(seen) == 3 and len(set(seen)) == 1
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
        assert not worker.is_alive()
