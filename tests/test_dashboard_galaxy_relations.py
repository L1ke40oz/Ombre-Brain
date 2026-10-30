"""Shared-category constellations keep all memory domains and ignore placeholders."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which('node') is None, reason='Node is unavailable')
def test_constellation_matches_any_domain_and_caps_the_brightest_related_stars():
    source = (ROOT / 'frontend/dashboard-galaxy.js').read_text(encoding='utf-8')
    helper = source[source.index('  function memoryDomains('):source.index('  var enginePromise')]
    script = "const NOISE_DOM={'':1,'其他':1,'未分类':1,'feel':1,'plan':1};\n" + helper + """
const memories=[
  {s:{domains:['其他',' 家庭 ','编程','家庭']},imp:5},
  {s:{domains:['工作','家庭']},imp:8},
  {s:{domains:['其他']},imp:10},
  {s:{domain:'编程'},imp:6},
  {s:{domains:['关系']},imp:9},
];
const matches=relatedMemories(memories,0).map(item=>item.i);
const allSame=Array.from({length:12},(_,i)=>({s:{domain:'家庭'},imp:i}));
const capped=relatedMemories(allSame,0).map(item=>item.i);
const placeholders=relatedMemories([{s:{domain:'其他'}},{s:{domain:'其他'}}],0);
console.log(JSON.stringify({matches,capped,placeholders,domains:memoryDomains([' 家庭 ',null,'家庭',''])}));
"""
    result = subprocess.run(['node', '-e', script], check=True, capture_output=True, encoding='utf-8')
    data = json.loads(result.stdout)
    assert data['matches'] == [1, 3]
    assert data['capped'] == [11, 10, 9, 8, 7, 6, 5, 4]
    assert data['placeholders'] == []
    assert data['domains'] == ['家庭']


@pytest.mark.skipif(shutil.which('node') is None, reason='Node is unavailable')
def test_star_fetch_retains_secondary_domains_and_hides_locked_letters():
    source = (ROOT / 'frontend/dashboard-galaxy.js').read_text(encoding='utf-8')
    helper = source[source.index('  function memoryDomains('):source.index('  var enginePromise')]
    fetcher = source[source.index('  function fetchStars()'):source.index('  // ── 粒子')]
    script = helper + fetcher + """
async function fetch(){return {ok:true,json:async()=>[
 {id:'a',domain:['工作',' 家庭 '],importance:8},
 {id:'b',domain:'编程'},
 {id:'locked',domain:['家庭'],letter_locked:true}
]};}
fetchStars().then(stars=>console.log(JSON.stringify(stars)));
"""
    result = subprocess.run(['node', '-e', script], check=True, capture_output=True, encoding='utf-8')
    stars = json.loads(result.stdout)
    assert [star['id'] for star in stars] == ['a', 'b']
    assert stars[0]['domain'] == '工作'
    assert stars[0]['domains'] == ['工作', '家庭']
    assert stars[1]['domains'] == ['编程']
