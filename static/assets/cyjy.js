/* ============================================================
   崇岳鉴渊 · 全站交互 (cyjy.js)
   导航 / 主题 / 滚动 / 揭示动效 / AI 助手 —— 并暴露 window.CY 供页面脚本使用
   ============================================================ */
(function(){
'use strict';
var root=document.documentElement;
function mq(q){return !!(window.matchMedia&&window.matchMedia(q).matches)}
var themeFns=[],scrollFns=[];

var CY=window.CY={
  reduced:mq('(prefers-reduced-motion: reduce)'),
  fine:mq('(hover: hover) and (pointer: fine)'),
  $:function(s,c){return (c||document).querySelector(s)},
  $$:function(s,c){return Array.prototype.slice.call((c||document).querySelectorAll(s))},
  esc:function(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})},
  lerp:function(a,b,t){return a+(b-a)*t},
  clamp:function(v,a,b){return v<a?a:v>b?b:v},
  isDark:function(){return root.getAttribute('data-theme')!=='light'},
  onTheme:function(f){themeFns.push(f)},
  onScroll:function(f){scrollFns.push(f)},
  setTheme:function(t){
    root.setAttribute('data-theme',t);
    try{localStorage.setItem('cyjy_theme',t)}catch(e){}
    themeFns.forEach(function(f){try{f(t)}catch(e){}});
  },
  token:function(){try{return localStorage.getItem('cyjy_access_token')}catch(e){return null}},
  user:function(){try{return JSON.parse(localStorage.getItem('cyjy_user')||'null')}catch(e){return null}}
};
var $=CY.$,$$=CY.$$,esc=CY.esc,REDUCED=CY.reduced,FINE=CY.fine;

/* ---------- theme ---------- */
var tt=$('#themeToggle');
if(tt)tt.addEventListener('click',function(){CY.setTheme(CY.isDark()?'light':'dark')});

/* ---------- nav: scroll state, hide on scroll, progress, back-to-top ---------- */
var nav=$('#nav'),progress=$('#cyProgress'),toTop=$('#toTop'),ring=$('#toTopRing'),megaWrap=$('#megaWrap');
var lastY=window.scrollY,ticking=false;
function onScroll(){
  var y=window.scrollY,h=document.documentElement.scrollHeight-window.innerHeight,p=h>0?y/h:0;
  if(progress)progress.style.transform='scaleX('+p+')';
  if(nav){
    nav.classList.toggle('scrolled',y>24);
    var locked=document.body.classList.contains('menu-open')||(megaWrap&&megaWrap.classList.contains('open'))||nav.hasAttribute('data-pin');
    if(!locked)nav.classList.toggle('hide',y>lastY&&y>600);
  }
  if(toTop){toTop.classList.toggle('on',y>900);if(ring)ring.style.strokeDashoffset=144.5*(1-p)}
  lastY=y;ticking=false;
  for(var i=0;i<scrollFns.length;i++){try{scrollFns[i](y,p)}catch(e){}}
}
window.addEventListener('scroll',function(){if(!ticking){ticking=true;requestAnimationFrame(onScroll)}},{passive:true});
if(toTop)toTop.addEventListener('click',function(){window.scrollTo({top:0,behavior:REDUCED?'auto':'smooth'})});
CY.refreshScroll=onScroll;

/* ---------- mega menu ---------- */
var megaBtn=$('#megaBtn'),megaTimer;
function setMega(o){if(!megaWrap)return;megaWrap.classList.toggle('open',o);if(megaBtn)megaBtn.setAttribute('aria-expanded',o?'true':'false')}
if(megaWrap){
  megaWrap.addEventListener('mouseenter',function(){clearTimeout(megaTimer);setMega(true)});
  megaWrap.addEventListener('mouseleave',function(){megaTimer=setTimeout(function(){setMega(false)},160)});
  if(megaBtn)megaBtn.addEventListener('click',function(){setMega(FINE?true:!megaWrap.classList.contains('open'))});
  document.addEventListener('click',function(e){if(!megaWrap.contains(e.target))setMega(false)});
}

