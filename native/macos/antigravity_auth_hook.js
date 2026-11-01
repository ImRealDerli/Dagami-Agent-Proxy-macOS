;(() => {
  const marker = 'dagami-auth-route-v1';
  const electron = require('electron');
  const original = electron.shell.openExternal.bind(electron.shell);
  const opened = new Set();
  electron.shell.openExternal = async (url, ...options) => {
    let parsed;
    try { parsed = new URL(url); } catch { return original(url, ...options); }
    const hosts = new Set(['accounts.google.com', 'antigravity.google', 'antigravity.google.com']);
    if (parsed.protocol !== 'https:' || !hosts.has(parsed.hostname) || !/auth|login|signin|oauth/i.test(parsed.pathname)) return original(url, ...options);
    if (parsed.hostname === 'accounts.google.com' && !['/o/oauth2/auth', '/o/oauth2/v2/auth'].includes(parsed.pathname)) {
      electron.dialog.showErrorBox('Dagami', 'Это промежуточная страница Google. Начните новую попытку входа в Antigravity; нужен исходный OAuth-запрос клиента.');
      return;
    }
    const port = Number(process.env.DAGAMI_AUTH_PORT);
    const token = process.env.DAGAMI_AUTH_TOKEN || '';
    if (!Number.isInteger(port) || port < 1 || port > 65535 || !/^[a-f0-9]{64}$/.test(token)) {
      electron.dialog.showErrorBox('Dagami', 'Запустите Antigravity через Dagami для входа через выбранный профиль.');
      return;
    }
    if (opened.has(url)) return;
    opened.add(url);
    try {
      await new Promise((resolve, reject) => {
        const body = JSON.stringify({command: 'login', url});
        const req = require('http').request({hostname: '127.0.0.1', port, path: '/', method: 'POST', headers: {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body)}}, res => {
          let body = '';
          res.on('data', chunk => { if (body.length < 8192) body += chunk.toString(); });
          res.on('end', () => {
            if (res.statusCode === 200) return resolve();
            let reason = 'Login route rejected: HTTP ' + res.statusCode;
            try { reason = JSON.parse(body).error || reason; } catch {}
            reject(new Error(reason));
          });
        });
        req.setTimeout(15000, () => req.destroy(new Error('Login route timeout')));
        req.on('error', reject);
        req.end(body);
      });
    } catch (error) {
      opened.delete(url);
      electron.dialog.showErrorBox('Dagami', String(error.message || 'Не удалось открыть вход через профиль.').slice(0, 1200));
    }
  };
})();
