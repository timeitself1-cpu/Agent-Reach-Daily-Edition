const {JSDOM, VirtualConsole} = require('jsdom');
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const assert = require('node:assert/strict');
const test = require('node:test');
const root = resolve(__dirname, '..');
const script = readFileSync(resolve(root, 'assets/site.js'), 'utf8');
const edition = JSON.parse(readFileSync(resolve(root, 'editions/2026-10-07.json')));
const index = JSON.parse(readFileSync(resolve(root, 'editions/index.json')));
const monthly = JSON.parse(readFileSync(resolve(root, 'search/2026-10.json')));
const settle = () => new Promise(r => setTimeout(r, 25));
async function open(path = '/', opts = {}) {
  const pathname = new URL(path, 'https://example.test').pathname;
  const file = opts.shell || (pathname.endsWith('/') ? pathname + 'index.html' : pathname);
  const errors = [];
  const vc = new VirtualConsole();
  vc.on('jsdomError', e => errors.push(e.message));
  const dom = new JSDOM(readFileSync(resolve(root, '.' + file), 'utf8'), {
    url: 'https://example.test' + path, runScripts: 'outside-only', virtualConsole: vc,
  });
  const w = dom.window, d = w.document, requests = [];
  w.scrollTo = () => {};
  w.HTMLElement.prototype.scrollIntoView = () => {};
  w.Date.now = () => Date.parse(opts.now || '2026-10-08T16:00:00Z');
  w.fetch = async url => {
    requests.push(url);
    const override = opts.fetch && await opts.fetch(url, requests);
    if (override !== undefined) {
      if (override === false) return {ok:false,status:503};
      if (override && override.ok === false) return override;
      return {ok:true,json:async()=>structuredClone(override)};
    }
    return {ok:true,json:async()=>JSON.parse(readFileSync(resolve(root, '.' + url)))};
  };
  w.eval(script);
  await settle();
  return {w,d,requests,errors,close:()=>dom.window.close()};
}

test('all public route shells render and keep RSS discovery', async () => {
  for (const path of ['/', '/daily/', '/daily/2026-10-07/', '/latest/', '/technology/', '/science/', '/world/', '/archive/', '/search/', '/about/', '/404.html']) {
    const p = await open(path);
    assert.ok(p.d.querySelector('main h1'), path);
    assert.ok(p.d.querySelector('link[rel="alternate"][href="/feed.xml"]'), path);
    assert.ok(p.d.querySelector('footer a[href="/feed.xml"]'), path);
    assert.equal(p.d.querySelectorAll('.nav a').length, 7);
    assert.deepEqual(p.errors, [], path);
    p.close();
  }
});

test('latest river and category pages retain every fixture story', async () => {
  const p = await open('/latest/');
  assert.equal(p.d.querySelectorAll('.river-item').length, edition.stories.length);
  p.close();
  for (const [path, cat] of [['technology','Tech'], ['science','Science & AI'], ['world','News']]) {
    const q = await open('/'+path+'/');
    assert.equal(q.d.querySelectorAll('.card').length, edition.sections.find(s=>s.category===cat).ids.length);
    assert.equal(q.d.querySelectorAll('.card h2').length,q.d.querySelectorAll('.card').length);
    assert.equal(q.d.querySelectorAll('.card h3').length,0);
    assert.equal(q.d.querySelector('.nav [aria-current="page"]').textContent, path === 'science' ? 'Science & AI' : path[0].toUpperCase()+path.slice(1));
    q.close();
  }
});

