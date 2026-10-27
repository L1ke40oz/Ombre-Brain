from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_checks_the_same_configured_source_as_the_installer():
    html = (ROOT / "frontend/dashboard.html").read_text(encoding="utf-8")
    source = (ROOT / "src/web/meta.py").read_text(encoding="utf-8")
    assert "authFetch('/api/update-check')" in html
    assert 'id="update-source-link"' in html
    assert "https://api.github.com/repos/P0luz/Ombre-Brain" not in html
    assert source.index('api.github.com/repos/{repo}/contents/{path}') < source.index('raw.githubusercontent.com/{repo}')


def test_dashboard_hot_update_surfaces_csrf_proxy_guidance():
    html = (ROOT / "frontend" / "dashboard.html").read_text(encoding="utf-8")
    block = html[html.index("window.doHotUpdate = async function()") :]
    block = block[: block.index("window.checkGitHubVersion = async function()")]

    assert "fetch(BASE + '/api/do-update'" in block
    assert "authFetch(BASE + '/api/do-update'" not in block
    assert "热更新不是可重试写操作" in block
    assert "failure.error === 'Cross-origin request rejected'" in block
    assert "这不是 CORS 缺失" in block
    assert "OMBRE_TRUSTED_PROXY_CIDRS" in block


def test_dashboard_retains_faq_content_without_a_navigation_entry():
    html = (ROOT / "frontend" / "dashboard.html").read_text(encoding="utf-8")
    faq_view = html[html.index('id="faq-view"') : html.index('<!-- Logs Tab View')]
    logs_view = html[html.index('id="logs-view"') : html.index('<!-- Settings Tab View -->')]

    faq_url = "https://docs.qq.com/doc/DRHp6UW9oYmd3QW5Z"
    assert 'data-tab="faq"' not in html
    assert 'id="faq-section"' in faq_view
    assert faq_url in faq_view
    assert 'target="_blank"' in faq_view
    assert 'rel="noopener noreferrer"' in faq_view
    assert 'id="faq-section"' not in logs_view
    assert "getElementById('faq-view').style.display = target === 'faq'" in html
