/* ============================================================
   崇岳鉴渊 · 化学讲义交互 (chem.js) — 依赖 cyjy.js (window.CY)
   目录抽屉 / 全文搜索 / 滚动高亮 / 折叠 / 测验 / 筛选
   ============================================================ */
(function(){
'use strict';
var CY=window.CY||{},$=function(s,r){return (r||document).querySelector(s)},$$=function(s,r){return Array.prototype.slice.call((r||document).querySelectorAll(s))};
var esc=CY.esc||function(s){return String(s).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})};
var RM=!!CY.reduced,doc=$('.chem-doc'),side=$('#sidebar'),main=$('#main-content')||$('.main');
if(!doc||!main)return;
function go(el){if(!el)return;el.scrollIntoView({behavior:RM?'auto':'smooth',block:'start'});flash(el)}
function flash(el){el.classList.remove('chem-flash');void el.offsetWidth;el.classList.add('chem-flash');setTimeout(function(){el.classList.remove('chem-flash')},1600)}

/* ---------- 移动端目录抽屉 ---------- */
var btn=$('#tocBtn'),bd=document.createElement('div');bd.className='chem-backdrop';document.body.appendChild(bd);
function drawer(on){if(!side)return;side.classList.toggle('show',on);bd.classList.toggle('on',on);document.body.style.overflow=on?'hidden':''}
if(btn)btn.addEventListener('click',function(){drawer(!side.classList.contains('show'))});
bd.addEventListener('click',function(){drawer(false)});
document.addEventListener('keydown',function(e){if(e.key==='Escape')drawer(false)});
if(side)side.addEventListener('click',function(e){if(e.target.closest('a[href^="#"]')&&window.innerWidth<1024)drawer(false)});

/* ---------- 全文搜索 ---------- */
var input=$('#search-input'),box=$('#search-results');
if(input&&box){
  var idx=null,cur=-1,hits=[];
  function build(){
    idx=[];var seen=new Set();
    $$('h1,h2,h3,h4,.pb-title,.card-title,.quiz-question,.chapter-num,p,li,td',main).forEach(function(el){
      if(el.closest('.search-box'))return;
      var t=(el.textContent||'').replace(/\s+/g,' ').trim();if(t.length<2)return;
      var key=t.slice(0,80);if(seen.has(key))return;seen.add(key);
      var w=/^H[1-4]$/.test(el.tagName)?3:el.matches('.pb-title,.card-title,.chapter-num')?2:1;
      idx.push({el:el,t:t,lt:t.toLowerCase(),w:w});
    });
  }
  function mark(t,q){var i=t.toLowerCase().indexOf(q),s=Math.max(0,i-18),snip=(s?'…':'')+t.slice(s,s+80)+(t.length>s+80?'…':'');var j=snip.toLowerCase().indexOf(q);return j<0?esc(snip):esc(snip.slice(0,j))+'<mark>'+esc(snip.slice(j,j+q.length))+'</mark>'+esc(snip.slice(j+q.length))}
  function render(){box.innerHTML=hits.length?hits.map(function(h,i){return '<div class="search-result-item'+(i===cur?' on':'')+'" data-i="'+i+'">'+mark(h.t,input.value.trim().toLowerCase())+'</div>'}).join(''):'<div class="search-empty">没有找到相关内容</div>';box.style.display='block'}
  function run(){
    var q=input.value.trim().toLowerCase();cur=-1;
    if(q.length<1){box.style.display='none';return}
    if(!idx)build();
    hits=idx.filter(function(x){return x.lt.indexOf(q)>-1}).sort(function(a,b){return b.w-a.w}).slice(0,12);render();
  }
  function pick(i){var h=hits[i];if(!h)return;box.style.display='none';input.blur();if(window.innerWidth<1024)drawer(false);var target=h.el.closest('.problem-block,.quiz-card,.knowledge-card')||h.el;var det=h.el.closest('details');if(det)det.open=true;go(target)}
  input.addEventListener('input',run);
  input.addEventListener('focus',function(){if(input.value.trim())run()});
  input.addEventListener('keydown',function(e){
    if(box.style.display!=='block')return;
    if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();cur=Math.max(0,Math.min(hits.length-1,cur+(e.key==='ArrowDown'?1:-1)));render()}
    else if(e.key==='Enter'){e.preventDefault();pick(cur<0?0:cur)}
    else if(e.key==='Escape'){box.style.display='none'}
  });
  box.addEventListener('mousedown',function(e){var it=e.target.closest('[data-i]');if(it){e.preventDefault();pick(+it.getAttribute('data-i'))}});
  /* 支持 ?q= 预填搜索（化学首页“反应类型速查”跳转过来） */
  var q0='';try{q0=new URLSearchParams(location.search).get('q')||''}catch(e){}
  if(q0){input.value=q0.slice(0,40);setTimeout(function(){run();if(hits.length){var h=hits[0],t=h.el.closest('.problem-block,.quiz-card,.knowledge-card')||h.el,d=h.el.closest('details');if(d)d.open=true;go(t)}if(window.innerWidth<1024)box.style.display='none'},400)}
  document.addEventListener('click',function(e){if(!box.contains(e.target)&&e.target!==input)box.style.display='none'});
}

