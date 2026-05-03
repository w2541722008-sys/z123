/**
 * 忘记密码页面逻辑
 * 
 * 三步流程：
 * 1. 输入邮箱 → 发送验证码
 * 2. 输入验证码 → 验证
 * 3. 设置新密码 → 完成
 */

const ForgotPassword = {
  // 当前步骤
  currentStep: 1,
  
  // 用户邮箱
  email: '',
  
  // 倒计时定时器
  countdownTimer: null,
  
  // API 基础地址
  get API_BASE() {
    const shared = window.AIFriendShared;
    if (shared && typeof shared.resolveApiBase === 'function') {
      return shared.resolveApiBase();
    }
    return '/api';
  },
  
  /**
   * 初始化
   */
  init() {
    this.bindCodeInputs();
    this.bindEnterKey();
  },
  
  /**
   * 绑定验证码输入框事件
   */
  bindCodeInputs() {
    const inputs = document.querySelectorAll('.code-input');
    
    inputs.forEach((input, index) => {
      // 输入时自动跳到下一个
      input.addEventListener('input', (e) => {
        const value = e.target.value;
        
        // 只保留数字
        if (value && !/^\d$/.test(value)) {
          e.target.value = '';
          return;
        }
        
        // 更新样式
        if (value) {
          e.target.classList.add('filled');
        } else {
          e.target.classList.remove('filled');
        }
        
        // 自动跳到下一个
        if (value && index < inputs.length - 1) {
          inputs[index + 1].focus();
        }
      });
      
      // 删除时回到上一个
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Backspace' && !e.target.value && index > 0) {
          inputs[index - 1].focus();
        }
      });
      
      // 粘贴处理
      input.addEventListener('paste', (e) => {
        e.preventDefault();
        const pasteData = e.clipboardData.getData('text').trim();
        
        // 如果是 6 位数字，自动填充
        if (/^\d{6}$/.test(pasteData)) {
          inputs.forEach((inp, i) => {
            inp.value = pasteData[i];
            inp.classList.add('filled');
          });
          inputs[inputs.length - 1].focus();
        }
      });
    });
  },
  
  /**
   * 绑定回车键
   */
  bindEnterKey() {
    // 邮箱输入框回车发送验证码
    document.getElementById('email-input')?.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') {
        this.sendCode();
      }
    });
    
    // 密码输入框回车提交
    document.getElementById('confirm-password-input')?.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') {
        this.resetPassword();
      }
    });
  },
  
  /**
   * 切换到指定步骤
   */
  goToStep(step) {
    // 隐藏所有步骤
    document.querySelectorAll('.step-content').forEach(el => {
      el.classList.remove('active');
    });
    
    // 显示目标步骤
    document.getElementById(`step-${step}`)?.classList.add('active');
    
    // 更新步骤指示器
    document.querySelectorAll('.step-dot').forEach((dot, index) => {
      dot.classList.toggle('active', index < step);
    });
    
    // 更新副标题
    const subtitles = {
      1: '输入邮箱获取验证码',
      2: '输入邮箱中收到的验证码',
      3: '设置您的新密码',
      4: '密码重置完成'
    };
    document.getElementById('step-subtitle').textContent = subtitles[step] || '';
    
    this.currentStep = step;
    
    // 自动聚焦
    if (step === 1) {
      document.getElementById('email-input')?.focus();
    } else if (step === 2) {
      document.querySelector('.code-input')?.focus();
    } else if (step === 3) {
      document.getElementById('new-password-input')?.focus();
    }
  },
  
  /**
   * 显示/隐藏错误信息
   */
  showError(elementId, message) {
    const errorEl = document.getElementById(elementId);
    if (errorEl) {
      errorEl.textContent = message;
      errorEl.classList.add('show');
    }
    
    // 给输入框添加错误样式
    const inputId = elementId.replace('-error', '-input');
    const inputEl = document.getElementById(inputId);
    if (inputEl) {
      inputEl.classList.add('error');
    }
  },
  
  /**
   * 清除错误信息
   */
  clearError(elementId) {
    const errorEl = document.getElementById(elementId);
    if (errorEl) {
      errorEl.textContent = '';
      errorEl.classList.remove('show');
    }
    
    const inputId = elementId.replace('-error', '-input');
    const inputEl = document.getElementById(inputId);
    if (inputEl) {
      inputEl.classList.remove('error');
    }
  },
  
  /**
   * 显示 Toast 提示
   */
  showToast(message, type = 'info') {
    const toast = document.getElementById('ui-toast');
    if (!toast) {
      alert(message);
      return;
    }
    
    toast.textContent = message;
    toast.style.background = type === 'error' ? '#EF4444' : '#10B981';
    toast.classList.add('show');
    
    setTimeout(() => {
      toast.classList.remove('show');
    }, 3000);
  },
  
  /**
   * 设置按钮加载状态
   */
  setButtonLoading(buttonId, loading) {
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
  },
  
  /**
   * 发送验证码
   */
  async sendCode() {
    const emailInput = document.getElementById('email-input');
    const email = emailInput.value.trim();
    
    // 验证邮箱
    if (!email) {
      this.showError('email-error', '请输入邮箱地址');
      return;
    }
    
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      this.showError('email-error', '请输入有效的邮箱地址');
      return;
    }
    
    this.clearError('email-error');
    this.setButtonLoading('send-code-btn', true);
    
    try {
      const response = await fetch(`${this.API_BASE}/auth/forgot-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email })
      });
      
      const data = await response.json();
      
      if (response.ok) {
        this.email = email;
        this.showToast(data.message || '如果该邮箱已注册，验证码会发送至邮箱');
        this.goToStep(2);
        this.startCountdown();
      } else {
        this.showError('email-error', data.detail || '发送失败，请稍后重试');
      }
    } catch (error) {
      console.error('发送验证码失败:', error);
      this.showError('email-error', '网络错误，请稍后重试');
    } finally {
      this.setButtonLoading('send-code-btn', false);
    }
  },
  
  /**
   * 开始倒计时
   */
  startCountdown() {
    const resendBtn = document.getElementById('resend-btn');
    if (!resendBtn) return;
    
    let seconds = 60;
    
    resendBtn.disabled = true;
    resendBtn.textContent = `${seconds}秒后重新发送`;
    
    this.countdownTimer = setInterval(() => {
      seconds--;
      
      if (seconds <= 0) {
        clearInterval(this.countdownTimer);
        resendBtn.disabled = false;
        resendBtn.textContent = '重新发送';
      } else {
        resendBtn.textContent = `${seconds}秒后重新发送`;
      }
    }, 1000);
  },
  
  /**
   * 重新发送验证码
   */
  async resendCode() {
    if (!this.email) return;
    
    this.setButtonLoading('resend-btn', true);
    
    try {
      const response = await fetch(`${this.API_BASE}/auth/forgot-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: this.email })
      });
      
      const data = await response.json();
      
      if (response.ok) {
        this.showToast(data.message || '如果该邮箱已注册，验证码会发送至邮箱');
        this.startCountdown();
      } else {
        this.showToast(data.detail || '发送失败', 'error');
      }
    } catch (error) {
      console.error('重新发送失败:', error);
      this.showToast('网络错误，请稍后重试', 'error');
    } finally {
      this.setButtonLoading('resend-btn', false);
    }
  },
  
  /**
   * 获取验证码输入值
   */
  getCodeValue() {
    const inputs = document.querySelectorAll('.code-input');
    let code = '';
    inputs.forEach(input => {
      code += input.value || '';
    });
    return code;
  },
  
  /**
   * 验证验证码
   */
  async verifyCode() {
    const code = this.getCodeValue();
    
    if (code.length !== 6) {
      this.showError('code-error', '请输入完整的 6 位验证码');
      return;
    }
    
    this.clearError('code-error');
    this.setButtonLoading('verify-code-btn', true);
    
    try {
      const response = await fetch(`${this.API_BASE}/auth/verify-code`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: this.email, code })
      });
      
      const data = await response.json();
      
      if (response.ok) {
        this.showToast('验证通过');
        this.goToStep(3);
      } else {
        this.showError('code-error', data.detail || '验证码错误');
      }
    } catch (error) {
      console.error('验证失败:', error);
      this.showError('code-error', '网络错误，请稍后重试');
    } finally {
      this.setButtonLoading('verify-code-btn', false);
    }
  },
  
  /**
   * 检查密码强度
   */
  checkPasswordStrength() {
    const password = document.getElementById('new-password-input')?.value || '';
    const strengthBar = document.getElementById('strength-bar');
    
    if (!strengthBar) return;
    
    // 清除样式
    strengthBar.className = 'password-strength-bar';
    
    if (password.length === 0) return;
    
    // 计算强度
    let strength = 0;
    if (password.length >= 6) strength++;
    if (password.length >= 10) strength++;
    if (/[a-z]/.test(password) && /[A-Z]/.test(password)) strength++;
    if (/\d/.test(password)) strength++;
    if (/[^a-zA-Z0-9]/.test(password)) strength++;
    
    // 应用样式
    if (strength <= 2) {
      strengthBar.classList.add('weak');
    } else if (strength <= 4) {
      strengthBar.classList.add('medium');
    } else {
      strengthBar.classList.add('strong');
    }
  },
  
  /**
   * 重置密码
   */
  async resetPassword() {
    const newPassword = document.getElementById('new-password-input').value;
    const confirmPassword = document.getElementById('confirm-password-input').value;
    const code = this.getCodeValue();
    
    // 验证
    if (!newPassword || newPassword.length < 6) {
      this.showError('password-error', '密码至少需要 6 位字符');
      return;
    }
    
    if (newPassword !== confirmPassword) {
      this.showError('password-error', '两次输入的密码不一致');
      return;
    }
    
    this.clearError('password-error');
    this.setButtonLoading('reset-password-btn', true);
    
    try {
      const response = await fetch(`${this.API_BASE}/auth/reset-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: this.email,
          code: code,
          new_password: newPassword
        })
      });
      
      const data = await response.json();
      
      if (response.ok) {
        this.showToast('密码重置成功');
        this.goToStep(4);
      } else {
        this.showError('password-error', data.detail || '重置失败，请重试');
      }
    } catch (error) {
      console.error('重置密码失败:', error);
      this.showError('password-error', '网络错误，请稍后重试');
    } finally {
      this.setButtonLoading('reset-password-btn', false);
    }
  }
};

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
  ForgotPassword.init();
});