/* ---------- mobile menu ---------- */
var menuBtn=$('#menuBtn'),mobileMenu=$('#mobileMenu');
function setMenu(o){
  document.body.classList.toggle('menu-open',o);
  if(menuBtn){menuBtn.setAttribute('aria-expanded',o?'true':'false');menuBtn.setAttribute('aria-label',o?'关闭菜单':'打开菜单')}
  if(mobileMenu)mobileMenu.setAttribute('aria-hidden',o?'false':'true');
  document.body.style.overflow=o?'hidden':'';
  if(o&&nav)nav.classList.remove('hide');
}
if(menuBtn)menuBtn.addEventListener('click',function(){setMenu(!document.body.classList.contains('menu-open'))});
if(mobileMenu)$$('a',mobileMenu).forEach(function(a){a.addEventListener('click',function(){setMenu(false)})});
CY.closeMenus=function(){setMega(false);setMenu(false)};

/* ---------- active nav link ---------- */
(function(){
  var path=location.pathname.replace(/\/+$/,'')||'/';
  function match(href){
    var h=href.replace(/\/+$/,'')||'/';
    if(h==='/')return path==='/';
    return path===h||path.indexOf(h+'/')===0||(h==='/chemistry'&&path.indexOf('/chemistry')===0);
  }
  $$('.nav-links a.nav-link,.mega-item,.mm-links a').forEach(function(a){
    var href=a.getAttribute('href');if(!href||href.charAt(0)!=='/')return;
    if(match(href)){a.classList.add('active');a.setAttribute('aria-current','page')}
  });
  if(megaBtn&&$('.mega-item.active')&&!$('.nav-links a.nav-link.active'))megaBtn.classList.add('active');
})();

/* ---------- auth-aware nav ---------- */
(function(){
  var token=CY.token();if(!token)return;
  var user=CY.user()||{},name=user.display_name||user.username||'U',initial=String(name).charAt(0).toUpperCase();
  var na=$('#navAuth');if(na)na.innerHTML='<a href="/profile" class="user-avatar" title="个人中心 · '+esc(name)+'">'+esc(initial)+'</a>';
  var mc=$('#mmCta');if(mc)mc.innerHTML='<a href="/profile" class="btn btn-primary" style="grid-column:1/-1">进入个人中心</a>';
})();

/* ---------- reveal + count-up ---------- */
function countUp(el){
  var end=parseFloat(el.getAttribute('data-count'));if(isNaN(end))return;
  var suf=el.getAttribute('data-suffix')||'',dec=+(el.getAttribute('data-decimals')||0),dur=1800,t0=performance.now();
  function fmt(v){return (dec?v.toFixed(dec):Math.round(v).toLocaleString())+suf}
  if(REDUCED){el.textContent=fmt(end);return}
  (function tick(now){var p=Math.min((now-t0)/dur,1),e=1-Math.pow(1-p,4);el.textContent=fmt(e*end);if(p<1)requestAnimationFrame(tick)})(t0);
}
CY.countUp=countUp;
var io=('IntersectionObserver' in window)?new IntersectionObserver(function(es){es.forEach(function(e){
  if(!e.isIntersecting)return;
  var el=e.target;el.classList.add('in');io.unobserve(el);
  $$('[data-count]',el).forEach(function(c){if(!c._counted){c._counted=1;countUp(c)}});
  if(el.hasAttribute('data-count')&&!el._counted){el._counted=1;countUp(el)}
  if(el._onIn){var f=el._onIn;el._onIn=null;f()}
})},{threshold:.15,rootMargin:'0px 0px -6% 0px'}):null;
CY.observe=function(el,cb){if(!el)return;if(cb)el._onIn=cb;if(io&&!REDUCED)io.observe(el);else{el.classList.add('in');$$('[data-count]',el).forEach(function(c){if(!c._counted){c._counted=1;countUp(c)}});if(cb){el._onIn=null;cb()}}};
CY.reveal=function(scope){$$('[data-reveal]:not(.in),[data-count]:not([data-reveal])',scope||document).forEach(function(el){
  if(el.hasAttribute('data-reveal'))CY.observe(el);
  else if(!el.closest('[data-reveal]')&&!el._counted&&!el.hasAttribute('data-manual'))CY.observe(el);
})};
CY.stagger=function(parent,step){$$(':scope > *',parent).forEach(function(c,i){c.style.setProperty('--d',(i*(step||.06)).toFixed(2)+'s')})};
if('MutationObserver' in window){
  var mo=new MutationObserver(function(ms){var hit=false;for(var i=0;i<ms.length&&!hit;i++){for(var j=0;j<ms[i].addedNodes.length;j++){var n=ms[i].addedNodes[j];if(n.nodeType===1&&(n.hasAttribute('data-reveal')||n.querySelector&&n.querySelector('[data-reveal]'))){hit=true;break}}}if(hit)CY.reveal()});
  mo.observe(document.body,{childList:true,subtree:true});
}

