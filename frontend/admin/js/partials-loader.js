/**
 * Synchronously inject admin HTML partials before feature modules run.
 *
 * The admin page uses a strict Content-Security-Policy, so this must live in an
 * external script instead of an inline <script> block.
 */
(function() {
  var partials = ['char-panels', 'system-panels', 'modals'];
  var base = '/api/frontend/admin/partials/';
  for (var i = 0; i < partials.length; i++) {
    var name = partials[i];
    var xhr = new XMLHttpRequest();
    xhr.open('GET', base + name + '.html', false);
    try {
      xhr.send();
    } catch (e) {
      console.error('加载模板失败: ' + name, e);
      continue;
    }
    if (xhr.status === 200) {
      var target = document.getElementById('partial-' + name);
      if (target) target.innerHTML = xhr.responseText;
    }
  }
})();
