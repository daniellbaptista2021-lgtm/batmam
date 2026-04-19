// theme-init.js — aplica tema salvo ANTES do render (evita flash).
// Rodar como <script> síncrono no <head>, antes do CSS.
(function(){
  try {
    var v = localStorage.getItem('clow_theme'); // 'light' | 'dark' | null
    if (v === 'light') {
      document.documentElement.classList.add('light-mode');
    } else if (v === 'dark') {
      document.documentElement.classList.remove('light-mode');
    }
  } catch (e) {}
  // Expose helper for toggles
  window.setClowTheme = function(isDark) {
    try {
      if (isDark) {
        document.documentElement.classList.remove('light-mode');
        localStorage.setItem('clow_theme', 'dark');
      } else {
        document.documentElement.classList.add('light-mode');
        localStorage.setItem('clow_theme', 'light');
      }
    } catch (e) {}
    // Notify other tabs
    try { window.dispatchEvent(new Event('clow-theme-change')); } catch (e) {}
  };
})();
