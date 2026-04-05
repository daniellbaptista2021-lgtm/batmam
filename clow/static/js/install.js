/**
 * Clow Install Page — tabs, copy, install tokens
 * External JS (CSP-safe)
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

      tabContainer.querySelectorAll('.tab').forEach(function(t) {
        t.classList.remove('active');
      });
      btn.classList.add('active');

      tabContents.forEach(function(el) { el.style.display = 'none'; });

      var target = document.getElementById('tab-' + tabId);
      if (target) target.style.display = 'block';
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
        flashBtn(btn);
      }).catch(function() { fallbackCopy(text, btn); });
    } else {
      fallbackCopy(text, btn);
    }
  });

  function flashBtn(btn) {
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
    try { document.execCommand('copy'); flashBtn(btn); } catch(e) {}
    document.body.removeChild(ta);
  }

  // ── Auto-detect OS ────────────────────────────────────────
  var ua = navigator.userAgent.toLowerCase();
  var detectedTab = 'windows';
  if (ua.indexOf('mac') !== -1) detectedTab = 'mac';
  else if (ua.indexOf('linux') !== -1) detectedTab = 'linux';
  var autoBtn = document.querySelector('[data-tab="' + detectedTab + '"]');
  if (autoBtn) autoBtn.click();

  // ── Token generation shared logic ─────────────────────────
  function doGenerateToken(btn, outputEl, isWindows) {
    btn.disabled = true;
    btn.textContent = 'Gerando...';

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
        btn.disabled = false;
        btn.textContent = '\uD83D\uDD11 Gerar meu comando de instalacao';
        return null;
      }
      return res.json();
    })
    .then(function(data) {
      if (!data) return;

      if (isWindows) {
        // Windows tab has os-tabs with cmd-win / cmd-unix
        var cmdWin = document.getElementById('cmdWindows');
        var cmdUnix = document.getElementById('cmdUnix');
        var generated = document.getElementById('generatedCommand');
        if (cmdWin) cmdWin.textContent = data.command_windows || '';
        if (cmdUnix) cmdUnix.textContent = data.command_unix || '';
        if (generated) generated.style.display = 'block';
      } else {
        // Mac/Linux/VPS tabs
        if (outputEl) {
          outputEl.textContent = data.command_unix || '';
          var wrapper = btn.closest('.step3-paid');
          if (wrapper) {
            var genDiv = wrapper.querySelector('.generated-unix');
            if (genDiv) genDiv.style.display = 'block';
          }
        }
      }
      btn.textContent = '\u2705 Comando gerado!';
    })
    .catch(function() {
      btn.textContent = '\u274C Erro — tente novamente';
      btn.disabled = false;
    });
  }

  // Windows tab generate button
  var btnGenerate = document.getElementById('btnGenerate');
  if (btnGenerate) {
    btnGenerate.addEventListener('click', function() {
      doGenerateToken(btnGenerate, null, true);
    });
  }

  // Mac/Linux/VPS tab generate buttons
  document.querySelectorAll('.btn-generate-unix').forEach(function(btn) {
    btn.addEventListener('click', function() {
      var step = btn.closest('.step3-paid');
      var output = step ? step.querySelector('.cmd-unix-output') : null;
      doGenerateToken(btn, output, false);
    });
  });

  // ── OS sub-tabs (Windows paid section) ────────────────────
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

  // ── Detect paid plan and toggle sections ──────────────────
  fetch('/api/v1/billing/status', {credentials: 'same-origin'})
    .then(function(res) { return res.ok ? res.json() : null; })
    .then(function(data) {
      if (!data) return;
      var planId = data.plan_id || '';
      var paidPlans = ['lite', 'starter', 'pro', 'business'];
      if (paidPlans.indexOf(planId) === -1) return;

      // Windows tab: show paid, hide free
      var installFree = document.getElementById('install-free');
      var installPaid = document.getElementById('install-paid');
      if (installFree) installFree.style.display = 'none';
      if (installPaid) {
        installPaid.style.display = 'block';
        var title = installPaid.querySelector('.paid-plan-title');
        if (title) title.textContent = 'Plano ' + (data.plan_name || planId) + ' — Instalacao automatica';
      }

      // Mac/Linux/VPS tabs: show paid sections, hide free
      document.querySelectorAll('.step3-paid').forEach(function(el) { el.style.display = 'block'; });
      document.querySelectorAll('.step3-free').forEach(function(el) { el.style.display = 'none'; });
    })
    .catch(function() {});

})();
