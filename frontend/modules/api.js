 const API = (() => {
   const REQUEST_TIMEOUT_MS = 20000;
   let _isRefreshing = false;
   let _refreshPromise = null;

   /** 尝试用 HttpOnly Refresh Cookie 续期 access token（并发请求共享同一个 promise） */
   async function _tryRefresh() {
     if (_isRefreshing) return _refreshPromise;
     _isRefreshing = true;
     _refreshPromise = (async () => {
       try {
         // 不发送 Authorization header，完全依赖 HttpOnly Refresh Cookie。
         // 避免旧 token 被后端误读，以及 IP 变化导致设备指纹不匹配的问题。
         const resp = await fetch(`${API_BASE}/auth/refresh`, {
           method: 'POST',
           headers: {
             'Content-Type': 'application/json',
           },
           credentials: 'include',
         });
         if (!resp.ok) return false;
         return true;
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
      const err = new Error(data?.detail || '请求失败');
      err.status = resp.status;
      throw err;
    }
    return data;
  }

   async function streamMessageToUrl(url, payload, handlers = {}, signal) {
    const STREAM_CHUNK_TIMEOUT_MS = 30000;
    const headers = {
      'Content-Type': 'application/json',
      'X-Device-ID': AppState.getDeviceId(),
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
        const err = new Error(data?.detail || '流式请求失败');
        err.status = resp.status;
        throw err;
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      while (true) {
        let readResult;
        try {
          readResult = await Promise.race([
            reader.read(),
            new Promise((_, reject) =>
              setTimeout(() => reject(new Error('响应超时，请检查网络后重试')), STREAM_CHUNK_TIMEOUT_MS)
            ),
          ]);
        } catch (readErr) {
          reader.cancel();
          if (handlers.onError) {
            handlers.onError({ message: '响应超时，请检查网络后重试' });
          }
          throw readErr;
        }
        const { done, value } = readResult;
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
          if (event === 'error') {
            if (handlers.onError) handlers.onError(payloadData);
            const err = new Error(payloadData?.message || '流式请求失败');
            err.status = 'sse_error';
            throw err;
          }
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
    refreshToken: () => request('/auth/refresh', { method: 'POST' }),
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
    getCharacterState: (characterId) => request(`/character/state?character_id=${encodeURIComponent(characterId)}`),
    getGreetings: (characterId) => request(`/character/greetings?character_id=${encodeURIComponent(characterId)}`),
    regenerateMessage: (payload, handlers, signal) => streamMessageToUrl(`${API_BASE}/chat/regenerate`, payload, handlers, signal),
    continueMessage: (payload, handlers, signal) => streamMessageToUrl(`${API_BASE}/chat/continue`, payload, handlers, signal),

    async uploadAvatar(file) {
      const formData = new FormData();
      formData.append('file', file);
      const resp = await fetch(`${API_BASE}/user/avatar`, {
        method: 'POST',
        headers: { 'X-Device-ID': AppState.getDeviceId() },
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