test('fresh, stale, and archived edition information survives', async () => {
  const p = await open('/');
  assert.match(p.d.querySelector('.strip').textContent, /Latest edition.*Update 2.*44 stories.*1,517 reports.*10 of 10/s);
  assert.equal(p.d.querySelector('.strip time[datetime="2026-10-07T23:42:20Z"]').textContent.startsWith('Generated'),true);
  assert.equal(p.d.querySelector('.live.old'),null);
  p.close();
  const stale = await open('/', {now:'2026-10-10T16:00:00Z'});
  assert.ok(stale.d.querySelector('.live.old'));
  assert.match(stale.d.querySelector('.notice').textContent,/most recent edition/);
  stale.close();
  const old = await open('/daily/2026-10-07/',{fetch:u=>u==='/editions/index.json'?{...index,latest:'2026-10-08'}:undefined});
  assert.match(old.d.querySelector('.strip').textContent,/Archived edition/);
  assert.equal(old.d.querySelector('.notice a').getAttribute('href'),'/daily/');
  old.close();
});

test('story sources and source groups match fixture, jump preserves URL', async () => {
  for (const story of edition.stories) {
    const p = await open('/daily/2026-10-07/#story-'+story.id);
    assert.equal(p.d.querySelector('h1').textContent,story.headline);
    assert.equal(p.d.querySelectorAll('.sources .source').length,story.sources.length);
    assert.deepEqual([...p.d.querySelectorAll('.sources a.title')].map(a=>a.href).sort(), story.sources.map(s=>s.url).sort());
    for (const [kind, title] of [['report','Independent reports'],['repeat','Repeats and syndicated copies'],['signal','Social and search signals']]) {
      const count=story.sources.filter(s=>s.kind===kind).length;
      const heading=[...p.d.querySelectorAll('.sources h3')].find(h=>h.textContent===`${title} (${count})`);
      if(count) {
        assert.ok(heading,`${story.id}: ${kind}`);
        assert.deepEqual([...heading.parentElement.querySelectorAll('a.title')].map(a=>a.href).sort(),story.sources.filter(s=>s.kind===kind).map(s=>s.url).sort());
      } else assert.equal([...p.d.querySelectorAll('.sources h3')].some(h=>h.textContent.startsWith(title)),false);
    }
    const hash = p.w.location.hash;
    p.d.querySelector('.source-jump').click();
    assert.equal(p.w.location.hash,hash);
    assert.equal(p.d.activeElement.id,'sources');
    assert.deepEqual(p.errors,[]);
    p.close();
  }
});

test('skip and regular anchors never remount a story; next/back focus title', async () => {
  const p = await open('/daily/2026-10-07/#story-'+edition.top[0]);
  const main = p.d.querySelector('main'), headline = p.d.querySelector('h1').textContent;
  p.d.querySelector('.skip').click();
  await settle();
  assert.equal(p.d.querySelector('main'),main);
  assert.equal(p.d.activeElement,main);
  assert.equal(p.w.location.hash,'#story-'+edition.top[0]);
  p.w.location.hash='#sources'; await settle();
  assert.equal(p.d.querySelector('main'),main);
  p.w.location.hash='#story-'+edition.top[0]; await settle();
  assert.equal(p.d.querySelector('main'),main);
  p.w.location.hash='#story-'+edition.top[1]; await settle();
  assert.notEqual(p.d.querySelector('h1').textContent,headline);
  assert.equal(p.d.activeElement,p.d.querySelector('h1'));
  p.w.location.hash='#story-'+edition.top[0]; await settle();
  assert.equal(p.d.querySelector('h1').textContent,headline);
  assert.equal(p.d.activeElement,p.d.querySelector('h1'));
  assert.deepEqual(p.errors,[]);
  p.close();
});

test('delayed page loading retains keyboard focus and a persistent status region',async()=>{
  for(const selector of ['.brand','.nav a[href="/"]','.skip','main']) {
    let release; const deferred=new Promise(r=>release=r);
    const p=await open('/',{fetch:u=>u==='/editions/index.json'?deferred:undefined});
    const status=p.d.querySelector('#page-status');
    assert.match(status.textContent,/Loading the edition/);
    assert.equal(p.d.querySelector('main').getAttribute('aria-busy'),'true');
    p.d.querySelector(selector).focus(); release(index); await settle();
    assert.equal(p.d.activeElement,p.d.querySelector(selector),selector);
    assert.equal(p.d.querySelector('#page-status'),status);
    assert.match(status.textContent,/Edition loaded.*44 stories/);
    assert.equal(p.d.querySelector('main').getAttribute('aria-busy'),'false');
    p.close();
  }
  const p=await open('/latest/');
  const main=p.d.querySelector('main');
  p.w.location.hash='#main'; await settle();
  p.w.location.hash=''; await settle();
  assert.equal(p.d.querySelector('main'),main);
  assert.notEqual(p.d.activeElement,p.d.querySelector('main h1'));
  p.close();
});

