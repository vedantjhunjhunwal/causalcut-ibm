/* ═══════════════════════════════════════════════════
   CAUSALCUT — Landing Page  |  script.js
   ═══════════════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', () => {

  // Mark document as JS-ready for progressive enhancement animations
  document.documentElement.classList.add('js-animated');

  /* ── Nav: scroll-aware active link ── */
  const navLinks = document.querySelectorAll('.nav-link');
  const sections = document.querySelectorAll('section[id], footer[id]');

  const navObs = new IntersectionObserver(entries => {
    entries.forEach(e => {
      if (e.isIntersecting) {
        navLinks.forEach(l => l.classList.remove('active'));
        const m = document.querySelector('.nav-link[href="#' + e.target.id + '"]');
        if (m) m.classList.add('active');
      }
    });
  }, { threshold: 0.25 });
  sections.forEach(s => navObs.observe(s));

  /* ── Scroll-in animations ── */
  const animObs = new IntersectionObserver(entries => {
    entries.forEach(e => {
      if (e.isIntersecting) {
        e.target.classList.add('anim-visible');
        animObs.unobserve(e.target);
      }
    });
  }, { threshold: 0.1, rootMargin: '0px 0px -20px 0px' });
  document.querySelectorAll('.anim-target').forEach(el => animObs.observe(el));

  /* ── Hero clock ── */
  const clock = document.getElementById('hero-clock');
  if (clock) setInterval(() => {
    const n = new Date();
    clock.textContent = [n.getHours(), n.getMinutes(), n.getSeconds()].map(v => String(v).padStart(2, '0')).join(':');
  }, 1000);

  /* ─────────────────────────────────────────────
     HERO FACTORY SCROLL PARALLAX
     ───────────────────────────────────────────── */
  const factoryImg = document.getElementById('factory-image');
  const orangeStrip = document.querySelector('.orange-strip');
  const heroTextLayer = document.querySelector('.hero-text-layer');
  const leftContent = document.querySelector('.left-content');

  let currentScrollY = 0;
  let targetScrollY = 0;

  window.addEventListener('scroll', () => {
    targetScrollY = window.scrollY;
  }, { passive: true });

  function renderHeroParallax() {
    // Smooth physics lerp
    currentScrollY += (targetScrollY - currentScrollY) * 0.12;

    const vh = window.innerHeight || 800;
    const progress = Math.max(currentScrollY / (vh * 0.8), 0);

    if (factoryImg) {
      const imgLift = progress * 140;
      factoryImg.style.transform = `translate3d(0, -${imgLift.toFixed(1)}px, 0)`;
    }

    if (orangeStrip) {
      const stripLift = progress * 90;
      orangeStrip.style.transform = `translate3d(0, -${stripLift.toFixed(1)}px, 0) rotate(-12deg)`;
    }

    if (heroTextLayer) {
      const textLift = progress * 50;
      heroTextLayer.style.transform = `translate3d(0, -${textLift.toFixed(1)}px, 0)`;
    }

    requestAnimationFrame(renderHeroParallax);
  }

  renderHeroParallax();

  /* ── Hero: Sever button ── */
  const severBtn = document.getElementById('btn-sever-chain');
  if (severBtn) severBtn.addEventListener('click', () => {
    severBtn.textContent = 'CHAIN SEVERED ✓';
    severBtn.style.background = '#22C55E';
    severBtn.style.color = '#fff';
  });

  /* ── Gauge ring animation ── */
  document.querySelectorAll('.gauge-fill').forEach(f => {
    const t = f.getAttribute('stroke-dashoffset');
    f.style.strokeDashoffset = '113';
    requestAnimationFrame(() => setTimeout(() => { f.style.strokeDashoffset = t; }, 200));
  });

  /* ── Sparkline cycle ── */
  const sL = document.querySelector('.spark-line'), sA = document.querySelector('.spark-area');
  if (sL) {
    const ps = [
      "M0,50 C20,45 35,38 55,42 C75,32 90,48 110,25 C130,15 145,30 165,20 C180,28 190,18 200,12",
      "M0,40 C20,50 35,30 55,42 C75,28 90,48 110,22 C130,38 145,18 165,35 C180,25 190,40 200,18",
      "M0,48 C20,32 35,42 55,28 C75,15 90,38 110,26 C130,40 145,22 165,32 C180,18 190,28 200,15"
    ];
    let i = 0;
    setInterval(() => { i = (i + 1) % ps.length; sL.setAttribute('d', ps[i]); sA.setAttribute('d', ps[i] + ' L200,60 L0,60 Z'); }, 3000);
  }

  /* ── Expand buttons ── */
  document.querySelectorAll('.expand-btn').forEach(b => {
    b.addEventListener('click', () => { b.textContent = b.textContent.trim() === '−' ? '+' : '−'; });
  });

  /* ── Build graph ── */
  const gSvg = document.getElementById('viz-graph');
  if (gSvg) buildGraph(gSvg);

  /* ── Counter animation on scroll ── */
  const stats = {
    paths: { el: document.getElementById('stat-paths'), to: 7 },
    interv: { el: document.getElementById('stat-interventions'), to: 2 },
    cost: { el: document.getElementById('stat-cost'), to: 83, suf: '%' }
  };
  let cFired = false;
  const vizSec = document.getElementById('visualizer');
  if (vizSec) {
    const cObs = new IntersectionObserver(entries => {
      entries.forEach(e => {
        if (e.isIntersecting && !cFired) {
          cFired = true;
          Object.values(stats).forEach(s => countUp(s.el, s.to, s.suf));
          cObs.unobserve(vizSec);
        }
      });
    }, { threshold: 0.2 });
    cObs.observe(vizSec);
  }

  /* ─────────────────────────────────────────────
     ENTERPRISE AUTH & REAL PERSISTENT ACCOUNTS
     ───────────────────────────────────────────── */
  const STORAGE_ACCOUNTS_KEY = 'causalcut_accounts';
  const STORAGE_SESSION_KEY = 'causalcut_current_session';

  function initAccounts() {
    try {
      const existing = localStorage.getItem(STORAGE_ACCOUNTS_KEY);
      if (!existing) {
        const defaultAccounts = [
          {
            company: 'Tata Steel Jamshedpur',
            facility: 'Coke Oven Battery 04',
            industry: 'steel',
            adminName: 'Arjun Mehta',
            email: 'shift.officer@steelworks.com',
            password: 'demo-passcode-2026',
            role: 'Senior Shift Officer',
            deployMode: 'onprem',
            createdAt: new Date().toISOString()
          },
          {
            company: 'ArcelorMittal Nippon',
            facility: 'Blast Furnace Unit 02',
            industry: 'steel',
            adminName: 'Sunita Rao',
            email: 'safety.director@steelworks.com',
            password: 'demo-passcode-2026',
            role: 'Lead Safety Manager',
            deployMode: 'cloud',
            createdAt: new Date().toISOString()
          }
        ];
        localStorage.setItem(STORAGE_ACCOUNTS_KEY, JSON.stringify(defaultAccounts));
      }
    } catch (e) {
      console.warn('LocalStorage error:', e);
    }
  }

  function getAccounts() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_ACCOUNTS_KEY) || '[]');
    } catch (e) {
      return [];
    }
  }

  function saveAccount(newAcc) {
    const accs = getAccounts();
    accs.push(newAcc);
    localStorage.setItem(STORAGE_ACCOUNTS_KEY, JSON.stringify(accs));
  }

  function getCurrentSession() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_SESSION_KEY) || 'null');
    } catch (e) {
      return null;
    }
  }

  function setCurrentSession(session) {
    localStorage.setItem(STORAGE_SESSION_KEY, JSON.stringify(session));
  }

  function clearCurrentSession() {
    localStorage.removeItem(STORAGE_SESSION_KEY);
  }

  initAccounts();

  // Modal Elements
  const authModal = document.getElementById('auth-modal');
  const btnCloseAuth = document.getElementById('btn-close-auth');
  const authBackdrop = document.getElementById('auth-backdrop');
  const tabLogin = document.getElementById('tab-login');
  const tabRegister = document.getElementById('tab-register');
  const paneLogin = document.getElementById('pane-login');
  const paneRegister = document.getElementById('pane-register');
  const successScreen = document.getElementById('auth-success-screen');
  const loginAlert = document.getElementById('login-alert');
  const registerAlert = document.getElementById('register-alert');

  function clearAlerts() {
    if (loginAlert) { loginAlert.style.display = 'none'; loginAlert.textContent = ''; }
    if (registerAlert) { registerAlert.style.display = 'none'; registerAlert.textContent = ''; }
  }

  function showLoginAlert(msg, isError = true) {
    if (!loginAlert) return;
    loginAlert.className = isError ? 'auth-alert error' : 'auth-alert info';
    loginAlert.textContent = msg;
    loginAlert.style.display = 'block';
  }

  function showRegisterAlert(msg, isError = true) {
    if (!registerAlert) return;
    registerAlert.className = isError ? 'auth-alert error' : 'auth-alert info';
    registerAlert.textContent = msg;
    registerAlert.style.display = 'block';
  }

  function openAuthModal(initialTab = 'login') {
    if (!authModal) return;
    clearAlerts();
    authModal.classList.add('open');
    authModal.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    switchAuthTab(initialTab);
  }

  function closeAuthModal() {
    if (!authModal) return;
    authModal.classList.remove('open');
    authModal.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
    if (successScreen) successScreen.classList.remove('active');
    clearAlerts();
  }

  function switchAuthTab(tab) {
    clearAlerts();
    if (successScreen) successScreen.classList.remove('active');

    if (tab === 'login') {
      tabLogin?.classList.add('active');
      tabLogin?.setAttribute('aria-selected', 'true');
      tabRegister?.classList.remove('active');
      tabRegister?.setAttribute('aria-selected', 'false');
      paneLogin?.classList.add('active');
      paneRegister?.classList.remove('active');
    } else {
      tabRegister?.classList.add('active');
      tabRegister?.setAttribute('aria-selected', 'true');
      tabLogin?.classList.remove('active');
      tabLogin?.setAttribute('aria-selected', 'false');
      paneRegister?.classList.add('active');
      paneLogin?.classList.remove('active');
    }
  }

  // Bind Open triggers
  document.getElementById('btn-signin')?.addEventListener('click', (e) => {
    e.preventDefault();
    openAuthModal('login');
  });

  document.getElementById('btn-get-started')?.addEventListener('click', () => {
    openAuthModal('register');
  });

  document.getElementById('btn-request-demo')?.addEventListener('click', () => {
    openAuthModal('register');
  });

  document.getElementById('btn-explore')?.addEventListener('click', () => {
    openAuthModal('login');
  });

  // Bind Close triggers
  btnCloseAuth?.addEventListener('click', closeAuthModal);
  authBackdrop?.addEventListener('click', closeAuthModal);

  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && authModal?.classList.contains('open')) {
      closeAuthModal();
    }
  });

  // Tab switching
  tabLogin?.addEventListener('click', () => switchAuthTab('login'));
  tabRegister?.addEventListener('click', () => switchAuthTab('register'));

  // Deployment Model Radio Card Toggles
  document.querySelectorAll('.deploy-radio-card').forEach(card => {
    card.addEventListener('click', () => {
      document.querySelectorAll('.deploy-radio-card').forEach(c => c.classList.remove('active'));
      card.classList.add('active');
      const input = card.querySelector('input[type="radio"]');
      if (input) input.checked = true;
    });
  });

  // 1-Click Demo Profiles Chip Auto-Fill
  document.querySelectorAll('.demo-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const email = chip.getAttribute('data-email');
      const pw = chip.getAttribute('data-password') || 'demo-passcode-2026';
      const emailInput = document.getElementById('login-email');
      const pwInput = document.getElementById('login-password');

      if (emailInput) emailInput.value = email || '';
      if (pwInput) pwInput.value = pw;

      clearAlerts();
      emailInput?.focus();
    });
  });

  // Real Login submission
  const formLogin = document.getElementById('form-login');
  const btnSubmitLogin = document.getElementById('btn-submit-login');

  formLogin?.addEventListener('submit', (e) => {
    e.preventDefault();
    clearAlerts();

    const email = document.getElementById('login-email')?.value.trim().toLowerCase();
    const password = document.getElementById('login-password')?.value;

    if (!email || !password) {
      showLoginAlert('Please enter both your corporate work email and passcode.');
      return;
    }

    const accounts = getAccounts();
    const matchedAccount = accounts.find(a => a.email.toLowerCase() === email);

    if (!matchedAccount) {
      showLoginAlert('No registered facility twin found for this email. Please register your company first.');
      return;
    }

    if (matchedAccount.password !== password) {
      showLoginAlert('Invalid shift passcode. Please re-enter your credential.');
      return;
    }

    const originalText = btnSubmitLogin?.innerHTML || '';
    if (btnSubmitLogin) {
      btnSubmitLogin.disabled = true;
      btnSubmitLogin.innerHTML = `<span class="btn-text">Authenticating Shift Session...</span>`;
    }

    setTimeout(() => {
      if (btnSubmitLogin) {
        btnSubmitLogin.disabled = false;
        btnSubmitLogin.innerHTML = originalText;
      }

      const session = {
        company: matchedAccount.company,
        facility: matchedAccount.facility,
        adminName: matchedAccount.adminName,
        email: matchedAccount.email,
        role: matchedAccount.role,
        deployMode: matchedAccount.deployMode,
        loggedInAt: new Date().toLocaleTimeString()
      };

      setCurrentSession(session);
      applySessionToUI(session);

      showAuthSuccess({
        title: 'Shift Session Authenticated',
        desc: `Welcome back <strong>${matchedAccount.adminName}</strong>. Connected to <strong>${matchedAccount.facility}</strong> at ${matchedAccount.company}.`,
        badge: `ROLE: ${matchedAccount.role.toUpperCase()}`,
        session: session
      });
    }, 600);
  });

  // Real Company Account Registration
  const formRegister = document.getElementById('form-register');
  const btnSubmitRegister = document.getElementById('btn-submit-register');

  formRegister?.addEventListener('submit', (e) => {
    e.preventDefault();
    clearAlerts();

    const company = document.getElementById('reg-company')?.value.trim();
    const facility = document.getElementById('reg-facility')?.value.trim();
    const industry = document.getElementById('reg-industry')?.value;
    const adminName = document.getElementById('reg-admin-name')?.value.trim();
    const email = document.getElementById('reg-admin-email')?.value.trim().toLowerCase();
    const password = document.getElementById('reg-password')?.value;
    const roleSelect = document.getElementById('reg-role');
    const roleText = roleSelect ? roleSelect.options[roleSelect.selectedIndex].text : 'Lead Safety Manager';
    const deployInput = document.querySelector('input[name="deploy_mode"]:checked');
    const deployMode = deployInput ? deployInput.value : 'onprem';

    if (!company || !facility || !adminName || !email || !password) {
      showRegisterAlert('Please fill in all required company and administrator fields.');
      return;
    }

    if (password.length < 6) {
      showRegisterAlert('Security token must be at least 6 characters.');
      return;
    }

    const accounts = getAccounts();
    if (accounts.some(a => a.email.toLowerCase() === email)) {
      showRegisterAlert('An account with this work email already exists. Please Sign In instead.');
      return;
    }

    const originalText = btnSubmitRegister?.innerHTML || '';
    if (btnSubmitRegister) {
      btnSubmitRegister.disabled = true;
      btnSubmitRegister.innerHTML = `<span class="btn-text">Initializing Safety Hypergraph Twin...</span>`;
    }

    setTimeout(() => {
      if (btnSubmitRegister) {
        btnSubmitRegister.disabled = false;
        btnSubmitRegister.innerHTML = originalText;
      }

      const newAccount = {
        company,
        facility,
        industry,
        adminName,
        email,
        password,
        role: roleText,
        deployMode,
        createdAt: new Date().toISOString()
      };

      saveAccount(newAccount);

      const session = {
        company,
        facility,
        adminName,
        email,
        role: roleText,
        deployMode,
        loggedInAt: new Date().toLocaleTimeString()
      };

      setCurrentSession(session);
      applySessionToUI(session);

      showAuthSuccess({
        title: `${company} Twin Provisioned`,
        desc: `Facility <strong>${facility}</strong> successfully linked. Defensive hypergraph twin initialized for <strong>${adminName}</strong>.`,
        badge: `ROLE: ${roleText.toUpperCase()}`,
        session: session
      });
    }, 900);
  });

  function showAuthSuccess({ title, desc, badge }) {
    paneLogin?.classList.remove('active');
    paneRegister?.classList.remove('active');

    const titleEl = document.getElementById('success-title');
    const descEl = document.getElementById('success-desc');
    const badgeEl = document.getElementById('success-badge');

    if (titleEl) titleEl.textContent = title;
    if (descEl) descEl.innerHTML = desc;
    if (badgeEl) badgeEl.textContent = badge;

    successScreen?.classList.add('active');

    const btnEnter = document.getElementById('btn-enter-dashboard');
    if (btnEnter) {
      btnEnter.onclick = () => {
        closeAuthModal();
      };
    }
  }

  function applySessionToUI(session) {
    if (!session) return;

    const navActions = document.querySelector('.nav-actions');
    if (navActions) {
      navActions.innerHTML = `
        <div class="nav-user-badge">
          <span class="user-name">🟢 ${session.adminName || session.email}</span>
          <span class="user-role">${session.company}</span>
          <button type="button" class="btn-logout" id="btn-logout" title="End shift session">Exit</button>
        </div>
      `;

      document.getElementById('btn-logout')?.addEventListener('click', () => {
        clearCurrentSession();
        restoreDefaultNav();
      });
    }

    const unitSector = document.querySelector('.unit-sector');
    if (unitSector && session.facility) {
      unitSector.innerHTML = `${session.facility.toUpperCase()} &mdash; <strong>ONLINE</strong>`;
    }

    const blockLabel = document.querySelector('.block-label');
    if (blockLabel && session.company) {
      blockLabel.textContent = `${session.company.toUpperCase()} &mdash; LIVE SAFETY TWIN`;
    }
  }

  function restoreDefaultNav() {
    const navActions = document.querySelector('.nav-actions');
    if (!navActions) return;

    navActions.innerHTML = `
      <a href="#login" class="nav-signin" id="btn-signin">Sign In</a>
      <button class="btn-get-started" id="btn-get-started">
        Get Started
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
          <path d="M2 12L12 2M12 2H5M12 2V9" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
    `;

    document.getElementById('btn-signin')?.addEventListener('click', (e) => {
      e.preventDefault();
      openAuthModal('login');
    });
    document.getElementById('btn-get-started')?.addEventListener('click', () => {
      openAuthModal('register');
    });

    const unitSector = document.querySelector('.unit-sector');
    if (unitSector) unitSector.innerHTML = `COKE OVEN <strong>BLOCK A</strong>`;

    const blockLabel = document.querySelector('.block-label');
    if (blockLabel) blockLabel.textContent = `LIVE THREAT ANALYSIS`;
  }

  const existingSession = getCurrentSession();
  if (existingSession) {
    applySessionToUI(existingSession);
  }

  // SSO Demos
  document.getElementById('btn-sso-okta')?.addEventListener('click', () => {
    const session = {
      company: 'Enterprise Steel Corp',
      facility: 'Blast Furnace #01',
      adminName: 'SAML Director',
      email: 'director@enterprise.com',
      role: 'Safety Director',
      deployMode: 'cloud',
      loggedInAt: new Date().toLocaleTimeString()
    };
    setCurrentSession(session);
    applySessionToUI(session);
    showAuthSuccess({
      title: 'Okta SAML 2.0 Authenticated',
      desc: 'Enterprise single sign-on confirmed via corporate identity provider.',
      badge: 'SSO ROLE: SAFETY DIRECTOR',
      session: session
    });
  });

  document.getElementById('btn-sso-azure')?.addEventListener('click', () => {
    const session = {
      company: 'Global Metallurgy Ltd',
      facility: 'Rolling Mill Unit 3',
      adminName: 'Azure Engineer',
      email: 'engineer@steelworks.com',
      role: 'Systems Engineer',
      deployMode: 'onprem',
      loggedInAt: new Date().toLocaleTimeString()
    };
    setCurrentSession(session);
    applySessionToUI(session);
    showAuthSuccess({
      title: 'Azure AD / Entra ID Authenticated',
      desc: 'Plant engineer session authorized with role-based security clearance.',
      badge: 'SSO ROLE: SYSTEMS ENGINEER',
      session: session
    });
  });

});

