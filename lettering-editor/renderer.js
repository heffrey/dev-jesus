(function () {
  const api = window.letteringApi;
  if (!api) return;

  const projectRootDisplay = document.getElementById('project-root-display');
  const btnProject = document.getElementById('btn-project');
  const storySelect = document.getElementById('story-select');
  const imageSelect = document.getElementById('image-select');
  const btnPrevImage = document.getElementById('btn-prev-image');
  const btnNextImage = document.getElementById('btn-next-image');
  const btnSave = document.getElementById('btn-save');
  const btnOverlay = document.getElementById('btn-overlay');
  const showLetteredCheckbox = document.getElementById('show-lettered');
  const overlayStatus = document.getElementById('overlay-status');
  const editorMain = document.getElementById('editor-main');
  const editorScaleContainer = document.getElementById('editor-scale-container');
  const editorWrap = document.getElementById('editor-wrap');
  const editorContainer = document.getElementById('editor-container');
  const boardImage = document.getElementById('board-image');
  const quadrantsEl = document.getElementById('quadrants');
  const gridOverlay = document.getElementById('grid-overlay');

  function fitComicToView() {
    if (!editorMain || !editorScaleContainer || !editorWrap || !boardImage) return;
    const nw = boardImage.naturalWidth;
    const nh = boardImage.naturalHeight;
    if (!nw || !nh) {
      editorScaleContainer.style.width = '';
      editorScaleContainer.style.height = '';
      editorWrap.style.width = '';
      editorWrap.style.height = '';
      editorWrap.style.transform = '';
      boardImage.style.width = '';
      boardImage.style.height = '';
      return;
    }
    const rect = editorMain.getBoundingClientRect();
    const w = Math.max(1, rect.width - 32);
    const h = Math.max(1, rect.height - 32);
    const scale = Math.min(w / nw, h / nh, 1);
    editorWrap.style.width = nw + 'px';
    editorWrap.style.height = nh + 'px';
    editorWrap.style.transform = 'scale(' + scale + ')';
    editorWrap.style.transformOrigin = 'top left';
    editorScaleContainer.style.width = (nw * scale) + 'px';
    editorScaleContainer.style.height = (nh * scale) + 'px';
    boardImage.style.width = nw + 'px';
    boardImage.style.height = nh + 'px';
  }

  const DEFAULT_SETTING_RECT = [0.05, 0.025, 0.95, 0.075];
  const DEFAULT_DIALOGUE_RECT = [0.05, 0.1, 0.95, 0.4];
  const DEFAULT_NARRATIVE_RECT = [0.05, 0.65, 0.95, 0.95];
  const MIN_BOX_SIZE = 0.04;
  const SNAP_GRID = 0.025;
  const SNAP_ALIGN_THRESHOLD = 0.0125;
  const SNAP_GUIDES = [0, 0.5, 1];

  let projectRoot = null;
  let currentStory = null;
  let currentImage = null;
  let boardImages = [];
  let letteringData = null;
  let definitions = null;
  let dragState = null;
  let resizeState = null;

  function setStatus(msg, isError) {
    overlayStatus.textContent = msg || '';
    overlayStatus.classList.toggle('error', !!isError);
  }

  function buildLetteringFromScene() {
    return {
      setting_label: '',
      setting_rect: DEFAULT_SETTING_RECT.slice(),
      panels: [0, 1, 2, 3].map(() => ({
        narrative: '',
        dialogue: '',
        narrative_rect: DEFAULT_NARRATIVE_RECT.slice(),
        dialogue_rect: DEFAULT_DIALOGUE_RECT.slice(),
      })),
    };
  }

  function mergeWithLoaded(loaded, rectReference) {
    const base = buildLetteringFromScene();
    if (!loaded || !loaded.panels) return base;
    base.setting_label = loaded.setting_label != null ? String(loaded.setting_label) : '';
    base.setting_rect = (rectReference && rectReference.setting_rect && rectReference.setting_rect.length >= 4)
      ? rectReference.setting_rect.slice()
      : (loaded.setting_rect && loaded.setting_rect.length >= 4 ? loaded.setting_rect.slice() : base.setting_rect);
    for (let i = 0; i < 4 && i < loaded.panels.length; i++) {
      const p = loaded.panels[i];
      base.panels[i].narrative = p.narrative != null ? String(p.narrative) : '';
      base.panels[i].dialogue = p.dialogue != null ? String(p.dialogue) : '';
      const ref = rectReference && rectReference.panels && rectReference.panels[i];
      base.panels[i].narrative_rect = (ref && ref.narrative_rect && ref.narrative_rect.length >= 4)
        ? ref.narrative_rect.slice()
        : (p.narrative_rect && p.narrative_rect.length >= 4 ? p.narrative_rect.slice() : base.panels[i].narrative_rect);
      base.panels[i].dialogue_rect = (ref && ref.dialogue_rect && ref.dialogue_rect.length >= 4)
        ? ref.dialogue_rect.slice()
        : (p.dialogue_rect && p.dialogue_rect.length >= 4 ? p.dialogue_rect.slice() : base.panels[i].dialogue_rect);
    }
    return base;
  }

  function clampRect(rect) {
    const [l, t, r, b] = rect;
    let left = Math.max(0, Math.min(1, l));
    let top = Math.max(0, Math.min(1, t));
    let right = Math.max(left + MIN_BOX_SIZE, Math.min(1, r));
    let bottom = Math.max(top + MIN_BOX_SIZE, Math.min(1, b));
    return [left, top, right, bottom];
  }

  function snapToGrid(v) {
    return Math.round(v / SNAP_GRID) * SNAP_GRID;
  }

  function getOtherRectsInQuadrant(quadrant, excludeBox) {
    const rects = [];
    quadrant.querySelectorAll('.text-box').forEach((box) => {
      if (box === excludeBox) return;
      rects.push(getRectFromBox(box));
    });
    return rects;
  }

  function snapValueToGuidesAndRects(value, guides, otherEdges) {
    for (const g of guides) {
      if (Math.abs(value - g) <= SNAP_ALIGN_THRESHOLD) return g;
    }
    for (const edge of otherEdges) {
      if (Math.abs(value - edge) <= SNAP_ALIGN_THRESHOLD) return edge;
    }
    return value;
  }

  function snapRect(rect, quadrant, excludeBox) {
    let [left, top, right, bottom] = rect;
    const afterGuide = [left, top, right, bottom];
    const others = getOtherRectsInQuadrant(quadrant, excludeBox);
    const allLeft = others.flatMap((r) => [r[0]]).concat(SNAP_GUIDES);
    const allRight = others.flatMap((r) => [r[2]]).concat(SNAP_GUIDES);
    const allTop = others.flatMap((r) => [r[1]]).concat(SNAP_GUIDES);
    const allBottom = others.flatMap((r) => [r[3]]).concat(SNAP_GUIDES);

    left = snapValueToGuidesAndRects(left, SNAP_GUIDES, allLeft);
    right = snapValueToGuidesAndRects(right, SNAP_GUIDES, allRight);
    top = snapValueToGuidesAndRects(top, SNAP_GUIDES, allTop);
    bottom = snapValueToGuidesAndRects(bottom, SNAP_GUIDES, allBottom);
    afterGuide[0]=left;afterGuide[1]=top;afterGuide[2]=right;afterGuide[3]=bottom;

    left = snapToGrid(left);
    top = snapToGrid(top);
    right = snapToGrid(right);
    bottom = snapToGrid(bottom);

    right = Math.max(left + MIN_BOX_SIZE, right);
    bottom = Math.max(top + MIN_BOX_SIZE, bottom);
    left = Math.max(0, Math.min(1, left));
    top = Math.max(0, Math.min(1, top));
    right = Math.max(left + MIN_BOX_SIZE, Math.min(1, right));
    bottom = Math.max(top + MIN_BOX_SIZE, Math.min(1, bottom));
    // #region agent log
    const gridChanged = (afterGuide[0]!==left||afterGuide[1]!==top||afterGuide[2]!==right||afterGuide[3]!==bottom);
    if (gridChanged) {
      fetch('http://127.0.0.1:7245/ingest/f4b8e3b3-a186-4c7c-a9f9-a946dace6f70',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'renderer.js:snapRect',message:'grid changed after guide',data:{rectIn:[...rect],afterGuide:[...afterGuide],out:[left,top,right,bottom]},timestamp:Date.now(),hypothesisId:'H3'})}).catch(()=>{});
    }
    // #endregion
    return [left, top, right, bottom];
  }

  function createBox(quadrantIndex, kind, rect, placeholder, className) {
    const [left, top, right, bottom] = rect;
    const div = document.createElement('div');
    div.className = 'text-box ' + className;
    div.dataset.quadrant = String(quadrantIndex);
    div.dataset.kind = kind;
    div.style.left = (left * 100) + '%';
    div.style.top = (top * 100) + '%';
    div.style.width = ((right - left) * 100) + '%';
    div.style.height = ((bottom - top) * 100) + '%';

    const dragHandle = document.createElement('div');
    dragHandle.className = 'drag-handle';
    div.appendChild(dragHandle);

    const textarea = document.createElement('textarea');
    textarea.placeholder = placeholder;
    textarea.value = '';
    div.appendChild(textarea);

    /* Edge strips first (n,s,e,w), then corners on top so corner wins when clicking corner */
    const handles = ['n', 's', 'e', 'w', 'nw', 'ne', 'sw', 'se'];
    handles.forEach(h => {
      const handle = document.createElement('div');
      handle.className = 'resize-handle ' + h;
      handle.dataset.handle = h;
      div.appendChild(handle);
    });

    return div;
  }

  function getRectFromBox(box) {
    const l = parseFloat(box.style.left) / 100;
    const t = parseFloat(box.style.top) / 100;
    const w = parseFloat(box.style.width) / 100;
    const h = parseFloat(box.style.height) / 100;
    return [l, t, l + w, t + h];
  }

  /** Expand narrative/dialogue box height so all text is visible (no scrollbar). Updates rect. WYSIWYG. */
  function fitBoxHeightToContent(box) {
    const kind = box.dataset.kind;
    if (kind !== 'narrative' && kind !== 'dialogue') return;
    const textarea = box.querySelector('textarea');
    if (!textarea || textarea.scrollHeight <= textarea.clientHeight) return;
    const quadrant = box.closest('.quadrant');
    if (!quadrant || !quadrant.offsetHeight) return;
    const padding = 12;
    const topFrac = parseFloat(box.style.top) / 100;
    const maxHeightFrac = 1 - topFrac;
    const neededPx = textarea.scrollHeight + padding;
    const newHeightFrac = Math.min(maxHeightFrac, neededPx / quadrant.offsetHeight);
    if (newHeightFrac <= 0) return;
    box.style.height = (newHeightFrac * 100) + '%';
    syncBoxToLetteringData(box);
  }

  function setBoxRect(box, rect) {
    // #region agent log
    const clamped = clampRect(rect);
    const changed = Math.abs((rect[0] - clamped[0]) + (rect[2] - clamped[2]) + (rect[1] - clamped[1]) + (rect[3] - clamped[3])) > 1e-6;
    if (changed) {
      fetch('http://127.0.0.1:7245/ingest/f4b8e3b3-a186-4c7c-a9f9-a946dace6f70',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'renderer.js:setBoxRect',message:'clampRect changed rect',data:{rectIn:[...rect],clamped:[...clamped]},timestamp:Date.now(),hypothesisId:'H1'})}).catch(()=>{});
    }
    // #endregion
    const [left, top, right, bottom] = clamped;
    box.style.left = (left * 100) + '%';
    box.style.top = (top * 100) + '%';
    box.style.width = ((right - left) * 100) + '%';
    box.style.height = ((bottom - top) * 100) + '%';
    return [left, top, right, bottom];
  }

  function collectLetteringData() {
    const data = { setting_label: '', setting_rect: DEFAULT_SETTING_RECT.slice(), panels: [] };
    const quadrants = quadrantsEl.querySelectorAll('.quadrant');
    quadrants.forEach((q, qi) => {
      const panel = letteringData && letteringData.panels[qi] ? {
        narrative: letteringData.panels[qi].narrative || '',
        dialogue: letteringData.panels[qi].dialogue || '',
        narrative_rect: (letteringData.panels[qi].narrative_rect || DEFAULT_NARRATIVE_RECT).slice(),
        dialogue_rect: (letteringData.panels[qi].dialogue_rect || DEFAULT_DIALOGUE_RECT).slice(),
      } : { narrative: '', dialogue: '', narrative_rect: DEFAULT_NARRATIVE_RECT.slice(), dialogue_rect: DEFAULT_DIALOGUE_RECT.slice() };
      const settingBox = q.querySelector('.text-box.setting');
      if (qi === 0 && settingBox) {
        data.setting_label = settingBox.querySelector('textarea').value.trim();
        data.setting_rect = getRectFromBox(settingBox);
      }
      ['dialogue', 'narrative'].forEach(kind => {
        const box = q.querySelector('.text-box.' + kind);
        if (box) {
          if (kind === 'dialogue') {
            panel.dialogue = box.querySelector('textarea').value.trim();
            panel.dialogue_rect = getRectFromBox(box);
          } else {
            panel.narrative = box.querySelector('textarea').value.trim();
            panel.narrative_rect = getRectFromBox(box);
          }
        }
      });
      data.panels.push(panel);
    });
    return data;
  }

  function hasContent(s) {
    return typeof s === 'string' && s.length > 0;
  }

  function addSlotAndRender(kind, qi) {
    if (!letteringData || !letteringData.panels) return;
    const panel = letteringData.panels[qi] || { narrative: '', dialogue: '', narrative_rect: DEFAULT_NARRATIVE_RECT.slice(), dialogue_rect: DEFAULT_DIALOGUE_RECT.slice() };
    if (kind === 'setting') {
      letteringData.setting_label = ' ';
      letteringData.setting_rect = DEFAULT_SETTING_RECT.slice();
    } else if (kind === 'dialogue') {
      panel.dialogue = ' ';
      panel.dialogue_rect = DEFAULT_DIALOGUE_RECT.slice();
    } else {
      panel.narrative = ' ';
      panel.narrative_rect = DEFAULT_NARRATIVE_RECT.slice();
    }
    if (!letteringData.panels[qi]) letteringData.panels[qi] = panel;
    renderEditor();
    const q = quadrantsEl.querySelector('.quadrant-' + qi);
    if (q) {
      const box = q.querySelector('.text-box.' + kind);
      if (box) {
        const ta = box.querySelector('textarea');
        if (ta) { ta.focus(); ta.setSelectionRange(0, ta.value.length); }
      }
    }
  }

  function renderEditor() {
    quadrantsEl.innerHTML = '';
    if (!letteringData || !letteringData.panels) return;

    for (let qi = 0; qi < 4; qi++) {
      const qDiv = document.createElement('div');
      qDiv.className = 'quadrant quadrant-' + qi;
      const panel = letteringData.panels[qi] || { narrative: '', dialogue: '', narrative_rect: DEFAULT_NARRATIVE_RECT.slice(), dialogue_rect: DEFAULT_DIALOGUE_RECT.slice() };
      const showSetting = qi === 0 && hasContent(letteringData.setting_label);
      const showDialogue = hasContent(panel.dialogue);
      const showNarrative = hasContent(panel.narrative);

      if (qi === 0) {
        if (showSetting) {
          const settingRect = letteringData.setting_rect || DEFAULT_SETTING_RECT.slice();
          const settingBox = createBox(0, 'setting', settingRect, 'Setting / location', 'setting');
          settingBox.querySelector('textarea').value = (letteringData.setting_label || '').trim();
          qDiv.appendChild(settingBox);
        }
        const addSetting = document.createElement('button');
        addSetting.type = 'button';
        addSetting.className = 'add-slot-btn';
        addSetting.textContent = '+ Setting';
        addSetting.addEventListener('click', () => addSlotAndRender('setting', 0));
        qDiv.appendChild(addSetting);
      }

      if (showDialogue) {
        const dialogueBox = createBox(qi, 'dialogue', panel.dialogue_rect || DEFAULT_DIALOGUE_RECT.slice(), 'Dialogue', 'dialogue');
        dialogueBox.querySelector('textarea').value = (panel.dialogue || '').trim();
        qDiv.appendChild(dialogueBox);
      }
      const addDialogue = document.createElement('button');
      addDialogue.type = 'button';
      addDialogue.className = 'add-slot-btn';
      addDialogue.textContent = '+ Dialogue';
      addDialogue.addEventListener('click', () => addSlotAndRender('dialogue', qi));
      qDiv.appendChild(addDialogue);

      if (showNarrative) {
        const narrativeBox = createBox(qi, 'narrative', panel.narrative_rect || DEFAULT_NARRATIVE_RECT.slice(), 'Narrative', 'narrative');
        narrativeBox.querySelector('textarea').value = (panel.narrative || '').trim();
        qDiv.appendChild(narrativeBox);
      }
      const addNarrative = document.createElement('button');
      addNarrative.type = 'button';
      addNarrative.className = 'add-slot-btn';
      addNarrative.textContent = '+ Narrative';
      addNarrative.addEventListener('click', () => addSlotAndRender('narrative', qi));
      qDiv.appendChild(addNarrative);

      quadrantsEl.appendChild(qDiv);

      attachBoxDragResize(qDiv);
      requestAnimationFrame(() => {
        qDiv.querySelectorAll('.text-box.narrative, .text-box.dialogue').forEach(fitBoxHeightToContent);
      });
    }
  }

  function syncBoxToLetteringData(box) {
    if (!letteringData || !letteringData.panels) return;
    const qi = parseInt(box.dataset.quadrant, 10);
    const kind = box.dataset.kind;
    const value = box.querySelector('textarea').value;
    const rect = getRectFromBox(box);
    if (kind === 'setting') {
      letteringData.setting_label = value;
      letteringData.setting_rect = rect;
    } else {
      const panel = letteringData.panels[qi] || { narrative: '', dialogue: '', narrative_rect: DEFAULT_NARRATIVE_RECT.slice(), dialogue_rect: DEFAULT_DIALOGUE_RECT.slice() };
      if (!letteringData.panels[qi]) letteringData.panels[qi] = panel;
      if (kind === 'dialogue') { panel.dialogue = value; panel.dialogue_rect = rect; }
      else { panel.narrative = value; panel.narrative_rect = rect; }
    }
  }

  function attachBoxDragResize(quadrant) {
    const boxes = quadrant.querySelectorAll('.text-box');
    boxes.forEach(box => {
      const dragHandle = box.querySelector('.drag-handle');
      const textarea = box.querySelector('textarea');

      textarea.addEventListener('blur', () => {
        if (resizeState || dragState) return;
        fitBoxHeightToContent(box);
        syncBoxToLetteringData(box);
        renderEditor();
      });

      function getRect() { return getRectFromBox(box); }
      function setRect(r) { setBoxRect(box, r); }

      dragHandle.addEventListener('mousedown', (e) => {
        e.preventDefault();
        if (resizeState) return;
        const rect = getRect();
        dragState = { box, quadrant, rect, startX: e.clientX, startY: e.clientY, left: rect[0], top: rect[1], right: rect[2], bottom: rect[3] };
      });

      box.querySelectorAll('.resize-handle').forEach(handle => {
        handle.addEventListener('mousedown', (e) => {
          e.preventDefault();
          e.stopPropagation();
          if (dragState) return;
          const rect = getRect();
          const r = handle.getBoundingClientRect();
          // #region agent log
          fetch('http://127.0.0.1:7245/ingest/f4b8e3b3-a186-4c7c-a9f9-a946dace6f70',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'renderer.js:resize-handle-mousedown',message:'resize handle mousedown',data:{handle:handle.dataset.handle,width:r.width,height:r.height},timestamp:Date.now(),hypothesisId:'R1'})}).catch(()=>{});
          // #endregion
          resizeState = { box, quadrant, handle: handle.dataset.handle, rect, startX: e.clientX, startY: e.clientY, left: rect[0], top: rect[1], right: rect[2], bottom: rect[3] };
        });
      });
    });
  }

  // #region agent log
  quadrantsEl.addEventListener('mousedown', (e) => {
    const t = e.target;
    const isHandle = t.classList && t.classList.contains('resize-handle');
    const isDrag = t.classList && t.classList.contains('drag-handle');
    const isTextarea = t.tagName === 'TEXTAREA';
    fetch('http://127.0.0.1:7245/ingest/f4b8e3b3-a186-4c7c-a9f9-a946dace6f70',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'renderer.js:quadrants-mousedown',message:'mousedown target',data:{tag:t.tagName,className:(t.className||'').slice(0,80),isResizeHandle:isHandle,isDragHandle:isDrag,isTextarea:isTextarea},timestamp:Date.now(),hypothesisId:'R2'})}).catch(()=>{});
  }, true);
  // #endregion

  document.addEventListener('mousemove', (e) => {
    if (dragState) {
      const q = dragState.quadrant.getBoundingClientRect();
      const dx = (e.clientX - dragState.startX) / q.width;
      const dy = (e.clientY - dragState.startY) / q.height;
      const w = dragState.right - dragState.left;
      const h = dragState.bottom - dragState.top;
      let left = dragState.left + dx;
      let top = dragState.top + dy;
      left = Math.max(0, Math.min(1 - w, left));
      top = Math.max(0, Math.min(1 - h, top));
      const clamped = clampRect([left, top, left + w, top + h]);
      setBoxRect(dragState.box, clamped);
    }
    if (resizeState) {
      const q = resizeState.quadrant.getBoundingClientRect();
      const dx = (e.clientX - resizeState.startX) / q.width;
      const dy = (e.clientY - resizeState.startY) / q.height;
      let { left, top, right, bottom } = resizeState;
      const h = resizeState.handle;
      if (h.includes('e')) right = Math.max(left + MIN_BOX_SIZE, right + dx);
      if (h.includes('w')) left = Math.min(right - MIN_BOX_SIZE, left + dx);
      if (h.includes('s')) bottom = Math.max(top + MIN_BOX_SIZE, bottom + dy);
      if (h.includes('n')) top = Math.min(bottom - MIN_BOX_SIZE, top + dy);
      left = Math.max(0, Math.min(1, left));
      top = Math.max(0, Math.min(1, top));
      right = Math.max(left + MIN_BOX_SIZE, Math.min(1, right));
      bottom = Math.max(top + MIN_BOX_SIZE, Math.min(1, bottom));
      const clamped = clampRect([left, top, right, bottom]);
      setBoxRect(resizeState.box, clamped);
      resizeState.left = clamped[0];
      resizeState.top = clamped[1];
      resizeState.right = clamped[2];
      resizeState.bottom = clamped[3];
      resizeState.startX = e.clientX;
      resizeState.startY = e.clientY;
    }
  });

  document.addEventListener('mouseup', async () => {
    let didMove = false;
    if (resizeState) {
      const rect = getRectFromBox(resizeState.box);
      const snapped = snapRect(rect, resizeState.quadrant, resizeState.box);
      setBoxRect(resizeState.box, snapped);
      // #region agent log
      fetch('http://127.0.0.1:7245/ingest/f4b8e3b3-a186-4c7c-a9f9-a946dace6f70',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'renderer.js:resize-mouseup',message:'snap on mouseup',data:{raw:rect.map(v=>+v.toFixed(4)),snapped:snapped.map(v=>+v.toFixed(4))},timestamp:Date.now(),hypothesisId:'S1-fix'})}).catch(()=>{});
      // #endregion
      syncBoxToLetteringData(resizeState.box);
      resizeState = null;
      didMove = true;
    }
    if (dragState) {
      const rect = getRectFromBox(dragState.box);
      const snapped = snapRect(rect, dragState.quadrant, dragState.box);
      setBoxRect(dragState.box, snapped);
      // #region agent log
      fetch('http://127.0.0.1:7245/ingest/f4b8e3b3-a186-4c7c-a9f9-a946dace6f70',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'renderer.js:drag-mouseup',message:'snap on mouseup',data:{raw:rect.map(v=>+v.toFixed(4)),snapped:snapped.map(v=>+v.toFixed(4))},timestamp:Date.now(),hypothesisId:'S1-fix'})}).catch(()=>{});
      // #endregion
      syncBoxToLetteringData(dragState.box);
      dragState = null;
      didMove = true;
    }
    if (didMove && currentStory && currentImage) {
      const data = collectLetteringData();
      const ok = await api.writeLetteringJson(currentStory, currentImage, data);
      if (ok) setStatus('Saved.');
    }
  });

  async function refreshProjectRoot() {
    projectRoot = await api.getProjectRoot();
    projectRootDisplay.textContent = projectRoot ? projectRoot : 'Not set';
    if (projectRoot) {
      const stories = await api.listStories();
      storySelect.innerHTML = '<option value="">—</option>' + stories.map(s => '<option value="' + s + '">' + s + '</option>').join('');
      if (currentStory) storySelect.value = currentStory;
    } else {
      storySelect.innerHTML = '<option value="">—</option>';
    }
  }

  const STORAGE_STORY = 'lettering-editor-story';
  const STORAGE_IMAGE = 'lettering-editor-image';

  storySelect.addEventListener('change', async () => {
    currentStory = storySelect.value || null;
    try { localStorage.setItem(STORAGE_STORY, currentStory || ''); } catch (_) {}
    imageSelect.innerHTML = '<option value="">—</option>';
    currentImage = null;
    if (!currentStory) { boardImage.src = ''; letteringData = buildLetteringFromScene(); boardImages = []; renderEditor(); updateNavButtons(); return; }
    const images = await api.listBoardImages(currentStory);
    boardImages = images;
    imageSelect.innerHTML = '<option value="">—</option>' + images.map(f => '<option value="' + f + '">' + f + '</option>').join('');
    const savedImage = (typeof localStorage !== 'undefined' && localStorage.getItem(STORAGE_IMAGE)) || '';
    if (savedImage && images.indexOf(savedImage) !== -1) {
      imageSelect.value = savedImage;
      currentImage = savedImage;
    } else if (images.length) {
      imageSelect.selectedIndex = 1;
      currentImage = imageSelect.value || null;
    }
    updateNavButtons();
    imageSelect.dispatchEvent(new Event('change'));
    if (currentStory && api.watchLetteredFolder) api.watchLetteredFolder(currentStory);
  });

  function updateNavButtons() {
    const idx = currentImage ? boardImages.indexOf(currentImage) : -1;
    btnPrevImage.disabled = idx <= 0;
    btnNextImage.disabled = idx < 0 || idx >= boardImages.length - 1;
  }

  btnPrevImage.addEventListener('click', () => {
    if (!currentImage || boardImages.length === 0) return;
    const idx = boardImages.indexOf(currentImage);
    if (idx > 0) {
      imageSelect.value = boardImages[idx - 1];
      imageSelect.dispatchEvent(new Event('change'));
    }
  });

  btnNextImage.addEventListener('click', () => {
    if (!currentImage || boardImages.length === 0) return;
    const idx = boardImages.indexOf(currentImage);
    if (idx >= 0 && idx < boardImages.length - 1) {
      imageSelect.value = boardImages[idx + 1];
      imageSelect.dispatchEvent(new Event('change'));
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.target.closest('textarea') || e.target.closest('select')) return;
    if (e.key === ' ') {
      if (showLetteredCheckbox && !showLetteredCheckbox.disabled) {
        showLetteredCheckbox.checked = !showLetteredCheckbox.checked;
        try { localStorage.setItem('lettering-editor-show-lettered', showLetteredCheckbox.checked ? '1' : '0'); } catch (_) {}
        updateBoardImage();
        e.preventDefault();
      }
      return;
    }
    const idx = currentImage ? boardImages.indexOf(currentImage) : -1;
    if (e.key === 'ArrowLeft' && idx > 0) {
      imageSelect.value = boardImages[idx - 1];
      imageSelect.dispatchEvent(new Event('change'));
      e.preventDefault();
    } else if (e.key === 'ArrowRight' && idx >= 0 && idx < boardImages.length - 1) {
      imageSelect.value = boardImages[idx + 1];
      imageSelect.dispatchEvent(new Event('change'));
      e.preventDefault();
    }
  });

  function letteredBasenameFor(imageBasename) {
    if (!imageBasename) return null;
    const base = imageBasename.replace(/\.(jpg|jpeg|png)$/i, '').replace(/-lettered$/, '');
    return base + '-lettered.jpg';
  }

  async function updateBoardImage() {
    if (!currentStory || !currentImage) {
      boardImage.src = '';
      if (quadrantsEl) quadrantsEl.style.display = '';
      if (gridOverlay) gridOverlay.style.display = '';
      fitComicToView();
      return;
    }
    const showLettered = showLetteredCheckbox && showLetteredCheckbox.checked;
    const letteredUrl = await api.getLetteredImagePath(currentStory, currentImage);
    if (showLetteredCheckbox) showLetteredCheckbox.disabled = !letteredUrl;
    const url = showLettered && letteredUrl
      ? letteredUrl + '?t=' + Date.now()
      : await api.getImagePath(currentStory, currentImage);
    boardImage.src = url || '';
    // Hide editable overlay when showing the lettered (rendered) image
    if (quadrantsEl) quadrantsEl.style.display = showLettered ? 'none' : '';
    if (gridOverlay) gridOverlay.style.display = showLettered ? 'none' : '';
    fitComicToView();
  }

  boardImage.addEventListener('load', fitComicToView);
  window.addEventListener('resize', fitComicToView);

  imageSelect.addEventListener('change', async () => {
    currentImage = imageSelect.value || null;
    updateNavButtons();
    try { localStorage.setItem(STORAGE_IMAGE, currentImage || ''); } catch (_) {}
    if (!currentStory || !currentImage) {
      boardImage.src = '';
      letteringData = buildLetteringFromScene();
      renderEditor();
      if (showLetteredCheckbox) showLetteredCheckbox.disabled = true;
      return;
    }
    await updateBoardImage();
    let loaded = await api.readLetteringJson(currentStory, currentImage);
    let usedPrefill = false;
    let rectReference = null;
    if (!loaded) {
      const images = await api.listBoardImages(currentStory);
      const idx = images.indexOf(currentImage);
      if (idx > 0) {
        const prevImage = images[idx - 1];
        rectReference = await api.readLetteringJson(currentStory, prevImage);
      }
      if (api.prefillLetteringFromScene) {
        const prefill = await api.prefillLetteringFromScene(currentStory, currentImage);
        if (prefill) {
          loaded = prefill;
          usedPrefill = true;
        }
      }
    }
    letteringData = mergeWithLoaded(loaded, rectReference);
    definitions = await api.readDefinitions(currentStory);
    renderEditor();
    if (usedPrefill && letteringData) {
      const ok = await api.writeLetteringJson(currentStory, currentImage, letteringData);
      if (ok) setStatus(rectReference ? 'Created lettering from scene (layout from previous).' : 'Created lettering from scene.');
    }
  });

  btnProject.addEventListener('click', async () => {
    const root = await api.setProjectRoot();
    if (root) await refreshProjectRoot();
    else setStatus('Invalid project root (need stories/ and scripts/overlay_storyboard_text.py)', true);
  });

  btnSave.addEventListener('click', async () => {
    if (!currentStory || !currentImage) { setStatus('Select story and image first', true); return; }
    const data = collectLetteringData();
    const ok = await api.writeLetteringJson(currentStory, currentImage, data);
    setStatus(ok ? 'Saved.' : 'Save failed.', !ok);
  });

  btnOverlay.addEventListener('click', async () => {
    if (!currentStory) { setStatus('Select a story first', true); return; }
    setStatus('Running overlay…');
    // #region agent log
    fetch('http://127.0.0.1:7245/ingest/f4b8e3b3-a186-4c7c-a9f9-a946dace6f70',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'renderer.js:btnOverlay-click',message:'overlay clicked',data:{story:currentStory},timestamp:Date.now(),hypothesisId:'O1'})}).catch(()=>{});
    // #endregion
    const result = await api.runOverlay(currentStory);
    // #region agent log
    fetch('http://127.0.0.1:7245/ingest/f4b8e3b3-a186-4c7c-a9f9-a946dace6f70',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'renderer.js:btnOverlay-result',message:'overlay result',data:{result},timestamp:Date.now(),hypothesisId:'O1'})}).catch(()=>{});
    // #endregion
    if (result.ok) {
      setStatus('Overlay finished.');
      if (currentStory && currentImage) await updateBoardImage();
    } else {
      setStatus('Overlay failed: ' + (result.error || 'unknown'), true);
    }
  });

  if (showLetteredCheckbox) {
    try {
      showLetteredCheckbox.checked = localStorage.getItem('lettering-editor-show-lettered') === '1';
    } catch (_) {}
    showLetteredCheckbox.addEventListener('change', async () => {
      try { localStorage.setItem('lettering-editor-show-lettered', showLetteredCheckbox.checked ? '1' : '0'); } catch (_) {}
      await updateBoardImage();
    });
  }

  if (api.onLetteredImageChanged) {
    api.onLetteredImageChanged((storySlug, filename) => {
      if (showLetteredCheckbox && showLetteredCheckbox.checked && currentStory === storySlug && currentImage && filename === letteredBasenameFor(currentImage)) {
        updateBoardImage();
      }
    });
  }

  refreshProjectRoot().then(() => {
    const savedStory = (typeof localStorage !== 'undefined' && localStorage.getItem(STORAGE_STORY)) || '';
    if (savedStory && storySelect.querySelector('option[value="' + savedStory + '"]')) {
      storySelect.value = savedStory;
      currentStory = savedStory;
      storySelect.dispatchEvent(new Event('change'));
    } else if (currentStory) {
      storySelect.dispatchEvent(new Event('change'));
    }
  });
})();
