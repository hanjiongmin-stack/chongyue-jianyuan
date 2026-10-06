(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var words = [], available = false, page = 1, pageSize = 24, masked = false, busy = false, checkedAt = null;
  var loggedIn = false, addBusy = false, matched = 0;
  var lookup = null, lookupSeq = 0, lookupTimer = null;
  var revealed = new Set();
  var SORT_KEY = 'cyjy_vocab_sort';
  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function definition(word) {
    return word.zh || (word.zhGroups || []).map(function (g) { return [g.pos, g.text].filter(Boolean).join(' · '); }).join('\n') || '暂无释义';
  }
  function render() {
    var query = $('wordSearch').value.trim().toLocaleLowerCase();
    var items = words.map(function (word, index) { return {word: word, index: index}; }).filter(function (item) {
      return (item.word.word + ' ' + definition(item.word)).toLocaleLowerCase().includes(query);
    });
    var sort = $('wordSort').value;
    items.sort(function (a, b) {
      if (sort === 'az') return a.word.word.localeCompare(b.word.word, 'en');
      if (sort === 'za') return b.word.word.localeCompare(a.word.word, 'en');
      var delta = (a.word.createdAt || 0) - (b.word.createdAt || 0);
      return sort === 'oldest' ? delta : -delta;
    });
    matched = items.length;
    var pages = Math.max(1, Math.ceil(items.length / pageSize));
    page = Math.min(page, pages);
    $('wordTotal').textContent = available ? words.length : '—';
    $('wordMatched').textContent = available ? items.length : '—';
    $('wordPage').textContent = '第 ' + page + ' / ' + pages + ' 页';
    $('wordPrev').disabled = page <= 1;
    $('wordNext').disabled = page >= pages;
    var list = $('wordList');
    list.replaceChildren();
    if (!items.length) {
      var empty = el('div', 'panel empty');
      empty.append(el('b', '', !available ? '暂时无法获取单词' : words.length ? '没有匹配的单词' : '还没有单词记录'));
      empty.append(el('span', '', !available ? '请稍后点击「同步更新」重试。' : words.length ? '换一个单词或中文关键词试试。' : '新的记录同步后会显示在这里。'));
      list.append(empty);
    }
    items.slice((page - 1) * pageSize, page * pageSize).forEach(function (item) {
      var word = item.word, card = el('article', 'panel vocab-word'), head = el('div', 'vocab-word-head'), title = el('div');
      title.append(el('h2', '', word.word));
      if (word.phonetic) title.append(el('p', 'vocab-phonetic', word.phonetic));
      head.append(title);
      if (loggedIn) head.append(deleteButton(word));
      card.append(head);
      var meaning = el('div', 'vocab-meaning', definition(word));
      meaning.hidden = masked && !revealed.has(item.index);
      if (masked) {
        var reveal = el('button', 'btn btn-ghost btn-xs vocab-reveal', meaning.hidden ? '查看释义' : '收起释义');
        reveal.type = 'button';
        reveal.setAttribute('aria-label', '查看或收起 ' + word.word + ' 的释义');
        reveal.setAttribute('aria-expanded', String(!meaning.hidden));
        reveal.addEventListener('click', function () {
          meaning.hidden = !meaning.hidden;
          if (meaning.hidden) revealed.delete(item.index); else revealed.add(item.index);
          reveal.textContent = meaning.hidden ? '查看释义' : '收起释义';
          reveal.setAttribute('aria-expanded', String(!meaning.hidden));
        });
        card.append(reveal);
      }
      card.append(meaning);
      if (word.createdAt) {
        var date = new Date(word.createdAt);
        if (!Number.isNaN(date.getTime())) {
          var time = el('time', 'vocab-date', '记录于 ' + date.toLocaleDateString('zh-CN'));
          time.dateTime = date.toISOString();
          card.append(time);
        }
      }
      list.append(card);
    });
  }
  async function sync() {
    if (busy) return;
    busy = true;
    $('wordSync').disabled = true;
    $('wordSync').textContent = '同步中…';
    $('wordList').setAttribute('aria-busy', 'true');
    $('syncStatus').textContent = '正在检查更新…';
    var controller = new AbortController(), timer = setTimeout(function () { controller.abort(); }, 18000);
    try {
      var response = await fetch('/api/v1/vocabulary', {cache: 'no-store', signal: controller.signal});
      var data = await response.json();
      if (!response.ok || !data.available || !Array.isArray(data.words)) throw new Error('unavailable');
      // Preserve page position and revealed answers when the feed is unchanged.
      if (JSON.stringify(words) !== JSON.stringify(data.words)) { words = data.words; revealed.clear(); }
      available = true;
      checkedAt = data.checkedAt;
      $('wordNotice').hidden = !data.stale;
      $('wordNotice').textContent = data.stale ? '暂时无法同步，正在显示上次成功获取的记录。' : '';
      $('syncStatus').textContent = (data.stale ? '上次成功同步：' : '已同步 · 最近检查：') + (checkedAt ? new Date(checkedAt).toLocaleString('zh-CN') : '—');
    } catch (error) {
      $('wordNotice').hidden = false;
      $('wordNotice').textContent = available ? '同步失败，已保留当前记录。请稍后重试。' : '单词数据暂不可用，请稍后重试或联系站点维护者。';
      $('syncStatus').textContent = available ? '同步失败 · 上次成功：' + new Date(checkedAt).toLocaleString('zh-CN') : '尚未成功同步';
    } finally {
      clearTimeout(timer);
      busy = false;
      $('wordSync').disabled = false;
      $('wordSync').textContent = '同步更新';
      $('wordList').setAttribute('aria-busy', 'false');
      render();
    }
  }
  // ── 添加单词（登录用户）──────────────────────────────
  function updateAddButton() {
    $('wordAdd').textContent = loggedIn ? '添加单词' : '登录后添加';
    if (available) render();   // 登录后单词卡片上才会出现「删除」
  }
  function checkAuth() {
    return CY.api('users/me').then(function (res) {
      loggedIn = !!res.ok;
      updateAddButton();
    }, function () { loggedIn = false; updateAddButton(); });
  }
  function openAdd() {
    if (!loggedIn) {
      location.href = '/login?redirect=' + encodeURIComponent('/ielts');
      return;
    }
    $('wordAddPanel').hidden = false;
    $('addError').hidden = true;
    $('addWord').focus();
  }
  function closeAdd() {
    $('wordAddPanel').hidden = true;
    $('addWord').value = ''; $('addPhonetic').value = ''; $('addZh').value = '';
    $('addError').hidden = true; $('addError').textContent = '';
    lookup = null; lookupSeq = 0;
    $('lookupBox').hidden = true; $('lookupStatus').hidden = true;
    $('manualFields').hidden = true;
    $('addManual').setAttribute('aria-expanded', 'false');
    $('addManual').textContent = '手动补充';
  }
  // ── 自动查词：只输入单词，音标和释义由服务端查好 ──────────
  function showLookup(status, tone) {
    $('lookupStatus').textContent = status;
    $('lookupStatus').hidden = !status;
    $('lookupStatus').className = 'vocab-lookup-status' + (tone ? ' ' + tone : '');
  }
  async function runLookup(word) {
    var seq = ++lookupSeq;
    lookup = null;
    $('lookupBox').hidden = true;
    showLookup('正在查询音标和释义…');
    try {
      var res = await CY.api('vocabulary/lookup?word=' + encodeURIComponent(word));
      if (seq !== lookupSeq) return;   // 期间又改了单词，丢弃旧结果
      if (!res.ok) { showLookup(CY.errText(res.data, '查询失败'), 'warn'); return; }
      var data = res.data || {};
      lookup = data;
      if (data.phonetic || data.zh) {
        $('lookupPhonetic').textContent = data.phonetic || '';
        $('lookupZh').textContent = data.zh || '（只查到音标，没查到中文释义）';
        $('lookupBox').hidden = false;
        showLookup('已自动查到，直接保存即可');
      } else {
        showLookup('没查到释义，可以先保存，之后手动补充', 'warn');
      }
    } catch (error) {
      if (seq === lookupSeq) showLookup('查询失败，可以先保存单词', 'warn');
    }
  }
  function scheduleLookup() {
    var word = $('addWord').value.trim();
    clearTimeout(lookupTimer);
    if (word.length < 2) { $('lookupBox').hidden = true; showLookup(''); return; }
    lookupTimer = setTimeout(function () { runLookup(word); }, 500);
  }
  function showAddError(msg) {
    var e = $('addError');
    e.textContent = msg;
    e.hidden = false;
  }
  async function submitAdd() {
    if (addBusy) return;
    var word = $('addWord').value.trim();
    if (!word) { showAddError('请填写单词'); $('addWord').focus(); return; }
    // 手动补充的内容优先，否则用自动查到的（服务端也会兜底再查一次）
    var phonetic = $('addPhonetic').value.trim() || (lookup && lookup.phonetic) || '';
    var zh = $('addZh').value.trim() || (lookup && lookup.zh) || '';
    var body = { word: word, phonetic: phonetic, zh: zh };
    addBusy = true;
    $('addSubmit').disabled = true;
    $('addSubmit').textContent = '保存中…';
    try {
      var res = await CY.api('vocabulary', { method: 'POST', json: body });
      if (res.ok) {
        closeAdd();
        await sync();
        CY.toast('已添加「' + word + '」', 'ok');
      } else {
        showAddError(CY.errText(res.data, '添加失败，请稍后再试'));
      }
    } catch (error) {
      showAddError('网络异常，请稍后再试');
    } finally {
      addBusy = false;
      $('addSubmit').disabled = false;
      $('addSubmit').textContent = '保存单词';
    }
  }
  // ── 删除单词（登录用户）──────────────────────────────
  function deleteButton(word) {
    var btn = el('button', 'btn btn-ghost btn-xs vocab-del', '删除');
    btn.type = 'button';
    btn.setAttribute('aria-label', '删除单词 ' + word.word);
    btn.addEventListener('click', function () {
      if (btn.dataset.confirm === '1') { removeWord(word); return; }
      btn.dataset.confirm = '1';
      btn.textContent = '确认删除？';
      btn.classList.add('danger');
      clearTimeout(btn._timer);
      btn._timer = setTimeout(function () {
        btn.dataset.confirm = ''; btn.textContent = '删除'; btn.classList.remove('danger');
      }, 4000);
    });
    return btn;
  }
  async function removeWord(word) {
    var backup = words.slice();
    words = words.filter(function (w) { return String(w.word).toLowerCase() !== String(word.word).toLowerCase(); });
    revealed.clear();
    render();
    try {
      var res = await CY.api('vocabulary', { method: 'DELETE', json: { word: word.word } });
      if (res.ok) {
        CY.toast('已删除「' + word.word + '」', 'ok');
        await sync();
      } else {
        words = backup; render();
        CY.toast(CY.errText(res.data, '删除失败，请稍后再试'), 'err');
      }
    } catch (error) {
      words = backup; render();
      CY.toast('网络异常，删除未成功', 'err');
    }
  }
  // ── 导出 Word ────────────────────────────────────────
  function exportWord() {
    var query = $('wordSearch').value.trim();
    var url = '/api/v1/vocabulary/export?sort=' + encodeURIComponent($('wordSort').value) +
              '&q=' + encodeURIComponent(query);
    var link = document.createElement('a');
    link.href = url;
    link.download = '';
    document.body.appendChild(link);
    link.click();
    link.remove();
    CY.toast('已导出 ' + (matched || words.length) + ' 个单词到 Word', 'ok');
  }
  // 记住排序方式，默认字母 A–Z
  try {
    var savedSort = localStorage.getItem(SORT_KEY);
    if (savedSort) $('wordSort').value = savedSort;
  } catch (e) {}
  $('wordSearch').addEventListener('input', function () { page = 1; render(); });
  $('wordSort').addEventListener('change', function () {
    try { localStorage.setItem(SORT_KEY, $('wordSort').value); } catch (e) {}
    page = 1; render();
  });
  $('wordMask').addEventListener('click', function () {
    masked = !masked; revealed.clear();
    this.setAttribute('aria-pressed', String(masked));
    this.textContent = masked ? '显示释义' : '隐藏释义'; render();
  });
  $('wordPrev').addEventListener('click', function () { page--; render(); });
  $('wordNext').addEventListener('click', function () { page++; render(); });
  $('wordSync').addEventListener('click', sync);
  $('wordExport').addEventListener('click', exportWord);
  $('wordAdd').addEventListener('click', openAdd);
  $('addCancel').addEventListener('click', closeAdd);
  $('addSubmit').addEventListener('click', submitAdd);
  $('addWord').addEventListener('input', scheduleLookup);
  $('addManual').addEventListener('click', function () {
    var open = $('manualFields').hidden;
    $('manualFields').hidden = !open;
    this.setAttribute('aria-expanded', String(open));
    this.textContent = open ? '收起手动补充' : '手动补充';
    if (open) {
      // 把自动查到的内容带进去，方便微调
      if (lookup && !$('addPhonetic').value) $('addPhonetic').value = lookup.phonetic || '';
      if (lookup && !$('addZh').value) $('addZh').value = lookup.zh || '';
      $('addPhonetic').focus();
    }
  });
  ['addWord', 'addPhonetic', 'addZh'].forEach(function (id) {
    $(id).addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); submitAdd(); }
    });
  });
  document.addEventListener('visibilitychange', function () { if (!document.hidden) sync(); });
  setInterval(function () { if (!document.hidden) sync(); }, 60000);
  checkAuth();
  sync();
})();
