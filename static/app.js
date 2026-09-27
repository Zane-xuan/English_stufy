(function () {
  var root = document.documentElement;
  var closers = [];

  // 抽屉：靠 html 上的一个 class 控制开合，状态存 sessionStorage。
  // 左右两个抽屉共用这套逻辑，彼此独立。
  function makeDrawer(toggleId, closeId, openClass, key) {
    var toggle = document.getElementById(toggleId);
    var closeBtn = document.getElementById(closeId);

    function isOpen() {
      return root.classList.contains(openClass);
    }

    function setOpen(open) {
      root.classList.toggle(openClass, open);
      if (toggle) toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      try {
        sessionStorage.setItem(key, open ? 'open' : 'closed');
      } catch (e) { /* 隐私模式下写不了，忽略 */ }
    }

    if (toggle) {
      toggle.addEventListener('click', function () {
        setOpen(!isOpen());
      });
    }

    if (closeBtn) {
      closeBtn.addEventListener('click', function () {
        setOpen(false);
      });
    }

    // 同步一次，保证按钮的 aria 状态与页面一致
    setOpen(isOpen());
    closers.push(function () { setOpen(false); });
  }

  makeDrawer('drawerToggle', 'drawerClose', 'drawer-open', 'drawer');
  makeDrawer('taskbarToggle', 'taskbarClose', 'taskbar-open', 'taskbar');

  function closeAll() {
    closers.forEach(function (close) { close(); });
  }

  var backdrop = document.getElementById('backdrop');
  if (backdrop) {
    backdrop.addEventListener('click', closeAll);
  }

  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape') closeAll();
  });

  // 选中某一天会整页跳转，先把右侧抽屉的开合状态存下来，跳转后照旧打开。
  // 只认历史抽屉里的条目；「今天任务」里的复习清单不参与。
  document.querySelectorAll('.sidebar .dayitem').forEach(function (item) {
    item.addEventListener('click', function () {
      try {
        sessionStorage.setItem('drawer', 'open');
      } catch (e) { /* 忽略 */ }
    });
  });
})();

// 补充：保存当前这一期的补充文字。需要口令，浏览器里输一次后记住。
(function () {
  var KEY = 'notesPassword';
  var editor = document.querySelector('.supp-editor');
  if (!editor) return;

  var enabled = editor.getAttribute('data-enabled') === 'true';
  var slug = editor.getAttribute('data-slug');
  var input = editor.querySelector('.supp-input');
  var save = editor.querySelector('.supp-save');
  var status = editor.querySelector('.supp-status');
  if (!save || !input) return;

  function say(msg, cls) {
    if (!status) return;
    status.textContent = msg;
    status.className = 'supp-status' + (cls ? ' ' + cls : '');
  }

  save.addEventListener('click', function () {
    if (!enabled) {
      say('未配置口令，无法保存', 'err');
      return;
    }

    var pw = '';
    try { pw = localStorage.getItem(KEY) || ''; } catch (e) { /* 隐私模式写不了，忽略 */ }
    if (!pw) {
      pw = window.prompt('请输入补充编辑口令') || '';
      if (!pw) { say('已取消', 'err'); return; }
      try { localStorage.setItem(KEY, pw); } catch (e) { /* 忽略 */ }
    }

    say('保存中…', '');
    fetch('/api/supplements', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Notes-Password': pw },
      body: JSON.stringify({ slug: slug, text: input.value })
    }).then(function (res) {
      if (res.status === 401) {
        try { localStorage.removeItem(KEY); } catch (e) { /* 忽略 */ }
        say('口令不正确，请重试', 'err');
        return null;
      }
      if (!res.ok) { say('保存失败（' + res.status + '）', 'err'); return null; }
      return res.json();
    }).then(function (data) {
      if (data) say('已保存', 'ok');
    }).catch(function () {
      say('网络错误', 'err');
    });
  });
})();
