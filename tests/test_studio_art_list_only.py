import subprocess

import pytest


def run_node(script):
    result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_studio_credits_are_text_links_without_image_requests():
    run_node(r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('frontend/app.js','utf8');
const ctx={esc:String,fmtDate:String};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('frontend/studio_art_overrides.js','utf8'),ctx);
vm.runInContext(source.slice(source.indexOf('function studioLink'),source.indexOf('function sceneRowsHtml')),ctx);
for(const row of [
  {studio:{id:'studio-1',name:'Example Studio'}},
  {studio:'Example Studio',studio_id:'studio-1'}
]){
  const html=ctx.studioLink({...row,release_date:'2026-09-01'});
  assert(!html.includes('<img'),'studio credits must not request images');
  assert(html.includes('data-studio-link="studio-1"'));
  assert(html.includes('Example Studio'));
  assert(html.includes('2026-09-01'));
  assert(!ctx.studioLink({...row,release_date:'2026-09-01'},false).includes('2026-09-01'));
}
assert(!ctx.studioLink({}).includes('<img'));
""")


def test_studios_list_keeps_artwork_and_profile_navigation():
    run_node(r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('frontend/app.js','utf8'),ctx={esc:String};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('frontend/studio_art_overrides.js','utf8'),ctx);
vm.runInContext(source.slice(source.indexOf('function entityCard'),source.indexOf('function bindEntityActions')),ctx);
for(const inLibrary of [true,false]){
  const html=ctx.entityCard('studios',{id:7,tpdb_id:'studio-1',name:'Example Studio',monitored:true},inLibrary);
  assert(html.includes('<img src="/api/artwork/studios/studio-1?'));
  assert(html.includes('data-id="studio-1"'));
  assert(html.includes('Example Studio'));
  assert(html.includes(inLibrary?'data-detail':'data-remote-detail'));
}
""")


@pytest.mark.parametrize('renderer', ['base', 'active'])
def test_studio_profile_has_no_artwork_or_empty_image_column(renderer):
    run_node(r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const app=fs.readFileSync('frontend/app.js','utf8');
const nodes=new Map();
const ctx={render(){},renderEntities(){},esc:String,empty:String,
  $:selector=>{if(!nodes.has(selector))nodes.set(selector,{});return nodes.get(selector)},
  pageHead:(title,subtitle,actions)=>`<h1>${title}</h1>${actions}`,
  nextNavigationGeneration:()=>1,navigationGenerationCurrent:()=>true,
  sceneProfileList:()=>'',bindProfileSceneLinks(){},loadAllStudioScenes:async()=>({items:[]}),
  notify:message=>{throw Error(message)},
  api:async url=>{
    assert.equal(url,'/api/library/studios/7/detail');
    return {id:7,tpdb_id:'studio-1',name:'Example Studio',logo_url:'logo.png',
      poster_url:'poster.png',image_url:'image.png',description:'Studio biography',
      url:'https://example.test',monitored:false};
  }
};
vm.createContext(ctx);
""" + (
        "vm.runInContext(app.slice(app.indexOf('async function studioProfile'),app.indexOf('async function openLocalScene')),ctx);"
        if renderer == 'base' else
        "vm.runInContext(fs.readFileSync('frontend/navigation_error_overrides.js','utf8'),ctx);ctx.initProfileSceneCatalog=()=>{};"
    ) + r"""
(async()=>{
  await ctx.studioProfile('studio-1',7);
  const html=nodes.get('#app').innerHTML;
  assert(!html.includes('<img'),'studio profiles must not request artwork');
  assert(!html.includes('profile-image'),'no empty image placeholder');
  assert(!html.includes('profile-shell'),'no reserved image column');
  assert(html.includes('Example Studio'));
  assert(html.includes('Studio biography'));
  assert(html.includes('Studio Scenes'));
  assert(html.includes('Open site'));
  assert(html.includes('Monitor'));
})().catch(error=>{console.error(error);process.exitCode=1});
""")
