declare const __BANK_APP_URL__: string;
declare const __SIGNAL_APP_URL__: string;

// Each app has its own document. Build/export select sibling URLs without
// forwarding the bank's company, account, session or authorization data.
export const bankAppUrl = typeof __BANK_APP_URL__ === 'string' ? __BANK_APP_URL__ : '/bank.html';
export const signalAppUrl = typeof __SIGNAL_APP_URL__ === 'string' ? __SIGNAL_APP_URL__ : '/register';
