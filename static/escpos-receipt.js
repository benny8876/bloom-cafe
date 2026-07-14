
(function (global) {
    const ESC = '\x1B';
    const GS = '\x1D';
    const LINE_WIDTH = 48;
    const RASTER_WIDTH = 576;
    const LOGO_URL = '/static/bloom-logo.png';
    const RECEIPT_FONTS_URL =
        'https://fonts.googleapis.com/css2?family=Noto+Sans+Myanmar:wght@400;700&family=Noto+Sans+SC:wght@400;700&display=swap';
    const TEXT_FONT =
        '"Noto Sans Myanmar", "Noto Sans SC", "Myanmar Text", "PingFang SC", "Microsoft YaHei", Padauk, "Pyidaungsu", sans-serif';

    const THANKS_LINE = 'အားပေးမှုအတွက် အထူးကျေးဇူးတင်ပါသည်';
    const ADDRESS_LINES = [
        'မူဆယ်မြို့ ၊ Royal Muse, ဆီဆိုင်ရှေ့ မြို့ပါတ်လမ်း',
        'ဖုန်း - 09693820039 / 09-66419274',
        'ကောင်းမှုတုံရပ်ကွက်',
    ];

    let logoImagePromise = null;
    let fontsReadyPromise = null;

    function dashedLine() {
        return '-'.repeat(LINE_WIDTH) + '\n';
    }

    function formatMoney(amount) {
        return `${Number(amount).toFixed(0)} Ks`;
    }

    function ensureReceiptFonts() {
        if (!fontsReadyPromise) {
            fontsReadyPromise = (async () => {
                if (!document.getElementById('escpos-receipt-fonts')) {
                    const link = document.createElement('link');
                    link.id = 'escpos-receipt-fonts';
                    link.rel = 'stylesheet';
                    link.href = RECEIPT_FONTS_URL;
                    document.head.appendChild(link);
                    await new Promise((resolve) => {
                        link.onload = () => resolve();
                        link.onerror = () => resolve();
                        setTimeout(resolve, 1200);
                    });
                }
                if (document.fonts && document.fonts.load) {
                    await Promise.all([
                        document.fonts.load('400 22px "Noto Sans Myanmar"'),
                        document.fonts.load('700 22px "Noto Sans Myanmar"'),
                        document.fonts.load('400 22px "Noto Sans SC"'),
                        document.fonts.load('700 22px "Noto Sans SC"'),
                    ]).catch(() => {});
                    await document.fonts.ready;
                }
            })();
        }
        return fontsReadyPromise;
    }

    function loadLogoImage() {
        if (!logoImagePromise) {
            logoImagePromise = new Promise((resolve, reject) => {
                const img = new Image();
                img.onload = () => resolve(img);
                img.onerror = () => reject(new Error('Could not load logo'));
                img.src = LOGO_URL;
            }).catch(() => null);
        }
        return logoImagePromise;
    }

    function canvasToEscPosRaster(canvas) {
        const width = canvas.width;
        const height = canvas.height;
        const ctx = canvas.getContext('2d');
        const imageData = ctx.getImageData(0, 0, width, height);
        const bytesPerRow = Math.ceil(width / 8);
        const data = new Uint8Array(bytesPerRow * height);

        for (let y = 0; y < height; y++) {
            for (let x = 0; x < width; x++) {
                const i = (y * width + x) * 4;
                const r = imageData.data[i];
                const g = imageData.data[i + 1];
                const b = imageData.data[i + 2];
                const a = imageData.data[i + 3];
                const luminance = 0.299 * r + 0.587 * g + 0.114 * b;
                if (a > 128 && luminance < 200) {
                    data[y * bytesPerRow + (x >> 3)] |= 0x80 >> (x & 7);
                }
            }
        }

        const xL = bytesPerRow & 0xff;
        const xH = (bytesPerRow >> 8) & 0xff;
        const yL = height & 0xff;
        const yH = (height >> 8) & 0xff;

        const header = new Uint8Array([0x1d, 0x76, 0x30, 0x00, xL, xH, yL, yH]);
        const out = new Uint8Array(header.length + data.length);
        out.set(header, 0);
        out.set(data, header.length);
        return out;
    }

    function wrapLine(ctx, text, maxWidth) {
        const value = String(text || '').trim();
        if (!value) return [];
        if (ctx.measureText(value).width <= maxWidth) return [value];

        const parts = value.split(/(\s+)/).filter((p) => p.length);
        const lines = [];
        let current = '';

        parts.forEach((part) => {
            const trial = current + part;
            if (current && ctx.measureText(trial).width > maxWidth) {
                lines.push(current.trim());
                current = part.trimStart();
            } else {
                current = trial;
            }
        });
        if (current.trim()) lines.push(current.trim());

        const finalLines = [];
        lines.forEach((line) => {
            if (ctx.measureText(line).width <= maxWidth) {
                finalLines.push(line);
                return;
            }
            let chunk = '';
            for (const ch of line) {
                const trial = chunk + ch;
                if (chunk && ctx.measureText(trial).width > maxWidth) {
                    finalLines.push(chunk);
                    chunk = ch;
                } else {
                    chunk = trial;
                }
            }
            if (chunk) finalLines.push(chunk);
        });
        return finalLines;
    }

    function makeCanvasContext(fontSize, bold) {
        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d');
        ctx.font = `${bold ? 'bold ' : ''}${fontSize}px ${TEXT_FONT}`;
        return { canvas, ctx };
    }

    function buildCenteredTextRaster(lines, options = {}) {
        const fontSize = options.fontSize || 22;
        const bold = options.bold !== false;
        const lineHeight = options.lineHeight || Math.round(fontSize * 1.5);
        const paddingY = options.paddingY ?? 8;
        const maxTextWidth = RASTER_WIDTH - 24;

        const { ctx } = makeCanvasContext(fontSize, bold);
        const wrapped = [];
        (lines || []).forEach((line) => {
            wrapLine(ctx, line, maxTextWidth).forEach((w) => wrapped.push(w));
        });
        if (!wrapped.length) return new Uint8Array(0);

        const width = RASTER_WIDTH;
        const height = paddingY * 2 + wrapped.length * lineHeight;
        const canvas = document.createElement('canvas');
        const drawCtx = canvas.getContext('2d');
        canvas.width = width;
        canvas.height = height;

        drawCtx.fillStyle = '#ffffff';
        drawCtx.fillRect(0, 0, width, height);
        drawCtx.fillStyle = '#000000';
        drawCtx.font = `${bold ? 'bold ' : ''}${fontSize}px ${TEXT_FONT}`;
        drawCtx.textAlign = 'center';
        drawCtx.textBaseline = 'middle';

        wrapped.forEach((line, index) => {
            const y = paddingY + lineHeight * index + lineHeight / 2;
            drawCtx.fillText(line, width / 2, y);
        });

        return canvasToEscPosRaster(canvas);
    }

    function buildLeftTextRaster(text, options = {}) {
        const fontSize = options.fontSize || 22;
        const bold = options.bold || false;
        const lineHeight = options.lineHeight || Math.round(fontSize * 1.35);
        const paddingY = options.paddingY ?? 3;
        const paddingX = options.paddingX ?? 8;
        const maxTextWidth = RASTER_WIDTH - paddingX * 2;

        const { ctx } = makeCanvasContext(fontSize, bold);
        const lines = wrapLine(ctx, text, maxTextWidth);
        if (!lines.length) return new Uint8Array(0);

        const width = RASTER_WIDTH;
        const height = paddingY * 2 + lines.length * lineHeight;
        const canvas = document.createElement('canvas');
        const drawCtx = canvas.getContext('2d');
        canvas.width = width;
        canvas.height = height;

        drawCtx.fillStyle = '#ffffff';
        drawCtx.fillRect(0, 0, width, height);
        drawCtx.fillStyle = '#000000';
        drawCtx.font = `${bold ? 'bold ' : ''}${fontSize}px ${TEXT_FONT}`;
        drawCtx.textAlign = 'left';
        drawCtx.textBaseline = 'middle';

        lines.forEach((line, index) => {
            const y = paddingY + lineHeight * index + lineHeight / 2;
            drawCtx.fillText(line, paddingX, y);
        });

        return canvasToEscPosRaster(canvas);
    }

    function buildLeftRightRaster(left, right, options = {}) {
        const fontSize = options.fontSize || 22;
        const bold = options.bold || false;
        const lineHeight = options.lineHeight || Math.round(fontSize * 1.35);
        const paddingY = options.paddingY ?? 3;
        const paddingX = options.paddingX ?? 8;
        const width = RASTER_WIDTH;

        const { ctx } = makeCanvasContext(fontSize, bold);
        const rightText = String(right);
        const rightWidth = ctx.measureText(rightText).width;
        const leftMaxWidth = Math.max(40, width - paddingX * 2 - rightWidth - 10);
        const leftLines = wrapLine(ctx, String(left), leftMaxWidth);
        if (!leftLines.length) leftLines.push('');

        const height = paddingY * 2 + leftLines.length * lineHeight;
        const canvas = document.createElement('canvas');
        const drawCtx = canvas.getContext('2d');
        canvas.width = width;
        canvas.height = height;

        drawCtx.fillStyle = '#ffffff';
        drawCtx.fillRect(0, 0, width, height);
        drawCtx.fillStyle = '#000000';
        drawCtx.font = `${bold ? 'bold ' : ''}${fontSize}px ${TEXT_FONT}`;
        drawCtx.textBaseline = 'middle';

        leftLines.forEach((line, index) => {
            const y = paddingY + lineHeight * index + lineHeight / 2;
            drawCtx.textAlign = 'left';
            drawCtx.fillText(line, paddingX, y);
            if (index === 0) {
                drawCtx.textAlign = 'right';
                drawCtx.fillText(rightText, width - paddingX, y);
            }
        });

        return canvasToEscPosRaster(canvas);
    }

    async function buildLogoTitleRaster() {
        const logo = await loadLogoImage();
        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d');

        const width = RASTER_WIDTH;
        const height = 100;
        canvas.width = width;
        canvas.height = height;

        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, width, height);

        const logoSize = 70;
        const gap = 12;
        const title = 'BLOOM CAFE';
        ctx.font = 'bold 42px Arial, Helvetica, sans-serif';
        const textWidth = ctx.measureText(title).width;
        const blockWidth = (logo ? logoSize + gap : 0) + textWidth;
        let x = Math.max(0, Math.floor((width - blockWidth) / 2));
        const yMid = Math.floor(height / 2);

        if (logo) {
            ctx.drawImage(logo, x, yMid - logoSize / 2, logoSize, logoSize);
            x += logoSize + gap;
        }

        ctx.fillStyle = '#000000';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'middle';
        ctx.fillText(title, x, yMid);

        return canvasToEscPosRaster(canvas);
    }

    function concatBytes(chunks) {
        const filtered = chunks.filter((c) => c && c.length);
        const total = filtered.reduce((sum, c) => sum + c.length, 0);
        const out = new Uint8Array(total);
        let offset = 0;
        filtered.forEach((chunk) => {
            out.set(chunk, offset);
            offset += chunk.length;
        });
        return out;
    }

    function encodeText(str) {
        return new TextEncoder().encode(str);
    }

    async function buildEscPosReceipt(receipt) {
        await ensureReceiptFonts();

        const chunks = [];

        chunks.push(encodeText(ESC + '@'));
        chunks.push(encodeText(ESC + 'a' + '\x01'));

        try {
            chunks.push(await buildLogoTitleRaster());
        } catch (err) {
            chunks.push(buildCenteredTextRaster(
                [receipt.restaurant_name || 'BLOOM CAFE'],
                { fontSize: 36, bold: true, lineHeight: 44 }
            ));
        }

        chunks.push(buildCenteredTextRaster([THANKS_LINE], {
            fontSize: 20,
            bold: true,
            lineHeight: 30,
            paddingY: 6,
        }));

        const metaLines = [];
        if (receipt.voucher_id) {
            metaLines.push(String(receipt.voucher_id));
        } else if (receipt.order_ids && receipt.order_ids.length) {
            metaLines.push('TABLE SESSION INVOICE');
        }
        if (receipt.timestamp) {
            metaLines.push(String(receipt.timestamp));
        }
        if (metaLines.length) {
            chunks.push(buildCenteredTextRaster(metaLines, {
                fontSize: 18,
                bold: true,
                lineHeight: 26,
                paddingY: 4,
            }));
        }

        chunks.push(encodeText(ESC + 'a' + '\x00'));
        chunks.push(encodeText(dashedLine()));
        chunks.push(buildLeftTextRaster(`Table: ${receipt.table_number}`, { fontSize: 22, bold: true }));

        if (receipt.order_ids && receipt.order_ids.length) {
            chunks.push(buildLeftTextRaster(
                `Orders: ${receipt.order_ids.map((id) => `#${id}`).join(', ')}`,
                { fontSize: 20 }
            ));
        }

        chunks.push(encodeText(dashedLine()));

        (receipt.items || []).forEach((item) => {
            const subtotal = item.subtotal != null
                ? item.subtotal
                : item.quantity * item.unit_price;
            chunks.push(buildLeftRightRaster(
                `${item.name} x${item.quantity}`,
                formatMoney(subtotal),
                { fontSize: 22, bold: true }
            ));

            const mods = item.modifiers || [];
            mods.forEach((mod) => {
                const modName = typeof mod === 'string' ? mod : mod.name;
                if (modName) {
                    chunks.push(buildLeftTextRaster(`+ ${modName}`, {
                        fontSize: 20,
                        bold: true,
                        paddingX: 28,
                    }));
                }
            });
        });

        chunks.push(encodeText(dashedLine()));
        const subtotal = receipt.subtotal != null
            ? receipt.subtotal
            : (receipt.grand_total != null ? receipt.grand_total : 0);
        const discountAmount = receipt.discount_amount || 0;
        const discountPercent = receipt.discount_percent || 0;
        if (discountAmount > 0) {
            chunks.push(buildLeftRightRaster('SUBTOTAL', formatMoney(subtotal), { fontSize: 22, bold: true }));
            chunks.push(buildLeftRightRaster(
                `DISCOUNT (${discountPercent}%)`,
                `-${formatMoney(discountAmount)}`,
                { fontSize: 22, bold: true }
            ));
        }
        chunks.push(buildLeftRightRaster(
            'TOTAL',
            formatMoney(receipt.grand_total != null ? receipt.grand_total : subtotal),
            { fontSize: 24, bold: true, lineHeight: 32, paddingY: 4 }
        ));
        chunks.push(encodeText(dashedLine()));

        if (receipt.status) {
            chunks.push(buildLeftTextRaster(`Status: ${receipt.status}`, { fontSize: 20 }));
        }

        chunks.push(encodeText(ESC + 'a' + '\x01'));
        chunks.push(buildCenteredTextRaster(ADDRESS_LINES, {
            fontSize: 17,
            bold: true,
            lineHeight: 24,
            paddingY: 4,
        }));

        chunks.push(encodeText('\n'));
        chunks.push(encodeText(GS + 'V' + '\x00'));

        return concatBytes(chunks);
    }

    global.EscPosReceipt = {
        buildEscPosReceipt,
    };
}(window));