test('search recovery has a stable pending focus target without stealing later focus',async()=>{
  let release,attempts=0; const deferred=new Promise(r=>release=r);
  const p=await open('/search/?q=Hamilton',{fetch:u=>u.startsWith('/search/')?(++attempts===1?false:deferred):undefined});
  const status=p.d.querySelector('#search-status'),input=p.d.querySelector('input');
  p.d.querySelector('[data-act="retry"]').click();
  assert.equal(p.d.activeElement,status);
  assert.equal(p.d.querySelector('#search-results').getAttribute('aria-busy'),'true');
  assert.equal(p.d.querySelector('#search-results').getAttribute('aria-describedby'),'search-status');
  assert.equal(p.d.querySelector('#search-results').getAttribute('aria-label'),'Search results');
  input.focus(); release(monthly); await settle();
  assert.equal(p.d.activeElement,input);
  assert.equal(p.d.querySelector('#search-results').getAttribute('aria-busy'),'false');
  assert.match(status.textContent,/1 story found/);
  p.close();
});

test('Show more continues keyboard reading at the first newly revealed result',async()=>{
  const p=await open('/search/?q=the',{fetch:u=>u==='/editions/index.json'?{...index,editions:[index.editions[0],{...index.editions[0],date:'2026-09-07'}]}:u.includes('/search/2026-09')?{...monthly,stories:monthly.stories.map(s=>({...s,d:'2026-09-07'}))}:undefined});
  assert.equal(p.d.querySelectorAll('.hit').length,40);
  p.d.querySelector('[data-act="more"]').click(); await settle();
  assert.equal(p.d.activeElement,p.d.querySelectorAll('.hit h2 a')[40]);
  p.close();
});

test('search prefix, phrase, outlet, empty results and URL state', async () => {
  for (const [q, text] of [['Hamilt','Hamilton'], ['"Margaret Hamilton"','Hamilton'], ['Reuters','Reuters']]) {
    const p = await open('/search/?q='+encodeURIComponent(q));
    assert.ok(p.d.querySelectorAll('.hit').length > 0,q);
    assert.match(p.d.querySelector('.hits').textContent,new RegExp(text));
    assert.ok(p.d.querySelector('mark'));
    assert.equal(p.d.querySelector('.hits').getAttribute('aria-busy'),'false');
    assert.deepEqual(p.errors,[]);
    p.close();
  }
  const p = await open('/search/?q=zzzznoresults');
  assert.equal(p.d.querySelectorAll('.hit').length,0);
  assert.match(p.d.querySelector('.search-empty').textContent,/No matching stories/);
  assert.equal(p.d.querySelector('.search-empty a').getAttribute('href'),'/archive/');
  p.close();
});

test('search live query, section, sort, submit focus and clear', async () => {
  const p = await open('/search/');
  const input = p.d.querySelector('input'), cat = p.d.querySelector('select');
  assert.notEqual(p.d.activeElement,input);
  input.focus(); input.value='AI'; input.dispatchEvent(new p.w.Event('input'));
  await new Promise(r=>setTimeout(r,180));
  assert.ok(p.d.querySelectorAll('.hit').length>0);
  cat.value='Science & AI'; cat.dispatchEvent(new p.w.Event('change')); await settle();
  assert.ok([...p.d.querySelectorAll('.hit')].every(n=>n.dataset.cat==='Science & AI'));
  p.d.querySelector('[data-sort="best"]').click(); await settle();
  assert.match(p.w.location.search,/sort=best/);
  assert.match(p.w.location.search,/cat=Science/);
  input.focus(); p.d.querySelector('form').dispatchEvent(new p.w.Event('submit',{cancelable:true})); await settle();
  assert.equal(p.d.activeElement,input);
  input.value=''; input.dispatchEvent(new p.w.Event('input')); await new Promise(r=>setTimeout(r,180));
  assert.equal(p.d.querySelectorAll('.hit').length,0);
  assert.match(p.d.querySelector('[role="status"]').textContent,/Type to search/);
  p.close();
});

