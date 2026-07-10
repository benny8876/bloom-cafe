/**
 * Shared ESC/POS receipt formatting for thermal printers.
 */
(function (global) {
    const ESC = '\x1B';
    const GS = '\x1D';
    const LINE_WIDTH = 32;

    function padLine(left, right) {
        const leftText = String(left);
        const rightText = String(right);
        const spaces = Math.max(1, LINE_WIDTH - leftText.length - rightText.length);
        return leftText + ' '.repeat(spaces) + rightText + '\n';
    }

    function center(text) {
        const value = String(text);
        const padding = Math.max(0, Math.floor((LINE_WIDTH - value.length) / 2));
        return ' '.repeat(padding) + value + '\n';
    }

    function dashedLine() {
        return '-'.repeat(LINE_WIDTH) + '\n';
    }

    function formatMoney(amount) {
        return `${Number(amount).toFixed(0)} Ks`;
    }

    function buildEscPosReceipt(receipt) {
        let out = '';
        out += ESC + '@';
        out += ESC + 'a' + '\x01';

        const title = receipt.restaurant_name || 'BLOOM CAFÉ';
        out += center(title);

        if (receipt.voucher_id) {
            out += center(receipt.voucher_id);
        } else if (receipt.order_ids && receipt.order_ids.length) {
            out += center('TABLE SESSION INVOICE');
        }

        if (receipt.timestamp) {
            out += center(receipt.timestamp);
        }

        out += ESC + 'a' + '\x00';
        out += dashedLine();
        out += `Table: ${receipt.table_number}\n`;

        if (receipt.order_ids && receipt.order_ids.length) {
            out += `Orders: ${receipt.order_ids.map((id) => `#${id}`).join(', ')}\n`;
        }

        out += dashedLine();

        (receipt.items || []).forEach((item) => {
            const subtotal = item.subtotal != null
                ? item.subtotal
                : item.quantity * item.unit_price;
            out += padLine(`${item.name} x${item.quantity}`, formatMoney(subtotal));

            const mods = item.modifiers || [];
            mods.forEach((mod) => {
                const modName = typeof mod === 'string' ? mod : mod.name;
                if (modName) {
                    out += `  + ${modName}\n`;
                }
            });
        });

        out += ESC + 'E' + '\x01';
        const billTotal = receipt.grand_total != null ? receipt.grand_total : receipt.subtotal;
        out += padLine('TOTAL', formatMoney(billTotal));
        out += ESC + 'E' + '\x00';
        out += dashedLine();

        if (receipt.status) {
            out += `Status: ${receipt.status}\n`;
        }

        out += ESC + 'a' + '\x01';
        out += '\nThank You For Supporting\n';
        out += center(receipt.restaurant_name || 'BLOOM CAFÉ');
        out += '\n\n\n';
        out += GS + 'V' + '\x00';

        return new TextEncoder().encode(out);
    }

    global.EscPosReceipt = {
        buildEscPosReceipt,
    };
}(window));
