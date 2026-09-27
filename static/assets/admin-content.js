/* 管理后台 · 内容管理：学习资源 / 页面编辑 / 文件库 / 真题库
   依赖 cyjy.js（window.CY）与 admin.html 在身份验证后提供的 window.CYAdmin。 */
(function(){
'use strict';
var $=CY.$,$$=CY.$$,esc=CY.esc;
var A=function(){return window.CYAdmin};
var MAX=50*1024*1024;
var EXTS=['.pdf','.doc','.docx','.ppt','.pptx','.xls','.xlsx','.csv','.txt','.md','.json','.py','.ipynb','.m','.c','.cpp','.java','.tex','.bib','.png','.jpg','.jpeg','.gif','.webp','.zip','.rar','.7z','.mp4','.webm','.mp3','.wav'];
var TYPE_COLOR={pdf:'#e5412d',doc:'#2563eb',docx:'#2563eb',ppt:'#ea580c',pptx:'#ea580c',xls:'#16a34a',xlsx:'#16a34a',csv:'#16a34a',zip:'#a16207',rar:'#a16207','7z':'#a16207',mp4:'#7c3aed',webm:'#7c3aed',mp3:'#db2777',wav:'#db2777'};
var STATUS=null,inited={};

/* 返回 {ok,status,data}；401 时跳转登录 */
function call(path,opt){
  return CY.api('admin/content/'+path,opt).then(function(r){
    if(r.status===401){CY.clearAuth();location.href='/login?redirect='+encodeURIComponent(location.pathname);throw new Error('401')}
    return r;
  });
}
function api(path,opt){return call(path,opt).then(function(r){if(!r.ok)throw new Error(CY.errText(r.data,'操作失败'));return r.data})}
function fail(err){if(err&&err.message!=='401')CY.toast(err.message||'操作失败','err')}
function when(s){if(!s)return '—';var d=new Date(typeof s==='number'?s*1000:s);return isNaN(d)?'—':d.toLocaleString('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})}
function extOf(n){var i=String(n).lastIndexOf('.');return i>0?String(n).slice(i+1).toLowerCase():''}
function sizeText(n){n=+n||0;return n<1024?n+' B':n<1048576?(n/1024).toFixed(1)+' KB':(n/1048576).toFixed(1)+' MB'}
function debounce(fn,ms){var t;return function(){var a=arguments,self=this;clearTimeout(t);t=setTimeout(function(){fn.apply(self,a)},ms)}}
function writable(){return !STATUS||STATUS.writable}

/* ---------------- 状态条 ---------------- */
function loadStatus(){
  if(STATUS)return Promise.resolve(STATUS);
  return api('status').then(function(s){STATUS=s;renderStatus();return s}).catch(function(e){fail(e);return null});
}
function renderStatus(){
  var s=STATUS,el=$('#cStat'),cls,html;
  if(s.mode==='github'){cls='ok';html='修改会提交到 GitHub 仓库 <a href="https://github.com/'+esc(s.repo)+'/commits/'+esc(s.branch)+'" target="_blank" rel="noopener">'+esc(s.repo)+'</a>（'+esc(s.branch)+' 分支）并立即在网站上生效，每次保存都可以在「历史版本」中找回；上传的文件保存在仓库的 Release「site-files」中。'}
  else if(s.writable){cls='';html='本地模式：修改直接写入项目目录下的文件，确认无误后用 git 提交并推送，线上网站才会更新。'}
  else{cls='warn';html=esc(s.reason||'当前为只读模式。')+' 在 Render 的 Environment 中添加 <code>CYJY_GITHUB_TOKEN</code> 后即可在线编辑，步骤见 <a href="https://github.com/hanjiongmin-stack/chongyue-jianyuan/blob/main/docs/deployment.md#开启管理后台的内容管理" target="_blank" rel="noopener">部署指南</a>。'}
  el.innerHTML='<div class="note '+cls+'"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg><span>'+html+'</span></div>';
  if(!s.writable)$$('#rNew,#peSave,#rfSave,#fDrop,#rfDrop,#rfPick').forEach(function(b){b.setAttribute('disabled','');b.style.pointerEvents='none';b.style.opacity='.5'});
}

/* ---------------- 上传（带进度） ---------------- */
function checkFile(f){
  if(EXTS.indexOf('.'+extOf(f.name))<0)return '不支持上传 .'+(extOf(f.name)||'无扩展名')+' 文件';
  if(f.size>MAX)return '单个文件不能超过 50 MB';
  if(!f.size)return '文件是空的';
  return '';
}
function xhrUpload(file,onProgress,retried){
  return new Promise(function(resolve,reject){
    var x=new XMLHttpRequest(),fd=new FormData();fd.append('files',file);
    x.open('POST','/api/v1/admin/content/files');
    var t=CY.token();if(t)x.setRequestHeader('Authorization','Bearer '+t);
    x.upload.onprogress=function(e){if(e.lengthComputable)onProgress(e.loaded/e.total)};
    x.onload=function(){
      var d=null;try{d=JSON.parse(x.responseText)}catch(e){}
      if(x.status>=200&&x.status<300&&d&&d[0])return resolve(d[0]);
      if(x.status===401&&!retried)return CY.refreshAuth().then(function(ok){if(!ok)return reject(new Error('登录已过期，请重新登录'));resolve(xhrUpload(file,onProgress,true))});
      reject(new Error(CY.errText(d,'上传失败（'+x.status+'）')));
    };
    x.onerror=function(){reject(new Error('网络错误，上传失败'))};
    x.send(fd);
  });
}
/* 依次上传，返回成功上传的文件信息 */
function uploadAll(files,queue){
  files=[].slice.call(files||[]);var done=[];
  var rows=files.map(function(f){
    var r=document.createElement('div');r.className='row';
    r.innerHTML='<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+esc(f.name)+' <small class="muted">'+sizeText(f.size)+'</small></span><span class="bar"><i></i></span>';
    queue.appendChild(r);return r;
  });
  return files.reduce(function(p,f,i){
    return p.then(function(){
      var row=rows[i],bar=$('.bar i',row),bad=checkFile(f);
      if(bad){row.lastChild.outerHTML='<small style="color:var(--err)">'+esc(bad)+'</small>';return}
      return xhrUpload(f,function(v){bar.style.width=(v*100).toFixed(0)+'%'}).then(function(item){
        bar.style.width='100%';done.push(item);setTimeout(function(){row.remove()},900);
      }).catch(function(e){row.lastChild.outerHTML='<small style="color:var(--err)">'+esc(e.message)+'</small>'});
    });
  },Promise.resolve()).then(function(){return done});
}
function bindDrop(zone,input,onFiles){
  input.addEventListener('change',function(){if(input.files.length)onFiles(input.files);input.value=''});
  ['dragenter','dragover'].forEach(function(ev){zone.addEventListener(ev,function(e){e.preventDefault();zone.classList.add('on')})});
  ['dragleave','drop'].forEach(function(ev){zone.addEventListener(ev,function(e){e.preventDefault();zone.classList.remove('on')})});
  zone.addEventListener('drop',function(e){if(writable()&&e.dataTransfer.files.length)onFiles(e.dataTransfer.files)});
}
function fileIcon(f){
  var ext=extOf(f.name);
  if(f.preview_type==='image')return '<span class="ic"><img src="'+esc(f.url)+'" alt="" loading="lazy"></span>';
  return '<span class="ic" style="--c:'+(TYPE_COLOR[ext]||'#64748b')+'">'+esc((ext||'FILE').slice(0,4).toUpperCase())+'</span>';
}

/* ---------------- 文件库 ---------------- */
var FILES=[],fq='';
function initFiles(){
  bindDrop($('#fDrop'),$('#fInput'),function(files){uploadAll(files,$('#fQueue')).then(function(items){if(items.length){CY.toast('已上传 '+items.length+' 个文件','ok');loadFiles()}})});
  $('#fSearch').addEventListener('input',debounce(function(){fq=this.value.trim().toLowerCase();renderFiles()},150));
  $('#fList').addEventListener('click',function(e){
    var b;
    if((b=e.target.closest('[data-copy]'))){CY.copy(location.origin+b.getAttribute('data-copy'));CY.toast('链接已复制','ok')}
    else if((b=e.target.closest('[data-fdel]'))){
      var f=FILES.filter(function(x){return x.key===b.getAttribute('data-fdel')})[0];if(!f)return;
      A().confirm('删除「'+f.name+'」？','删除后，网站上引用这个文件的链接会失效，且无法恢复。','删除',function(){
        api('files/'+encodeURIComponent(f.key),{method:'DELETE'}).then(function(){CY.toast('已删除','ok');loadFiles()}).catch(fail);
      });
    }
  });
  loadFiles();
}
function loadFiles(){return api('files').then(function(d){FILES=d||[];renderFiles();return FILES}).catch(function(e){$('#fList').innerHTML='<div class="empty"><b>文件库加载失败</b><span>'+esc(e.message)+'</span></div>'})}
function fileRow(f,ops){
  return '<div class="fl" data-key="'+esc(f.key)+'">'+fileIcon(f)+'<div class="nm"><b title="'+esc(f.name)+'">'+esc(f.name)+'</b><small>'+esc(f.size_text||sizeText(f.size))+' · '+esc(when(f.created_at))+'</small></div><div class="ops">'+ops+'</div></div>';
}
function renderFiles(){
  var list=FILES.filter(function(f){return !fq||f.name.toLowerCase().indexOf(fq)>=0});
  $('#fCount').textContent='共 '+FILES.length+' 个文件';
  $('#fList').innerHTML=list.length?list.map(function(f){
    return fileRow(f,'<button class="btn btn-ghost btn-xs" type="button" data-copy="'+esc(f.url)+'">复制链接</button><a class="btn btn-ghost btn-xs" href="'+esc(f.url)+'" target="_blank" rel="noopener">打开</a>'+(writable()?'<button class="btn btn-danger btn-xs" type="button" data-fdel="'+esc(f.key)+'">删除</button>':''));
  }).join(''):'<div class="empty"><b>'+(FILES.length?'没有匹配的文件':'文件库还是空的')+'</b><span>上传的文件可以作为学习资源的附件，也可以在页面编辑中插入链接或图片。</span></div>';
}
/* 选择文件（资源附件、页面插入共用） */
var pickCb=null;
function openPicker(title,cb){
  pickCb=cb;$('#pkTitle').textContent=title;$('#pkSearch').value='';
  $('#pkList').innerHTML='<div class="spinner" style="margin:20px auto"></div>';
  A().open('mPick');
  loadFiles().then(renderPicker);
}
function renderPicker(){
  var q=$('#pkSearch').value.trim().toLowerCase();
  var list=FILES.filter(function(f){return !q||f.name.toLowerCase().indexOf(q)>=0});
  $('#pkList').innerHTML=list.length?list.map(function(f){return fileRow(f,'<span class="badge">选择</span>')}).join(''):'<div class="empty"><b>没有可选的文件</b><span>请先在「文件库」中上传。</span></div>';
}
$('#pkSearch').addEventListener('input',debounce(renderPicker,120));
$('#pkList').addEventListener('click',function(e){
  var row=e.target.closest('[data-key]');if(!row)return;
  var f=FILES.filter(function(x){return x.key===row.getAttribute('data-key')})[0];
  $('#mPick').classList.remove('open');if(f&&pickCb)pickCb(f);
});

/* ---------------- 学习资源 ---------------- */
var RES=[],TAX={categories:[],tags:[]},rq='',rc='',editing=null,atts=[];
function initResources(){
  $('#rSearch').addEventListener('input',debounce(function(){rq=this.value.trim().toLowerCase();renderRes()},150));
  $('#rCat').addEventListener('change',function(){rc=this.value;renderRes()});
  $('#rNew').addEventListener('click',function(){fillRes(null)});
  $('#rBody').addEventListener('click',function(e){
    var b;
    if((b=e.target.closest('[data-redit]')))api('resources/'+b.getAttribute('data-redit')).then(fillRes).catch(fail);
    else if((b=e.target.closest('[data-rdel]'))){
      var r=RES.filter(function(x){return x.id===+b.getAttribute('data-rdel')})[0];if(!r)return;
      A().confirm('删除「'+r.title+'」？','资源会从学习资源库中移除，访客的收藏与学习进度也会一并删除；附件文件仍保留在文件库中。','删除',function(){
        api('resources/'+r.id,{method:'DELETE'}).then(function(){CY.toast('已删除','ok');loadRes()}).catch(fail);
      });
    }
  });
  bindDrop($('#rfDrop'),$('#rfFile'),function(files){
    uploadAll(files,$('#rfQueue')).then(function(items){items.forEach(function(it){atts.push({key:it.key,name:it.name,size:it.size,url:it.url})});renderAtts()});
  });
  $('#rfPick').addEventListener('click',function(){openPicker('选择附件',function(f){if(!atts.some(function(a){return a.key===f.key}))atts.push({key:f.key,name:f.name,size:f.size,url:f.url});renderAtts()})});
  $('#rfAtts').addEventListener('click',function(e){var b=e.target.closest('[data-arm]');if(b){atts.splice(+b.getAttribute('data-arm'),1);renderAtts()}});
  $('#fRes').addEventListener('submit',saveRes);
  Promise.all([api('taxonomy'),loadRes()]).then(function(v){
    TAX=v[0];
    var opts=TAX.categories.map(function(c){return '<option value="'+esc(c.slug)+'">'+esc(c.name)+'</option>'}).join('');
    $('#rCat').innerHTML='<option value="">全部分类</option>'+opts;$('#rfCat').innerHTML=opts;
    $('#rfTagList').innerHTML=TAX.tags.map(function(t){return '<option value="'+esc(t)+'">'}).join('');
  }).catch(fail);
}
function loadRes(){return api('resources').then(function(d){RES=d||[];renderRes();return RES})}
function renderRes(){
  var list=RES.filter(function(r){
    if(rc&&r.category_slug!==rc)return false;
    if(rq&&(r.title+' '+r.tag_names.join(' ')).toLowerCase().indexOf(rq)<0)return false;
    return true;
  });
  $('#rBody').innerHTML=list.length?list.map(function(r){
    return '<tr><td class="num">'+(+r.id)+'</td><td class="rt-title"><b>'+esc(r.title)+'</b>'+(r.tag_names.length?'<small>'+r.tag_names.slice(0,5).map(function(t){return '<span>'+esc(t)+'</span>'}).join('')+'</small>':'')+'</td><td>'+esc(r.category_name)+'</td><td>'+(r.status==='draft'?'<span class="badge">草稿</span>':'<span class="badge ok">已发布</span>')+(r.is_featured?' <span class="badge warn">精选</span>':'')+'</td><td class="num">'+(r.attachments.length||'—')+'</td><td class="num">'+esc(when(r.updated_at))+'</td><td><div class="ops"><a class="btn btn-ghost btn-xs" href="/knowledge/'+(+r.id)+'" target="_blank" rel="noopener">查看</a><button class="btn btn-ghost btn-xs" type="button" data-redit="'+(+r.id)+'">编辑</button>'+(writable()?'<button class="btn btn-danger btn-xs" type="button" data-rdel="'+(+r.id)+'">删除</button>':'')+'</div></td></tr>';
  }).join(''):'<tr><td colspan="7"><div class="empty" style="padding:36px"><b>'+(RES.length?'没有符合条件的资源':'还没有学习资源')+'</b></div></td></tr>';
}
function fillRes(r){
  editing=r;
  $('#rTitle').textContent=r?'编辑学习资源 #'+r.id:'新建学习资源';
  $('#rfTitle').value=r?r.title:'';
  $('#rfCat').value=r?r.category_slug:(rc||(TAX.categories[0]||{}).slug||'');
  $('#rfStatus').value=r?r.status:'published';
  $('#rfDiff').value=String(r?r.difficulty:1);
  $('#rfTags').value=r?r.tag_names.join(', '):'';
  $('#rfAuthor').value=r?r.author:'';
  $('#rfDesc').value=r?r.description:'';
  $('#rfContent').value=r?r.content:'';
  $('#rfSource').value=r?r.source:'';
  $('#rfFeat').checked=!!(r&&r.is_featured);
  atts=r?r.attachments.slice():[];renderAtts();
  $('#rfQueue').innerHTML='';
  var f=$('#rfTitle').closest('.field');f.classList.remove('bad');$('.ferr',f).hidden=true;
  $('#rfView').hidden=!r;if(r)$('#rfView').href='/knowledge/'+r.id;
  A().open('mRes');
}
function renderAtts(){
  $('#rfAtts').innerHTML=atts.length?atts.map(function(a,i){
    return '<div class="att"><span class="nm"><a href="'+esc(a.url||('/files/'+a.key))+'" target="_blank" rel="noopener" title="'+esc(a.name)+'">'+esc(a.name)+'</a></span><span class="sz">'+sizeText(a.size)+'</span><button class="btn btn-ghost btn-xs" type="button" data-arm="'+i+'" aria-label="移除附件">移除</button></div>';
  }).join(''):'<p class="muted" style="font-size:13.5px">还没有附件。上传的 PDF、PPT、Word 等文件会显示在资源详情页，访客可以在线预览或下载。</p>';
}
function saveRes(e){
  e.preventDefault();
  var title=$('#rfTitle').value.trim(),f=$('#rfTitle').closest('.field');
  if(!title){f.classList.add('bad');$('.ferr',f).textContent='请填写标题';$('.ferr',f).hidden=false;$('#rfTitle').focus();return}
  var body={
    title:title,category_slug:$('#rfCat').value,status:$('#rfStatus').value,difficulty:+$('#rfDiff').value,
    tag_names:$('#rfTags').value.split(/[,，、]/).map(function(t){return t.trim()}).filter(Boolean),
    author:$('#rfAuthor').value.trim(),description:$('#rfDesc').value.trim(),content:$('#rfContent').value,
    source:$('#rfSource').value.trim(),is_featured:$('#rfFeat').checked,
    attachments:atts.map(function(a){return {key:a.key,name:a.name,size:+a.size||0}})
  };
  if(editing){body.slug=editing.slug;if(!atts.length){body.file_type=editing.file_type;body.file_size=editing.file_size}}  // 有附件时由服务端按附件自动填写
  var btn=$('#rfSave');btn.disabled=true;btn.textContent='保存中…';
  api(editing?'resources/'+editing.id:'resources',{method:editing?'PUT':'POST',json:body}).then(function(r){
    $('#mRes').classList.remove('open');
    CY.toast((editing?'已保存':'已创建')+'「'+r.title+'」'+(STATUS&&STATUS.mode==='github'?'，并已提交到 GitHub':''),'ok');
    return loadRes();
  }).catch(fail).then(function(){btn.disabled=false;btn.textContent='保存'});
}

/* ---------------- 页面编辑 ---------------- */
var PAGES=[],PE={page:null,sha:null,orig:'',cm:null,ta:null,dirty:false,split:false};
var CM='https://cdn.jsdelivr.net/npm/codemirror@5.65.18/';
var cmP=null;
function loadScript(src){return new Promise(function(res,rej){var s=document.createElement('script');s.src=src;s.onload=res;s.onerror=rej;document.head.appendChild(s)})}
function loadCss(href){var l=document.createElement('link');l.rel='stylesheet';l.href=href;document.head.appendChild(l)}
function ensureCM(){
  if(cmP)return cmP;
  cmP=new Promise(function(res){
    if(window.CodeMirror)return res(true);
    loadCss(CM+'lib/codemirror.min.css');loadCss(CM+'addon/dialog/dialog.min.css');
    var t=setTimeout(function(){res(!!window.CodeMirror)},15000);
    loadScript(CM+'lib/codemirror.min.js').then(function(){
      return ['mode/xml/xml','mode/javascript/javascript','mode/css/css','mode/htmlmixed/htmlmixed','addon/dialog/dialog','addon/search/searchcursor','addon/search/search','addon/selection/active-line']
        .reduce(function(p,m){return p.then(function(){return loadScript(CM+m+'.min.js')})},Promise.resolve());
    }).then(function(){clearTimeout(t);res(!!window.CodeMirror)}).catch(function(){clearTimeout(t);res(!!window.CodeMirror&&!!CodeMirror.modes.htmlmixed)});
  });
  return cmP;
}
function initPages(){
  api('pages').then(function(d){PAGES=d||[];renderPageList()}).catch(function(e){$('#pList').innerHTML='<div class="empty"><b>加载失败</b><span>'+esc(e.message)+'</span></div>'});
  $('#pSearch').addEventListener('input',debounce(renderPageList,120));
  $('#pList').addEventListener('click',function(e){var b=e.target.closest('[data-p]');if(b)openPage(b.getAttribute('data-p'))});
  $('#peSave').addEventListener('click',savePage);
  $('#pePrev').addEventListener('click',function(){PE.split=!PE.split;layout();if(PE.split)refreshPreview()});
  $('#peHist').addEventListener('click',showHistory);
  $('#peInsert').addEventListener('click',function(){openPicker('插入文件',insertFile)});
  $('#hList').addEventListener('click',function(e){
    var b=e.target.closest('[data-ref]');if(!b)return;
    api('page/version?path='+encodeURIComponent(PE.page.path)+'&ref='+b.getAttribute('data-ref')).then(function(d){
      setValue(d.content);markDirty();$('#mHist').classList.remove('open');CY.toast('已载入历史版本，确认后点「保存并发布」即可恢复','ok');
    }).catch(fail);
  });
  document.addEventListener('keydown',function(e){if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'&&PE.page&&!$('#p-pages').hidden){e.preventDefault();savePage()}});
  window.addEventListener('beforeunload',function(e){if(PE.dirty){e.preventDefault();e.returnValue=''}});
}
function renderPageList(){
  var q=$('#pSearch').value.trim().toLowerCase(),html='',g=null;
  PAGES.filter(function(p){return !q||(p.title+' '+p.path).toLowerCase().indexOf(q)>=0}).forEach(function(p){
    if(p.group!==g){g=p.group;html+='<div class="pe-g">'+esc(g)+'</div>'}
    html+='<button type="button" data-p="'+esc(p.path)+'" title="'+esc(p.path)+'"'+(PE.page&&PE.page.path===p.path?' class="on"':'')+'>'+esc(p.title)+'</button>';
  });
  $('#pList').innerHTML=html||'<p class="muted" style="padding:10px;font-size:13px">没有匹配的页面</p>';
}
function getValue(){return PE.cm?PE.cm.getValue():PE.ta?PE.ta.value:''}
function setValue(v){if(PE.cm){PE.cm.setValue(v);PE.cm.clearHistory()}else if(PE.ta)PE.ta.value=v}
function markDirty(){PE.dirty=getValue()!==PE.orig;$('#peDirty').hidden=!PE.dirty}
var livePreview=debounce(function(){if(PE.split)refreshPreview()},900);
function layout(){
  var body=$('#peBody');body.classList.toggle('split',PE.split);$('#pePrev').classList.toggle('on',PE.split);
  var prev=$('.pe-prev',body);
  if(PE.split&&!prev){prev=document.createElement('div');prev.className='pe-prev';prev.innerHTML='<iframe title="页面预览" sandbox="allow-scripts"></iframe>';body.appendChild(prev)}
  if(!PE.split&&prev)prev.remove();
  if(PE.cm)PE.cm.refresh();
}
function openPage(path){
  if(PE.dirty&&!window.confirm('当前页面有未保存的修改，确定要切换吗？'))return;
  var page=PAGES.filter(function(p){return p.path===path})[0];if(!page)return;
  $('#peEmpty')&&($('#peEmpty').innerHTML='<div class="spinner"></div>');
  Promise.all([api('page?path='+encodeURIComponent(path)),ensureCM()]).then(function(v){
    var d=v[0],hasCM=v[1];
    PE.page=page;PE.sha=d.sha;PE.orig=d.content;PE.dirty=false;
    $('#peHead').hidden=false;$('#peTitle').textContent=page.title;$('#pePath').textContent=page.path;
    var view=$('#peView');view.hidden=!page.url;if(page.url)view.href=page.url;
    $('#peDirty').hidden=true;$('#peMsg').value='';
    var body=$('#peBody');body.innerHTML='<div class="pe-code" id="peCode"></div>';PE.cm=null;PE.ta=null;
    if(hasCM){
      PE.cm=CodeMirror($('#peCode'),{value:d.content,mode:'htmlmixed',theme:'cy',lineNumbers:true,lineWrapping:true,styleActiveLine:true,indentUnit:2,tabSize:2});
      PE.cm.on('change',function(){markDirty();livePreview()});
    }else{
      PE.ta=document.createElement('textarea');PE.ta.spellcheck=false;PE.ta.value=d.content;$('#peCode').appendChild(PE.ta);
      PE.ta.addEventListener('input',function(){markDirty();livePreview()});
    }
    layout();if(PE.split)refreshPreview();renderPageList();
  }).catch(function(e){fail(e);if($('#peEmpty'))$('#peEmpty').textContent='加载失败：'+e.message});
}
function refreshPreview(){
  var frame=$('.pe-prev iframe');if(!frame||!PE.page)return;
  var t=CY.token();
  fetch('/api/v1/admin/content/page/preview',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+t},body:JSON.stringify({path:PE.page.path,content:getValue()})})
    .then(function(r){if(!r.ok)throw new Error('预览失败（'+r.status+'）');return r.text()})
    .then(function(html){frame.srcdoc=html})
    .catch(function(e){frame.srcdoc='<p style="font:14px sans-serif;color:#e5412d;padding:20px">'+esc(e.message)+'</p>'});
}
function savePage(){
  if(!PE.page||!writable())return;
  if(!PE.dirty){CY.toast('没有需要保存的修改');return}
  var btn=$('#peSave'),content=getValue();btn.disabled=true;btn.textContent='保存中…';
  call('page',{method:'PUT',json:{path:PE.page.path,content:content,sha:PE.sha,message:$('#peMsg').value.trim()||null}}).then(function(r){
    if(r.status===409){
      A().confirm('页面已被修改',CY.errText(r.data,'页面在你编辑期间已被修改。')+' 点击「重新加载」会放弃你当前的修改，你可以先复制需要保留的内容。','重新加载',function(){PE.dirty=false;openPage(PE.page.path)});
      return;
    }
    if(!r.ok)throw new Error(CY.errText(r.data,'保存失败'));
    PE.sha=r.data.sha||PE.sha;PE.orig=content;markDirty();$('#peMsg').value='';
    CY.toast('已保存并发布'+(r.data.commit?'（已提交到 GitHub）':''),'ok');
  }).catch(fail).then(function(){btn.disabled=false;btn.textContent='保存并发布'});
}
function showHistory(){
  if(!PE.page)return;
  $('#hName').textContent=PE.page.title;$('#hList').innerHTML='<div class="spinner" style="margin:20px auto"></div>';A().open('mHist');
  api('page/history?path='+encodeURIComponent(PE.page.path)).then(function(list){
    $('#hList').innerHTML=list&&list.length?list.map(function(c){
      return '<div class="h"><div style="min-width:0"><b title="'+esc(c.message)+'">'+esc(c.message)+'</b><small>'+esc(when(c.date))+' · '+esc(c.author)+' · '+esc(String(c.sha).slice(0,7))+'</small></div><div class="ops" style="display:flex;gap:6px"><a class="btn btn-ghost btn-xs" href="'+esc(c.url)+'" target="_blank" rel="noopener">查看改动</a><button class="btn btn-ghost btn-xs" type="button" data-ref="'+esc(c.sha)+'">载入</button></div></div>';
    }).join(''):'<div class="empty"><b>'+(STATUS&&STATUS.mode==='github'?'还没有历史版本':'本地模式没有版本历史')+'</b>'+(STATUS&&STATUS.mode!=='github'?'<span>请使用 git log 查看文件的修改记录。</span>':'')+'</div>';
  }).catch(function(e){$('#hList').innerHTML='<div class="empty"><b>加载失败</b><span>'+esc(e.message)+'</span></div>'});
}
function insertFile(f){
  var url=f.url,snippet=f.preview_type==='image'?'<img src="'+url+'" alt="'+esc(f.name)+'" loading="lazy">':'<a href="'+url+'" target="_blank" rel="noopener">'+esc(f.name)+'</a>';
  if(PE.cm){PE.cm.replaceSelection(snippet);PE.cm.focus()}
  else if(PE.ta){var s=PE.ta.selectionStart,e=PE.ta.selectionEnd;PE.ta.setRangeText(snippet,s,e,'end');PE.ta.focus();markDirty()}
  CY.toast('已插入「'+f.name+'」','ok');
}

/* ---------------- 真题库 ---------------- */
var MODE={drive:'Google Drive 在线直读',remote:'云端存储（R2）在线直读',local:'本地文件',offline:'仅目录（在线阅读未开启）'};
function initMath(){
  $('#mCard').addEventListener('click',function(e){
    if(!e.target.closest('#mRefresh'))return;
    var b=$('#mRefresh');b.disabled=true;b.textContent='正在读取 Google Drive…';
    api('math/refresh',{method:'POST'}).then(function(d){CY.toast('目录已更新，共 '+d.total+' 个文件','ok');loadMath()}).catch(function(err){fail(err);b.disabled=false;b.textContent='立即刷新目录'});
  });
  loadMath();
}
function loadMath(){
  CY.api('admin/content/math').then(function(r){
    if(!r.ok)throw new Error(CY.errText(r.data,'加载失败'));
    var d=r.data;
    var steps=d.drive_enabled
      ?'<ol class="steps"><li>打开 Google Drive 中的真题文件夹，把新文件上传到对应年份的子文件夹（也可以新建年份文件夹）。</li><li>回到这里点「立即刷新目录」，网站上的真题库会马上显示新文件；不点也会在 30 分钟内自动更新。</li><li>删除或重命名文件同样在 Google Drive 中操作，然后刷新目录。</li></ol>'
      :'<ol class="steps"><li>真题文件保存在 Google Drive 文件夹中，当前还没有开启在线阅读，页面只显示目录。</li><li>在 Render 的 Environment 中添加 <code>CYJY_GDRIVE_API_KEY</code>（步骤见 <a href="https://github.com/hanjiongmin-stack/chongyue-jianyuan/blob/main/docs/deployment.md#开启数学竞赛真题在线阅读" target="_blank" rel="noopener" style="text-decoration:underline">部署指南</a>），之后在 Drive 中增删文件，网站会自动同步。</li></ol>';
    $('#mCard').innerHTML='<div style="display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between"><div><h3 style="font-size:1.1rem;font-weight:700">数学竞赛真题库</h3><p class="muted" style="font-size:13.5px;margin-top:4px">文件来源：'+esc(MODE[d.mode]||d.mode)+(d.drive_updated_at?' · 上次读取 '+esc(when(d.drive_updated_at)):'')+'</p></div><div style="display:flex;gap:8px;flex-wrap:wrap">'+(d.drive_enabled?'<button class="btn btn-primary btn-sm" type="button" id="mRefresh">立即刷新目录</button>':'')+'<a class="btn btn-ghost btn-sm" href="'+esc(d.drive_url)+'" target="_blank" rel="noopener">打开 Google Drive 文件夹</a><a class="btn btn-ghost btn-sm" href="/math/" target="_blank" rel="noopener">查看真题库</a></div></div>'
      +'<div class="mstats"><div><b>'+(+d.total)+'</b><span>文件总数</span></div><div><b>'+(+d.pdfs)+'</b><span>PDF 论文 / 赛题</span></div><div><b>'+(+d.years)+'</b><span>年份目录</span></div><div><b>'+esc(d.mode==='drive'||d.mode==='remote'||d.mode==='local'?'已开启':'未开启')+'</b><span>在线阅读</span></div></div>'
      +'<div><h4 style="font-size:14.5px;font-weight:600;margin-bottom:8px">怎样增加或修改真题</h4>'+steps+'</div>';
  }).catch(function(e){$('#mCard').innerHTML='<div class="empty"><b>加载失败</b><span>'+esc(e.message)+'</span></div>'});
}

/* ---------------- 对外接口 ---------------- */
window.CYContent={
  show:function(t){
    if(['resources','pages','files','math'].indexOf(t)<0)return;
    loadStatus().then(function(){
      if(inited[t])return;inited[t]=true;
      ({resources:initResources,pages:initPages,files:initFiles,math:initMath})[t]();
    });
  }
};
})();
