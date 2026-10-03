let timeElement;
let greetingElement;
let dateElement;
let currentLanguageIndex = 0;
let isFadingGreeting = false;
let isFadingCarousel = false;
let lastPeriod = null;
let themeOverride = null;

const GREETINGS = {
  morning: {
    en: 'Good morning!',
    fr: 'Bonjour !',
    de: 'Guten Morgen!',
    pa: 'ਸ਼ੁਭ ਸਵੇਰ!',
    hi: 'सुप्रभात!',
  },
  afternoon: {
    en: 'Good afternoon!',
    fr: 'Bon après-midi !',
    de: 'Guten Tag!',
    pa: 'ਸ਼ੁਭ ਦੁਪਹਿਰ!',
    hi: 'शुभ दोपहर!',
  },
  evening: {
    en: 'Good evening!',
    fr: 'Bonsoir !',
    de: 'Guten Abend!',
    pa: 'ਸ਼ੁਭ ਸ਼ਾਮ!',
    hi: 'शुभ संध्या!',
  },
  night: {
    en: 'Good night!',
    fr: 'Bonne nuit !',
    de: 'Gute Nacht!',
    pa: 'ਸ਼ੁਭ ਰਾਤ!',
    hi: 'शुभ रात्रि!',
  },
};

const LANGUAGES = ['en', 'fr', 'de', 'pa', 'hi'];

const timeFormatter = new Intl.DateTimeFormat('en-CH', {
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
});

const dateFormatter = new Intl.DateTimeFormat('en-US', {
  month: 'long',
  day: 'numeric',
  year: 'numeric',
});

// Greeter Transition Times:
// - Morning:   0500 to 1200 (05:00 - 11:59)
// - Afternoon: 1200 to 1700 (12:00 - 16:59)
// - Evening:   1700 to 2100 (17:00 - 20:59)
// - Night:     9 PM to 4 AM (21:00 - 04:59)
function getPeriod(hour) {
  if (hour >= 5 && hour < 12) return 'morning';
  if (hour >= 12 && hour < 17) return 'afternoon';
  if (hour >= 17 && hour < 21) return 'evening';
  return 'night';
}

function getGreetingText(languageIndex, hour) {
  const period = getPeriod(hour);
  const lang = LANGUAGES[languageIndex % LANGUAGES.length];
  return GREETINGS[period][lang];
}

function prepareCarouselFade() {
  const stage = document.querySelector('.carousel-stage');
  if (!stage || isFadingCarousel) return null;

  const views = Array.from(stage.querySelectorAll('.carousel-view'));
  if (views.length <= 1) return null;

  const activeIdx = views.findIndex((v) => v.classList.contains('is-active'));
  const currentIdx = activeIdx >= 0 ? activeIdx : 0;
  const nextIdx = (currentIdx + 1) % views.length;

  const currentView = views[currentIdx];
  const nextView = views[nextIdx];

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reducedMotion) {
    currentView.classList.remove('is-active', 'is-fading');
    nextView.classList.add('is-active');
    return null;
  }

  isFadingCarousel = true;

  // Phase 1: Start fading out current view (1.2s) in sync with greeter fade-out
  currentView.classList.add('is-fading');

  return async function finishFadeIn() {
    // Phase 2: Switch views and fade in next view (1.2s) in sync with greeter fade-in
    currentView.classList.remove('is-active', 'is-fading');
    nextView.classList.add('is-active', 'is-fading');
    void nextView.offsetHeight; // Force reflow
    nextView.classList.remove('is-fading');

    await new Promise((resolve) => setTimeout(resolve, 1_200));
    isFadingCarousel = false;
  };
}

async function advanceCarouselSlide() {
  const finish = prepareCarouselFade();
  if (!finish) return;
  await new Promise((resolve) => setTimeout(resolve, 1_200));
  await finish();
}

window.advanceCarouselSlide = advanceCarouselSlide;