test('unavailable search month can be retried without reloading', async () => {
  let attempts=0;
  const p=await open('/search/?q=Hamilton',{fetch:u=>u.startsWith('/search/') && ++attempts===1 ? false : undefined});
  assert.match(p.d.querySelector('[role="status"]').textContent,/unavailable.*No editions could be searched/);
  assert.match(p.d.querySelector('.search-recovery').textContent,/October 2026/);
  assert.ok(p.d.querySelector('.search-recovery a[href="/archive/"]'));
  assert.doesNotMatch(p.d.querySelector('.hits').textContent,/No matching stories/);
  p.d.querySelector('[data-act="retry"]').click(); await settle();
  assert.equal(attempts,2);
  assert.ok(p.d.querySelectorAll('.hit').length>0);
  assert.equal(p.d.querySelector('[data-act="retry"]'),null);
  assert.equal(p.d.querySelector('.search-recovery').textContent,'');
  assert.equal(p.d.activeElement,p.d.querySelector('[role="status"]'));
  p.close();
});

test('a failed prefetched month stays retryable after repeated failures',async()=>{
  let attempts=0;
  const p=await open('/search/',{fetch:u=>u.startsWith('/search/') && ++attempts<=2 ? false : undefined});
  assert.equal(attempts,1);
  const input=p.d.querySelector('input'); input.value='Hamilton';
  const cat=p.d.querySelector('select'); cat.value='Tech'; cat.dispatchEvent(new p.w.Event('change'));
  p.d.querySelector('[data-sort="best"]').click(); await settle();
  assert.equal(attempts,1);
  assert.match(p.d.querySelector('[role="status"]').textContent,/unavailable/);
  p.d.querySelector('[data-act="retry"]').click(); await settle();
  assert.equal(attempts,2);
  assert.ok(p.d.querySelector('[data-act="retry"]'));
  assert.equal(p.d.activeElement,p.d.querySelector('[role="status"]'));
  p.d.querySelector('[data-act="retry"]').click(); await settle();
  assert.equal(attempts,3);
  assert.equal(p.d.querySelectorAll('.hit').length,1);
  assert.equal(new URLSearchParams(p.w.location.search).get('q'),'Hamilton');
  assert.equal(new URLSearchParams(p.w.location.search).get('cat'),'Tech');
  assert.equal(new URLSearchParams(p.w.location.search).get('sort'),'best');
  assert.equal(p.d.querySelector('[data-act="retry"]'),null);
  p.close();
});

test('monthly batching, partial failure, older search and pagination remain intact', async () => {
  const dates=Array.from({length:7},(_,i)=>`2026-${String(10-i).padStart(2,'0')}-07`);
  const idx={...index,editions:dates.map(date=>({...index.editions[0],date}))};
  let fail=true;
  const p=await open('/search/?q=the',{fetch:u=>{
    if(u==='/editions/index.json') return idx;
    if(u.startsWith('/search/')) {
      if(u.includes('2026-09') && fail) return false;
      return {...monthly,stories:monthly.stories.map(s=>({...s,d:u.slice(8,15)+'-07'}))};
    }
  }});
  assert.equal(p.requests.filter(u=>u.startsWith('/search/')).length,6);
  assert.equal(p.d.querySelectorAll('.hit').length,40);
  assert.match(p.d.querySelector('[role="status"]').textContent,/incomplete/);
  assert.match(p.d.querySelector('[role="status"]').textContent,/5 searched editions/);
  assert.match(p.d.querySelector('.search-recovery').textContent,/September 2026/);
  p.d.querySelector('[data-act="more"]').click(); await settle();
  assert.ok(p.d.querySelectorAll('.hit').length>40);
  fail=false; p.d.querySelector('[data-act="retry"]').click(); await settle();
  assert.doesNotMatch(p.d.querySelector('[role="status"]').textContent,/incomplete/);
  assert.match(p.d.querySelector('[role="status"]').textContent,/6 searched editions/);
  p.d.querySelector('[data-act="older"]').click(); await settle();
  assert.ok(p.requests.includes('/search/2026-04.json'));
  assert.equal(p.d.querySelector('[data-act="older"]'),null);
  p.close();
});

