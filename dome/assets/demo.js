/* 演示页通用交互（轻量）：菜单高亮 / 弹窗 / 选项卡 / 轻提示 */
(function () {
  /* 1. 侧栏当前页高亮：<body data-page="record"> 对应 a[data-page] */
  var page = document.body.dataset.page;
  if (page) {
    document.querySelectorAll('.zp-menu a[data-page="' + page + '"]').forEach(function (a) {
      a.classList.add('is-active');
    });
  }

  /* 2. 弹窗：[data-open="#id"] 打开 / [data-close] 关闭 / 点遮罩关闭 */
  document.addEventListener('click', function (e) {
    var opener = e.target.closest('[data-open]');
    if (opener) {
      var d = document.querySelector(opener.dataset.open);
      if (d) d.classList.add('is-open');
    }
    if (e.target.closest('[data-close]') || e.target.classList.contains('zp-dialog-mask')) {
      var mask = e.target.closest('.zp-dialog-mask');
      if (mask) mask.classList.remove('is-open');
    }
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      document.querySelectorAll('.zp-dialog-mask.is-open').forEach(function (m) { m.classList.remove('is-open'); });
    }
  });

  /* 3. 选项卡：容器内 button[data-tab] 切换同容器 .zp-tab-panel */
  document.querySelectorAll('[data-tab-group]').forEach(function (group) {
    group.addEventListener('click', function (e) {
      var btn = e.target.closest('button[data-tab]');
      if (!btn) return;
      var scope = document.getElementById(group.dataset.tabGroup) || group.parentElement;
      group.querySelectorAll('button[data-tab]').forEach(function (b) { b.classList.toggle('is-active', b === btn); });
      scope.querySelectorAll('.zp-tab-panel').forEach(function (p) {
        p.classList.toggle('is-active', p.dataset.panel === btn.dataset.tab);
      });
    });
  });

  /* 4. 轻提示：<button data-toast="..."> */
  var toastTimer = null;
  document.addEventListener('click', function (e) {
    var t = e.target.closest('[data-toast]');
    if (!t) return;
    var el = document.getElementById('zpToast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'zpToast';
      el.className = 'zp-toast';
      document.body.appendChild(el);
    }
    el.textContent = t.dataset.toast;
    el.classList.add('is-show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.classList.remove('is-show'); }, 1800);
  });
})();