/* ═══════════════ Graph Builder Functions ═══════════════ */
function buildGraph(svg) {
  const N = [
    { id:'src', x:50,  y:200, l:'HAZARD\nSOURCE',   t:'danger' },
    { id:'g',   x:150, y:70,  l:'GAS\nLEAK',        t:'danger' },
    { id:'h',   x:150, y:200, l:'HYDRAULIC\nFAILURE',t:'danger' },
    { id:'p',   x:150, y:330, l:'PERMIT\nERROR',     t:'danger' },
    { id:'v',   x:270, y:110, l:'VENT\nLOSS',        t:'risk' },
    { id:'pr',  x:270, y:240, l:'PRESSURE\nDROP',    t:'risk' },
    { id:'z',   x:270, y:350, l:'ZONE\nBREACH',      t:'risk' },
    { id:'c1',  x:370, y:160, l:'VALVE\nB7',         t:'cut' },
    { id:'c2',  x:370, y:300, l:'REROUTE\nW09',      t:'cut' },
    { id:'f',   x:460, y:100, l:'FIRE',              t:'target' },
    { id:'e',   x:460, y:230, l:'EXPLOSION',         t:'target' },
    { id:'w',   x:460, y:340, l:'INJURY',            t:'target' },
  ];

  const E = [
    { f:'src',to:'g', r:1 }, { f:'src',to:'h', r:1 }, { f:'src',to:'p', r:1 },
    { f:'g',  to:'v', r:1 }, { f:'h',  to:'pr',r:1 }, { f:'p',  to:'z', r:1 },
    { f:'v',  to:'c1',r:1, cut:1 }, { f:'pr', to:'c1',r:1, cut:1 }, { f:'z',  to:'c2',r:1, cut:1 },
    { f:'c1', to:'f' }, { f:'c1', to:'e' }, { f:'c2', to:'w' },
  ];

  const eG = svg.querySelector('#viz-edges');
  const cG = svg.querySelector('#viz-cuts');
  const nG = svg.querySelector('#viz-nodes');
  const lG = svg.querySelector('#viz-labels');
  if (!eG || !cG || !nG || !lG) return;

  const nm = {}; N.forEach(n => nm[n.id] = n);

  // edges
  E.forEach((e, i) => {
    const a = nm[e.f], b = nm[e.to];
    eG.appendChild(mkSvg('line', {
      x1:a.x, y1:a.y, x2:b.x, y2:b.y,
      stroke: e.r ? '#F26522' : '#2D4456',
      'stroke-width': e.r ? 1.8 : 1,
      'stroke-opacity': e.r ? 0.6 : 0.25,
      class: 'edge' + (e.r ? ' edge-risk' : '') + (e.cut ? ' edge-cut' : ''),
      'data-i': i
    }));
  });

  // nodes
  const cols = {
    danger: { f:'#2A1408', s:'#F26522' },
    risk:   { f:'#2A1A08', s:'#F5A623' },
    cut:    { f:'#0F2030', s:'#4A8CB5' },
    target: { f:'#2A0A08', s:'#FF4500' },
  };

  N.forEach(n => {
    const c = cols[n.t] || cols.risk;
    if (n.t === 'danger' || n.t === 'target') {
      nG.appendChild(mkSvg('circle', { cx:n.x, cy:n.y, r:22, fill:'none', stroke:c.s, 'stroke-width':1, class:'glow', opacity:0 }));
    }
    nG.appendChild(mkSvg('circle', { cx:n.x, cy:n.y, r:22, fill:c.f, stroke:c.s, 'stroke-width':1.5, class:'node node-'+n.t }));
    n.l.split('\n').forEach((t, i, a) => {
      lG.appendChild(mkSvg('text', {
        x:n.x, y: n.y + (i - (a.length-1)/2) * 10,
        fill:'#D1D5DB', 'font-family':'Inter,sans-serif', 'font-size':'6.5',
        'font-weight':'600', 'text-anchor':'middle', 'dominant-baseline':'middle',
        'letter-spacing':'0.06em'
      })).textContent = t;
    });
  });

  animateGraph(eG, cG, nm, E.filter(e=>e.cut));
}

