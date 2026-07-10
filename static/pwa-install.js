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

  function installButtons() {
    return [
      document.getElementById('pwa-install-header-btn'),
      document.getElementById('pwa-install-login-btn'),
    ].filter(Boolean);
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
      updateInstallButtons();
      return;
    }
    panelEl()?.classList.remove('hidden');
    updateInstallButtons();
  }

  function updateInstallButtons() {
    const show = !isStandalone() && !isDismissed();
    installButtons().forEach((btn) => {
      btn.classList.toggle('hidden', !show);
    });
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

  function refreshPwaInstallUi() {
    updateInstallButtons();
    if (!isStandalone() && !isDismissed() && isIos()) {
      configureIosUi();
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
      updateInstallButtons();
      return;
    }
    iosStepsEl()?.classList.remove('hidden');
    const installBtn = document.getElementById('pwa-install-action-btn');
    if (installBtn) installBtn.textContent = 'How to install';
  };

  window.dismissPwaInstall = function () {
    localStorage.setItem(config.dismissKey, '1');
    hidePanel();
    updateInstallButtons();
  };

  window.refreshPwaInstallUi = refreshPwaInstallUi;

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
    updateInstallButtons();
  });

  if ('serviceWorker' in navigator && config.swPath) {
    navigator.serviceWorker
      .register(config.swPath, { scope: '/' })
      .then(() => {
        refreshPwaInstallUi();
        if (!isStandalone() && !isDismissed()) {
          if (isIos()) {
            setTimeout(() => {
              showPanel();
              configureIosUi();
            }, 1200);
          } else if (!deferredPrompt) {
            setTimeout(refreshPwaInstallUi, 500);
          }
        }
      })
      .catch((err) => {
        console.warn('Service worker registration failed:', err);
        refreshPwaInstallUi();
      });
  } else {
    refreshPwaInstallUi();
  }
})();