async function triggerGreetingCycle() {
  if (!greetingElement || isFadingGreeting) return;

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const nextIndex = (currentLanguageIndex + 1) % LANGUAGES.length;
  const currentHour = mockHour !== null ? mockHour : new Date().getHours();
  const nextText = getGreetingText(nextIndex, currentHour);

  if (reducedMotion) {
    currentLanguageIndex = nextIndex;
    greetingElement.textContent = nextText;
    advanceCarouselSlide();
    return;
  }

  isFadingGreeting = true;

  // Start simultaneous fade-out of greeter AND carousel cards
  const finishCarouselFade = prepareCarouselFade();
  greetingElement.classList.add('is-fading');

  // Wait 1.2s for simultaneous fade-out to complete
  await new Promise((resolve) => setTimeout(resolve, 1_200));

  // Swap greeter text while invisible, and start simultaneous fade-in
  currentLanguageIndex = nextIndex;
  greetingElement.textContent = nextText;
  greetingElement.classList.remove('is-fading');

  const finishPromise = finishCarouselFade ? finishCarouselFade() : Promise.resolve();

  // Wait 1.2s for simultaneous fade-in to complete
  await Promise.all([
    finishPromise,
    new Promise((resolve) => setTimeout(resolve, 1_200)),
  ]);

  isFadingGreeting = false;
}

window.triggerGreetingCycle = triggerGreetingCycle;

let mockTime = null;
let mockHour = null;
let mockMinute = null;
let mockSecond = null;
let mockDate = null;

function updateGreetingAlignment() {
  const clock = document.querySelector('.clock-stack sbb-clock');
  const greeting = document.querySelector('#display-greeting');
  const header = document.querySelector('.display-header');
  if (!clock || !greeting || !header) return;

  const clockRect = clock.getBoundingClientRect();
  const headerRect = header.getBoundingClientRect();
  const clockMidpointY = (clockRect.top + clockRect.height / 2) - headerRect.top;

  header.style.setProperty('--clock-face-midpoint-y', `${clockMidpointY}px`);
}

window.updateGreetingAlignment = updateGreetingAlignment;

function updateColorScheme(override = null) {
  if (override !== null) {
    themeOverride = override;
  }
  const hour = mockHour !== null ? mockHour : new Date().getHours();
  // Auto switch to dark mode at 1800, auto switch to light mode at 0600
  const isDark = themeOverride !== null ? (themeOverride === 'dark') : (hour >= 18 || hour < 6);
  const theme = isDark ? 'dark' : 'light';
  if (document.documentElement.getAttribute('data-theme') !== theme) {
    document.documentElement.setAttribute('data-theme', theme);
    document.documentElement.style.colorScheme = theme;
  }
  const host = document.querySelector('.display-host');
  if (host && host.getAttribute('data-theme') !== theme) {
    host.setAttribute('data-theme', theme);
  }
}

window.updateColorScheme = updateColorScheme;
window.setTheme = (t) => updateColorScheme(t);

