"""Browser delivery regressions: stable public caches and private auth state."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
from starlette.requests import Request
from web import dashboard

ROOT = Path(__file__).resolve().parents[1]


def request(name, revision='', etag=''):
    return Request({'type':'http', 'method':'GET', 'path':'/static/' + name,
                    'path_params':{'name':name}, 'query_string':('v=' + revision).encode(),
                    'headers':[(b'if-none-match', etag.encode())] if etag else []})


class MCP:
    def __init__(self):
        self.routes = {}

    def custom_route(self, path, methods):
        def register(handler):
            self.routes[path] = handler
            return handler
        return register


@pytest.mark.asyncio
async def test_versioned_image_is_cacheable_and_conditional_get_is_304(monkeypatch):
    monkeypatch.setattr(dashboard.sh, 'repo_root', str(ROOT))
    mcp = MCP()
    dashboard.register(mcp)
    handler = mcp.routes['/static/{name}']
    revision = dashboard._asset_revision('login-sky.webp')
    response = await handler(request('login-sky.webp', revision))
    assert response.status_code == 200
    assert 'immutable' in response.headers['cache-control']
    cached = await handler(request('login-sky.webp', revision, response.headers['etag']))
    assert cached.status_code == 304
    assert cached.body == b''
    for version in ['', 'old-version']:
        unversioned = await handler(request('login-sky.webp', version))
        assert unversioned.headers['cache-control'] == 'no-cache'


def test_identical_redeployment_keeps_asset_url_but_dependency_changes_invalidate_css(monkeypatch, tmp_path):
    frontend = tmp_path / 'frontend'
    frontend.mkdir()
    image = frontend / 'login-sky.webp'
    image.write_bytes(b'first picture')
    (frontend / 'login-cover.css').write_text("body{background:url('/static/login-sky.webp')}")
    monkeypatch.setattr(dashboard.sh, 'repo_root', str(tmp_path))
    before = dashboard._version_assets("/static/login-cover.css /static/login-sky.webp")
    stat = image.stat()
    os.utime(image, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000000))
    assert dashboard._version_assets("/static/login-cover.css /static/login-sky.webp") == before
    image.write_bytes(b'a different picture')
    after = dashboard._version_assets("/static/login-cover.css /static/login-sky.webp")
    assert after.split()[0] != before.split()[0]
    assert after.split()[1] != before.split()[1]


@pytest.mark.skipif(shutil.which('node') is None, reason='Node unavailable')
@pytest.mark.parametrize('failure', ['network', 'gateway'])
def test_auth_check_failure_keeps_cover_and_refuses_dashboard(failure):
    html = (ROOT / 'frontend/dashboard.html').read_text(encoding='utf-8')
    source = html[html.index('async function checkAuth()'):html.index('async function readAuthFailure(')]
    script = '''
let _dashboardAuthGeneration=0;
const nodes=new Map();
const document={getElementById(id){if(!nodes.has(id))nodes.set(id,{style:{},textContent:''});return nodes.get(id);}};
function invalidateAuthenticatedDashboardSession(){_dashboardAuthGeneration++;}
async function fetch(){FAILURE}
''' .replace('FAILURE', "throw new Error('offline');" if failure == 'network' else 'return {ok:false,status:502};')
    script += source + '''
(async()=>{const result=await checkAuth();console.log(JSON.stringify({result,
display:document.getElementById('auth-overlay').style.display,
error:document.getElementById('auth-error').textContent}));})();
'''
    result = subprocess.run(['node', '-e', script], check=True, capture_output=True, encoding='utf-8')
    data = json.loads(result.stdout)
    assert data['result'] is False
    assert data['display'] == 'flex'
    assert data['error']


@pytest.mark.skipif(shutil.which('node') is None, reason='Node unavailable')
def test_service_worker_does_not_intercept_private_requests():
    script = '''
const handlers={};const self={location:{origin:'https://example.test'},addEventListener(n,f){handlers[n]=f;}};
''' + (ROOT / 'frontend/sw.js').read_text(encoding='utf-8') + '''
for(const path of ['/','/auth/status','/api/buckets','/api/bucket/secret/media/a.png','/static/login-cover.js?v=0123456789abcdef']){
 const url='https://example.test'+path;
 handlers.fetch({request:{url,method:'GET',mode:'cors'},respondWith(){throw Error('private request intercepted: '+path);}});
}
console.log('ok');
'''
    subprocess.run(['node', '-e', script], check=True, capture_output=True, encoding='utf-8')


def test_manifest_has_real_standard_icons_and_root_scope():
    import struct
    manifest = json.loads((ROOT / 'frontend/manifest.json').read_text())
    assert manifest['scope'] == '/' and manifest['id'] == '/'
    assert manifest['display'] == 'standalone'
    for size in [192, 512]:
        icon = next(icon for icon in manifest['icons'] if icon['sizes'] == f'{size}x{size}')
        image = (ROOT / 'frontend' / icon['src'].split('/')[-1]).read_bytes()
        assert image[:8] == b'\x89PNG\r\n\x1a\n'
        assert struct.unpack('>II', image[16:24]) == (size, size)
