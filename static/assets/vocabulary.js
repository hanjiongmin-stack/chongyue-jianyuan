(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var words = [], available = false, page = 1, pageSize = 24, masked = false, busy = false, checkedAt = null;
  var loggedIn = false, addBusy = false;
  var revealed = new Set();
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
      var delta = (a.word.createdAt || 0) - (b.word.createdAt || 0);
      return sort === 'oldest' ? delta : -delta;
    });
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
    var body = { word: word, phonetic: $('addPhonetic').value.trim(), zh: $('addZh').value.trim() };
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
  $('wordSearch').addEventListener('input', function () { page = 1; render(); });
  $('wordSort').addEventListener('change', function () { page = 1; render(); });
  $('wordMask').addEventListener('click', function () {
    masked = !masked; revealed.clear();
    this.setAttribute('aria-pressed', String(masked));
    this.textContent = masked ? '显示释义' : '隐藏释义'; render();
  });
  $('wordPrev').addEventListener('click', function () { page--; render(); });
  $('wordNext').addEventListener('click', function () { page++; render(); });
  $('wordSync').addEventListener('click', sync);
  $('wordAdd').addEventListener('click', openAdd);
  $('addCancel').addEventListener('click', closeAdd);
  $('addSubmit').addEventListener('click', submitAdd);
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
