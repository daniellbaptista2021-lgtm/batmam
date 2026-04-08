/**
 * Clow Premium Background
 * Canvas: partículas flutuantes + cursor glow discreto
 * Design ref: Vercel / Stripe / Linear
 * GPU-friendly: requestAnimationFrame + visibility pause
 */
(function () {
  'use strict';
  if (typeof window === 'undefined' || typeof document === 'undefined') return;

  /* ── Config ─────────────────────────────────────────────── */
  var CFG = {
    count:   22,          // partículas
    minR:    1.0,         // raio mín px
    maxR:    2.2,         // raio máx px
    speed:   0.000055,    // velocidade de drift
    minA:    0.10,        // alpha mín
    maxA:    0.28,        // alpha máx
    color:   '155,89,252',
    glowMul: 7,           // multiplicador do halo
    fps:     60,
  };

  var canvas, ctx, W, H, dpr, raf;
  var particles = [];
  var mouseX = -9999, mouseY = -9999;
  var glowEl;
  var time = 0;
  var lastFrame = 0;
  var interval = 1000 / CFG.fps;
  var hidden = false;

  /* ── Setup canvas ─────────────────────────────────────────── */
  function createCanvas() {
    canvas = document.createElement('canvas');
    canvas.id = 'clow-bg';
    canvas.setAttribute('aria-hidden', 'true');
    canvas.style.cssText = [
      'position:fixed',
      'top:0', 'left:0',
      'width:100%', 'height:100%',
      'z-index:-1',
      'pointer-events:none',
    ].join(';');
    /* Inserir como primeiro filho do body para ficar atrás de tudo */
    if (document.body.firstChild) {
      document.body.insertBefore(canvas, document.body.firstChild);
    } else {
      document.body.appendChild(canvas);
    }
    ctx = canvas.getContext('2d');
  }

  /* ── Cursor glow (div CSS — mais leve que canvas) ──────────── */
  function createCursorGlow() {
    glowEl = document.createElement('div');
    glowEl.id = 'clow-cursor-glow';
    document.body.appendChild(glowEl);

    window.addEventListener('mousemove', function (e) {
      mouseX = e.clientX;
      mouseY = e.clientY;
      glowEl.style.left = mouseX + 'px';
      glowEl.style.top  = mouseY + 'px';
    }, { passive: true });
  }

  /* ── Resize ───────────────────────────────────────────────── */
  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    W   = window.innerWidth;
    H   = window.innerHeight;
    canvas.width  = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    ctx.scale(dpr, dpr);
  }

  /* ── Particles ────────────────────────────────────────────── */
  function spawnParticles() {
    particles = [];
    for (var i = 0; i < CFG.count; i++) {
      particles.push({
        x:     Math.random(),
        y:     Math.random(),
        vx:    (Math.random() - 0.5) * CFG.speed,
        vy:    (Math.random() - 0.5) * CFG.speed,
        r:     CFG.minR + Math.random() * (CFG.maxR - CFG.minR),
        alpha: CFG.minA + Math.random() * (CFG.maxA - CFG.minA),
        phase: Math.random() * Math.PI * 2,
        freq:  0.18 + Math.random() * 0.45,
      });
    }
  }

  /* ── Draw loop ────────────────────────────────────────────── */
  function draw(ts) {
    if (hidden) return;
    raf = requestAnimationFrame(draw);

    var delta = ts - lastFrame;
    if (delta < interval) return;
    lastFrame = ts - (delta % interval);

    time += 0.006;
    ctx.clearRect(0, 0, W, H);

    for (var i = 0; i < particles.length; i++) {
      var p = particles[i];

      /* drift */
      p.x += p.vx;
      p.y += p.vy;
      if (p.x < -0.02) p.x = 1.02;
      if (p.x >  1.02) p.x = -0.02;
      if (p.y < -0.02) p.y = 1.02;
      if (p.y >  1.02) p.y = -0.02;

      /* pulsating alpha */
      var a = p.alpha * (0.5 + 0.5 * Math.sin(time * p.freq + p.phase));

      /* halo radial gradient */
      var px = p.x * W;
      var py = p.y * H;
      var gr = ctx.createRadialGradient(px, py, 0, px, py, p.r * CFG.glowMul);
      gr.addColorStop(0,   'rgba(' + CFG.color + ',' + (a * 0.9).toFixed(3) + ')');
      gr.addColorStop(0.4, 'rgba(' + CFG.color + ',' + (a * 0.4).toFixed(3) + ')');
      gr.addColorStop(1,   'rgba(' + CFG.color + ',0)');

      ctx.beginPath();
      ctx.arc(px, py, p.r * CFG.glowMul, 0, Math.PI * 2);
      ctx.fillStyle = gr;
      ctx.fill();

      /* núcleo brilhante */
      ctx.beginPath();
      ctx.arc(px, py, p.r, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(' + CFG.color + ',' + Math.min(a * 1.6, 0.6).toFixed(3) + ')';
      ctx.fill();
    }
  }

  /* ── Visibility pause (economiza CPU em abas ocultas) ──────── */
  function handleVisibility() {
    hidden = document.hidden;
    if (!hidden) {
      lastFrame = performance.now();
      raf = requestAnimationFrame(draw);
    } else {
      cancelAnimationFrame(raf);
    }
  }

  /* ── Resize debounce ──────────────────────────────────────── */
  var resizeTimer;
  function onResize() {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      cancelAnimationFrame(raf);
      resize();
      if (!hidden) {
        lastFrame = performance.now();
        raf = requestAnimationFrame(draw);
      }
    }, 180);
  }

  /* ── Init ─────────────────────────────────────────────────── */
  function init() {
    createCanvas();
    createCursorGlow();
    resize();
    spawnParticles();

    lastFrame = performance.now();
    raf = requestAnimationFrame(draw);

    window.addEventListener('resize', onResize, { passive: true });
    document.addEventListener('visibilitychange', handleVisibility);
  }

  /* Aguarda DOM pronto */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
