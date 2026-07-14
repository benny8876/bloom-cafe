/**
 * Kitchen display EN / MM UI strings.
 * Item names keep their original Myanmar / English / Chinese text;
 * Noto Sans Myanmar + SC fonts handle rendering.
 */
(function (global) {
    const LANG_KEY = 'kitchen_lang';

    const STRINGS = {
        en: {
            'lang.en': 'EN',
            'lang.mm': 'MM',
            'login.subtitle': 'Kitchen — enter staff PIN to view and manage orders.',
            'login.pin_placeholder': 'Kitchen PIN',
            'login.unlock': 'Unlock Kitchen Panel',
            'login.invalid_pin': 'Invalid PIN. Please try again.',
            'login.connection_failed': 'Connection failed. Please retry.',
            'header.logout': 'Logout',
            'header.audio_hint': 'Click anywhere to enable alert sounds',
            'header.audio_hint_short': 'Tap to enable sounds',
            'header.connecting': 'Connecting...',
            'header.live': 'Live',
            'header.offline': 'Offline',
            'col.pending': 'Pending',
            'col.preparing': 'Preparing',
            'col.served': 'Served / Ready',
            'btn.cancel': 'Cancel',
            'btn.mark_ready': 'Mark Ready',
            'btn.dismiss': 'Dismiss',
            'table.label': 'Table {label}',
            'table.counter': 'Counter',
            'alert.new_order': 'NEW ORDER!',
            'alert.new_order_table': 'NEW ORDER — Table {table}!',
            'notify.new_title': 'New Kitchen Order',
            'notify.new_body': 'A new order just arrived.',
            'notify.new_body_table': 'Table {table} placed a new order.',
            'notify.service_title': 'Guest needs help',
            'confirm.cancel_order': 'Cancel this order? Stock will be restored.',
            'error.cancel_fail': 'Could not cancel order.',
            'station.coffee.title': 'Coffee Bar Display',
            'station.coffee.subtitle': 'Drinks and coffee orders',
            'station.coffee.ready': '✓ Drinks Ready for Pickup',
            'station.coffee.start': 'Start Preparing',
            'station.food.title': 'Food Kitchen Display',
            'station.food.subtitle': 'Food orders monitor',
            'station.food.ready': '✓ Food Delivered to Table',
            'station.food.start': 'Start Cooking',
            'station.login_pin': 'Enter staff PIN to open the {title}.',
            'default.title': 'BLOOM CAFÉ Kitchen',
            'default.subtitle': 'Paid and validated orders monitor',
        },
        mm: {
            'lang.en': 'EN',
            'lang.mm': 'MM',
            'login.subtitle': 'မီးဖိုချောင် — အော်ဒါကြည့်ရန် ဝန်ထမ်း PIN ထည့်ပါ',
            'login.pin_placeholder': 'မီးဖိုချောင် PIN',
            'login.unlock': 'မီးဖိုချောင် ဖွင့်မည်',
            'login.invalid_pin': 'PIN မှားနေသည်။ ထပ်စမ်းပါ',
            'login.connection_failed': 'ချိတ်ဆက်မှု မအောင်မြင်ပါ။ ထပ်စမ်းပါ',
            'header.logout': 'ထွက်မည်',
            'header.audio_hint': 'အသံဖွင့်ရန် နေရာမရွေး နှိပ်ပါ',
            'header.audio_hint_short': 'အသံဖွင့်ရန် နှိပ်ပါ',
            'header.connecting': 'ချိတ်ဆက်နေသည်...',
            'header.live': 'အသက်ဝင်',
            'header.offline': 'အော့ဖ်လိုင်း',
            'col.pending': 'စောင့်ဆိုင်း',
            'col.preparing': 'ပြင်ဆင်နေ',
            'col.served': 'ပြီး / အဆင်သင့်',
            'btn.cancel': 'ပယ်ဖျက်',
            'btn.mark_ready': 'အဆင်သင့်',
            'btn.dismiss': 'ပိတ်မည်',
            'table.label': 'စားပွဲ {label}',
            'table.counter': 'ကောင်တာ',
            'alert.new_order': 'အော်ဒါအသစ်!',
            'alert.new_order_table': 'အော်ဒါအသစ် — စားပွဲ {table}!',
            'notify.new_title': 'မီးဖိုချောင် အော်ဒါအသစ်',
            'notify.new_body': 'အော်ဒါအသစ် ရောက်လာပါပြီ',
            'notify.new_body_table': 'စားပွဲ {table} အော်ဒါတင်ပါပြီ',
            'notify.service_title': 'ဧည့်သည် အကူအညီလိုသည်',
            'confirm.cancel_order': 'ဤအော်ဒါကို ပယ်ဖျက်မလား? ကုန်ပစ္စည်း ပြန်ထည့်ပါမည်',
            'error.cancel_fail': 'အော်ဒါ ပယ်ဖျက်မရပါ',
            'station.coffee.title': 'ကော်ဖီဘား မျက်နှာပြင်',
            'station.coffee.subtitle': 'အဖျော်ယမကာနှင့် ကော်ဖီ အော်ဒါများ',
            'station.coffee.ready': '✓ ယူဆောင်ရန် အဆင်သင့်',
            'station.coffee.start': 'ပြင်ဆင် စတင်',
            'station.food.title': 'အစား မီးဖိုချောင် မျက်နှာပြင်',
            'station.food.subtitle': 'အစားအော်ဒါ စောင့်ကြည့်',
            'station.food.ready': '✓ စားပွဲသို့ ပို့ပြီး',
            'station.food.start': 'ချက်ပြုတ် စတင်',
            'station.login_pin': '{title} ဖွင့်ရန် ဝန်ထမ်း PIN ထည့်ပါ',
            'default.title': 'BLOOM CAFÉ မီးဖိုချောင်',
            'default.subtitle': 'ငွေပေးပြီး အတည်ပြုထားသော အော်ဒါများ',
        },
    };

    function getLang() {
        const saved = localStorage.getItem(LANG_KEY);
        return saved === 'mm' ? 'mm' : 'en';
    }

    function interpolate(template, vars) {
        if (!vars) return template;
        return template.replace(/\{(\w+)\}/g, (_, key) => (
            vars[key] != null ? String(vars[key]) : `{${key}}`
        ));
    }

    function t(key, vars) {
        const lang = getLang();
        const text = STRINGS[lang][key] ?? STRINGS.en[key] ?? key;
        return interpolate(text, vars);
    }

    function updateLangSwitchButtons() {
        const lang = getLang();
        document.querySelectorAll('[data-lang-btn]').forEach((btn) => {
            const active = btn.getAttribute('data-lang-btn') === lang;
            btn.classList.toggle('lang-switch-btn--active', active);
            btn.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
    }

    function apply() {
        document.querySelectorAll('[data-i18n]').forEach((el) => {
            el.textContent = t(el.getAttribute('data-i18n'));
        });
        document.querySelectorAll('[data-i18n-placeholder]').forEach((el) => {
            el.placeholder = t(el.getAttribute('data-i18n-placeholder'));
        });
        document.documentElement.lang = getLang() === 'mm' ? 'my' : 'en';
        updateLangSwitchButtons();
    }

    function setLang(lang) {
        localStorage.setItem(LANG_KEY, lang === 'mm' ? 'mm' : 'en');
        apply();
        if (typeof global.onKitchenLanguageChange === 'function') {
            global.onKitchenLanguageChange(getLang());
        }
    }

    global.KitchenI18n = { t, getLang, setLang, apply };
}(window));
