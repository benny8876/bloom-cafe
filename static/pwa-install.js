(function () {
  const config = window.PWA_CONFIG || {};
  let deferredPrompt = null;

  function isStandalone() {
    return (
      window.matchMedia('(display-mode: standalone)').matches ||
      window.navigator.standalone === true
    );
  }

  function isIos() {
    return /iphone|ipad|ipod/i.test(navigator.userAgent);
  }

  function isDismissed() {
    return localStorage.getItem(config.dismissKey) === '1';
  }

  function panelEl() {
    return document.getElementById('pwa-install-panel');
  }

  function headerBtnEl() {
    return document.getElementById('pwa-install-header-btn');
  }

  function iosStepsEl() {
    return document.getElementById('pwa-ios-steps');
  }

  function hidePanel() {
    panelEl()?.classList.add('hidden');
  }

  function showPanel() {
    if (isStandalone() || isDismissed()) {
      hidePanel();
      updateHeaderButton();
      return;
    }
    panelEl()?.classList.remove('hidden');
    updateHeaderButton();
  }

  function updateHeaderButton() {
    const btn = headerBtnEl();
    if (!btn) return;
    if (isStandalone() || isDismissed()) {
      btn.classList.add('hidden');
    } else {
      btn.classList.remove('hidden');
    }
  }

  function configureIosUi() {
    const iosSteps = iosStepsEl();
    const installBtn = document.getElementById('pwa-install-action-btn');
    if (!iosSteps || !installBtn) return;
    if (isIos() && !deferredPrompt) {
      iosSteps.classList.remove('hidden');
      installBtn.textContent = 'How to install';
    }
  }

  window.showPwaInstallPanel = function () {
    if (isStandalone()) return;
    localStorage.removeItem(config.dismissKey);
    showPanel();
    configureIosUi();
  };

  window.installPwaApp = async function () {
    if (deferredPrompt) {
      deferredPrompt.prompt();
      const choice = await deferredPrompt.userChoice;
      deferredPrompt = null;
      if (choice.outcome === 'accepted') hidePanel();
      updateHeaderButton();
      return;
    }
    iosStepsEl()?.classList.remove('hidden');
    const installBtn = document.getElementById('pwa-install-action-btn');
    if (installBtn) installBtn.textContent = 'How to install';
  };

  window.dismissPwaInstall = function () {
    localStorage.setItem(config.dismissKey, '1');
    hidePanel();
    updateHeaderButton();
  };

  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault();
    deferredPrompt = event;
    const installBtn = document.getElementById('pwa-install-action-btn');
    if (installBtn) installBtn.textContent = 'Install';
    iosStepsEl()?.classList.add('hidden');
    showPanel();
  });

  window.addEventListener('appinstalled', () => {
    deferredPrompt = null;
    hidePanel();
    updateHeaderButton();
  });

  if ('serviceWorker' in navigator && config.swPath) {
    navigator.serviceWorker
      .register(config.swPath, { scope: '/' })
      .then(() => {
        updateHeaderButton();
        if (!isStandalone() && !isDismissed()) {
          if (isIos()) {
            setTimeout(() => {
              showPanel();
              configureIosUi();
            }, 1200);
          } else if (!deferredPrompt) {
            setTimeout(updateHeaderButton, 500);
          }
        }
      })
      .catch((err) => console.warn('Service worker registration failed:', err));
  } else {
    updateHeaderButton();
  }
})();
