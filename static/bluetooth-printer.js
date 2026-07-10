/**
 * Bluetooth thermal printer support for Android Chrome (Web Bluetooth API).
 * Formats receipt JSON as ESC/POS and sends to paired BLE printers.
 */
(function (global) {
    const PRINTER_PROFILES = [
        {
            name: 'Generic BLE thermal',
            service: '000018f0-0000-1000-8000-00805f9b34fb',
            write: '00002af1-0000-1000-8000-00805f9b34fb',
        },
        {
            name: 'Nordic UART style',
            service: '6e400001-b5a3-f393-e0a9-e50e24dcca9e',
            write: '6e400002-b5a3-f393-e0a9-e50e24dcca9e',
        },
        {
            name: 'HM-10 / SPP BLE',
            service: '49535343-fe7d-4ae5-8fa7-af26b7df8e01',
            write: '49535343-fe7d-4ae5-8fa7-af26b7df8e02',
        },
    ];

    const PRINTER_ID_KEY = 'bluetooth_printer_device_id';

    let bluetoothDevice = null;
    let writeCharacteristic = null;
    let currentReceipt = null;
    let lastStatusEl = null;
    let reconnectTimer = null;
    let reconnectInFlight = false;

    async function findWritableCharacteristic(server) {
        for (const profile of PRINTER_PROFILES) {
            try {
                const service = await server.getPrimaryService(profile.service);
                const characteristic = await service.getCharacteristic(profile.write);
                return characteristic;
            } catch (err) {
                // Try the next known printer profile.
            }
        }

        const services = await server.getPrimaryServices();
        for (const service of services) {
            const characteristics = await service.getCharacteristics();
            for (const characteristic of characteristics) {
                if (characteristic.properties.write || characteristic.properties.writeWithoutResponse) {
                    return characteristic;
                }
            }
        }

        throw new Error('No writable printer characteristic found. Check that the printer supports BLE printing.');
    }

    async function connectToDevice(device) {
        if (bluetoothDevice && bluetoothDevice !== device) {
            bluetoothDevice.removeEventListener('gattserverdisconnected', onGattDisconnected);
        }

        bluetoothDevice = device;
        bluetoothDevice.removeEventListener('gattserverdisconnected', onGattDisconnected);
        bluetoothDevice.addEventListener('gattserverdisconnected', onGattDisconnected);

        const server = await bluetoothDevice.gatt.connect();
        writeCharacteristic = await findWritableCharacteristic(server);
        localStorage.setItem(PRINTER_ID_KEY, device.id);
        return bluetoothDevice.name || 'Bluetooth printer';
    }

    function scheduleAutoReconnect() {
        if (reconnectTimer || reconnectInFlight) {
            return;
        }

        if (!localStorage.getItem(PRINTER_ID_KEY)) {
            return;
        }

        reconnectTimer = setTimeout(async () => {
            reconnectTimer = null;
            reconnectInFlight = true;
            try {
                await tryReconnectStoredPrinter(lastStatusEl);
            } finally {
                reconnectInFlight = false;
            }
        }, 800);
    }

    function onGattDisconnected() {
        writeCharacteristic = null;
        if (lastStatusEl) {
            updatePrinterStatus(
                lastStatusEl,
                'Printer disconnected. Reconnecting...',
                'text-xs text-amber-600'
            );
        }
        scheduleAutoReconnect();
    }

    function updatePrinterStatus(statusEl, text, className) {
        if (!statusEl) return;
        statusEl.innerText = text;
        statusEl.className = className;
    }

    async function tryReconnectStoredPrinter(statusEl) {
        if (statusEl) {
            lastStatusEl = statusEl;
        }

        if (!navigator.bluetooth || !navigator.bluetooth.getDevices) {
            return false;
        }

        const savedId = localStorage.getItem(PRINTER_ID_KEY);
        if (!savedId) {
            return false;
        }

        if (writeCharacteristic && bluetoothDevice?.gatt?.connected && bluetoothDevice.id === savedId) {
            updatePrinterStatus(
                statusEl,
                `Connected: ${getPrinterName()}`,
                'text-xs text-emerald-600 font-semibold'
            );
            return true;
        }

        const devices = await navigator.bluetooth.getDevices();
        const device = devices.find((entry) => entry.id === savedId);
        if (!device) {
            return false;
        }

        try {
            updatePrinterStatus(statusEl, 'Reconnecting to printer...', 'text-xs text-blue-600');
            const printerName = await connectToDevice(device);
            updatePrinterStatus(
                statusEl,
                `Connected: ${printerName}`,
                'text-xs text-emerald-600 font-semibold'
            );
            return true;
        } catch (err) {
            writeCharacteristic = null;
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

        if (statusEl && localStorage.getItem(PRINTER_ID_KEY)) {
            updatePrinterStatus(
                statusEl,
                'Printer not connected. Tap Connect Bluetooth Printer.',
                'text-xs text-amber-600'
            );
        }

        return false;
    }

    async function connectBluetoothPrinter() {
        if (global.PrinterSupport) {
            global.PrinterSupport.requireSecureContext();
        } else if (!global.isSecureContext) {
            throw new Error('Web Bluetooth requires HTTPS in Chrome.');
        }

        if (!navigator.bluetooth) {
            throw new Error('Web Bluetooth is not supported in this browser. Use Chrome on Android over HTTPS.');
        }

        const optionalServices = PRINTER_PROFILES.map((profile) => profile.service);
        const device = await navigator.bluetooth.requestDevice({
            acceptAllDevices: true,
            optionalServices,
        });

        return connectToDevice(device);
    }

    async function ensurePrinterConnected(statusEl) {
        if (writeCharacteristic && bluetoothDevice?.gatt?.connected) {
            return getPrinterName();
        }

        writeCharacteristic = null;

        const reconnected = await tryReconnectStoredPrinter(statusEl);
        if (reconnected) {
            return getPrinterName();
        }

        return connectPrinterWithStatus(statusEl);
    }

    async function sendEscPosData(data) {
        if (!writeCharacteristic) {
            throw new Error('Printer not connected. Tap "Connect Printer" first.');
        }

        const chunkSize = 100;
        for (let i = 0; i < data.length; i += chunkSize) {
            const chunk = data.slice(i, i + chunkSize);
            if (writeCharacteristic.properties.writeWithoutResponse) {
                await writeCharacteristic.writeValueWithoutResponse(chunk);
            } else {
                await writeCharacteristic.writeValue(chunk);
            }
        }
    }

    function setCurrentReceipt(receipt) {
        currentReceipt = receipt;
    }

    function isPrinterConnected() {
        return Boolean(writeCharacteristic);
    }

    function getPrinterName() {
        return bluetoothDevice ? (bluetoothDevice.name || 'Bluetooth printer') : null;
    }

    async function connectPrinterWithStatus(statusEl) {
        const reconnected = await tryReconnectStoredPrinter(statusEl);
        if (reconnected) {
            return getPrinterName();
        }

        updatePrinterStatus(statusEl, 'Searching for printer...', 'text-xs text-blue-600');

        const printerName = await connectBluetoothPrinter();

        updatePrinterStatus(
            statusEl,
            `Connected: ${printerName}`,
            'text-xs text-emerald-600 font-semibold'
        );

        return printerName;
    }

    async function printCurrentReceipt(statusEl) {
        if (!currentReceipt) {
            throw new Error('No receipt loaded. Open a receipt first.');
        }

        updatePrinterStatus(statusEl, 'Printing...', 'text-xs text-blue-600');

        await ensurePrinterConnected(statusEl);

        if (!global.EscPosReceipt) {
            throw new Error('Receipt formatter not loaded.');
        }

        const data = await global.EscPosReceipt.buildEscPosReceipt(currentReceipt);
        await sendEscPosData(data);

        updatePrinterStatus(
            statusEl,
            `Printed on ${getPrinterName()}`,
            'text-xs text-emerald-600 font-semibold'
        );
    }

    function isApiAvailable() {
        return global.PrinterSupport
            ? global.PrinterSupport.isBluetoothAvailable()
            : Boolean(global.isSecureContext && navigator.bluetooth);
    }

    global.BluetoothPrinter = {
        setCurrentReceipt,
        connectBluetoothPrinter,
        connectPrinterWithStatus,
        tryReconnectStoredPrinter,
        tryReconnectStoredPrinterWithRetries,
        printCurrentReceipt,
        isPrinterConnected,
        getPrinterName,
        isApiAvailable,
    };
}(window));
