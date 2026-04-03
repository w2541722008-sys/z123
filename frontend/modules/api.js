 const API = (() => {
   const REQUEST_TIMEOUT_MS = 20000;

  async function request(path, options = {}) {
    const headers = {
      'Content-Type': 'application/json',
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
       });
     } catch (err) {
       if (err.name === 'AbortError') throw new Error('请求超时，请检查网络后重试');
       throw err;
     } finally {
       clearTimeout(timer);
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
    const resp = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(payload),
      signal,
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
           if (line.startsWith('data: ')) dataLine += line.slice(6);
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
    getCharacters: async () => (await request('/characters')).map(normalizeCharacterCardPayload),
    getHistory: (characterId) => request(`/chat/history?character_id=${encodeURIComponent(characterId)}`),
    getCharacterProfile: (characterId) => request(`/character/profile?character_id=${encodeURIComponent(characterId)}`),
    updateCharacterProfile: (payload) => request('/character/profile', { method: 'POST', body: payload }),
    // 清空聊天并指定剧情线（greeting_index: -1=默认，>=1=alternate_greetings 对应下标）
    clearChatWithGreeting: (payload) => request('/chat/clear', { method: 'POST', body: payload }),
    sendMessage: (payload) => request('/chat/send', { method: 'POST', body: payload }),
    streamMessage,
    // 游客试聊流式接口（不需要 token）
    guestStreamMessage: (payload, handlers, signal) => streamMessageToUrl(`${API_BASE}/chat/guest-stream`, payload, handlers, signal),
    getGuestQuota: () => request('/chat/guest-quota'),
    // 关系状态
    getCharacterState: (characterId) => request(`/character/state?character_id=${encodeURIComponent(characterId)}`),
    // 获取角色所有开场白选项（含 alternate_greetings）
   getGreetings: (characterId) => request(`/character/greetings?character_id=${encodeURIComponent(characterId)}`),
  // Regenerate / Continue 功能
  regenerateMessage: (payload, handlers, signal) => streamMessageToUrl(`${API_BASE}/chat/regenerate`, payload, handlers, signal),
  continueMessage: (payload, handlers, signal) => streamMessageToUrl(`${API_BASE}/chat/continue`, payload, handlers, signal),

  // 头像上传（FormData，非 JSON）
  async uploadAvatar(file) {
    const token = AppState.getToken();
    if (!token) throw new Error('请先登录');
    const formData = new FormData();
    formData.append('file', file);
    const resp = await fetch(`${API_BASE}/user/avatar`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: formData,
    });
    let data = null;
    try { data = await resp.json(); } catch (_) { data = null; }
    if (!resp.ok) throw new Error(data?.detail || '上传失败');
    return data;
  },
 };
 })();