/* ---------- canvas helper (runs only when visible) ---------- */
CY.animCanvas=function(canvas,setup){
  if(!canvas||!canvas.getContext)return null;
  var ctx=canvas.getContext('2d'),w=1,h=1,visible=false,raf=0,api=setup(ctx),t=0,last=0;
  function draw(dt){api.draw(ctx,w,h,t,dt)}
  function size(){
    var r=canvas.getBoundingClientRect(),dpr=Math.min(window.devicePixelRatio||1,2);
    w=Math.max(1,r.width);h=Math.max(1,r.height);
    canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);
    ctx.setTransform(dpr,0,0,dpr,0,0);
    if(api.resize)api.resize(w,h);
    if(REDUCED){t=api.still||2;draw(0)}else if(!raf)draw(0);
  }
  function frame(now){raf=0;if(!visible||document.hidden)return;var dt=last?Math.min((now-last)/1000,.05):.016;last=now;t+=dt;draw(dt);raf=requestAnimationFrame(frame)}
  function start(){if(!raf&&!REDUCED){last=0;raf=requestAnimationFrame(frame)}}
  if('IntersectionObserver' in window){new IntersectionObserver(function(es){visible=es[0].isIntersecting;if(visible)start()},{rootMargin:'120px'}).observe(canvas)}else{visible=true;start()}
  document.addEventListener('visibilitychange',function(){if(!document.hidden&&visible)start()});
  if('ResizeObserver' in window)new ResizeObserver(size).observe(canvas);else window.addEventListener('resize',size);
  size();
  CY.onTheme(function(){if(REDUCED||!raf)draw(0)});
  return api;
};
CY.hexA=function(hex,a){var n=parseInt(hex.slice(1),16);return 'rgba('+(n>>16&255)+','+(n>>8&255)+','+(n&255)+','+a+')'};
CY.mix=function(c1,c2,t){var a=parseInt(c1.slice(1),16),b=parseInt(c2.slice(1),16);return [Math.round(CY.lerp(a>>16&255,b>>16&255,t)),Math.round(CY.lerp(a>>8&255,b>>8&255,t)),Math.round(CY.lerp(a&255,b&255,t))]};

