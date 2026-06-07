const ForgotPassword = (() => {
  let currentStep = 1;
  let email = '';
  let countdownTimer = null;

  const API_BASE = (() => {
    const shared = window.AIFriendShared;
    return (shared && typeof shared.resolveApiBase === 'function') ? shared.resolveApiBase() : '/api';
  })();

  function bindCodeInputs() {
    const inputs = document.querySelectorAll('.code-input');
    inputs.forEach((input, index) => {
      input.addEventListener('input', (e) => {
        const value = e.target.value;
        if (value && !/^\d$/.test(value)) { e.target.value = ''; return; }
        e.target.classList.toggle('filled', !!value);
        if (value && index < inputs.length - 1) inputs[index + 1].focus();
      });
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Backspace' && !e.target.value && index > 0) inputs[index - 1].focus();
      });
      input.addEventListener('paste', (e) => {
        e.preventDefault();
        const pasteData = e.clipboardData.getData('text').trim();
        if (/^\d{6}$/.test(pasteData)) {
          inputs.forEach((inp, i) => { inp.value = pasteData[i]; inp.classList.add('filled'); });
          inputs[inputs.length - 1].focus();
        }
      });
    });
  }

  function bindEnterKey() {
    document.getElementById('email-input')?.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') sendCode();
    });
    document.getElementById('confirm-password-input')?.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') resetPassword();
    });
  }

  function goToStep(step) {
    document.querySelectorAll('.step-content').forEach(el => el.classList.remove('active'));
    document.getElementById(`step-${step}`)?.classList.add('active');
    document.querySelectorAll('.step-dot').forEach((dot, index) => {
      dot.classList.toggle('active', index < step);
    });
    const subtitles = { 1: '输入邮箱获取验证码', 2: '输入邮箱中收到的验证码', 3: '设置您的新密码', 4: '密码重置完成' };
    document.getElementById('step-subtitle').textContent = subtitles[step] || '';
    currentStep = step;
    const focusMap = { 1: 'email-input', 3: 'new-password-input' };
    if (focusMap[step]) document.getElementById(focusMap[step])?.focus();
    else if (step === 2) document.querySelector('.code-input')?.focus();
  }

  function showError(elementId, message) {
    const errorEl = document.getElementById(elementId);
    if (errorEl) { errorEl.textContent = message; errorEl.classList.add('show'); }
    document.getElementById(elementId.replace('-error', '-input'))?.classList.add('error');
  }

  function clearError(elementId) {
    const errorEl = document.getElementById(elementId);
    if (errorEl) { errorEl.textContent = ''; errorEl.classList.remove('show'); }
    document.getElementById(elementId.replace('-error', '-input'))?.classList.remove('error');
  }

  function showToast(message, type = 'info') {
    const toast = document.getElementById('ui-toast');
    if (!toast) { alert(message); return; }
    toast.textContent = message;
    toast.style.background = type === 'error' ? '#EF4444' : '#10B981';
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 3000);
  }

  function setButtonLoading(buttonId, loading) {
    const btn = document.getElementById(buttonId);
    if (!btn) return;
    if (loading) {
      btn.disabled = true;
      btn.dataset.originalText = btn.textContent;
      btn.innerHTML = '<div class="loading-spinner"></div>';
    } else {
      btn.disabled = false;
      btn.textContent = btn.dataset.originalText || btn.textContent;
    }
  }

  async function sendCode() {
    const emailInput = document.getElementById('email-input').value.trim();
    if (!emailInput) { showError('email-error', '请输入邮箱地址'); return; }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(emailInput)) { showError('email-error', '请输入有效的邮箱地址'); return; }
    clearError('email-error');
    setButtonLoading('send-code-btn', true);
    try {
      const response = await fetch(`${API_BASE}/auth/forgot-password`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: emailInput })
      });
      const data = await response.json();
      if (response.ok) {
        email = emailInput;
        showToast(data.message || '如果该邮箱已注册，验证码会发送至邮箱');
        goToStep(2);
        startCountdown();
      } else {
        showError('email-error', data.detail || '发送失败，请稍后重试');
      }
    } catch { showError('email-error', '网络错误，请稍后重试'); }
    finally { setButtonLoading('send-code-btn', false); }
  }

  function startCountdown() {
    const resendBtn = document.getElementById('resend-btn');
    if (!resendBtn) return;
    let seconds = 60;
    resendBtn.disabled = true;
    resendBtn.textContent = `${seconds}秒后重新发送`;
    countdownTimer = setInterval(() => {
      seconds--;
      if (seconds <= 0) {
        clearInterval(countdownTimer);
        resendBtn.disabled = false;
        resendBtn.textContent = '重新发送';
      } else {
        resendBtn.textContent = `${seconds}秒后重新发送`;
      }
    }, 1000);
  }

  async function resendCode() {
    if (!email) return;
    setButtonLoading('resend-btn', true);
    try {
      const response = await fetch(`${API_BASE}/auth/forgot-password`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email })
      });
      const data = await response.json();
      if (response.ok) {
        showToast(data.message || '如果该邮箱已注册，验证码会发送至邮箱');
        startCountdown();
      } else {
        showToast(data.detail || '发送失败', 'error');
      }
    } catch { showToast('网络错误，请稍后重试', 'error'); }
    finally { setButtonLoading('resend-btn', false); }
  }

  function getCodeValue() {
    let code = '';
    document.querySelectorAll('.code-input').forEach(input => { code += input.value || ''; });
    return code;
  }

  async function verifyCode() {
    const code = getCodeValue();
    if (code.length !== 6) { showError('code-error', '请输入完整的 6 位验证码'); return; }
    clearError('code-error');
    setButtonLoading('verify-code-btn', true);
    try {
      const response = await fetch(`${API_BASE}/auth/verify-code`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, code })
      });
      const data = await response.json();
      if (response.ok) { showToast('验证通过'); goToStep(3); }
      else { showError('code-error', data.detail || '验证码错误'); }
    } catch { showError('code-error', '网络错误，请稍后重试'); }
    finally { setButtonLoading('verify-code-btn', false); }
  }

  function checkPasswordStrength() {
    const password = document.getElementById('new-password-input')?.value || '';
    const strengthBar = document.getElementById('strength-bar');
    if (!strengthBar) return;
    strengthBar.className = 'password-strength-bar';
    if (!password.length) return;
    let strength = 0;
    if (password.length >= 6) strength++;
    if (password.length >= 10) strength++;
    if (/[a-z]/.test(password) && /[A-Z]/.test(password)) strength++;
    if (/\d/.test(password)) strength++;
    if (/[^a-zA-Z0-9]/.test(password)) strength++;
    strengthBar.classList.add(strength <= 2 ? 'weak' : strength <= 4 ? 'medium' : 'strong');
  }

  async function resetPassword() {
    const newPassword = document.getElementById('new-password-input').value;
    const confirmPassword = document.getElementById('confirm-password-input').value;
    const code = getCodeValue();
    if (!newPassword || newPassword.length < 6) { showError('password-error', '密码至少需要 6 位字符'); return; }
    if (newPassword !== confirmPassword) { showError('password-error', '两次输入的密码不一致'); return; }
    clearError('password-error');
    setButtonLoading('reset-password-btn', true);
    try {
      const response = await fetch(`${API_BASE}/auth/reset-password`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, code, new_password: newPassword })
      });
      const data = await response.json();
      if (response.ok) { showToast('密码重置成功'); goToStep(4); }
      else { showError('password-error', data.detail || '重置失败，请重试'); }
    } catch { showError('password-error', '网络错误，请稍后重试'); }
    finally { setButtonLoading('reset-password-btn', false); }
  }

  function init() {
    bindCodeInputs();
    bindEnterKey();
    bindButtons();
  }

  function bindButtons() {
    document.getElementById('send-code-btn')?.addEventListener('click', sendCode);
    document.getElementById('verify-code-btn')?.addEventListener('click', verifyCode);
    document.getElementById('resend-btn')?.addEventListener('click', resendCode);
    document.getElementById('back-to-step1-btn')?.addEventListener('click', () => goToStep(1));
    document.getElementById('back-to-step2-btn')?.addEventListener('click', () => goToStep(2));
    document.getElementById('reset-password-btn')?.addEventListener('click', resetPassword);
    document.getElementById('go-login-btn')?.addEventListener('click', () => { window.location.href = "/"; });
    document.getElementById('new-password-input')?.addEventListener('input', checkPasswordStrength);
  }

  return { init, sendCode, verifyCode, resetPassword, checkPasswordStrength, resendCode };
})();

document.addEventListener('DOMContentLoaded', () => ForgotPassword.init());
