 const API = (() => {
   const REQUEST_TIMEOUT_MS = 20000;
   let _isRefreshing = false;
   let _refreshPromise = null;

   /** 尝试用 refresh token 续期 access token（并发请求共享同一个 promise） */
   async function _tryRefresh() {
     const refreshToken = AppState.getRefreshToken();
     if (!refreshToken) return false;
     if (_isRefreshing) return _refreshPromise;
     _isRefreshing = true;
     _refreshPromise = (async () => {
       try {
         const resp = await fetch(`${API_BASE}/auth/refresh`, {
           method: 'POST',
           headers: {
             'Content-Type': 'application/json',
             'Authorization': `Bearer ${refreshToken}`,
             'X-Device-ID': AppState.getDeviceId(),
           },
           credentials: 'include',
         });
         if (!resp.ok) return false;
         const data = await resp.json();
         if (data.access_token) {
           AppState.setToken(data.access_token);
           return true;
         }
         return false;
       } catch (_) {
         return false;
       } finally {
         _isRefreshing = false;
         _refreshPromise = null;
       }
     })();
     return _refreshPromise;
   }

  async function request(path, options = {}) {
    const headers = {
      'Content-Type': 'application/json',
      'X-Device-ID': AppState.getDeviceId(),
      ...(options.headers || {}),
    };

    const token = AppState.getToken();
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }

    const timeoutMs = options.timeout || REQUEST_TIMEOUT_MS;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);

    let resp;
     try {
       resp = await fetch(`${API_BASE}${path}`, {
         method: options.method || 'GET',
         headers,
         body: options.body ? JSON.stringify(options.body) : undefined,
         signal: controller.signal,
         credentials: 'include',
       });
     } catch (err) {
       if (err.name === 'AbortError') throw new Error('请求超时，请检查网络后重试');
       throw err;
     } finally {
       clearTimeout(timer);
     }

    // 401 自动刷新：用 refresh token 续期后重试一次
    if (resp.status === 401 && !options._retried) {
      const refreshed = await _tryRefresh();
      if (refreshed) {
        return request(path, { ...options, _retried: true });
      }
    }

    let data = null;
    try {
      data = await resp.json();
    } catch (_) {
      data = null;
    }

    if (!resp.ok) {
      throw new Error(data?.detail || '请求失败');
    }
    return data;
  }

   async function streamMessageToUrl(url, payload, handlers = {}, signal) {
    const token = AppState.getToken();
    const headers = {
      'Content-Type': 'application/json',
      'X-Device-ID': AppState.getDeviceId(),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    };
    const resp = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
      signal,
      credentials: 'include',
    });

      if (!resp.ok) {
        let data = null;
        try { data = await resp.json(); } catch (_) { data = null; }
        throw new Error(data?.detail || '流式请求失败');
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const blocks = buffer.split('\n\n');
        buffer = blocks.pop() || '';

        for (const block of blocks) {
          const lines = block.split('\n');
          let event = 'message';
          let dataLine = '';
          for (const line of lines) {
            if (line.startsWith('event: ')) event = line.slice(7).trim();
            if (line.startsWith('data: ')) dataLine += (dataLine ? '\n' : '') + line.slice(6);
          }
          if (!dataLine) continue;
          let payloadData = null;
          try { payloadData = JSON.parse(dataLine); } catch (_) { continue; }
          if (event === 'chunk' && handlers.onChunk) handlers.onChunk(payloadData.text || '');
          if (event === 'done' && handlers.onDone) handlers.onDone(payloadData);
          if (event === 'error' && handlers.onError) handlers.onError(payloadData);
        }
      }
    }

    async function streamMessage(payload, handlers = {}, signal) {
    return streamMessageToUrl(`${API_BASE}/chat/stream`, payload, handlers, signal);
  }

  return {
    health: () => request('/health'),
    login:    (payload) => request('/auth/login',    { method: 'POST', body: payload }),
    register: (payload) => request('/auth/register', { method: 'POST', body: payload }),
    me: () => request('/auth/me'),
    logout: () => request('/auth/logout', { method: 'POST' }),
    refreshToken: (refreshToken) => request('/auth/refresh', { method: 'POST', headers: { 'Authorization': `Bearer ${refreshToken}` } }),
    logoutOthers: () => request('/auth/logout-others', { method: 'POST' }),
    getCharacters: async () => (await request('/characters')).map(normalizeCharacterCardPayload),
    getHistory: (characterId, page = 1, pageSize = 50) => request(`/chat/history?character_id=${encodeURIComponent(characterId)}&page=${page}&page_size=${pageSize}`),
    getCharacterProfile: (characterId) => request(`/character/profile?character_id=${encodeURIComponent(characterId)}`),
    updateCharacterProfile: (payload) => request('/character/profile', { method: 'POST', body: payload }),
    clearChatWithGreeting: (payload) => request('/chat/clear', { method: 'POST', body: payload }),
    sendMessage: (payload) => request('/chat/send', { method: 'POST', body: payload }),
    streamMessage,
    guestStreamMessage: (payload, handlers, signal) => streamMessageToUrl(`${API_BASE}/chat/guest-stream`, payload, handlers, signal),
    getGuestQuota: () => request('/chat/guest-quota'),
    mergeGuestHistory: (payload) => request('/chat/merge-guest-history', { method: 'POST', body: payload }),
    getCharacterState: (characterId) => request(`/character/state?character_id=${encodeURIComponent(characterId)}`),
    getGreetings: (characterId) => request(`/character/greetings?character_id=${encodeURIComponent(characterId)}`),
    regenerateMessage: (payload, handlers, signal) => streamMessageToUrl(`${API_BASE}/chat/regenerate`, payload, handlers, signal),
    continueMessage: (payload, handlers, signal) => streamMessageToUrl(`${API_BASE}/chat/continue`, payload, handlers, signal),

    async uploadAvatar(file) {
      const token = AppState.getToken();
      if (!token) throw new Error('请先登录');
      const formData = new FormData();
      formData.append('file', file);
      const headers = { 'X-Device-ID': AppState.getDeviceId() };
      if (token) headers.Authorization = `Bearer ${token}`;
      const resp = await fetch(`${API_BASE}/user/avatar`, {
        method: 'POST',
        headers,
        body: formData,
        credentials: 'include',
      });
      let data = null;
      try { data = await resp.json(); } catch (_) { data = null; }
      if (!resp.ok) throw new Error(data?.detail || '上传失败');
      return data;
    },
   };
 })();