/* ---------- code highlighting ---------- */
var HL=/(https?:\/\/[^\s'"<>]+)|(\/\/[^\n]*|#[^\n]*)|('(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*")|(\b(?:import|from|const|let|var|await|async|new|return|function|def|class|for|in|if|else|elif|while|print|True|False|None|as)\b|^(?:git|npm|pnpm|pip|cd|claude|python)\b)|\b(\d+(?:\.\d+)?)\b|([A-Za-z_]\w*)(?=\()/g;
CY.hl=function(src){var out='',last=0,m;HL.lastIndex=0;while((m=HL.exec(src))){out+=esc(src.slice(last,m.index));if(m[1]){out+=esc(m[0]);last=HL.lastIndex;continue}var c=m[2]?'c':m[3]?'s':m[4]?'k':m[5]?'n':'f';out+='<span class="t-'+c+'">'+esc(m[0])+'</span>';last=HL.lastIndex}return out+esc(src.slice(last))};
CY.renderCode=function(el,code,stagger){el.innerHTML=code.split('\n').map(function(line,i){return '<div class="l" style="--d:'+(REDUCED?0:i*(stagger||.06))+'s"><span class="n">'+(i+1)+'</span><span>'+(CY.hl(line)||' ')+'</span></div>'}).join('')};

/* ---------- toast ---------- */
CY.toast=function(msg,type){
  var wrap=$('#cyToasts');if(!wrap){wrap=document.createElement('div');wrap.className='toast-wrap';wrap.id='cyToasts';document.body.appendChild(wrap)}
  var t=document.createElement('div');t.className='toast'+(type?' '+type:'');t.textContent=msg;wrap.appendChild(t);
  setTimeout(function(){t.style.transition='opacity .4s';t.style.opacity='0';setTimeout(function(){t.remove()},400)},2600);
};

/* ---------- pointer effects: spotlight, tilt, magnetic, cursor glow ---------- */
if(FINE&&!REDUCED){
  document.addEventListener('pointermove',function(e){
    var el=e.target.closest&&e.target.closest('.spot');if(!el)return;
    var r=el.getBoundingClientRect();el.style.setProperty('--mx',(e.clientX-r.left)+'px');el.style.setProperty('--my',(e.clientY-r.top)+'px');
  },{passive:true});
  document.addEventListener('pointermove',function(e){
    var el=e.target.closest&&e.target.closest('[data-tilt]');
    if(el){var r=el.getBoundingClientRect(),x=(e.clientX-r.left)/r.width-.5,y=(e.clientY-r.top)/r.height-.5;el.style.transform='perspective(1000px) rotateX('+(-y*5).toFixed(2)+'deg) rotateY('+(x*6).toFixed(2)+'deg) translateY(-4px)';el._tilted=1}
    var mg=e.target.closest&&e.target.closest('[data-magnetic]');
    if(mg){var b=mg.getBoundingClientRect(),dx=e.clientX-b.left-b.width/2,dy=e.clientY-b.top-b.height/2;mg.style.transform='translate('+(dx*.22).toFixed(1)+'px,'+(dy*.3).toFixed(1)+'px)';mg._mag=1}
  },{passive:true});
  document.addEventListener('pointerout',function(e){
    var el=e.target.closest&&e.target.closest('[data-tilt],[data-magnetic]');
    if(el&&!el.contains(e.relatedTarget)){el.style.transform=''}
  });
  var glow=$('#cyGlow');
  if(glow){
    var gx=0,gy=0,tx=0,ty=0,gRun=false;
    var glowLoop=function(){gx=CY.lerp(gx,tx,.12);gy=CY.lerp(gy,ty,.12);glow.style.transform='translate3d('+gx.toFixed(1)+'px,'+gy.toFixed(1)+'px,0)';if(Math.abs(tx-gx)+Math.abs(ty-gy)>.5)requestAnimationFrame(glowLoop);else gRun=false};
    window.addEventListener('pointermove',function(e){tx=e.clientX;ty=e.clientY;glow.classList.add('on');if(!gRun){gRun=true;requestAnimationFrame(glowLoop)}},{passive:true});
    document.addEventListener('pointerleave',function(){glow.classList.remove('on')});
  }
  var wm=$('#cyWordmark');
  if(wm)wm.parentNode.addEventListener('pointermove',function(e){var r=wm.getBoundingClientRect();wm.style.setProperty('--mx',(e.clientX-r.left)+'px');wm.style.setProperty('--my',(e.clientY-r.top)+'px')},{passive:true});
}

/* ---------- footer: real service status + year ---------- */
(function(){
  var y=$('#cyYear');if(y)y.textContent=new Date().getFullYear();
  var st=$('#cyStatus');if(!st)return;
  var lab=$('span',st);
  var run=function(){
    var ctl=('AbortController' in window)?new AbortController():null,to=setTimeout(function(){if(ctl)ctl.abort()},8000);
    fetch('/health',{cache:'no-store',signal:ctl?ctl.signal:undefined}).then(function(r){return r.json()}).then(function(d){clearTimeout(to);if(d&&d.status==='ok'){st.classList.add('ok');lab.textContent='所有服务运行正常'}else throw 0}).catch(function(){clearTimeout(to);st.classList.add('bad');lab.textContent='服务状态暂不可用'});
  };
  if('IntersectionObserver' in window){var o=new IntersectionObserver(function(es){if(es[0].isIntersecting){o.disconnect();run()}},{rootMargin:'300px'});o.observe(st)}else run();
})();

/* ---------- AI chat widget ---------- */
var aiFab=$('#aiChat'),aiInput=$('#aiInput'),aiMsgs=$('#aiMsgs'),aiGreeted=false;
function setAI(o){if(!aiFab)return;aiFab.classList.toggle('open',o);var b=$('#aiBtn');if(b)b.setAttribute('aria-label',o?'关闭 AI 助手':'打开 AI 助手');if(o){greet();setTimeout(function(){aiInput&&aiInput.focus()},250)}}
function addMsg(content,role,html){var d=document.createElement('div');d.className='ai-msg '+role;if(html)d.innerHTML=content;else d.textContent=content;aiMsgs.appendChild(d);aiMsgs.scrollTop=aiMsgs.scrollHeight;return d}
function greet(){
  if(aiGreeted||!aiMsgs)return;aiGreeted=true;
  addMsg('你好！我是崇岳鉴渊的 <b>AI 学术助教</b>。可以问我平台使用、公式推导或编程问题，勾选「搜文件」还能检索知识库资源。','bot',true);
  var s=document.createElement('div');s.className='ai-sugg';
  s.innerHTML=['平台有哪些功能？','数学竞赛题库怎么用？','Claude Code 怎么用？'].map(function(q){return '<button type="button">'+q+'</button>'}).join('');
  aiMsgs.appendChild(s);
  $$('button',s).forEach(function(b){b.addEventListener('click',function(){s.remove();send(b.textContent)})});
}
function md(text){return esc(text).replace(/\*\*(.+?)\*\*/g,'<b>$1</b>').replace(/\[([^\]]+)\]\((\/[^)\s]*)\)/g,'<a href="$2">$1</a>').replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\n/g,'<br>')}
function send(text){
  if(!aiMsgs)return;
  var msg=(text!=null?text:aiInput.value).trim();if(!msg)return;
  addMsg(msg,'user');aiInput.value='';
  var bot=addMsg('<span class="typing"><i></i><i></i><i></i></span>','bot',true),search=$('#aiSearch')&&$('#aiSearch').checked;
  fetch('/api/v1/ai/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:msg,search_files:!!search})}).then(function(r){
    var ct=r.headers.get('content-type')||'';
    if(ct.indexOf('text/event-stream')!==-1&&r.body){
      var reader=r.body.getReader(),dec=new TextDecoder(),buf='',acc='';
      var pump=function(){return reader.read().then(function(res){
        if(res.done){bot.innerHTML=md(acc)||'（无回复）';return}
        buf+=dec.decode(res.value,{stream:true});var lines=buf.split('\n');buf=lines.pop()||'';
        for(var i=0;i<lines.length;i++){var line=lines[i];if(line.indexOf('data: ')!==0)continue;var pl=line.slice(6);if(pl==='[DONE]'){bot.innerHTML=md(acc);aiMsgs.scrollTop=aiMsgs.scrollHeight;return}
          try{var o=JSON.parse(pl);if(o.t){acc+=o.t;bot.innerHTML=md(acc);aiMsgs.scrollTop=aiMsgs.scrollHeight}if(o.error){acc=o.error;bot.textContent=o.error}}catch(e){}}
        return pump();
      })};
      return pump().catch(function(){bot.textContent='连接中断，请重试'});
    }
    if(r.status===429){bot.textContent='提问太频繁了，请稍等一分钟再试';return}
    return r.json().then(function(d){bot.innerHTML=(d&&d.reply?String(d.reply):'（无回复）').replace(/\n/g,'<br>');aiMsgs.scrollTop=aiMsgs.scrollHeight});
  }).catch(function(){bot.textContent='网络错误，请稍后重试'});
}
CY.openAssistant=window.openAssistant=function(q){if(!aiFab)return;setAI(true);if(q)setTimeout(function(){send(q)},300)};
if(aiFab){
  $('#aiBtn').addEventListener('click',function(){setAI(!aiFab.classList.contains('open'))});
  $('#aiClose').addEventListener('click',function(){setAI(false)});
  $('#aiSend').addEventListener('click',function(){send()});
  aiInput.addEventListener('keydown',function(e){if(e.key==='Enter'&&!e.isComposing)send()});
}

document.addEventListener('keydown',function(e){if(e.key==='Escape'){setMega(false);setMenu(false);setAI(false)}});

/* go */
function boot(){CY.reveal();onScroll()}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();
