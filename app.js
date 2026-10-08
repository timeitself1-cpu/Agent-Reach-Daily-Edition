// The demo shows a real sample of an Agent Reach Daily edition (daily-sample.json, written by the app:
// python -m agent_reach.daily --export-sample daily-sample.json --stories 1,2,3,4,9). All text goes in as text.
let sample=null,selected=0;
const $=id=>document.getElementById(id);
function webUrl(u){try{const x=new URL(u);return x.protocol==='https:'||x.protocol==='http:'?x.href:null;}catch(e){return null;}}
function el(tag,text,cls){const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;}
function renderStory(){const s=sample.stories[selected];
  $('demo-id').textContent='Story '+s.rank+' of '+sample.stories_in_edition+' / '+s.category+(s.independent_reports?' / '+s.independent_reports+' independent reports':'');
  $('demo-title').textContent=s.headline;
  const d=$('demo-description');d.replaceChildren(...s.summary.map(t=>el('p',t)));
  if(s.why_it_matters)d.append(el('p','Why it matters: '+s.why_it_matters,'why'));
  $('demo-sources').replaceChildren(...s.sources.map(src=>{const li=document.createElement('li');const url=webUrl(src.url);
    const a=url?el('a',src.title):el('span',src.title);if(url){a.href=url;a.rel='noopener noreferrer';a.target='_blank';}
    li.append(a,el('small',src.outlet+(src.via&&src.via!==src.outlet?' via '+src.via:'')));return li;}));
  $('demo-evidence').textContent=s.evidence.length?s.evidence.join('; ')+'.':'One report.';
  $('demo-grouping').textContent='Agent Reach Daily on a Windows PC: grouped with '+sample.models.grouping+', written by '+sample.models.summaries+', both running locally in Ollama.';
  $('event-json').textContent=JSON.stringify(s,null,2);
  document.querySelectorAll('[data-story]').forEach(b=>{const on=Number(b.dataset.story)===selected;b.classList.toggle('active',on);b.setAttribute('aria-pressed',String(on));});}
function renderList(){$('story-list').replaceChildren(...sample.stories.map((s,i)=>{const b=el('button',null,'event-option');b.type='button';b.dataset.story=String(i);
    b.append(el('span',s.category.toUpperCase(),'tiny-label'),el('strong',s.headline),el('span',s.sources.length+' sources'));
    b.addEventListener('click',()=>{selected=i;renderStory();});return b;}));
  const day=new Date(sample.edition_date+'T12:00:00Z').toLocaleDateString('en-US',{month:'long',day:'numeric',year:'numeric',timeZone:'UTC'});
  $('sample-label').textContent=day.toUpperCase()+' · TOP STORIES';
  $('sample-note').textContent=sample.stories.length+' of the edition’s '+sample.stories_in_edition+' stories. Summaries are written by the app; the articles belong to their publishers.';}
document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>{const json=button.dataset.view==='json';$('event-summary').hidden=json;$('event-json').hidden=!json;document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));}));
fetch('daily-sample.json',{cache:'no-cache'}).then(r=>{if(!r.ok)throw new Error(r.status);return r.json();})
  .then(data=>{if(!data||!Array.isArray(data.stories)||!data.stories.length)throw new Error('empty');sample=data;renderList();renderStory();})
  .catch(()=>{$('demo-title').textContent='The sample edition could not be loaded.';$('demo-description').replaceChildren(el('p','Please reload the page.'));});
