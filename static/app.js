(function () {
  var root = document.documentElement;
  var KEY = 'drawer';
  var toggle = document.getElementById('drawerToggle');
  var closeBtn = document.getElementById('drawerClose');
  var backdrop = document.getElementById('backdrop');

  function isOpen() {
    return root.classList.contains('drawer-open');
  }

  function setOpen(open) {
    root.classList.toggle('drawer-open', open);
    if (toggle) toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    try {
      sessionStorage.setItem(KEY, open ? 'open' : 'closed');
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

  if (backdrop) {
    backdrop.addEventListener('click', function () {
      setOpen(false);
    });
  }

  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape' && isOpen()) setOpen(false);
  });

  // 选中某一天会整页跳转，先把抽屉的开合状态存下来，跳转后照旧打开
  document.querySelectorAll('.dayitem').forEach(function (item) {
    item.addEventListener('click', function () {
      try {
        sessionStorage.setItem(KEY, 'open');
      } catch (e) { /* 忽略 */ }
    });
  });

  // 同步一次，保证按钮的 aria 状态与页面一致
  setOpen(isOpen());
})();