function updateClockHands(hours, minutes, seconds = 0) {
  const clock = document.querySelector('.clock-stack sbb-clock');
  if (!clock) return;

  const timeAttr = `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;

  // Declarative only. The component parses `now` itself, stops its animations
  // and renders this static time, so a mocked clock behaves exactly like a
  // native one. We never touch its shadow DOM or private methods.
  clock.setAttribute('now', timeAttr);
  clock.now = timeAttr;
}

function setMockTime(timeStr, dateStr = null) {
  const clock = document.querySelector('.clock-stack sbb-clock');
  if (!timeStr || timeStr === 'reset') {
    mockTime = null;
    mockHour = null;
    mockMinute = null;
    mockSecond = null;
    mockDate = null;
    window.hasMockTime = false;
    window.mockTime = null;
    window.mockHour = null;
    if (clock) {
      // Clearing `now` hands control back to the component: it restarts its own
      // native sweep from the onboard system clock. No private calls needed.
      clock.removeAttribute('now');
      clock.now = null;
    }
    renderTime();
    if (greetingElement) {
      greetingElement.textContent = getGreetingText(currentLanguageIndex, new Date().getHours());
    }
    return { status: 'reset' };
  }

  const parts = String(timeStr).trim().split(':');
  const hours = parseInt(parts[0], 10) || 0;
  const minutes = parseInt(parts[1] || '0', 10);
  const seconds = parseInt(parts[2] || '0', 10);

  mockHour = hours;
  mockMinute = minutes;
  mockSecond = seconds;
  mockTime = `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`;
  window.mockTime = mockTime;
  window.mockHour = mockHour;
  window.hasMockTime = true;

  if (dateStr) {
    mockDate = dateStr;
    window.mockDate = mockDate;
  }

  if (timeElement) {
    timeElement.textContent = mockTime;
  }
  if (dateElement && mockDate) {
    dateElement.textContent = mockDate;
  }

  updateColorScheme();
  if (greetingElement) {
    greetingElement.textContent = getGreetingText(currentLanguageIndex, mockHour);
  }
  updateClockHands(hours, minutes, seconds);

  return {
    status: 'ok',
    time: mockTime,
    hour: mockHour,
    minute: mockMinute,
    theme: document.documentElement.getAttribute('data-theme'),
    period: getPeriod(mockHour),
    greeting: greetingElement ? greetingElement.textContent : null,
  };
}

window.setMockTime = setMockTime;

let serverTimeOffsetMs = 0;
let isSyncingTime = false;
let backendMockApplied = false;
let lastRenderedSecond = -1;

// A round trip this slow means the sample is noise rather than drift: the
// browser and the server share the same onboard clock, so a large RTT cannot be
// trusted to refine the offset and is discarded instead.
const MAX_SYNC_RTT_MS = 2000;

async function syncServerTime() {
  if (isSyncingTime) return;
  isSyncingTime = true;
  try {
    const t0 = performance.now();
    const res = await fetch('/api/time', { cache: 'no-store' });
    const t1 = performance.now();
    if (!res.ok) return;
    const data = await res.json();
    const rtt = t1 - t0;

    const urlParams = new URLSearchParams(window.location.search);
    const hasUrlMock = Boolean(urlParams.get('time') || window.INITIAL_MOCK_TIME);

    // If backend reports mock_time and URL hasn't set one
    if (data.mock_time && !hasUrlMock) {
      backendMockApplied = true;
      setMockTime(data.mock_time, data.mock_date);
    } else if (backendMockApplied && !data.mock_time && !hasUrlMock) {
      backendMockApplied = false;
      setMockTime('reset');
    }

    if (!data.mock_time && !mockTime && Number.isFinite(data.timestamp) && rtt <= MAX_SYNC_RTT_MS) {
      // RTT/2 compensation against the server's onboard-clock timestamp.
      const nextOffset = data.timestamp * 1000 + rtt / 2 - Date.now();
      if (Math.abs(nextOffset - serverTimeOffsetMs) >= 1) {
        // A material step (for example an NTP correction): repaint immediately
        // instead of waiting for the next tick.
        lastRenderedSecond = -1;
      }
      serverTimeOffsetMs = nextOffset;
    }
  } catch (err) {
    // Graceful fallback to client time if server API is temporarily unreachable
  } finally {
    isSyncingTime = false;
  }
}

window.syncServerTime = syncServerTime;

function renderTime() {
  if (!timeElement || !greetingElement) return;

  if (mockTime !== null) {
    timeElement.textContent = mockTime;
    if (dateElement && mockDate) {
      dateElement.textContent = mockDate;
    }
    updateColorScheme();
    updateClockHands(mockHour, mockMinute, mockSecond || 0);
    return;
  }

  // Live wall-clock time, corrected against the server, which follows the
  // onboard system clock (the lab's time authority).
  //
  // CRITICAL: do NOT touch the <sbb-clock> element here. It renders the analogue
  // face itself, straight from the onboard clock, using its native Lit/CSS
  // keyframes. Writing its `now` attribute or its shadow-DOM hands from here
  // knocks the tick off, so live mode leaves it completely alone.
  const now = new Date(Date.now() + serverTimeOffsetMs);
  const currentSecond = now.getSeconds();
  if (currentSecond === lastRenderedSecond) {
    return;
  }
  lastRenderedSecond = currentSecond;

  timeElement.textContent = timeFormatter.format(now);
  if (dateElement) {
    dateElement.textContent = dateFormatter.format(now);
  }

  updateColorScheme();

  const currentPeriod = getPeriod(now.getHours());
  if (lastPeriod === null) {
    lastPeriod = currentPeriod;
  } else if (lastPeriod !== currentPeriod) {
    lastPeriod = currentPeriod;
    triggerGreetingCycle();
  }
}

async function bindDisplayElements() {
  while (
    !document.querySelector('#digital-time') ||
    !document.querySelector('#display-greeting') ||
    !document.querySelector('.clock-stack sbb-clock') ||
    !document.querySelector('#clock-date')
  ) {
    await new Promise(requestAnimationFrame);
  }
  timeElement = document.querySelector('#digital-time');
  greetingElement = document.querySelector('#display-greeting');
  dateElement = document.querySelector('#clock-date');
}

function updateGridLayout(grid) {
  if (!grid) return;
  const count = grid.querySelectorAll(':scope > .person-card').length;

  grid.classList.remove(
    'people-grid--1row',
    'people-grid--2rows',
    'people-grid--3rows',
    'people-grid--standard',
    'people-grid--compact',
    'people-grid--dense'
  );

  if (count <= 4) {
    grid.classList.add('people-grid--1row');
  } else if (count <= 8) {
    grid.classList.add('people-grid--2rows');
  } else {
    grid.classList.add('people-grid--3rows');
  }
}

let alertQueue = [];
let isDisplayingAlert = false;
let currentAlertStartTime = 0;
let currentAlertTimer = null;
let seenEventIds = new Set();
let lastSeenEventId = 0;

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

const SBB_BUILTIN_ICONS = {
  'entrance-medium': '<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" fill="none" viewBox="0 0 36 36"><path fill="#000" fill-rule="evenodd" d="M5.25 6.25h-.5v23.5h19V25.5h-1v3.25h-17V7.25h17v3.25h1V6.25H5.25m5.66 12.147 4.712-4.724.708.706-3.86 3.871h19.045v1H12.473l3.857 3.858-.707.707-4.712-4.712-.353-.353z" clip-rule="evenodd"/></svg>',
  'entrance-small': '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24"><path fill="#000" fill-rule="evenodd" d="M3.5 4H3v16h13v-3h-1v2H4V5h11v2h1V4H3.5m3.656 8.147 3.14-3.15.709.707L8.715 12H21.01v1H8.717l2.287 2.287-.707.707-3.14-3.14-.354-.354z" clip-rule="evenodd"/></svg>',
  'exit-medium': '<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" fill="none" viewBox="0 0 36 36"><path fill="#000" fill-rule="evenodd" d="M5.25 6.25h-.5v23.5h19V25.5h-1v3.25h-17V7.25h17v3.25h1V6.25H5.25m21.141 7.435 4.713 4.711.353.354-.352.353-4.713 4.724-.708-.707 3.861-3.87H10.5v-1h19.043l-3.859-3.858z" clip-rule="evenodd"/></svg>',
  'exit-small': '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24"><path fill="#000" fill-rule="evenodd" d="M3.5 4H3v16h13v-3h-1v2H4V5h11v2h1V4H3.5m14.212 5.005 3.142 3.141.353.354-.353.353-3.142 3.15-.707-.707L19.295 13H7v-1h12.293l-2.288-2.287z" clip-rule="evenodd"/></svg>',
  'cross-small': '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24"><path fill="#000" fill-rule="evenodd" d="m12.707 12 5.647-5.647-.707-.707L12 11.293 6.354 5.646l-.708.707L11.293 12l-5.647 5.646.708.707L12 12.707l5.647 5.646.707-.707z" clip-rule="evenodd"/></svg>'
};

if (typeof globalThis !== 'undefined') {
  globalThis.sbbConfig = globalThis.sbbConfig || {};
  globalThis.sbbConfig.icon = globalThis.sbbConfig.icon || {};
  if (!globalThis.sbbConfig.icon.interceptor) {
    globalThis.sbbConfig.icon.interceptor = function(context) {
      if (context && context.name && SBB_BUILTIN_ICONS[context.name]) {
        return SBB_BUILTIN_ICONS[context.name];
      }
      return typeof context.request === 'function' ? context.request() : Promise.resolve('');
    };
  }
}

function renderAlertCard(event) {
  const isSmallScreen = window.innerWidth < 640;
  const isOut = event.type === 'OUT';
  const iconName = isOut
    ? (isSmallScreen ? 'exit-small' : 'exit-medium')
    : (isSmallScreen ? 'entrance-small' : 'entrance-medium');
  const person = event.person || {};
  const name = person.name || 'User';
  const photo = person.photo || '/static/portraits/default.svg';
  const access = Array.isArray(person.access) ? person.access : [];
  const checkIn = event.check_in || person.checked_in || '--:--';
  const checkOut = event.check_out || '--:--';

  const toolCount = access.length;
  const chipsHtml = access
    .map((tool) => `<sbb-chip-label size="s">${escapeHtml(tool)}</sbb-chip-label>`)
    .join('');

  const svgFallback = SBB_BUILTIN_ICONS[iconName] || '';

  return `
    <div class="auth-alert-card" role="document">
      <div class="alert-card-bar">
        <span class="alert-bar-label">${escapeHtml(event.type)}</span>
        <sbb-icon name="${iconName}" class="alert-bar-icon" aria-hidden="true">${svgFallback}</sbb-icon>
      </div>
      <div class="alert-card-content">
        <div class="card-id-header">
          <figure class="person-photo sbb-figure">
            <sbb-image image-src="${escapeHtml(photo)}" alt="Portrait of ${escapeHtml(name)}" class="sbb-image-1-1"></sbb-image>
          </figure>
          <sbb-title level="2" visual-level="3" class="person-name">${escapeHtml(name)}</sbb-title>
        </div>
        <div class="alert-card-body">
          <div class="check-in">
            <span class="check-in-label">Check-in time</span>
            <time class="check-in-time" datetime="${escapeHtml(checkIn)}">${escapeHtml(checkIn)}</time>
          </div>
          ${
            isOut
              ? `
          <div class="check-out">
            <span class="check-out-label">Check-out time</span>
            <time class="check-out-time" datetime="${escapeHtml(checkOut)}">${escapeHtml(checkOut)}</time>
          </div>`
              : ''
          }
          <div class="access-list access-list--grid access-list--tools-${Math.min(toolCount, 4)}">
            ${chipsHtml}
          </div>
        </div>
      </div>
    </div>
  `;
}

function processAlertQueue() {
  const overlay = document.querySelector('#auth-alert-overlay');
  const frame = document.querySelector('.display-frame');
  if (!overlay) return;

  if (alertQueue.length === 0) {
    const card = overlay.querySelector('.auth-alert-card');
    if (card) {
      card.classList.remove('is-active');
    }
    overlay.classList.remove('is-active');
    if (frame) frame.classList.remove('is-dimmed');

    clearTimeout(currentAlertTimer);
    currentAlertTimer = setTimeout(() => {
      overlay.hidden = true;
      overlay.innerHTML = '';
      isDisplayingAlert = false;
      // Reconcile any presence change that happened behind the alert, in place.
      refreshPresence();
    }, 350);
    return;
  }

  isDisplayingAlert = true;
  clearTimeout(currentAlertTimer);

  const event = alertQueue.shift();
  overlay.hidden = false;
  overlay.innerHTML = renderAlertCard(event);

  void overlay.offsetHeight;
  overlay.classList.add('is-active');
  const card = overlay.querySelector('.auth-alert-card');
  if (card) {
    void card.offsetHeight;
    card.classList.add('is-active');
  }
  if (frame) {
    frame.classList.add('is-dimmed');
  }

  currentAlertStartTime = Date.now();
  // If there are more bunched-up events in the queue, show for 1 second; otherwise full 5 seconds.
  const displayDuration = alertQueue.length > 0 ? 1_000 : 5_000;

  currentAlertTimer = setTimeout(() => {
    processAlertQueue();
  }, displayDuration);
}

function handleAuthEvent(event) {
  if (!event || !event.type || !event.person) return;
  if (event.id) {
    if (seenEventIds.has(event.id)) {
      return;
    }
    seenEventIds.add(event.id);
    if (event.id > lastSeenEventId) {
      lastSeenEventId = event.id;
    }
    if (seenEventIds.size > 200) {
      const arr = Array.from(seenEventIds);
      seenEventIds = new Set(arr.slice(-100));
    }
  }
  alertQueue.push(event);

  if (!isDisplayingAlert) {
    processAlertQueue();
  } else {
    // Event arrived while another alert is on screen: accelerate remaining time to 1 second
    const elapsed = Date.now() - currentAlertStartTime;
    const remaining = Math.max(0, 1_000 - elapsed);
    clearTimeout(currentAlertTimer);
    currentAlertTimer = setTimeout(() => {
      processAlertQueue();
    }, remaining);
  }
}

async function pollAuthEvents() {
  try {
    const res = await fetch(`/api/presence/events?since=${lastSeenEventId}`);
    if (!res.ok) return;
    const data = await res.json();
    if (data && Array.isArray(data.events)) {
      for (const evt of data.events) {
        handleAuthEvent(evt);
      }
    }
  } catch (err) {
    // Network hiccup ignored
  }
}

window.handleAuthEvent = handleAuthEvent;
window.showAuthAlert = handleAuthEvent;
window.getAlertQueue = () => alertQueue;
window.pollAuthEvents = pollAuthEvents;

window.setTestOccupants = function (count) {
  const section = document.querySelector('.current-presence, .presence');
  if (!section) return;
  const existingContent = section.querySelector('.people-grid, .carousel-stage');
  if (existingContent) existingContent.remove();

  const samplePerson = (i) => ({
    name: `User ${i + 1}`,
    photo: '/static/portraits/default.svg',
    checked_in: `09:${String(10 + i).padStart(2, '0')}`,
    access: ['Lab interior', 'Tool area'],
  });

  const createCard = (p, density) => {
    const spacing = density === '3rows' ? 'sbb-card-spacing-4x-xxs' : 'sbb-card-spacing-xxs';
    const visualLevel = density === '3rows' ? 5 : density === '2rows' ? 4 : 3;
    const toolCount = p.access.length;
    const chipsHtml = p.access.map((tool) => `<sbb-chip-label size="${density === '3rows' ? 'xs' : 's'}">${tool}</sbb-chip-label>`).join('');
    return `
      <sbb-card color="transparent-bordered" class="person-card person-card--${density} person-card--tools-${Math.min(toolCount, 4)} ${spacing}">
        <div class="card-id-header">
          <figure class="person-photo sbb-figure">
            <sbb-image image-src="${p.photo}" alt="Portrait of ${p.name}" class="sbb-image-1-1"></sbb-image>
          </figure>
          <sbb-title level="2" visual-level="${visualLevel}" class="person-name">${p.name}</sbb-title>
        </div>
        <div class="card-id-body">
          <div class="check-in">
            <span class="check-in-label">Check-in time</span>
            <time class="check-in-time" datetime="${p.checked_in}">${p.checked_in}</time>
          </div>
          <div class="access-list access-list--grid access-list--tools-${Math.min(toolCount, 4)}">
            ${chipsHtml}
          </div>
        </div>
      </sbb-card>
    `;
  };

  if (count <= 12) {
    const density = count <= 4 ? '1row' : count <= 8 ? '2rows' : '3rows';
    const cardsHtml = Array.from({ length: count }, (_, i) => createCard(samplePerson(i), density)).join('');
    const gridHtml = `<div class="people-grid people-grid--${density}">${cardsHtml}</div>`;
    section.insertAdjacentHTML('beforeend', gridHtml);
  } else {
    const pagesCount = Math.ceil(count / 8);
    let viewsHtml = '';
    for (let p = 0; p < pagesCount; p++) {
      const pagePeople = Array.from({ length: Math.min(8, count - p * 8) }, (_, i) => samplePerson(p * 8 + i));
      const row1 = pagePeople.slice(0, 4).map((person) => createCard(person, '2rows')).join('');
      const row2 = pagePeople.slice(4, 8).map((person) => createCard(person, '2rows')).join('');
      viewsHtml += `
        <div class="carousel-view ${p === 0 ? 'is-active' : ''}" data-page="${p}">
          <div class="carousel-row carousel-row--top">${row1}</div>
          <div class="carousel-row carousel-row--bottom">${row2}</div>
        </div>
      `;
    }
    section.insertAdjacentHTML('beforeend', `<div class="carousel-stage">${viewsHtml}</div>`);
  }
};

// --- In-place synchronisation (no full-page reload) -------------------------
//
// The display previously hard-reloaded on an interval to keep the analogue
// clock and the presence cards fresh. That reload was visually jarring. Both are
// now kept correct in place by:
//   * ticking the digital clock against server-corrected time,
//   * asking the SBB clock to restart its native animation when needed,
//   * reconciling the presence cards against the server-rendered markup.
let lastPresenceSignature =
  typeof window.INITIAL_PRESENCE_SIGNATURE === 'string'
    ? window.INITIAL_PRESENCE_SIGNATURE
    : null;
let lastAnalogueResync = Date.now();

window.setPresenceSignature = (signature) => {
  if (typeof signature === 'string') lastPresenceSignature = signature;
};
window.getPresenceSignature = () => lastPresenceSignature;

/**
 * Selective refresh of the analogue clock face.
 *
 * This uses ONLY the component's inbuilt reset (`_resetClock`), which re-arms
 * the native animation from the current system time. We deliberately never
 * replace the node, never set its `now` attribute and never write to its shadow
 * DOM, so the native keyframe sweep — and therefore the tick — stays exactly as
 * SBB ships it. If the inbuilt method is unavailable we do nothing at all: the
 * component already re-arms itself on `visibilitychange` and on its own
 * internal interval.
 */
function resyncAnalogueClock() {
  const clock = document.querySelector('.clock-stack sbb-clock');
  if (!clock) return;

  if (mockTime !== null) {
    // An explicit mock override; re-apply it through the existing path.
    setMockTime(mockTime, mockDate);
    return;
  }

  if (typeof clock._resetClock === 'function') {
    clock._resetClock();
  }
}

/**
 * Re-align the clock parts we own (#digital-time, #clock-date, theme, greeting)
 * against server time, and refresh the analogue face via its inbuilt reset.
 */
async function resyncClock() {
  await syncServerTime();
  resyncAnalogueClock();
  lastRenderedSecond = -1;
  renderTime();
  lastAnalogueResync = Date.now();
}

/** Pull the server-rendered card markup when the presence signature changes. */
async function refreshPresence() {
  try {
    const res = await fetch('/api/presence/render');
    if (!res.ok) return;
    const data = await res.json();
    if (!data || typeof data.signature !== 'string') return;
    if (data.signature === lastPresenceSignature) return;
    lastPresenceSignature = data.signature;
    const wrapper = document.querySelector('.presence-content-wrapper');
    if (wrapper && typeof data.html === 'string') {
      wrapper.innerHTML = data.html;
      updateGreetingAlignment();
    }
  } catch (err) {
    // Network hiccup: the next tick retries.
  }
}

window.resyncClock = resyncClock;
window.refreshPresence = refreshPresence;

function startUnthrottledTimer(onTick) {
  try {
    const workerBlob = new Blob([`
      let timerId = null;
      self.onmessage = function(e) {
        if (e.data === 'start') {
          if (!timerId) {
            timerId = setInterval(function() {
              self.postMessage('tick');
            }, 250);
          }
        } else if (e.data === 'stop') {
          if (timerId) {
            clearInterval(timerId);
            timerId = null;
          }
        }
      };
    `], { type: 'application/javascript' });
    const workerUrl = URL.createObjectURL(workerBlob);
    const worker = new Worker(workerUrl);
    worker.onmessage = function(e) {
      if (e.data === 'tick') {
        onTick();
      }
    };
    worker.postMessage('start');
    return worker;
  } catch (err) {
    console.warn('Web Worker timer unavailable, falling back to setInterval:', err);
    const interval = setInterval(onTick, 250);
    return {
      postMessage: function(msg) {
        if (msg === 'stop') clearInterval(interval);
      }
    };
  }
}

async function start() {
  await bindDisplayElements();
  await syncServerTime();

  const urlParams = new URLSearchParams(window.location.search);
  const initialTime = window.INITIAL_MOCK_TIME || urlParams.get('time');
  const initialDate = window.INITIAL_MOCK_DATE || urlParams.get('date');

  if (initialTime) {
    setMockTime(initialTime, initialDate);
  } else {
    const nowHour = new Date(Date.now() + serverTimeOffsetMs).getHours();
    greetingElement.textContent = getGreetingText(currentLanguageIndex, nowHour);
    renderTime();
  }

  updateGreetingAlignment();
  window.addEventListener('resize', updateGreetingAlignment);

  // Re-align the clock and cards when the tab returns to view after being
  // hidden, instead of reloading the whole page.
  let hiddenAt = document.hidden ? Date.now() : 0;

  const recoverDisplay = () => {
    const hiddenFor = hiddenAt > 0 ? Date.now() - hiddenAt : 0;
    hiddenAt = 0;
    if (hiddenFor >= 5_000 || Date.now() - lastAnalogueResync >= 30_000) {
      resyncClock();
      refreshPresence();
    }
  };

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      hiddenAt = Date.now();
    } else {
      recoverDisplay();
    }
  });

  window.addEventListener('focus', () => {
    if (hiddenAt === 0) recoverDisplay();
  });

  const testAlert = urlParams.get('test_alert');
  if (testAlert === 'in') {
    handleAuthEvent({
      type: 'IN',
      person: {
        name: urlParams.get('name') || 'Elena Rossi',
        photo: urlParams.get('photo') || '/static/portraits/default.svg',
        checked_in: urlParams.get('in_time') || '09:15',
        access: ['Lab interior', 'CNC mill', 'Laser cutter'],
      },
      check_in: urlParams.get('in_time') || '09:15',
    });
  } else if (testAlert === 'out') {
    handleAuthEvent({
      type: 'OUT',
      person: {
        name: urlParams.get('name') || 'Elena Rossi',
        photo: urlParams.get('photo') || '/static/portraits/default.svg',
        checked_in: urlParams.get('in_time') || '09:15',
        access: ['Lab interior', 'CNC mill', 'Laser cutter'],
      },
      check_in: urlParams.get('in_time') || '09:15',
      check_out: urlParams.get('out_time') || '17:30',
    });
  } else if (window.INITIAL_AUTH_EVENT) {
    handleAuthEvent(window.INITIAL_AUTH_EVENT);
  } else {
    try {
      const res = await fetch('/api/presence/events');
      if (res.ok) {
        const data = await res.json();
        if (data.events && data.events.length > 0) {
          for (const e of data.events) {
            if (e.id) {
              seenEventIds.add(e.id);
              if (e.id > lastSeenEventId) lastSeenEventId = e.id;
            }
          }
        }
      }
    } catch (e) {}
  }

  // Replace standard window intervals with unthrottled Web Worker ticks (every 250ms)
  let lastPollTime = 0;
  let lastGreetingTime = 0;
  let lastSyncTime = Date.now();
  let lastPresenceRefresh = Date.now();

  startUnthrottledTimer(() => {
    const nowTimestamp = Date.now();

    // 1. Digital clock & date update
    renderTime();

    // 2. Presence reconciliation against server-rendered markup (every 30s)
    if (nowTimestamp - lastPresenceRefresh >= 30_000) {
      lastPresenceRefresh = nowTimestamp;
      refreshPresence();
    }

    // 3. Presence events polling (every 400ms)
    if (nowTimestamp - lastPollTime >= 400) {
      lastPollTime = nowTimestamp;
      pollAuthEvents();
    }

    // 4. Greeting cycle (every 10s)
    if (nowTimestamp - lastGreetingTime >= 10_000) {
      lastGreetingTime = nowTimestamp;
      triggerGreetingCycle();
    }

    // 5. Server time re-sync (every 15s)
    if (nowTimestamp - lastSyncTime >= 15_000) {
      lastSyncTime = nowTimestamp;
      syncServerTime();
    }
  });
}

start();
