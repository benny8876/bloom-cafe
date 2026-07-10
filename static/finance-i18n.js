/**
 * Finance panel English / Myanmar translations.
 * Shares language preference with Manager (manager_lang).
 */
(function (global) {
    const LANG_KEY = 'manager_lang';

    const STRINGS = {
        en: {
            'theme.dark': 'Dark',
            'theme.light': 'Light',
            'common.password': 'Password',
            'common.logout': 'Logout',
            'common.username': 'Username',
            'common.date': 'Date',
            'common.edit': 'Edit',
            'common.delete': 'Delete',
            'common.table': 'Table',
            'common.orders': 'Orders',
            'common.install_app': 'Install app',
            'common.not_now': 'Not now',
            'pwa.title': 'Install Finance on your phone',
            'pwa.subtitle': 'Add to home screen for quick owner access.',
            'pwa.install': 'Install',
            'login.hint': 'Owner login — income & expenses',
            'login.submit': 'Sign In',
            'login.remember': 'Remember me',
            'access.title': 'Owner access only',
            'access.body': 'Finance is restricted to the shop owner account (admin). Floor managers should use Operations at /manager.',
            'access.go_ops': 'Go to Operations',
            'access.sign_out': 'Sign out',
            'app.subtitle': 'Income, outcome & net profit',
            'nav.operations': 'Operations →',
            'range.day': 'Day',
            'range.week': 'Week',
            'range.month': 'Month',
            'range.custom': 'Custom range',
            'export.today': 'Today',
            'export.week': 'Week',
            'export.month': 'Month',
            'btn.add_expense': '+ Expense',
            'btn.add_expense_soft': '+ Add Expense',
            'stats.income': 'Income (Sales)',
            'stats.outcome': 'Outcome (Expenses)',
            'stats.net_day': 'Net Profit (Day)',
            'stats.net_week': 'Net Profit (Week)',
            'stats.net_month': 'Net Profit (Month)',
            'stats.net_period': 'Net Profit (Period)',
            'stats.net_sub': 'Income minus outcome',
            'stats.month_net': '{month} Net',
            'stats.month_sub': 'Monthly income vs expenses',
            'stats.income_sub': '{tables} table · {orders} order',
            'stats.income_sub_plural': '{tables} tables · {orders} orders',
            'stats.outcome_sub': '{count} expense',
            'stats.outcome_sub_plural': '{count} expenses',
            'stats.outcome_today': '{count} expense today',
            'stats.outcome_today_plural': '{count} expenses today',
            'stats.month_flow': '{income} in · {outcome} out',
            'chart.income_vs_outcome': 'Income vs Outcome',
            'chart.period_snapshot': 'Period snapshot',
            'chart.selected_period': 'Selected period',
            'chart.expense_categories': 'Expense Categories',
            'chart.where_money': 'Where money went out',
            'chart.no_data': 'No data for this period',
            'chart.income': 'Income',
            'chart.outcome': 'Outcome',
            'chart.net_flow': 'Net flow',
            'chart.total_out': 'Total out',
            'expenses.title': 'Outcome — Expenses',
            'expenses.subtitle': 'Track rent, supplies, staff & other costs',
            'expenses.col.time': 'Time',
            'expenses.col.category': 'Category',
            'expenses.col.description': 'Description',
            'expenses.col.amount': 'Amount',
            'expenses.col.actions': 'Actions',
            'expenses.empty': 'No expenses recorded for this date',
            'income.title': 'Income — Sales by Table',
            'income.subtitle': 'Daily total per table (counted when bill was settled)',
            'income.col.table': 'Table',
            'income.col.orders': 'Orders',
            'income.col.last_settled': 'Last settled',
            'income.col.total': 'Total sales',
            'income.empty': 'No completed sales on this date',
            'income.table_label': 'Table {label}',
            'password.title': 'Change Admin Password',
            'password.old': 'Old Password',
            'password.new': 'New Password',
            'password.confirm': 'Confirm New Password',
            'password.update': 'Update Password',
            'expense.modal_add': 'Add Expense',
            'expense.modal_edit': 'Edit Expense',
            'expense.category': 'Category',
            'expense.presets': 'Presets',
            'expense.custom': 'Custom',
            'expense.custom_placeholder': 'e.g. Cleaning, Delivery fee...',
            'expense.custom_hint': 'Tap a saved custom category or type a new one.',
            'expense.amount': 'Amount (Ks)',
            'expense.date': 'Date',
            'expense.description': 'Description',
            'expense.desc_placeholder': 'Optional note',
            'expense.save': 'Save Expense',
            'receipt.print': 'Print Receipt',
            'toast.invalid_login': 'Invalid username or password.',
            'toast.network': 'Network error occurred.',
            'toast.password_mismatch': 'New passwords do not match.',
            'toast.password_updated': 'Password updated. Please log in again.',
            'toast.wrong_password': 'Incorrect old password.',
            'toast.category_required': 'Please enter a category.',
            'toast.expense_saved': 'Expense saved.',
            'toast.expense_deleted': 'Expense deleted.',
            'toast.export_ok': '{range} finance PDF downloaded.',
            'toast.export_fail': 'Export failed.',
            'toast.export_network': 'Network error exporting document.',
            'toast.receipt_fail': 'Receipt compilation failed.',
            'confirm.delete_expense': 'Delete this expense entry?',
        },
        mm: {
            'theme.dark': 'အမှောင်',
            'theme.light': 'အလင်း',
            'common.password': 'စကားဝှက်',
            'common.logout': 'ထွက်မည်',
            'common.username': 'အသုံးပြုသူအမည်',
            'common.date': 'ရက်စွဲ',
            'common.edit': 'ပြင်မည်',
            'common.delete': 'ဖျက်မည်',
            'common.table': 'စားပွဲ',
            'common.orders': 'အော်ဒါ',
            'common.install_app': 'အက်ပ် ထည့်မည်',
            'common.not_now': 'နောက်မှ',
            'pwa.title': 'Finance ကို ဖုန်းမှာ ထည့်မည်',
            'pwa.subtitle': 'ပိုင်ရှင် အမြန် ဝင်ရန် home screen ထည့်ပါ',
            'pwa.install': 'ထည့်မည်',
            'login.hint': 'ပိုင်ရှင် ဝင်ရောက်ရန် — ဝင်ငွေနှင့် အသုံးစရိတ်',
            'login.submit': 'ဝင်မည်',
            'login.remember': 'မှတ်ထားမည်',
            'access.title': 'ပိုင်ရှင်သာ ဝင်ခွင့်ရှိသည်',
            'access.body': 'Finance ကို ဆိုင်ပိုင်ရှင် (admin) သာ သုံးနိုင်သည်။ စားပွဲ မန်နေဂျာများ /manager ကို သုံးပါ',
            'access.go_ops': 'Operations သို့',
            'access.sign_out': 'ထွက်မည်',
            'app.subtitle': 'ဝင်ငွေ၊ အသုံးစရိတ်နှင့် အသားတင်အမြတ်',
            'nav.operations': 'Operations →',
            'range.day': 'နေ့',
            'range.week': 'အပတ်',
            'range.month': 'လ',
            'range.custom': 'ကိုယ်တိုင် ရွေးမည်',
            'export.today': 'ယနေ့',
            'export.week': 'အပတ်',
            'export.month': 'လ',
            'btn.add_expense': '+ အသုံးစရိတ်',
            'btn.add_expense_soft': '+ အသုံးစရိတ် ထည့်မည်',
            'stats.income': 'ဝင်ငွေ (အရောင်း)',
            'stats.outcome': 'အသုံးစရိတ်',
            'stats.net_day': 'အသားတင်အမြတ် (နေ့)',
            'stats.net_week': 'အသားတင်အမြတ် (အပတ်)',
            'stats.net_month': 'အသားတင်အမြတ် (လ)',
            'stats.net_period': 'အသားတင်အမြတ် (ကာလ)',
            'stats.net_sub': 'ဝင်ငွေ − အသုံးစရိတ်',
            'stats.month_net': '{month} အသားတင်',
            'stats.month_sub': 'လစဉ် ဝင်ငွေနှင့် အသုံးစရိတ်',
            'stats.income_sub': 'စားပွဲ {tables} · အော်ဒါ {orders}',
            'stats.income_sub_plural': 'စားပွဲ {tables} · အော်ဒါ {orders}',
            'stats.outcome_sub': 'အသုံးစရိတ် {count} ခု',
            'stats.outcome_sub_plural': 'အသုံးစရိတ် {count} ခု',
            'stats.outcome_today': 'ယနေ့ အသုံးစရိတ် {count} ခု',
            'stats.outcome_today_plural': 'ယနေ့ အသုံးစရိတ် {count} ခု',
            'stats.month_flow': 'ဝင် {income} · ထွက် {outcome}',
            'chart.income_vs_outcome': 'ဝင်ငွေ နှင့် အသုံးစရိတ်',
            'chart.period_snapshot': 'ကာလ အကျဉ်း',
            'chart.selected_period': 'ရွေးထားသော ကာလ',
            'chart.expense_categories': 'အသုံးစရိတ် အမျိုးအစားများ',
            'chart.where_money': 'ငွေ ဘယ်ကို သုံးသလဲ',
            'chart.no_data': 'ဤကာလအတွက် ဒေတာ မရှိပါ',
            'chart.income': 'ဝင်ငွေ',
            'chart.outcome': 'အသုံးစရိတ်',
            'chart.net_flow': 'အသားတင်',
            'chart.total_out': 'စုစုပေါင်း ထွက်',
            'expenses.title': 'အသုံးစရိတ် စာရင်း',
            'expenses.subtitle': 'ငှားရမ်းခ၊ ပစ္စည်း၊ ဝန်ထမ်းနှင့် အခြား ကုန်ကျစရိတ်',
            'expenses.col.time': 'အချိန်',
            'expenses.col.category': 'အမျိုးအစား',
            'expenses.col.description': 'ဖော်ပြချက်',
            'expenses.col.amount': 'ပမာဏ',
            'expenses.col.actions': 'လုပ်ဆောင်ချက်',
            'expenses.empty': 'ဤရက်အတွက် အသုံးစရိတ် မရှိပါ',
            'income.title': 'ဝင်ငွေ — စားပွဲအလိုက်',
            'income.subtitle': 'စားပွဲတစ်ခုချင်း နေ့စဉ် စုစုပေါင်း (ဘီလ်ပိတ်ချိန်)',
            'income.col.table': 'စားပွဲ',
            'income.col.orders': 'အော်ဒါ',
            'income.col.last_settled': 'နောက်ဆုံး ပိတ်ချိန်',
            'income.col.total': 'စုစုပေါင်း အရောင်း',
            'income.empty': 'ဤရက်အတွက် အရောင်း မရှိပါ',
            'income.table_label': 'စားပွဲ {label}',
            'password.title': 'စကားဝှက် ပြောင်းမည်',
            'password.old': 'စကားဝှက် အဟောင်း',
            'password.new': 'စကားဝှက် အသစ်',
            'password.confirm': 'စကားဝှက် အသစ် ထပ်ရိုက်ပါ',
            'password.update': 'စကားဝှက် သိမ်းမည်',
            'expense.modal_add': 'အသုံးစရိတ် ထည့်မည်',
            'expense.modal_edit': 'အသုံးစရိတ် ပြင်မည်',
            'expense.category': 'အမျိုးအစား',
            'expense.presets': 'ပုံသေ',
            'expense.custom': 'ကိုယ်တိုင်',
            'expense.custom_placeholder': 'ဥပမာ သန့်ရှင်းရေး၊ ပို့ဆောင်ခ...',
            'expense.custom_hint': 'သိမ်းထားသော အမျိုးအစား နှိပ်ပါ သို့မဟုတ် အသစ် ရိုက်ပါ',
            'expense.amount': 'ပမာဏ (ကျပ်)',
            'expense.date': 'ရက်စွဲ',
            'expense.description': 'ဖော်ပြချက်',
            'expense.desc_placeholder': 'မှတ်ချက် (မဖြစ်မနေ မဟုတ်)',
            'expense.save': 'အသုံးစရိတ် သိမ်းမည်',
            'receipt.print': 'ဘီလ် ပရင့်ထုတ်မည်',
            'toast.invalid_login': 'အသုံးပြုသူအမည် သို့မဟုတ် စကားဝှက် မှားနေသည်',
            'toast.network': 'ကွန်ရက် အမှားအယွင်း',
            'toast.password_mismatch': 'စကားဝှက် အသစ် မတူညီပါ',
            'toast.password_updated': 'စကားဝှက် ပြောင်းပြီးပါပြီ။ ပြန် ဝင်ပါ',
            'toast.wrong_password': 'စကားဝှက် အဟောင်း မှားနေသည်',
            'toast.category_required': 'အမျိုးအစား ထည့်ပါ',
            'toast.expense_saved': 'အသုံးစရိတ် သိမ်းပြီးပါပြီ',
            'toast.expense_deleted': 'အသုံးစရိတ် ဖျက်ပြီးပါပြီ',
            'toast.export_ok': '{range} ဘဏ္ဍာရေး PDF ဒေါင်းလုပ်ပြီးပါပြီ',
            'toast.export_fail': 'Export မအောင်မြင်ပါ',
            'toast.export_network': 'Export လုပ်ရာတွင် ကွန်ရက် အမှား',
            'toast.receipt_fail': 'ဘီလ် ဖန်တီးမရပါ',
            'confirm.delete_expense': 'ဤအသုံးစရိတ်ကို ဖျက်မလား?',
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

    function applyStaticTranslations() {
        document.querySelectorAll('[data-i18n]').forEach((el) => {
            el.textContent = t(el.getAttribute('data-i18n'));
        });
        document.querySelectorAll('[data-i18n-placeholder]').forEach((el) => {
            el.placeholder = t(el.getAttribute('data-i18n-placeholder'));
        });
        document.querySelectorAll('[data-i18n-html]').forEach((el) => {
            el.innerHTML = t(el.getAttribute('data-i18n-html'));
        });
        document.documentElement.lang = getLang() === 'mm' ? 'my' : 'en';
        updateLangSwitchButtons();
    }

    function setFinanceLanguage(lang) {
        const next = lang === 'mm' ? 'mm' : 'en';
        localStorage.setItem(LANG_KEY, next);
        applyStaticTranslations();
        if (typeof global.onFinanceLanguageChange === 'function') {
            global.onFinanceLanguageChange(next);
        }
    }

    global.FinanceI18n = {
        t,
        getLang,
        setLang: setFinanceLanguage,
        apply: applyStaticTranslations,
    };
    global.t = t;
}(window));
