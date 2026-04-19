/**
 * sonnet-selector.js — Seletor de agente + modal Stripe + badge de saldo
 *
 * 2 botões: CLOW (DeepSeek) | SYSTEM CLOW SONNET 4 (premium via créditos)
 * Ao trocar: cria nova conversa (padrão Claude)
 * Ao clicar em Sonnet sem créditos: abre modal de compra via Stripe
 * Quando ativo: mostra badge de saldo daily/weekly
 */

(function() {
  'use strict';

  const SYSTEM_CLOW_URL = 'https://system-clow.pvcorretor01.com.br/';
  const STORAGE_KEY = 'clow_selected_agent';
  let currentAgent = localStorage.getItem(STORAGE_KEY) || 'clow';
  let sonnetBalance = null;
  let sonnetIframeOpen = false;

  // ═══════════════════════════════════════════════════════════════════════
  // Fetch balance from backend
  // ═══════════════════════════════════════════════════════════════════════

  async function fetchSonnetBalance() {
    try {
      const r = await fetch('/api/v1/addons/sonnet/balance', { credentials: 'same-origin' });
      if (!r.ok) return null;
      sonnetBalance = await r.json();
      return sonnetBalance;
    } catch (e) {
      return null;
    }
  }

  function formatResetTime(seconds) {
    if (seconds < 3600) return Math.ceil(seconds / 60) + 'min';
    if (seconds < 86400) return Math.ceil(seconds / 3600) + 'h';
    return Math.ceil(seconds / 86400) + 'd';
  }

  // ═══════════════════════════════════════════════════════════════════════
  // Render segmented selector in header
  // ═══════════════════════════════════════════════════════════════════════

  function renderSelector() {
    const oldSel = document.getElementById('modSel');
    if (!oldSel) return;

    // Hide old select
    oldSel.style.display = 'none';

    // Create segmented container if not exists
    let seg = document.getElementById('agentSeg');
    if (!seg) {
      seg = document.createElement('div');
      seg.id = 'agentSeg';
      seg.className = 'agent-seg';
      seg.innerHTML = `
        <button type="button" class="agent-btn" data-agent="clow" onclick="window.selectAgent('clow')">
          <span class="agent-btn-label">CLOW</span>
        </button>
        <button type="button" class="agent-btn" data-agent="sonnet" onclick="window.selectAgent('sonnet')">
          <span class="agent-btn-icon">∞</span>
          <span class="agent-btn-label">SYSTEM CLOW SONNET 4</span>
        </button>
      `;
      oldSel.parentNode.insertBefore(seg, oldSel);

      // Create balance badge (shown when Sonnet active)
      const badge = document.createElement('div');
      badge.id = 'sonnetBadge';
      badge.className = 'sonnet-badge hidden';
      badge.innerHTML = '<span id="sonnetBadgeText">—</span>';
      seg.parentNode.insertBefore(badge, seg.nextSibling);
    }

    updateSelectorUI();
  }

  function updateSelectorUI() {
    document.querySelectorAll('.agent-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.agent === currentAgent);
    });

    const badge = document.getElementById('sonnetBadge');
    if (!badge) return;

    if (currentAgent === 'sonnet' && sonnetBalance && sonnetBalance.has_credit) {
      const txt = document.getElementById('sonnetBadgeText');
      if (sonnetBalance.is_admin) {
        txt.innerHTML = `<span class="sb-key">ADMIN</span> · ilimitado`;
      } else {
        txt.innerHTML =
          `<span class="sb-key">${sonnetBalance.daily.remaining}/${sonnetBalance.daily.limit}</span> hoje · ` +
          `<span class="sb-key">${sonnetBalance.weekly.remaining}/${sonnetBalance.weekly.limit}</span> semana` +
          (sonnetBalance.expiry_warning ? ` · <span class="sb-warn">expira em ${sonnetBalance.days_until_expiry}d</span>` : '');
      }
      badge.classList.remove('hidden');
    } else {
      badge.classList.add('hidden');
    }
  }

  // ═══════════════════════════════════════════════════════════════════════
  // Main handler: user clicks an agent
  // ═══════════════════════════════════════════════════════════════════════

  async function selectAgent(agent) {
    if (agent === currentAgent && !sonnetIframeOpen) return;

    if (agent === 'sonnet') {
      // Check credits first
      const balance = await fetchSonnetBalance();
      const isAdmin = !!(balance && balance.is_admin);

      if (!isAdmin) {
        if (!balance || !balance.has_credit) {
          openPackageModal();
          return;
        }

        // Check daily/weekly limits (admin bypass)
        if (balance.daily && balance.daily.remaining <= 0) {
          showToast(`Limite diário atingido (${balance.daily.limit} mensagens). Reseta em ${formatResetTime(balance.daily.reset_in_seconds)}.`);
          return;
        }
        if (balance.weekly && balance.weekly.remaining <= 0) {
          showToast(`Limite semanal atingido (${balance.weekly.limit} mensagens). Reseta em ${formatResetTime(balance.weekly.reset_in_seconds)}.`);
          return;
        }
      }

      // Confirm new conversation
      if (currentAgent !== 'sonnet') {
        const confirm = await customConfirm(
          'Trocar para System Clow Sonnet 4',
          'Uma nova conversa será iniciada. Você continuará podendo acessar as conversas do Clow pela barra lateral. Deseja continuar?'
        );
        if (!confirm) return;
      }

      currentAgent = 'sonnet';
      localStorage.setItem(STORAGE_KEY, 'sonnet');
      updateSelectorUI();
      openSonnetIframe();
    } else {
      // agent === 'clow' — fecha iframe e volta. NAO cria nova conversa.
      currentAgent = 'clow';
      localStorage.setItem(STORAGE_KEY, 'clow');
      closeSonnetIframe();
      updateSelectorUI();
    }
  }

  // ═══════════════════════════════════════════════════════════════════════
  // Sonnet iframe (embed System Clow)
  // ═══════════════════════════════════════════════════════════════════════

  async function openSonnetIframe() {
    // Fetch short-lived signed token from Clow backend
    let iframeUrl = SYSTEM_CLOW_URL;
    try {
      const tr = await fetch('/api/v1/addons/sonnet/token', { credentials: 'same-origin' });
      if (tr.ok) {
        const td = await tr.json();
        if (td.iframe_url) iframeUrl = td.iframe_url;
        else if (td.token) iframeUrl = SYSTEM_CLOW_URL + '?clow_token=' + encodeURIComponent(td.token);
      }
    } catch (e) {
      // fall back to plain SYSTEM_CLOW_URL (will show System Clow login)
    }

    let wrap = document.getElementById('sonnetIframeWrap');
    if (!wrap) {
      wrap = document.createElement('div');
      wrap.id = 'sonnetIframeWrap';
      wrap.className = 'sonnet-iframe-wrap';
      wrap.innerHTML = `
        <div class="sonnet-iframe-bar">
          <div class="sonnet-iframe-title">
            <span class="sonnet-iframe-dot"></span>
            <strong>System Clow</strong>
            <span class="sonnet-iframe-sub">Sonnet 4</span>
          </div>
          <button class="sonnet-iframe-close" onclick="window.selectAgent('clow')">&times;</button>
        </div>
        <iframe id="sonnetIframe" src="${iframeUrl}" allow="clipboard-read; clipboard-write; microphone"></iframe>
      `;
      document.body.appendChild(wrap);
    } else {
      const ifr = document.getElementById('sonnetIframe');
      if (ifr && ifr.src !== iframeUrl) ifr.src = iframeUrl;
    }
    wrap.classList.add('open');
    sonnetIframeOpen = true;

    // iOS virtual keyboard fix: apply visualViewport height to wrap
    if (window.visualViewport && !window._sonnetVVBound) {
      window._sonnetVVBound = true;
      const applyVV = () => {
        const w = document.getElementById('sonnetIframeWrap');
        if (!w || !w.classList.contains('open')) return;
        const vv = window.visualViewport;
        w.style.height = vv.height + 'px';
        w.style.top = vv.offsetTop + 'px';
      };
      window.visualViewport.addEventListener('resize', applyVV);
      window.visualViewport.addEventListener('scroll', applyVV);
      window._sonnetVVApply = applyVV;
      applyVV();
    } else if (window._sonnetVVApply) {
      window._sonnetVVApply();
    }

    // Refresh balance periodically
    if (!window._sonnetBalanceTimer) {
      window._sonnetBalanceTimer = setInterval(async () => {
        await fetchSonnetBalance();
        updateSelectorUI();
      }, 30000);
    }
  }

  function closeSonnetIframe() {
    const wrap = document.getElementById('sonnetIframeWrap');
    if (wrap) {
      // Clear iframe src first to stop any in-flight requests
      const ifr = document.getElementById('sonnetIframe');
      if (ifr) {
        try { ifr.src = 'about:blank'; } catch (e) {}
      }
      wrap.style.height = '';
      wrap.style.top = '';
      wrap.classList.remove('open');
      // Remove from DOM after transition
      setTimeout(() => { try { wrap.remove(); } catch (e) {} }, 50);
    }
    sonnetIframeOpen = false;
    if (window._sonnetBalanceTimer) {
      clearInterval(window._sonnetBalanceTimer);
      window._sonnetBalanceTimer = null;
    }
  }

  // ═══════════════════════════════════════════════════════════════════════
  // Package purchase modal
  // ═══════════════════════════════════════════════════════════════════════

  async function openPackageModal() {
    let r;
    try {
      r = await fetch('/api/v1/addons/sonnet/packages', { credentials: 'same-origin' });
    } catch {
      showToast('Erro ao carregar pacotes. Tente novamente.');
      return;
    }
    const data = await r.json();
    const packages = data.packages || [];

    let modal = document.getElementById('sonnetModal');
    if (modal) modal.remove();
    modal = document.createElement('div');
    modal.id = 'sonnetModal';
    modal.className = 'sonnet-modal-bg';
    modal.innerHTML = `
      <div class="sonnet-modal" role="dialog" aria-modal="true">
        <button class="sonnet-modal-x" onclick="this.closest('.sonnet-modal-bg').remove()">&times;</button>
        <h2 class="sonnet-modal-title">Sonnet 4 Premium</h2>
        <p class="sonnet-modal-sub">Escolha seu pacote de créditos. Válido por 90 dias após a compra.</p>
        <div class="sonnet-pkgs">
          ${packages.map(p => `
            <div class="sonnet-pkg ${p.id === 'pro' ? 'highlight' : ''}" data-pkg="${p.id}">
              ${p.id === 'pro' ? '<span class="sonnet-pkg-recommended">Mais popular</span>' : ''}
              <h3 class="sonnet-pkg-name">${p.name.replace('Sonnet 4 ', '')}</h3>
              <div class="sonnet-pkg-price">R$ ${p.price_brl.toFixed(2).replace('.', ',')}</div>
              <ul class="sonnet-pkg-features">
                <li><strong>${p.daily_msgs}</strong> mensagens/dia</li>
                <li><strong>${p.weekly_msgs}</strong> mensagens/semana</li>
                <li>Válido por <strong>90 dias</strong></li>
              </ul>
              <button class="sonnet-pkg-btn" onclick="window.purchaseSonnet('${p.id}')">Comprar</button>
            </div>
          `).join('')}
        </div>
        <p class="sonnet-modal-foot">Pagamento seguro via Stripe. Aceita cartão de crédito.</p>
      </div>
    `;
    document.body.appendChild(modal);
  }

  async function purchaseSonnet(packageId) {
    const btn = document.querySelector(`.sonnet-pkg[data-pkg="${packageId}"] .sonnet-pkg-btn`);
    if (btn) { btn.disabled = true; btn.textContent = 'Processando...'; }

    try {
      const r = await fetch('/api/v1/addons/sonnet/purchase', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ package_id: packageId })
      });
      const data = await r.json();
      if (data.checkout_url) {
        window.location.href = data.checkout_url;
      } else {
        showToast('Erro: ' + (data.message || 'Falha ao criar checkout'));
        if (btn) { btn.disabled = false; btn.textContent = 'Comprar'; }
      }
    } catch (e) {
      showToast('Erro de conexão. Tente novamente.');
      if (btn) { btn.disabled = false; btn.textContent = 'Comprar'; }
    }
  }

  // ═══════════════════════════════════════════════════════════════════════
  // UI helpers
  // ═══════════════════════════════════════════════════════════════════════

  function customConfirm(title, message) {
    return new Promise(resolve => {
      const bg = document.createElement('div');
      bg.className = 'sonnet-modal-bg';
      bg.innerHTML = `
        <div class="sonnet-modal small">
          <h2 class="sonnet-modal-title">${title}</h2>
          <p class="sonnet-modal-sub">${message}</p>
          <div class="sonnet-confirm-actions">
            <button class="sonnet-btn-ghost" data-a="no">Cancelar</button>
            <button class="sonnet-btn-primary" data-a="yes">Continuar</button>
          </div>
        </div>
      `;
      document.body.appendChild(bg);
      bg.addEventListener('click', e => {
        const a = e.target.dataset.a;
        if (a === 'yes') { bg.remove(); resolve(true); }
        else if (a === 'no' || e.target === bg) { bg.remove(); resolve(false); }
      });
    });
  }

  function showToast(msg) {
    const t = document.createElement('div');
    t.className = 'sonnet-toast';
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => t.classList.add('show'), 20);
    setTimeout(() => { t.classList.remove('show'); setTimeout(() => t.remove(), 300); }, 4500);
  }

  // ═══════════════════════════════════════════════════════════════════════
  // Handle Stripe return URL
  // ═══════════════════════════════════════════════════════════════════════

  function handleStripeReturn() {
    const params = new URLSearchParams(window.location.search);
    const sp = params.get('sonnet_purchase');
    if (sp === 'success') {
      showToast('Pagamento confirmado! Seus créditos estão sendo processados.');
      // Poll balance for up to 30s
      let tries = 0;
      const poll = setInterval(async () => {
        tries++;
        await fetchSonnetBalance();
        if (sonnetBalance && sonnetBalance.has_credit) {
          clearInterval(poll);
          updateSelectorUI();
          showToast('Créditos adicionados! Você já pode usar Sonnet 4.');
          setTimeout(() => selectAgent('sonnet'), 1500);
        }
        if (tries > 15) clearInterval(poll);
      }, 2000);
      // Clean URL
      history.replaceState({}, '', window.location.pathname);
    } else if (sp === 'cancelled') {
      showToast('Compra cancelada.');
      history.replaceState({}, '', window.location.pathname);
    }
  }

  // ═══════════════════════════════════════════════════════════════════════
  // Init
  // ═══════════════════════════════════════════════════════════════════════

  window.selectAgent = selectAgent;
  window.purchaseSonnet = purchaseSonnet;

  function init() {
    // Always boot into Clow (DeepSeek). Sonnet only opens on explicit click.
    currentAgent = 'clow';
    localStorage.setItem(STORAGE_KEY, 'clow');
    renderSelector();
    fetchSonnetBalance().then(() => updateSelectorUI());
    handleStripeReturn();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
