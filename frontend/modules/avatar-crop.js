/**
 * avatar-crop.js — 头像裁剪模块
 *
 * 提供方形裁剪弹窗：拖拽移动图片位置 + 缩放滑块 → Canvas 输出 512×512
 */
const AvatarCrop = (() => {
  let _file = null;
  let _img = null;
  let _scale = 1;
  let _offsetX = 0, _offsetY = 0;
  let _dragging = false;
  let _dragStartX = 0, _dragStartY = 0;
  let _dragOrigX = 0, _dragOrigY = 0;
  let _cropSize = 300; // CSS 像素，会在 open 时根据屏幕调整

  function open(file) {
    _file = file;
    _scale = 1;
    _offsetX = 0;
    _offsetY = 0;
    _dragging = false;

    // 移动端 crop 区域不超过屏幕宽度
    _cropSize = Math.min(300, window.innerWidth - 60);

    const reader = new FileReader();
    reader.onload = function(e) {
      _img = new Image();
      _img.onload = function() {
        _showModal();
      };
      _img.src = e.target.result;
    };
    reader.readAsDataURL(file);
  }

  function _showModal() {
    var modal = document.getElementById('crop-modal');
    var imgEl = document.getElementById('crop-image');
    var wrapper = document.getElementById('crop-wrapper');
    var zoomSlider = document.getElementById('crop-zoom');

    wrapper.style.width = _cropSize + 'px';
    wrapper.style.height = _cropSize + 'px';
    imgEl.src = _img.src;
    zoomSlider.value = 100;

    _fitImage();
    _updateImagePosition();

    modal.style.display = 'flex';
    setTimeout(function() { modal.classList.add('open'); }, 10);

    // 拖拽事件
    var mask = document.getElementById('crop-mask');
    mask.addEventListener('mousedown', _onDragStart);
    mask.addEventListener('touchstart', _onDragStart, { passive: false });
    document.addEventListener('mousemove', _onDragMove);
    document.addEventListener('touchmove', _onDragMove, { passive: false });
    document.addEventListener('mouseup', _onDragEnd);
    document.addEventListener('touchend', _onDragEnd);
  }

  function _fitImage() {
    // 缩放图片使短边填满 crop 区域
    var imgW = _img.naturalWidth;
    var imgH = _img.naturalHeight;
    _scale = Math.max(_cropSize / imgW, _cropSize / imgH);
    _offsetX = (_cropSize - imgW * _scale) / 2;
    _offsetY = (_cropSize - imgH * _scale) / 2;
  }

  function _updateImagePosition() {
    var imgEl = document.getElementById('crop-image');
    if (!imgEl) return;
    var s = _scale;
    var w = _img.naturalWidth * s;
    var h = _img.naturalHeight * s;
    imgEl.style.width = w + 'px';
    imgEl.style.height = h + 'px';
    imgEl.style.transform = 'translate(' + _offsetX + 'px, ' + _offsetY + 'px)';
  }

  function _clampOffset() {
    var imgW = _img.naturalWidth * _scale;
    var imgH = _img.naturalHeight * _scale;
    // 不允许图片边缘进入 crop 区域内部（保证始终填满）
    _offsetX = Math.min(0, Math.max(_cropSize - imgW, _offsetX));
    _offsetY = Math.min(0, Math.max(_cropSize - imgH, _offsetY));
  }

  function _onDragStart(e) {
    e.preventDefault();
    _dragging = true;
    var pt = e.touches ? e.touches[0] : e;
    _dragStartX = pt.clientX;
    _dragStartY = pt.clientY;
    _dragOrigX = _offsetX;
    _dragOrigY = _offsetY;
  }

  function _onDragMove(e) {
    if (!_dragging) return;
    e.preventDefault();
    var pt = e.touches ? e.touches[0] : e;
    _offsetX = _dragOrigX + (pt.clientX - _dragStartX);
    _offsetY = _dragOrigY + (pt.clientY - _dragStartY);
    _clampOffset();
    _updateImagePosition();
  }

  function _onDragEnd() {
    _dragging = false;
  }

  function _cleanup() {
    document.removeEventListener('mousemove', _onDragMove);
    document.removeEventListener('touchmove', _onDragMove);
    document.removeEventListener('mouseup', _onDragEnd);
    document.removeEventListener('touchend', _onDragEnd);
  }

  function close() {
    _cleanup();
    var modal = document.getElementById('crop-modal');
    modal.classList.remove('open');
    setTimeout(function() { modal.style.display = 'none'; }, 250);
  }

  function zoom(val) {
    var oldW = _img.naturalWidth * _scale;
    var oldH = _img.naturalHeight * _scale;
    // 保持 crop 区域中心点对应的图片位置不变
    var cx = (_cropSize / 2 - _offsetX) / oldW;
    var cy = (_cropSize / 2 - _offsetY) / oldH;

    _scale = val / 100;
    // 限制最小缩放：图片至少填满 crop 区域
    var minScale = Math.max(_cropSize / _img.naturalWidth, _cropSize / _img.naturalHeight);
    _scale = Math.max(minScale, Math.min(3, _scale));

    var newW = _img.naturalWidth * _scale;
    var newH = _img.naturalHeight * _scale;
    _offsetX = _cropSize / 2 - cx * newW;
    _offsetY = _cropSize / 2 - cy * newH;
    _clampOffset();
    _updateImagePosition();
  }

  function confirm() {
    // Canvas 裁剪为 512×512
    var canvas = document.createElement('canvas');
    canvas.width = 512;
    canvas.height = 512;
    var ctx = canvas.getContext('2d');

    // 计算 crop 区域在原始图片上的坐标
    var imgW = _img.naturalWidth;
    var imgH = _img.naturalHeight;
    var displayedW = imgW * _scale;
    var displayedH = imgH * _scale;

    // crop 区域内显示的图片像素范围
    var sx = (-_offsetX / displayedW) * imgW;
    var sy = (-_offsetY / displayedH) * imgH;
    var sw = (_cropSize / displayedW) * imgW;
    var sh = (_cropSize / displayedH) * imgH;

    ctx.drawImage(_img, sx, sy, sw, sh, 0, 0, 512, 512);

    canvas.toBlob(function(blob) {
      if (!blob) { UI.toast('裁剪失败，请重试', 'error'); return; }
      // 包装为 File 对象，确保有合法的文件名（后端校验扩展名）
      var croppedFile = new File([blob], 'avatar.jpg', { type: 'image/jpeg' });
      Auth.uploadAvatar(croppedFile);
      close();
    }, 'image/jpeg', 0.9);
  }

  return { open, close, zoom, confirm };
})();