test('section and sort actions use the latest input before its debounce finishes', async()=>{
  for(const action of ['section','sort']) {
    const p=await open('/search/?q=zzzznoresults');
    const input=p.d.querySelector('input');
    input.value='Hamilton'; input.dispatchEvent(new p.w.Event('input'));
    if(action==='section') {
      const cat=p.d.querySelector('select'); cat.value='Tech'; cat.dispatchEvent(new p.w.Event('change'));
    } else p.d.querySelector('[data-sort="best"]').click();
    await settle();
    assert.equal(p.d.querySelectorAll('.hit').length,1);
    assert.equal(new URLSearchParams(p.w.location.search).get('q'),'Hamilton');
    assert.match(p.d.querySelector('.hit h2').textContent,/Hamilton/);
    p.close();
  }
});

test('invalid section links recover to all sections; filtered empty results can broaden',async()=>{
  for(const cat of ['bogus','toString','__proto__']) {
    const p=await open('/search/?q=Hamilton&cat='+cat+'&sort=best');
    assert.equal(p.d.querySelector('select').value,'');
    assert.equal(p.d.querySelectorAll('.hit').length,1);
    assert.equal(new URLSearchParams(p.w.location.search).has('cat'),false);
    assert.equal(new URLSearchParams(p.w.location.search).get('sort'),'best');
    p.close();
  }
  const p=await open('/search/?q=Hamilton&cat=Sports&sort=best');
  assert.equal(p.d.querySelectorAll('.hit').length,0);
  assert.match(p.d.querySelector('.search-empty').textContent,/No matching stories/);
  p.d.querySelector('[data-act="all-sections"]').click(); await settle();
  assert.equal(p.d.querySelectorAll('.hit').length,1);
  assert.equal(p.d.querySelector('select').value,'');
  assert.equal(new URLSearchParams(p.w.location.search).get('q'),'Hamilton');
  assert.equal(new URLSearchParams(p.w.location.search).get('sort'),'best');
  assert.equal(p.d.activeElement,p.d.querySelector('[role="status"]'));
  p.close();
});

test('invalid monthly data is retryable; valid empty data remains a true empty result',async()=>{
  const p=await open('/search/?q=Hamilton',{fetch:u=>u.startsWith('/search/')?{}:undefined});
  assert.match(p.d.querySelector('[role="status"]').textContent,/unavailable/);
  assert.ok(p.d.querySelector('[data-act="retry"]'));
  assert.equal(p.d.querySelector('.search-empty'),null);
  p.close();
  const empty=await open('/search/?q=Hamilton',{fetch:u=>u.startsWith('/search/')?{...monthly,stories:[]}:undefined});
  assert.match(empty.d.querySelector('[role="status"]').textContent,/0 stories found across 1 searched edition/);
  assert.match(empty.d.querySelector('.search-empty').textContent,/No matching stories/);
  assert.equal(empty.d.querySelector('[data-act="retry"]'),null);
  empty.close();
});

