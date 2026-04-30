(() => {
  function resolveApiBase({ admin = false } = {}) {
    const { protocol, hostname, port } = location;
    const isBackendOrigin = port === '8000' || port === '' || port === '443' || port === '80';
    if (isBackendOrigin) {
      const origin = `${protocol}//${hostname}${port ? ':' + port : ''}`;
      return admin ? `${origin}/api/admin` : `${origin}/api`;
    }
    if (admin) {
      return `${protocol}//${hostname}:8000/api/admin`;
    }
    return `${protocol}//${hostname}:8000/api`;
  }

  window.AIFriendShared = {
    STORAGE_KEYS: {
      TOKEN_KEY: 'aifriend_token',
      USER_KEY: 'aifriend_user',
    },
    resolveApiBase,
  };
})();
