/**
 * USB thermal printer support via Web USB API.
 * Formats receipt JSON as ESC/POS and sends to USB-connected printers.
 */
(function (global) {
    const PRINTER_STORAGE_KEY = 'usb_printer_device';

    const USB_FILTERS = [
        { classCode: 7 },
        { vendorId: 0x0fe6 },
        { vendorId: 0x0483 },
        { vendorId: 0x0416 },
        { vendorId: 0x04b8 },
        { vendorId: 0x0519 },
        { vendorId: 0x154f },
        { vendorId: 0x28e9 },
        { vendorId: 0x4348 },
        { vendorId: 0x6868 },
        { vendorId: 0x1fc9 },
        { vendorId: 0x1659 },
    ];

    let usbDevice = null;
    let usbEndpoint = null;
    let usbInterfaceNumber = null;
    let currentReceipt = null;
    let lastStatusEl = null;

    function updatePrinterStatus(statusEl, text, className) {
        if (!statusEl) return;
        statusEl.innerText = text;
        statusEl.className = className;
    }

    function getDeviceLabel(device) {
        return device.productName || `USB printer (${device.vendorId.toString(16)}:${device.productId.toString(16)})`;
    }

    function saveDeviceIdentity(device) {
        localStorage.setItem(
            PRINTER_STORAGE_KEY,
            JSON.stringify({ vendorId: device.vendorId, productId: device.productId })
        );
    }

    function getSavedDeviceIdentity() {
        const raw = localStorage.getItem(PRINTER_STORAGE_KEY);
        if (!raw) return null;

        try {
            const parsed = JSON.parse(raw);
            if (parsed && parsed.vendorId != null && parsed.productId != null) {
                return parsed;
            }
        } catch (err) {
            return null;
        }

        return null;
    }

    function findBulkOutEndpoint(device) {
        if (!device.configuration) {
            throw new Error('USB printer has no active configuration.');
        }

        for (const iface of device.configuration.interfaces) {
            for (const alternate of iface.alternates) {
                const endpoint = alternate.endpoints.find(
                    (entry) => entry.direction === 'out' && entry.type === 'bulk'
                );
                if (endpoint) {
                    return {
                        interfaceNumber: iface.interfaceNumber,
                        endpointNumber: endpoint.endpointNumber,
                    };
                }
            }
        }

        throw new Error('No USB bulk OUT endpoint found on this printer.');
    }

    async function openUsbDevice(device) {
        if (!device.opened) {
            await device.open();
        }

        if (device.configuration === null) {
            await device.selectConfiguration(1);
        }

        const target = findBulkOutEndpoint(device);

        if (usbInterfaceNumber !== null && usbDevice && usbDevice.opened) {
            try {
                await usbDevice.releaseInterface(usbInterfaceNumber);
            } catch (err) {
                // Ignore release errors when switching devices.
            }
        }

        await device.claimInterface(target.interfaceNumber);

        usbDevice = device;
        usbInterfaceNumber = target.interfaceNumber;
        usbEndpoint = target.endpointNumber;
        saveDeviceIdentity(device);

        return getDeviceLabel(device);
    }

    async function connectUsbPrinter() {
        if (global.PrinterSupport) {
            global.PrinterSupport.requireSecureContext();
        } else if (!global.isSecureContext) {
            throw new Error('Web USB requires HTTPS in Chrome.');
        }

        if (!navigator.usb) {
            throw new Error('Web USB is not supported in this browser. Use Chrome or Edge over HTTPS.');
        }

        const device = await navigator.usb.requestDevice({ filters: USB_FILTERS });
        return openUsbDevice(device);
    }

    async function tryReconnectStoredPrinter(statusEl) {
        if (statusEl) {
            lastStatusEl = statusEl;
        }

        if (!navigator.usb || !navigator.usb.getDevices) {
            return false;
        }

        const saved = getSavedDeviceIdentity();
        if (!saved) {
            return false;
        }

        if (usbDevice?.opened && usbEndpoint != null
            && usbDevice.vendorId === saved.vendorId
            && usbDevice.productId === saved.productId) {
            updatePrinterStatus(
                statusEl,
                `USB connected: ${getPrinterName()}`,
                'text-xs text-emerald-600 font-semibold'
            );
            return true;
        }

        const devices = await navigator.usb.getDevices();
        const device = devices.find(
            (entry) => entry.vendorId === saved.vendorId && entry.productId === saved.productId
        );
        if (!device) {
            return false;
        }

        try {
            updatePrinterStatus(statusEl, 'Reconnecting to USB printer...', 'text-xs text-blue-600');
            const printerName = await openUsbDevice(device);
            updatePrinterStatus(
                statusEl,
                `USB connected: ${printerName}`,
                'text-xs text-emerald-600 font-semibold'
            );
            return true;
        } catch (err) {
            usbEndpoint = null;
            usbInterfaceNumber = null;
            return false;
        }
    }

    async function tryReconnectStoredPrinterWithRetries(statusEl, maxAttempts = 3, delayMs = 600) {
        for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
            const connected = await tryReconnectStoredPrinter(statusEl);
            if (connected) {
                return true;
            }

            if (attempt < maxAttempts) {
                await new Promise((resolve) => setTimeout(resolve, delayMs * attempt));
            }
        }

        if (statusEl && getSavedDeviceIdentity()) {
            updatePrinterStatus(
                statusEl,
                'USB printer not connected. Tap Connect USB Printer.',
                'text-xs text-amber-600'
            );
        }

        return false;
    }

    async function connectPrinterWithStatus(statusEl) {
        const reconnected = await tryReconnectStoredPrinter(statusEl);
        if (reconnected) {
            return getPrinterName();
        }

        updatePrinterStatus(statusEl, 'Select USB printer...', 'text-xs text-blue-600');

        const printerName = await connectUsbPrinter();

        updatePrinterStatus(
            statusEl,
            `USB connected: ${printerName}`,
            'text-xs text-emerald-600 font-semibold'
        );

        return printerName;
    }

    async function ensurePrinterConnected(statusEl) {
        if (usbDevice?.opened && usbEndpoint != null) {
            return getPrinterName();
        }

        usbEndpoint = null;

        const reconnected = await tryReconnectStoredPrinter(statusEl);
        if (reconnected) {
            return getPrinterName();
        }

        return connectPrinterWithStatus(statusEl);
    }

    async function sendEscPosData(data) {
        if (!usbDevice?.opened || usbEndpoint == null) {
            throw new Error('USB printer not connected. Tap "Connect USB Printer" first.');
        }

        const chunkSize = 16384;
        for (let i = 0; i < data.length; i += chunkSize) {
            const chunk = data.slice(i, i + chunkSize);
            const result = await usbDevice.transferOut(usbEndpoint, chunk);
            if (result.status !== 'ok') {
                throw new Error(`USB transfer failed: ${result.status}`);
            }
        }
    }

    function setCurrentReceipt(receipt) {
        currentReceipt = receipt;
    }

    function isPrinterConnected() {
        return Boolean(usbDevice?.opened && usbEndpoint != null);
    }

    function getPrinterName() {
        return usbDevice ? getDeviceLabel(usbDevice) : null;
    }

    async function printCurrentReceipt(statusEl) {
        if (!currentReceipt) {
            throw new Error('No receipt loaded. Open a receipt first.');
        }

        if (!global.EscPosReceipt) {
            throw new Error('Receipt formatter not loaded.');
        }

        updatePrinterStatus(statusEl, 'Printing via USB...', 'text-xs text-blue-600');

        await ensurePrinterConnected(statusEl);

        const data = await global.EscPosReceipt.buildEscPosReceipt(currentReceipt);
        await sendEscPosData(data);

        updatePrinterStatus(
            statusEl,
            `Printed on ${getPrinterName()}`,
            'text-xs text-emerald-600 font-semibold'
        );
    }

    if (navigator.usb) {
        navigator.usb.addEventListener('disconnect', (event) => {
            if (!usbDevice || event.device !== usbDevice) {
                return;
            }

            usbEndpoint = null;
            usbInterfaceNumber = null;
            usbDevice = null;

            if (lastStatusEl) {
                updatePrinterStatus(
                    lastStatusEl,
                    'USB printer disconnected. Reconnect to print.',
                    'text-xs text-amber-600'
                );
            }
        });
    }

    function isApiAvailable() {
        return global.PrinterSupport
            ? global.PrinterSupport.isUsbAvailable()
            : Boolean(global.isSecureContext && navigator.usb);
    }

    global.UsbPrinter = {
        setCurrentReceipt,
        connectUsbPrinter,
        connectPrinterWithStatus,
        tryReconnectStoredPrinter,
        tryReconnectStoredPrinterWithRetries,
        printCurrentReceipt,
        isPrinterConnected,
        getPrinterName,
        isApiAvailable,
    };
}(window));