test('empty search scope and punctuation guidance stay distinct from unavailable data',async()=>{
  const p=await open('/search/?q=zzzznoresults',{fetch:u=>u==='/editions/index.json'?{...index,editions:Array.from({length:7},(_,i)=>({...index.editions[0],date:`2026-${String(10-i).padStart(2,'0')}-07`}))}:u.startsWith('/search/')?monthly:undefined});
  assert.match(p.d.querySelector('.search-empty').textContent,/No matches in the searched editions/);
  assert.ok(p.d.querySelector('[data-act="older"]'));
  p.close();
  const punctuation=await open('/search/?q=!!!');
  assert.match(punctuation.d.querySelector('[role="status"]').textContent,/Enter a word or phrase/);
  assert.equal(punctuation.d.querySelector('.search-empty'),null);
  punctuation.close();
});

test('a delayed earlier search cannot overwrite the current query', async()=>{
  let release;
  const deferred=new Promise(r=>release=r);
  const p=await open('/search/?q=Hamilton',{fetch:u=>u.startsWith('/search/')?deferred:undefined});
  const input=p.d.querySelector('input'); input.value='zzzznoresults';
  p.d.querySelector('form').dispatchEvent(new p.w.Event('submit',{cancelable:true}));
  release(monthly); await settle();
  assert.equal(p.d.querySelectorAll('.hit').length,0);
  assert.match(p.d.querySelector('.search-empty').textContent,/No matching stories/);
  assert.equal(p.d.querySelector('.hits').getAttribute('aria-busy'),'false');
  p.close();
});

test('failed edition load keeps archive recovery and safe text rendering', async()=>{
  const p=await open('/',{fetch:u=>u.includes('/editions/2026')?false:undefined});
  assert.match(p.d.querySelector('main').textContent,/could not be loaded/);
  assert.ok(p.d.querySelector('main a[href="/archive/"]'));
  p.close();
  const unsafe=structuredClone(edition); unsafe.stories[0].headline='<img src=x onerror=alert(1)>';
  const q=await open('/',{fetch:u=>u.includes('/editions/2026')?unsafe:undefined});
  assert.equal(q.d.querySelector('h1').textContent,unsafe.stories[0].headline);
  assert.equal(q.d.querySelector('h1 img'),null);
  q.close();
});

test('generation and source times remain explicit on every news-reading view',async()=>{
  for(const path of ['/', '/daily/2026-10-07/', '/latest/', '/technology/', '/science/', '/world/', '/daily/2026-10-07/#story-'+edition.top[0]]) {
    const p=await open(path);
    const generated=p.d.querySelector('.strip time[datetime="'+edition.generated_utc+'"]');
    assert.ok(generated,path);
    assert.match(generated.textContent,/Generated.*2026/);
    assert.match(p.d.querySelector('.strip').textContent,/Latest edition.*Update 2/);
    if(path.includes('#story')) {
      assert.ok(p.d.querySelector('.sources time[datetime]'));
      assert.equal(p.d.querySelector('.story-main .meta time').getAttribute('datetime'),edition.stories[0].newest_published_utc);
    }
    p.close();
  }
});

test('null source URLs and empty optional values remain readable plain text',async()=>{
  const ed=structuredClone(edition),story=ed.stories[0];
  story.sources[0].url=null; story.sources[0].published_utc=null;
  story.sources[0].title='<b>Source title is plain text</b>';
  story.why_it_matters=''; story.top_rank=null; story.summary=['A short summary.']; ed.compared_with=null;
  const p=await open('/daily/2026-10-07/#story-'+story.id,{fetch:u=>u.includes('/editions/2026')?ed:undefined});
  const source=p.d.querySelector('.source');
  assert.equal(source.querySelector('a'),null);
  assert.equal(source.querySelector('.title').textContent,story.sources[0].title);
  assert.equal(source.querySelector('b'),null);
  assert.equal(source.querySelector('time'),null);
  assert.match(source.textContent,/Time not stated/);
  assert.equal(p.d.querySelector('.why-box'),null);
  assert.equal(p.d.querySelectorAll('.story-body p').length,1);
  p.close();
  const card=await open('/technology/',{fetch:u=>u.includes('/editions/2026')?ed:undefined});
  assert.equal(card.d.querySelectorAll('.card').length,8);
  assert.equal(card.d.querySelector('details.src a[href$="/null"]'),null);
  assert.ok([...card.d.querySelectorAll('details.src li')].some(li=>li.textContent.includes(story.sources[0].title)&&!li.querySelector('a')));
  card.close();
});