/* ---------- 目录 / 章节导航 滚动高亮 ---------- */
function spy(links){
  links=links.filter(function(a){return a.hash&&a.hash.length>1});
  var targets=links.map(function(a){try{return document.getElementById(decodeURIComponent(a.hash.slice(1)))}catch(e){return null}}),last=-2;
  function run(){
    var cur=-1;for(var i=0;i<targets.length;i++)if(targets[i]&&targets[i].getBoundingClientRect().top<=140)cur=i;
    if(cur===last)return;last=cur;
    links.forEach(function(a,i){a.classList.toggle('active',i===cur)});
    var a=links[cur],p=a&&(a.closest('.sidebar')||a.closest('.cn-panel'));
    if(p&&p.scrollHeight>p.clientHeight){var r=a.getBoundingClientRect(),pr=p.getBoundingClientRect();if(r.top<pr.top+60||r.bottom>pr.bottom-40)p.scrollTo({top:p.scrollTop+(r.top-pr.top)-pr.height/3,behavior:RM?'auto':'smooth'})}
  }
  if(CY.onScroll)CY.onScroll(run);else window.addEventListener('scroll',run,{passive:true});
  run();
}
spy($$('.sidebar-nav a'));spy($$('.cn-list a'));

/* ---------- 右侧章节导航折叠 ---------- */
var cnt=$('#cn-toggle');
if(cnt){
  var K='cy_chem_cn';
  function setCn(c){doc.classList.toggle('cn-collapsed',c);cnt.innerHTML=c?'&#8249;':'&#8250;';cnt.setAttribute('aria-label',c?'展开章节导航':'折叠章节导航');try{localStorage.setItem(K,c?'1':'0')}catch(e){}}
  var saved='0';try{saved=localStorage.getItem(K)||'0'}catch(e){}
  setCn(saved==='1');
  cnt.addEventListener('click',function(){setCn(!doc.classList.contains('cn-collapsed'))});
}

/* ---------- 折叠块 ---------- */
$$('.collapse-toggle').forEach(function(t){
  var c=t.nextElementSibling;if(!c||!c.classList.contains('collapse-content'))return;
  if(!$('.cc-in',c)){var w=document.createElement('div');w.className='cc-in';while(c.firstChild)w.appendChild(c.firstChild);c.appendChild(w)}
  c.style.maxHeight='';c.style.display='';
  t.setAttribute('role','button');t.setAttribute('tabindex','0');t.setAttribute('aria-expanded',c.classList.contains('open')?'true':'false');
  function toggle(){var o=!c.classList.contains('open');c.classList.toggle('open',o);t.classList.toggle('open',o);t.setAttribute('aria-expanded',o?'true':'false')}
  t.addEventListener('click',toggle);
  t.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();toggle()}});
});

/* ---------- 测验 ---------- */
function isAns(txt,ans){txt=txt.trim();ans=(ans||'').trim();if(!ans)return false;if(txt===ans)return true;return txt.indexOf(ans)===0&&/^[.．、\s:：)）]/.test(txt.slice(ans.length))}
$$('.quiz-card').forEach(function(card){
  var ans=card.getAttribute('data-answer'),opts=$$('.quiz-option',card),exp=$('.quiz-explanation',card);
  opts.forEach(function(o){
    o.setAttribute('role','button');o.setAttribute('tabindex','0');
    function choose(){
      if($('.quiz-option.correct,.quiz-option.wrong',card))return;
      opts.forEach(function(x){x.style.pointerEvents='none';x.setAttribute('aria-disabled','true');if(isAns(x.textContent,ans))x.classList.add('correct')});
      if(!isAns(o.textContent,ans))o.classList.add('wrong');
      if(exp)exp.classList.add('show');
    }
    o.addEventListener('click',choose);
    o.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();choose()}});
  });
});

/* ---------- 知识卡片筛选 ---------- */
$$('.filter-bar').forEach(function(bar){
  var grid=bar.nextElementSibling;if(!grid||!grid.classList.contains('card-grid'))grid=bar.parentElement.querySelector('.card-grid');
  bar.addEventListener('click',function(e){
    var t=e.target.closest('.filter-tag');if(!t||!grid)return;
    $$('.filter-tag',bar).forEach(function(x){x.classList.toggle('active',x===t)});
    var f=t.getAttribute('data-filter');
    $$('.knowledge-card',grid).forEach(function(c){c.style.display=(f==='all'||c.getAttribute('data-category')===f)?'':'none'});
  });
});

/* ---------- 页内锚点：展开所在折叠块 ---------- */
function openAt(hash){if(!hash||hash.length<2)return;var el=null;try{el=document.getElementById(decodeURIComponent(hash.slice(1)))}catch(e){}if(!el)return;var d=el.closest('details');if(d)d.open=true;var cc=el.closest('.collapse-content');if(cc&&!cc.classList.contains('open')){var t=cc.previousElementSibling;if(t)t.click()}}
window.addEventListener('hashchange',function(){openAt(location.hash)});
if(location.hash)setTimeout(function(){openAt(location.hash);var el=null;try{el=document.getElementById(decodeURIComponent(location.hash.slice(1)))}catch(e){}if(el)el.scrollIntoView()},300);
})();