function animateGraph(eG, cG, nm, cuts) {
  const rEdges = eG.querySelectorAll('.edge-risk');
  let on = true;
  setInterval(() => {
    on = !on;
    rEdges.forEach(e => {
      if (!e.classList.contains('severed')) e.setAttribute('stroke-opacity', on ? '0.8' : '0.3');
    });
  }, 900);

  document.querySelectorAll('.glow').forEach(g => {
    let gr = true;
    setInterval(() => { gr = !gr; g.setAttribute('r', gr ? '30' : '22'); g.setAttribute('opacity', gr ? '0.3' : '0'); }, 1400);
  });

  const sec = document.getElementById('visualizer');
  let done = false;
  const obs = new IntersectionObserver(entries => {
    entries.forEach(e => {
      if (e.isIntersecting && !done) {
        done = true;
        const statusEl = document.getElementById('graph-status');

        setTimeout(() => {
          eG.querySelectorAll('.edge-cut').forEach(el => {
            el.setAttribute('stroke', '#4A8CB5');
            el.setAttribute('stroke-dasharray', '5 3');
            el.setAttribute('stroke-opacity', '0.8');
            el.classList.add('severed');
          });

          cuts.forEach(ce => {
            const a = nm[ce.f], b = nm[ce.to];
            const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
            cG.appendChild(mkSvg('line', { x1:mx-16, y1:my-12, x2:mx+16, y2:my+12, stroke:'#4A8CB5', 'stroke-width':2.5, 'stroke-linecap':'round' }));
            cG.appendChild(mkSvg('circle', { cx:mx, cy:my, r:4, fill:'#4A8CB5' }));
          });

          eG.querySelectorAll('.edge:not(.edge-risk)').forEach(el => {
            el.setAttribute('stroke-opacity', '0.1');
            el.setAttribute('stroke-dasharray', '3 3');
          });

          setTimeout(() => {
            document.querySelectorAll('.node-target').forEach(n => { n.setAttribute('stroke', '#22C55E'); n.setAttribute('fill', '#0C2818'); });
            if (statusEl) { statusEl.textContent = 'CUT APPLIED'; statusEl.style.color = '#22C55E'; }
          }, 600);

        }, 1500);

        obs.unobserve(sec);
      }
    });
  }, { threshold: 0.25 });
  if (sec) obs.observe(sec);
}

function mkSvg(tag, attrs) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));
  return el;
}

function countUp(el, to, suf) {
  if (!el) return;
  const dur = 1400, st = performance.now();
  (function step(now) {
    const p = Math.min((now - st) / dur, 1);
    const v = Math.round((1 - Math.pow(1 - p, 3)) * to);
    el.innerHTML = suf ? v + '<span class="s3-unit">' + suf + '</span>' : v;
    if (p < 1) requestAnimationFrame(step);
  })(st);
}
