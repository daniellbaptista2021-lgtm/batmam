/**
 * Clow Install Page — tabs, copy, install tokens
 * External JS file (CSP-safe, no inline scripts needed)
 */

(function() {
  'use strict';

  // ── Tab Switching ─────────────────────────────────────────
  var tabContainer = document.getElementById('installTabs');
  var tabContents = document.querySelectorAll('.install-content');

  if (tabContainer) {
    tabContainer.addEventListener('click', function(e) {
      var btn = e.target.closest('.tab');
      if (!btn) return;
      var tabId = btn.getAttribute('data-tab');
      if (!tabId) return;

      // Deactivate all tabs
      tabContainer.querySelectorAll('.tab').forEach(function(t) {
        t.classList.remove('active');
      });
      btn.classList.add('active');

      // Hide all content
      tabContents.forEach(function(el) {
        el.style.display = 'none';
      });

      // Show selected
      var target = document.getElementById('tab-' + tabId);
      if (target) {
        target.style.display = 'block';
      }
    });
  }

  // ── Copy Code Buttons ─────────────────────────────────────
  document.addEventListener('click', function(e) {
    var btn = e.target.closest('.copy-btn');
    if (!btn) return;

    var block = btn.closest('.code-block');
    if (!block) return;
    var codeEl = block.querySelector('code') || block.querySelector('pre');
    if (!codeEl) return;

    var text = codeEl.textContent.trim();

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function() {
        showCopied(btn);
      }).catch(function() {
        fallbackCopy(text, btn);
      });
    } else {
      fallbackCopy(text, btn);
    }
  });

  function showCopied(btn) {
    var orig = btn.textContent;
    btn.textContent = '\u2705';
    setTimeout(function() { btn.textContent = orig; }, 2000);
  }

  function fallbackCopy(text, btn) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand('copy');
      showCopied(btn);
    } catch (e) {
      // ignore
    }
    document.body.removeChild(ta);
  }

  // ── Auto-detect OS ────────────────────────────────────────
  var ua = navigator.userAgent.toLowerCase();
  var detectedTab = 'windows';
  if (ua.indexOf('mac') !== -1) detectedTab = 'mac';
  else if (ua.indexOf('linux') !== -1) detectedTab = 'linux';

  var autoBtn = document.querySelector('[data-tab="' + detectedTab + '"]');
  if (autoBtn) autoBtn.click();

  // ── Install Token Generation (paid plans) ─────────────────
  var btnGenerate = document.getElementById('btnGenerate');
  if (btnGenerate) {
    btnGenerate.addEventListener('click', generateInstallToken);
  }

  function generateInstallToken() {
    btnGenerate.disabled = true;
    btnGenerate.textContent = 'Gerando...';

    fetch('/api/v1/install/generate-token', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      credentials: 'same-origin'
    })
    .then(function(res) {
      if (res.status === 401) {
        alert('Faca login primeiro.');
        window.location.href = '/login';
        return null;
      }
      if (res.status === 403) {
        alert('Disponivel apenas para planos pagos (Lite, Starter, Pro, Business).');
        btnGenerate.disabled = false;
        btnGenerate.textContent = '\uD83D\uDD11 Gerar meu comando de instalacao';
        return null;
      }
      return res.json();
    })
    .then(function(data) {
      if (!data) return;
      var cmdWin = document.getElementById('cmdWindows');
      var cmdUnix = document.getElementById('cmdUnix');
      var generated = document.getElementById('generatedCommand');

      if (cmdWin) cmdWin.textContent = data.command_windows || '';
      if (cmdUnix) cmdUnix.textContent = data.command_unix || '';
      if (generated) generated.style.display = 'block';
      btnGenerate.textContent = '\u2705 Comando gerado!';
    })
    .catch(function() {
      btnGenerate.textContent = '\u274C Erro — tente novamente';
      btnGenerate.disabled = false;
    });
  }

  // ── OS sub-tabs (inside paid install) ─────────────────────
  document.addEventListener('click', function(e) {
    var btn = e.target.closest('[data-os]');
    if (!btn) return;
    var os = btn.getAttribute('data-os');
    var parent = btn.closest('.os-tabs');
    if (parent) {
      parent.querySelectorAll('button').forEach(function(b) { b.classList.remove('active'); });
      btn.classList.add('active');
    }
    var cmdWinDiv = document.getElementById('cmd-win');
    var cmdUnixDiv = document.getElementById('cmd-unix');
    if (cmdWinDiv) cmdWinDiv.style.display = (os === 'win') ? 'block' : 'none';
    if (cmdUnixDiv) cmdUnixDiv.style.display = (os === 'unix') ? 'block' : 'none';
  });

  // ── Check if user is logged in with paid plan ─────────────
  fetch('/api/v1/billing/status', {credentials: 'same-origin'})
    .then(function(res) {
      if (!res.ok) return null;
      return res.json();
    })
    .then(function(data) {
      if (!data) return;
      var planId = data.plan_id || '';
      var paidPlans = ['lite', 'starter', 'pro', 'business'];
      var installFree = document.getElementById('install-free');
      var installPaid = document.getElementById('install-paid');

      if (paidPlans.indexOf(planId) !== -1 && installPaid && installFree) {
        installFree.style.display = 'none';
        installPaid.style.display = 'block';
        var planTitle = installPaid.querySelector('.paid-plan-title');
        if (planTitle) {
          planTitle.textContent = 'Plano ' + (data.plan_name || planId) + ' — Instalacao automatica';
        }
      }
    })
    .catch(function() {
      // Not logged in — show free version (default)
    });

})();
