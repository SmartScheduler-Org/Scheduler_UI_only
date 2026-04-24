/* neuron_bg.js — shared neural network canvas background
   Skip if <body data-no-neuron="true"> is set, or if page has its own canvas animation
*/
(function () {
    'use strict';
  
    if (document.body && document.body.dataset.noNeuron === 'true') return;
  
    const COLORS = [
      '0,229,255',
      '168,85,247',
      '16,185,129',
      '99,102,241',
      '0,180,255',
      '245,158,11',
    ];
  
    let canvas, ctx, W, H, pts;
    const COUNT = window.NEURON_COUNT || 110;
    const DIST  = window.NEURON_DIST  || 130;
  
    class Pt {
      constructor(init) { this.reset(init); }
      reset(init) {
        this.x  = Math.random() * W;
        this.y  = init ? Math.random() * H : H + 6;
        this.vx = (Math.random() - 0.5) * 0.42;
        this.vy = -(Math.random() * 0.55 + 0.1);
        this.r  = Math.random() * 2 + 0.5;
        this.life = 1;
        this.dc = Math.random() * 0.004 + 0.0008;
        this.c  = COLORS[Math.floor(Math.random() * COLORS.length)];
      }
      update() {
        this.x += this.vx; this.y += this.vy; this.life -= this.dc;
        if (this.life <= 0) this.reset(false);
      }
      draw() {
        ctx.beginPath();
        ctx.arc(this.x, this.y, this.r, 0, Math.PI * 2);
        ctx.fillStyle   = `rgba(${this.c},${this.life * 0.8})`;
        ctx.shadowBlur  = 14;
        ctx.shadowColor = `rgba(${this.c},0.55)`;
        ctx.fill();
        ctx.shadowBlur  = 0;
      }
    }
  
    function resize() {
      W = canvas.width  = window.innerWidth;
      H = canvas.height = window.innerHeight;
    }
  
    function loop() {
      ctx.clearRect(0, 0, W, H);
      for (let i = 0; i < pts.length; i++) {
        for (let j = i + 1; j < pts.length; j++) {
          const dx = pts[i].x - pts[j].x, dy = pts[i].y - pts[j].y;
          const d  = Math.sqrt(dx * dx + dy * dy);
          if (d < DIST) {
            ctx.beginPath();
            ctx.moveTo(pts[i].x, pts[i].y);
            ctx.lineTo(pts[j].x, pts[j].y);
            const alpha = (1 - d / DIST) * 0.15;
            ctx.strokeStyle = `rgba(0,200,255,${alpha})`;
            ctx.lineWidth = 0.8;
            ctx.stroke();
          }
        }
      }
      pts.forEach(p => { p.update(); p.draw(); });
      requestAnimationFrame(loop);
    }
  
    function init() {
      canvas = document.getElementById('neuron-canvas');
      if (!canvas) return;
      canvas.style.cssText = [
        'position:fixed', 'inset:0', 'width:100vw', 'height:100vh',
        'pointer-events:none', 'z-index:0',
      ].join(';');
      ctx = canvas.getContext('2d');
      resize();
      window.addEventListener('resize', resize);
      pts = Array.from({ length: COUNT }, (_, i) => new Pt(i < COUNT));
      loop();
    }
  
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', init);
    } else {
      init();
    }
  })();
  