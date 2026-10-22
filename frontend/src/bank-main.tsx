import React from 'react';
import ReactDOM from 'react-dom/client';
import { BankHome } from './signal/BankHome';

// BankHome owns its isolated stylesheet; never import Signal's global styles.
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><BankHome /></React.StrictMode>,
);
