export function youtubeVideoId(uri) {
  try {
    const url = new URL(uri);
    if (!['https:', 'http:'].includes(url.protocol)) return null;
    let id;
    if (['youtu.be', 'www.youtu.be'].includes(url.hostname)) {
      id = url.pathname.split('/')[1];
    } else if (['youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'].includes(url.hostname)) {
      const [, route, value] = url.pathname.split('/');
      id = route === 'watch' ? url.searchParams.get('v')
        : ['embed', 'shorts', 'live'].includes(route) ? value : null;
    }
    return /^[\w-]{11}$/.test(id ?? '') ? id : null;
  } catch { return null; }
}

export function playableVideos(record) {
  const seen = new Set();
  return (record.videos ?? []).flatMap(video => {
    const id = youtubeVideoId(video.uri);
    if (!id || video.embed === false || seen.has(id)) return [];
    seen.add(id);
    return [{ ...video, id }];
  });
}

export function createReleasePlayer({ document = globalThis.document, window = globalThis.window } = {}) {
  const element = id => document.getElementById(id);
  const bar = element('player-bar');
  const pane = element('player-video');
  const toggle = element('player-toggle');
  const next = element('player-next');
  const message = element('player-message');
  // Wrapped titles change the mobile dock height. Keep the video above it.
  if (window.ResizeObserver) {
    new window.ResizeObserver(() => {
      document.documentElement.style.setProperty('--player-bar-height', `${bar.getBoundingClientRect().height}px`);
    }).observe(bar);
  }
  let current = null;
  let youtube = null;
  let ready = false;
  let playing = false;
  let apiPromise = null;
  let initializing = null;
  let revision = 0;

  function render() {
    bar.hidden = pane.hidden = !current;
    document.body.classList.toggle('player-open', !!current);
    if (!current) return;
    const video = current.videos[current.index];
    element('player-title').textContent = video.title || current.record.title;
    element('player-release').textContent = [current.record.artists.join(', '), current.record.title].filter(Boolean).join(' — ');
    element('player-position').textContent = `${current.index + 1}/${current.videos.length}`;
    const external = element('player-youtube');
    external.href = `https://www.youtube.com/watch?v=${video.id}`;
    toggle.disabled = !ready;
    toggle.textContent = playing ? '⏸' : '▶';
    toggle.setAttribute('aria-label', playing ? 'Pause preview' : 'Play preview');
    toggle.title = playing ? 'Pause' : 'Play';
    next.disabled = !ready || current.index >= current.videos.length - 1;
  }

  function loadApi() {
    if (window.YT?.Player) return Promise.resolve(window.YT);
    if (apiPromise) return apiPromise;
    apiPromise = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      let finished = false;
      const previous = window.onYouTubeIframeAPIReady;
      const finish = error => {
        if (finished) return;
        finished = true;
        window.clearTimeout(timeout);
        window.onYouTubeIframeAPIReady = previous;
        if (error) { script.remove(); reject(error); }
        else { resolve(window.YT); previous?.(); }
      };
      const timeout = window.setTimeout(() => finish(new Error('YouTube did not load. Try the cover again or open YouTube.')), 15000);
      window.onYouTubeIframeAPIReady = () => finish();
      script.src = 'https://www.youtube.com/iframe_api';
      script.async = true;
      script.onerror = () => finish(new Error('Could not load YouTube. Try the cover again or open YouTube.'));
      document.head.append(script);
    }).catch(error => { apiPromise = null; throw error; });
    return apiPromise;
  }

  async function ensurePlayer() {
    if (ready) return youtube;
    if (initializing) return initializing;
    initializing = (async () => {
      const YT = await loadApi();
      if (!current) return null;
      return new Promise(resolve => {
        youtube = new YT.Player('youtube-player', {
          width: '100%', height: 200,
          playerVars: { playsinline: 1, origin: window.location.origin, rel: 0 },
          events: {
            onReady(event) {
              youtube = event.target;
              ready = true;
              const iframe = youtube.getIframe();
              iframe.title = 'YouTube release preview';
              iframe.setAttribute('allow', 'autoplay; encrypted-media; picture-in-picture; fullscreen');
              iframe.referrerPolicy = 'strict-origin-when-cross-origin';
              render();
              resolve(youtube);
            },
            onStateChange(event) {
              if (!current) return;
              playing = event.data === 1;
              if (playing) message.textContent = '';
              if (event.data === 0 && current.index < current.videos.length - 1) advance();
              else render();
            },
            onAutoplayBlocked() {
              if (current) { playing = false; message.textContent = 'Press Play to start.'; render(); }
            },
            onError() {
              if (current) {
                playing = false;
                message.textContent = 'Video unavailable. Try Next or open YouTube.';
                render();
              }
            },
          },
        });
      });
    })().finally(() => { initializing = null; });
    return initializing;
  }

  function loadCurrent() {
    if (!current || !ready) return;
    playing = false;
    message.textContent = '';
    youtube.loadVideoById(current.videos[current.index].id);
    render();
  }

  function advance() {
    if (!current || !ready || current.index >= current.videos.length - 1) return;
    current.index++;
    loadCurrent();
  }

  async function play(record) {
    const videos = playableVideos(record);
    if (!videos.length) return;
    const request = ++revision;
    current = { record, videos, index: 0 };
    playing = false;
    message.textContent = ready ? '' : 'Loading YouTube…';
    render();
    try {
      const player = await ensurePlayer();
      if (player && request === revision && current) loadCurrent();
    } catch (error) {
      if (request === revision && current) { message.textContent = error.message; render(); }
    }
  }

  function close() {
    revision++;
    current = null;
    playing = false;
    if (ready) youtube.stopVideo();
    message.textContent = '';
    render();
  }

  toggle.onclick = () => {
    if (!current || !ready) return;
    if (playing) youtube.pauseVideo();
    else youtube.playVideo();
  };
  next.onclick = advance;
  element('player-close').onclick = close;
  render();
  return { play, close };
}
