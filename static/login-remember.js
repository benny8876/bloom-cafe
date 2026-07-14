
(function (global) {
    const TOKEN_KEY = 'manager_token';
    const ROLE_KEY = 'manager_role';
    const USERNAME_KEY = 'manager_username';
    const REMEMBER_FLAG = 'login_remember_me';
    const CREDS_KEY = 'login_saved_creds';

    function authGet(key) {
        return localStorage.getItem(key) || sessionStorage.getItem(key);
    }

    function clearAuthKeys() {
        [TOKEN_KEY, ROLE_KEY, USERNAME_KEY].forEach((key) => {
            localStorage.removeItem(key);
            sessionStorage.removeItem(key);
        });
    }

    function getToken() {
        return authGet(TOKEN_KEY);
    }

    function getRole() {
        return authGet(ROLE_KEY);
    }

    function getUsername() {
        return authGet(USERNAME_KEY);
    }

    function setSession(data, remember, username, password) {
        clearAuthKeys();
        const store = remember ? localStorage : sessionStorage;
        store.setItem(TOKEN_KEY, data.token);
        store.setItem(ROLE_KEY, data.role || 'manager');
        store.setItem(USERNAME_KEY, data.username || username || '');

        if (remember) {
            localStorage.setItem(REMEMBER_FLAG, '1');
            localStorage.setItem(
                CREDS_KEY,
                JSON.stringify({
                    u: username || data.username || '',
                    p: password || '',
                })
            );
        } else {
            localStorage.removeItem(REMEMBER_FLAG);
            localStorage.removeItem(CREDS_KEY);
        }
    }

    function clearSession() {
        clearAuthKeys();
    }

    function isRememberEnabled() {
        return localStorage.getItem(REMEMBER_FLAG) === '1';
    }

    function loadSavedCredentials() {
        if (!isRememberEnabled()) return null;
        try {
            const raw = localStorage.getItem(CREDS_KEY);
            if (!raw) return null;
            const parsed = JSON.parse(raw);
            if (!parsed || typeof parsed !== 'object') return null;
            return {
                username: parsed.u || '',
                password: parsed.p || '',
            };
        } catch {
            return null;
        }
    }

    function fillLoginForm(usernameId, passwordId, checkboxId) {
        const creds = loadSavedCredentials();
        const checkbox = document.getElementById(checkboxId);
        const userEl = document.getElementById(usernameId);
        const passEl = document.getElementById(passwordId);
        if (checkbox) checkbox.checked = Boolean(creds);
        if (creds && userEl) userEl.value = creds.username;
        if (creds && passEl) passEl.value = creds.password;
    }

    global.LoginRemember = {
        getToken,
        getRole,
        getUsername,
        setSession,
        clearSession,
        isRememberEnabled,
        loadSavedCredentials,
        fillLoginForm,
        TOKEN_KEY,
        ROLE_KEY,
        USERNAME_KEY,
    };
}(window));