test('search links recover changed IDs by exact or clearly shared headlines on the same date',async()=>{
  const original=edition.stories[0], ed=structuredClone(edition), replacement='abcdef123456';
  ed.stories[0].id=replacement; ed.revision=3;
  ed.top=ed.top.map(id=>id===original.id?replacement:id);
  ed.sections.forEach(sec=>sec.ids=sec.ids.map(id=>id===original.id?replacement:id));
  for(const hint of [original.headline.toUpperCase()+'!', 'Computing Pioneer Margaret Hamilton Dies Aged 90']) {
    const p=await open('/daily/2026-10-07/?headline='+encodeURIComponent(hint)+'#story-'+original.id,{fetch:u=>u.includes('/editions/2026')?ed:undefined});
    assert.equal(p.d.querySelector('h1').textContent,original.headline);
    assert.equal(p.w.location.hash,'#story-'+replacement);
    assert.equal(p.w.location.search,'');
    assert.match(p.d.querySelector('.story-recovery').textContent,/headline match/);
    assert.equal(p.d.querySelectorAll('.sources .source').length,original.sources.length);
    p.close();
  }
  const search=await open('/search/?q=Hamilton');
  const href=new URL(search.d.querySelector('.hit h2 a').href);
  assert.equal(href.searchParams.get('headline'),original.headline);
  assert.equal(href.hash,'#story-'+original.id);
  search.close();
});

test('missing story recovery never guesses on ties, weak matches, or absent headline hints',async()=>{
  const ed=structuredClone(edition);
  ed.stories[0].headline='Alpha beta gamma delta'; ed.stories[1].headline='Alpha beta gamma epsilon';
  for(const hint of ['Alpha beta gamma zeta', 'Alpha beta gamma delta', 'Alpha unknown unrelated', '']) {
    const doc=structuredClone(ed);
    if(hint==='Alpha beta gamma delta') doc.stories[1].headline=doc.stories[0].headline;
    const p=await open('/daily/2026-10-07/'+(hint?'?headline='+encodeURIComponent(hint):'')+'#story-abcdef123456',{fetch:u=>u.includes('/editions/2026')?doc:undefined});
    assert.ok(p.d.querySelector('.front'));
    assert.equal(p.d.querySelector('.story'),null);
    assert.match(p.d.querySelector('.story-recovery').textContent,/full edition/);
    p.close();
  }
});

test('withdrawn edition JSON and dated 404 shells provide archive recovery',async()=>{
  const removed=await open('/daily/2026-10-07/#story-'+edition.top[0],{fetch:u=>u.includes('/editions/2026')?{ok:false,status:404}:undefined});
  assert.match(removed.d.querySelector('h1').textContent,/This edition was taken off/);
  assert.ok(removed.d.querySelector('main a[href="/archive/"]'));
  removed.close();
  const p=await open('/daily/2026-10-07/#story-'+edition.top[0],{fetch:u=>u.includes('/editions/2026')?false:undefined});
  // A temporary server failure is not described as a withdrawal.
  assert.doesNotMatch(p.d.querySelector('h1').textContent,/taken off/);
  p.close();
  const withdrawn=await open('/daily/2026-10-06/',{shell:'/404.html'});
  assert.match(withdrawn.d.querySelector('h1').textContent,/This edition was taken off/);
  assert.ok(withdrawn.d.querySelector('main a[href="/archive/"]'));
  assert.equal(withdrawn.d.querySelector('#page-status').textContent,withdrawn.d.querySelector('h1').textContent);
  withdrawn.close();
});
