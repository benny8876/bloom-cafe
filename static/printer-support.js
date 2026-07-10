/**
 * Shared helpers for Web Bluetooth / Web USB printer APIs (secure context required).
 */
(function (global) {
    function isSecureContext() {
        return global.isSecureContext === true;
    }

    function getHttpsUrl() {
        const port = global.location.port;
        const portSuffix = port ? `:${port}` : '';
        return `https://${global.location.hostname}${portSuffix}${global.location.pathname}`;
    }

    function getSecureContextError() {
        if (isSecureContext()) {
            return null;
        }

        return `Printer APIs require HTTPS in Chrome. Open ${getHttpsUrl()} instead of ${global.location.href}.`;
    }

    function requireSecureContext() {
        const message = getSecureContextError();
        if (message) {
            throw new Error(message);
        }
    }

    function isUsbAvailable() {
        return isSecureContext() && Boolean(global.navigator.usb);
    }

    function isBluetoothAvailable() {
        return isSecureContext() && Boolean(global.navigator.bluetooth);
    }

    global.PrinterSupport = {
        isSecureContext,
        getHttpsUrl,
        getSecureContextError,
        requireSecureContext,
        isUsbAvailable,
        isBluetoothAvailable,
    };
}(window));
