/**
 * RevivaX - Frontend Application v2.1
 * Módulo principal: i18n, SMART, Dashboard, Scanner
 * Fix: removed duplicate event listener bindings; dashboard banner reset on stats load;
 *      SMART drive-letter resolution + OS drive badge; robust N/A handling.
 */

// ============================================================
// i18n System
// ============================================================
const TRANSLATIONS = Object.assign({}, window.REVIVAX_TRANSLATIONS || {});
const LANGUAGE_META = {
  'pt-BR': { flag: '🇧🇷', code: 'PT-BR' },
  'pt-PT': { flag: '🇵🇹', code: 'PT-PT' },
  en: { flag: '🇺🇸', code: 'EN' },
  es: { flag: '🇪🇸', code: 'ES' },
};
const CATEGORY_EXTENSION_MAP = {
  image: ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'webp', 'avif', 'ico', 'heic', 'raw'],
  video: ['mp4', 'mov', 'avi', 'mkv', 'wmv', 'flv', 'webm', 'm4v', '3gp', 'mpeg', 'mpg'],
  audio: ['mp3', 'wav', 'flac', 'aac', 'ogg', 'wma', 'm4a', 'opus'],
  document: ['pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'odt', 'ods', 'rtf'],
  archive: ['zip', 'rar', '7z', 'tar', 'gz', 'bz2', 'xz', 'iso'],
};
const RESPONSIVE_GRID_CLASSES = {
  1: 'grid grid-cols-1 gap-4',
  2: 'grid grid-cols-2 md:grid-cols-2 gap-4',
  3: 'grid grid-cols-2 md:grid-cols-3 gap-4',
  4: 'grid grid-cols-2 md:grid-cols-4 gap-4',
  5: 'grid grid-cols-2 md:grid-cols-5 gap-4',
};

let currentLang = localStorage.getItem('revivax-lang') || 'pt-BR';

function formatTranslation(template, params = {}) {
  return String(template).replace(/\{(\w+)\}/g, (_, key) => params[key] ?? `{${key}}`);
}

function t(key, params = {}) {
  const value = (TRANSLATIONS[currentLang] && TRANSLATIONS[currentLang][key])
    || (TRANSLATIONS['pt-BR'] && TRANSLATIONS['pt-BR'][key])
    || key;
  return formatTranslation(value, params);
}

function applyTranslations() {
  document.title = t('meta.title');
  document.querySelectorAll('[data-i18n]').forEach(el => {
    el.textContent = t(el.dataset.i18n);
  });

  const folderInput = document.getElementById('scan-folder-path');
  if (folderInput) folderInput.placeholder = t('recovery.folderPlaceholder');

  const browseBtn = folderInput?.parentElement?.querySelector('button');
  if (browseBtn) {
    browseBtn.title = t('recovery.browseFolder');
    browseBtn.setAttribute('aria-label', t('recovery.browseFolder'));
  }

  const driveSelect = document.getElementById('scan-drive');
  if (driveSelect) driveSelect.title = t('recovery.selectDrive');
  const modeSelect = document.getElementById('scan-mode');
  if (modeSelect) modeSelect.title = t('recovery.mode');
  const selectAllInput = document.getElementById('select-all');
  if (selectAllInput) {
    selectAllInput.title = t('recovery.selectPage');
    selectAllInput.setAttribute('aria-label', t('recovery.selectPage'));
  }

  const paginationInfo = document.getElementById('pagination-info');
  if (paginationInfo && state.scanResults.length === 0) {
    paginationInfo.textContent = t('pagination.empty');
  }

  const pageButton = document.getElementById('btn-select-page');
  if (pageButton) pageButton.textContent = t('recovery.selectPage');
  const allButton = document.getElementById('btn-select-all-results');
  if (allButton) allButton.textContent = t('recovery.selectAll');
  renderFolderScanLegend();
}

function updateLanguageUI(button = null) {
  const meta = LANGUAGE_META[currentLang] || LANGUAGE_META['pt-BR'];
  document.getElementById('lang-flag').textContent = meta.flag;
  document.getElementById('lang-code').textContent = meta.code;
  document.getElementById('html-root').setAttribute('lang', currentLang);
  document.querySelectorAll('#lang-menu button').forEach(btn => btn.classList.remove('active'));
  if (button) {
    button.classList.add('active');
  } else {
    document.querySelector(`#lang-menu button[onclick*="${currentLang}"]`)?.classList.add('active');
  }
}

function setLanguage(lang, button = null) {
  currentLang = lang;
  localStorage.setItem('revivax-lang', currentLang);
  updateLanguageUI(button);
  document.getElementById('lang-menu').classList.remove('open');
  closeMobileNav();
  applyTranslations();
  setScanSource(document.getElementById('scan-source')?.value || 'drive');
  updateDriveSelect();
  updateFileTypesFilter();
  updateRecoverButton();
  if (state.scanResults.length > 0) displayScanResults();
  if (state.currentSection === 'smart') loadSmartData();
  if (state.currentSection === 'logs') loadLogs();
  if (state.currentSection === 'dashboard') loadDashboardStats();
}

function toggleLangMenu() {
  document.getElementById('lang-menu').classList.toggle('open');
}

function toggleMobileNav(event = null) {
  event?.stopPropagation();
  const panel = document.getElementById('mobile-nav-panel');
  const button = document.getElementById('mobile-nav-toggle');
  if (!panel || !button) return;
  suppressNextDocumentClick = true;
  const open = panel.classList.toggle('open');
  button.innerHTML = `<i class="fas ${open ? 'fa-xmark' : 'fa-bars'}"></i>`;
  button.setAttribute('aria-expanded', open ? 'true' : 'false');
  window.setTimeout(() => { suppressNextDocumentClick = false; }, 0);
}

function closeMobileNav() {
  const panel = document.getElementById('mobile-nav-panel');
  const button = document.getElementById('mobile-nav-toggle');
  if (!panel || !button) return;
  panel.classList.remove('open');
  button.innerHTML = '<i class="fas fa-bars"></i>';
  button.setAttribute('aria-expanded', 'false');
}

document.addEventListener('click', e => {
  if (suppressNextDocumentClick) return;
  const dropdown = document.querySelector('.lang-dropdown');
  if (dropdown && !dropdown.contains(e.target)) {
    const menu = document.getElementById('lang-menu');
    if (menu) menu.classList.remove('open');
  }

  const resultsMenu = document.getElementById('results-filter-menu');
  const resultsToggle = document.getElementById('results-filter-toggle');
  if (
    resultsMenu && resultsToggle
    && !resultsMenu.contains(e.target)
    && !resultsToggle.contains(e.target)
  ) {
    closeResultsMenu();
  }

  const mobilePanel = document.getElementById('mobile-nav-panel');
  const mobileButton = document.getElementById('mobile-nav-toggle');
  if (mobilePanel && mobileButton && !mobilePanel.contains(e.target) && !mobileButton.contains(e.target)) {
    closeMobileNav();
  }
});

window.addEventListener('resize', () => {
  if (window.innerWidth >= 1280) closeMobileNav();
});

// ============================================================
// State
// ============================================================
const state = {
  currentSection: 'dashboard',
  drives: [],
  fileTypes: [],
  scanResults: [],
  selectedFiles: new Set(),
  currentJob: null,
  currentScanMeta: null,
};
// UI State globais
let isScanning = false;
let progressPollTimer = null; // mantido por compatibilidade histórica, caso sobre alguma var local
let scanEventSource = null; // SSE (Server Sent Events)
let recoveryResultsPollTimer = null;
let smartChart = null;
let suppressNextDocumentClick = false;
let activeScanViewToken = 0;
// ============================================================
// Init
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
  updateLanguageUI();
  applyTranslations();
  initApp();
  setScanSource(document.getElementById('scan-source')?.value || 'drive');
  const yearEl = document.getElementById('footer-year');
  if (yearEl) yearEl.textContent = new Date().getFullYear();
});

async function initApp() {
  try {
    showSection('dashboard'); // Força a ativação visual do botão na inicialização
    await Promise.all([loadDrives(), loadFileTypes(), loadDashboardStats()]);
    setupEventListeners();
    showToast(t('toast.appStarted'), 'success');
  } catch (error) {
    showToast(t('toast.initError', { message: error.message }), 'error');
  }
}

function setupEventListeners() {
  // IMPORTANT: buttons with onclick="" in HTML must NOT also get addEventListener —
  // that causes double-fire (duplicate toast notifications).
  // Only bind elements that have NO inline onclick attribute.
  document.getElementById('select-all')?.addEventListener('change', e => {
    setPageSelection(e.target.checked);
  });
  document.getElementById('scan-drive')?.addEventListener('change', e => {
    e.target.value ? loadRecoveryEstimate(e.target.value)
                   : document.getElementById('estimate-container')?.classList.add('hidden');
  });
  document.getElementById('scan-folder-path')?.addEventListener('input', () => {
    renderFolderScanLegend();
  });
  document.getElementById('scan-mode')?.addEventListener('change', () => {
    renderFolderScanLegend();
  });
  // Note: nav-btn clicks, startScan, stopScan, pauseScan etc. already have onclick= in HTML.
}

function translateCategory(cat) {
  return {
    image: t('category.image'),
    video: t('category.video'),
    document: t('category.document'),
    audio: t('category.audio'),
    archive: t('category.archive'),
  }[cat] || capitalize(cat);
}

function pluralCategoryLabel(cat) {
  return {
    image: t('category.images'),
    video: t('category.videos'),
    audio: t('category.audio'),
    document: t('category.documents'),
    archive: t('category.archives'),
  }[cat] || capitalize(cat);
}

function getEstimateDescription(estimate) {
  const chance = estimate?.recovery_chance;
  if (chance === 'high') return t('estimate.desc.high');
  if (chance === 'medium') return t('estimate.desc.medium');
  if (chance === 'low') return t('estimate.desc.low');
  return t('estimate.desc.unknown');
}

function normalizePathForMatch(path) {
  return String(path || '').replace(/\//g, '\\').replace(/\\+$/, '').toUpperCase();
}

function findDriveForPath(path) {
  const normalizedPath = normalizePathForMatch(path);
  if (!normalizedPath) return null;
  let bestMatch = null;
  state.drives.forEach(drive => {
    const mountpoint = normalizePathForMatch(drive.mountpoint || drive.device);
    if (!mountpoint) return;
    if (normalizedPath === mountpoint || normalizedPath.startsWith(`${mountpoint}\\`)) {
      const bestLen = bestMatch ? normalizePathForMatch(bestMatch.mountpoint || bestMatch.device).length : -1;
      if (mountpoint.length > bestLen) {
        bestMatch = drive;
      }
    }
  });
  return bestMatch;
}

function getFolderScanPreviewContext() {
  const folderPath = document.getElementById('scan-folder-path')?.value?.trim() || '';
  const requestedMode = document.getElementById('scan-mode')?.value || 'quick';
  const drive = folderPath ? findDriveForPath(folderPath) : null;
  const filesystem = String(drive?.fstype || '').toUpperCase();
  const supportsDeepFolderScan = filesystem === 'NTFS';
  return {
    source_kind: 'folder',
    filesystem,
    supports_deep_folder_scan: supportsDeepFolderScan,
    requested_mode: requestedMode,
    effective_mode: requestedMode === 'deep' && supportsDeepFolderScan ? 'deep' : 'quick',
    strategy: requestedMode === 'deep' && supportsDeepFolderScan ? 'ntfs_mft' : 'filesystem_walk',
    note_code: requestedMode === 'deep'
      ? (supportsDeepFolderScan ? 'folder_ntfs_metadata' : 'folder_deep_unsupported')
      : 'folder_accessible_files',
    path_selected: Boolean(folderPath),
  };
}

function getFolderLegendContent(context) {
  if (!context?.path_selected) {
    return {
      tone: 'primary',
      title: t('recovery.folderLegendTitle'),
      body: t('recovery.folderLegendPending'),
    };
  }

  const filesystemHint = t('recovery.folderLegendFilesystem', {
    filesystem: context.filesystem || t('common.unknown'),
  });

  if (context.note_code === 'folder_ntfs_metadata') {
    return {
      tone: 'success',
      title: t('recovery.folderLegendNtfsTitle'),
      body: `${filesystemHint} ${t('recovery.folderLegendDeepNtfs')}`,
    };
  }

  if (context.note_code === 'folder_deep_unsupported') {
    return {
      tone: 'warning',
      title: t('recovery.folderLegendFallbackTitle'),
      body: `${filesystemHint} ${t('recovery.folderLegendDeepUnsupported')}`,
    };
  }

  if (context.note_code === 'folder_deep_permission_fallback') {
    return {
      tone: 'warning',
      title: t('recovery.folderLegendPermissionTitle'),
      body: `${filesystemHint} ${t('recovery.folderLegendPermissionFallback')}`,
    };
  }

  return {
    tone: 'primary',
    title: t('recovery.folderLegendTitle'),
    body: `${filesystemHint} ${t('recovery.folderLegendQuick')}`,
  };
}

function renderFolderScanLegend(context = null) {
  const container = document.getElementById('folder-scan-note');
  const titleEl = document.getElementById('folder-scan-note-title');
  const bodyEl = document.getElementById('folder-scan-note-body');
  const source = document.getElementById('scan-source')?.value || 'drive';
  if (!container || !titleEl || !bodyEl) return;

  if (source !== 'folder') {
    container.classList.add('hidden');
    return;
  }

  const previewContext = getFolderScanPreviewContext();
  const legendContext = context || (previewContext.path_selected ? previewContext : state.currentScanMeta?.scanContext || previewContext);
  const content = getFolderLegendContent(legendContext);

  container.classList.remove('hidden', 'border-primary/30', 'bg-primary/10', 'border-success/30', 'bg-success/10', 'border-warning/30', 'bg-warning/10');
  titleEl.classList.remove('text-primary', 'text-success', 'text-warning');

  if (content.tone === 'success') {
    container.classList.add('border-success/30', 'bg-success/10');
    titleEl.classList.add('text-success');
  } else if (content.tone === 'warning') {
    container.classList.add('border-warning/30', 'bg-warning/10');
    titleEl.classList.add('text-warning');
  } else {
    container.classList.add('border-primary/30', 'bg-primary/10');
    titleEl.classList.add('text-primary');
  }

  titleEl.textContent = content.title;
  bodyEl.textContent = content.body;
}

function getLocalizedProgressMessage(progress) {
  if (!progress) return t('scan.inProgress');
  if (progress.status === 'paused') return t('scan.paused');
  if (progress.status === 'completed') return t('scan.completedToast', { count: progress.files_found || 0 });
  if (progress.status === 'stopped') return t('scan.stopped');
  if (progress.status === 'error') return progress.message || t('common.error');
  if (progress.status === 'scanning') return t('scan.scanningSummary', { count: progress.files_found || 0 });
  return progress.message || t('scan.inProgress');
}

// ============================================================
// Navigation
// ============================================================
function showSection(sectionName) {
  state.currentSection = sectionName;
  closeMobileNav();
  document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.classList.toggle('bg-primary/20', btn.dataset.section === sectionName);
    btn.classList.toggle('text-primary', btn.dataset.section === sectionName);
  });
  document.querySelectorAll('.section').forEach(s => s.classList.add('hidden'));
  document.getElementById(`${sectionName}-section`)?.classList.remove('hidden');
  if (sectionName === 'smart') loadSmartData();
  else if (sectionName === 'logs') loadLogs();
  else if (sectionName === 'dashboard') loadDashboardStats();
}

// ============================================================
// API Helpers
// ============================================================
async function apiGet(endpoint) {
  try {
    const r = await fetch(`/api${endpoint}`, {
      cache: 'no-store',
      headers: { 'X-RevivaX-Lang': currentLang },
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } catch (error) {
    if (error.message.includes('Failed to fetch') || error.name === 'TypeError') {
      showToast(t('api.offlineLost'), 'error');
    }
    throw error;
  }
}
async function apiPost(endpoint, data = {}) {
  try {
    const r = await fetch(`/api${endpoint}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-RevivaX-Lang': currentLang,
      },
      body: JSON.stringify(data)
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } catch (error) {
    if (error.message.includes('Failed to fetch') || error.name === 'TypeError') {
      showToast(t('api.offlineAbort'), 'error');
    }
    throw error;
  }
}

// ============================================================
// Dashboard
// ============================================================
async function loadDashboardStats() {
  try {
    // Always sync banner with current scan status when dashboard is opened
    try {
      const progRes = await apiGet('/scan/progress');
      if (progRes.success) {
        updateDashboardScanBanner(progRes.progress);
      }
    } catch (_) { /* ignore if no scan endpoint */ }

    const drivesRes = await apiGet('/drives');
    if (drivesRes.success) document.getElementById('total-drives').textContent = drivesRes.drives.length;

    const smartRes = await apiGet('/smart');
    const smartStatus = document.getElementById('smart-status');
    if (smartRes.success && smartRes.available) {
      document.getElementById('healthy-drives').textContent = smartRes.data.healthy;
      document.getElementById('warning-drives').textContent = smartRes.data.warning;
      if (smartRes.data.critical > 0) {
        smartStatus.className = 'px-2 py-1 bg-danger/20 text-danger rounded text-xs font-medium';
        smartStatus.textContent = t('smart.critical');
      } else if (smartRes.data.warning > 0) {
        smartStatus.className = 'px-2 py-1 bg-warning/20 text-warning rounded text-xs font-medium';
        smartStatus.textContent = t('smart.warning');
      } else {
        smartStatus.className = 'px-2 py-1 bg-success/20 text-success rounded text-xs font-medium';
        smartStatus.textContent = t('common.available');
      }
    } else {
      document.getElementById('healthy-drives').textContent = '-';
      document.getElementById('warning-drives').textContent = '-';
      smartStatus.className = 'px-2 py-1 bg-gray-700 text-gray-400 rounded text-xs font-medium';
      smartStatus.textContent = t('common.unavailable');
    }

    const recoveryRes = await apiGet('/recover/results');
    if (recoveryRes.success) document.getElementById('recovered-files').textContent = recoveryRes.successful || 0;
  } catch (error) {
    console.error('Erro ao carregar estatísticas:', error);
  }
}

// ============================================================
// Drives
// ============================================================
async function loadDrives() {
  try {
    const response = await apiGet('/drives');
    if (response.success) {
      state.drives = response.drives;
      updateDriveSelect();
      renderFolderScanLegend();
    }
  } catch (error) { console.error('Erro ao carregar drives:', error); }
}

function updateDriveSelect() {
  const select = document.getElementById('scan-drive');
  if (!select) return;
  const previousValue = select.value;
  select.innerHTML = `<option value="">${t('recovery.selectDrive')}</option>`;
  state.drives.forEach(drive => {
    const opt = document.createElement('option');
    opt.value = drive.device || drive.mountpoint;
    const totalGB = drive.total ? (drive.total / 1024 / 1024 / 1024).toFixed(1) : '?';
    const freeGB  = drive.free  ? (drive.free  / 1024 / 1024 / 1024).toFixed(1) : '?';
    const mp = drive.mountpoint ? drive.mountpoint.replace(/\\$/, '') : null;
    const label = mp ? `${mp} — ${freeGB} GB / ${totalGB} GB`
                     : `${drive.device} — ${freeGB} GB / ${totalGB} GB`;
    opt.textContent = drive.is_system ? `⚙️ ${label} [${t('smart.systemDrive')}]` : label;
    opt.selected = opt.value === previousValue;
    select.appendChild(opt);
  });
}

// ============================================================
// File Types
// ============================================================
async function loadFileTypes() {
  try {
    const response = await apiGet('/file-types');
    if (response.success) { state.fileTypes = response.categories; updateFileTypesFilter(); }
  } catch (error) { console.error('Erro ao carregar tipos:', error); }
}

function updateFileTypesFilter() {
  const container = document.getElementById('file-types-container');
  if (!container) return;
  const previousSelection = new Set(
    Array.from(document.querySelectorAll('.file-type-checkbox:checked')).map(cb => cb.value)
  );
  const selectAll = previousSelection.size === 0 || previousSelection.has('all');
  container.innerHTML = '';
  const allLabel = document.createElement('label');
  allLabel.className = 'inline-flex items-center px-3 py-1 bg-primary/20 text-primary rounded-full text-sm cursor-pointer hover:bg-primary/30 transition';
  allLabel.innerHTML = `<input type="checkbox" value="all" ${selectAll ? 'checked' : ''} class="mr-2 file-type-checkbox" onchange="toggleAllFileTypes(this)">${t('filter.allTypes')}`;
  container.appendChild(allLabel);
  ['image','video','document','audio','archive'].forEach(cat => {
    if (state.fileTypes[cat]) {
      const label = document.createElement('label');
      label.className = 'inline-flex items-center px-3 py-1 bg-gray-800 text-gray-300 rounded-full text-sm cursor-pointer hover:bg-gray-700 transition';
      label.innerHTML = `<input type="checkbox" value="${cat}" ${previousSelection.has(cat) ? 'checked' : ''} class="mr-2 file-type-checkbox" onchange="updateFileTypeSelection()"> ${getCategoryIcon(cat)} ${pluralCategoryLabel(cat)}`;
      container.appendChild(label);
    }
  });
}

function getCategoryIcon(c) {
  return {'image':'<i class="fas fa-image mr-1"></i>','video':'<i class="fas fa-video mr-1"></i>',
          'document':'<i class="fas fa-file-lines mr-1"></i>','audio':'<i class="fas fa-music mr-1"></i>',
          'archive':'<i class="fas fa-file-zipper mr-1"></i>'}[c] || '<i class="fas fa-file mr-1"></i>';
}

function capitalize(s) { return s.charAt(0).toUpperCase() + s.slice(1); }
function getCategoryByExtension(extension) {
  const ext = String(extension || '').toLowerCase();
  for (const [category, extensions] of Object.entries(CATEGORY_EXTENSION_MAP)) {
    if (extensions.includes(ext)) return category;
  }
  return 'other';
}

function getMetricGridClass(count) {
  const safeCount = Math.max(1, Math.min(Number(count) || 1, 5));
  return RESPONSIVE_GRID_CLASSES[safeCount] || RESPONSIVE_GRID_CLASSES[5];
}

function closeResultsMenu() {
  const menu = document.getElementById('results-filter-menu');
  const toggle = document.getElementById('results-filter-toggle');
  if (menu) menu.classList.add('hidden');
  if (toggle) toggle.setAttribute('aria-expanded', 'false');
}

function toggleResultsMenu(event = null) {
  event?.stopPropagation();
  const menu = document.getElementById('results-filter-menu');
  const toggle = document.getElementById('results-filter-toggle');
  if (!menu || !toggle) return;
  const willOpen = menu.classList.contains('hidden');
  menu.classList.toggle('hidden', !willOpen);
  toggle.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
}
function toggleAllFileTypes(cb) {
  // 'Todos' marcado → desmarca todos os individuais
  // 'Todos' desmarcado → não marca nada (estado limpo)
  document.querySelectorAll('.file-type-checkbox').forEach(c => {
    if (c !== cb) c.checked = false;
  });
}
function updateFileTypeSelection() {
  // Ao marcar qualquer categoria individual, desmarca 'Todos'
  const allCb = document.querySelector('.file-type-checkbox[value="all"]');
  if (allCb) allCb.checked = false;
}
function getSelectedFileTypes() {
  const types = [];
  document.querySelectorAll('.file-type-checkbox:checked').forEach(cb => {
    if (cb.value === 'all') return;
    const cat = state.fileTypes[cb.value];
    if (cat) cat.forEach(fileType => types.push(fileType.extension));
  });
  return types.length > 0 ? types : null;
}

// ============================================================
// Recovery Estimate
// ============================================================
async function loadRecoveryEstimate(drive) {
  try {
    const response = await apiPost('/estimate', { drive });
    if (response.success) {
      const container = document.getElementById('estimate-container');
      const text = document.getElementById('estimate-text');
      const badge = document.getElementById('estimate-badge');
      container.classList.remove('hidden');
      text.textContent = getEstimateDescription(response.estimate);
      const chance = response.estimate.recovery_chance;
      if (chance === 'high') {
        badge.className = 'px-3 py-1 rounded-full text-sm font-medium bg-success/20 text-success';
        badge.textContent = t('estimate.high');
      } else if (chance === 'medium') {
        badge.className = 'px-3 py-1 rounded-full text-sm font-medium bg-warning/20 text-warning';
        badge.textContent = t('estimate.medium');
      } else if (chance === 'low') {
        badge.className = 'px-3 py-1 rounded-full text-sm font-medium bg-danger/20 text-danger';
        badge.textContent = t('estimate.low');
      } else {
        badge.className = 'px-3 py-1 rounded-full text-sm font-medium bg-gray-700 text-gray-400';
        badge.textContent = t('estimate.unknown');
      }
    }
  } catch (error) { console.error('Erro ao carregar estimativa:', error); }
}

// ============================================================
// Scanning
// ============================================================
function resetRecoveryResultsPolling() {
  if (recoveryResultsPollTimer) {
    clearTimeout(recoveryResultsPollTimer);
    recoveryResultsPollTimer = null;
  }
}

function clearLocalScanState({ preserveControls = true } = {}) {
  activeScanViewToken += 1;
  state.currentJob = null;
  state.currentScanMeta = null;
  state.scanResults = [];
  state.selectedFiles.clear();
  currentSelectionFilter = 'all';
  currentSelectionSort = 'confidence_desc';
  currentPage = 1;
  resetRecoveryResultsPolling();
  closeResultsMenu();

  document.getElementById('scan-results')?.classList.add('hidden');
  document.getElementById('scan-progress')?.classList.add('hidden');
  document.getElementById('scan-live-counts')?.remove();

  const tbody = document.getElementById('results-table-body');
  if (tbody) {
    tbody.innerHTML = `<tr><td colspan="6" class="px-4 py-8 text-center text-gray-500">${t('scan.noFiles')}</td></tr>`;
  }

  const progressBar = document.getElementById('progress-bar');
  const progressMsg = document.getElementById('progress-message');
  const progressPct = document.getElementById('progress-percent');
  if (progressBar) progressBar.style.width = '0%';
  if (progressMsg) progressMsg.textContent = t('scan.waiting');
  if (progressPct) progressPct.textContent = '0%';

  const selectAll = document.getElementById('select-all');
  if (selectAll) selectAll.checked = false;
  const resultsMeta = document.getElementById('scan-results-meta');
  if (resultsMeta) {
    resultsMeta.textContent = '';
    resultsMeta.classList.add('hidden');
  }

  renderPaginationControls(0, 0);
  updateRecoverButton();
  hideScanBanner();
  renderFolderScanLegend();

  if (preserveControls) {
    restoreScanActionButtons();
  }
}

function restoreScanActionButtons() {
  const pauseBtn = document.getElementById('pause-btn');
  const stopBtn = document.getElementById('stop-btn');
  if (pauseBtn) {
    pauseBtn.dataset.paused = 'false';
    pauseBtn.onclick = pauseScan;
    pauseBtn.innerHTML = `<i class="fas fa-pause mr-1"></i>${t('recovery.pause')}`;
    pauseBtn.className = 'px-4 py-2 bg-warning/20 hover:bg-warning/30 text-warning rounded-lg text-sm font-medium transition';
  }
  if (stopBtn) {
    stopBtn.onclick = stopScan;
    stopBtn.innerHTML = `<i class="fas fa-stop mr-1"></i>${t('recovery.stop')}`;
    stopBtn.className = 'px-4 py-2 bg-danger/20 hover:bg-danger/30 text-danger rounded-lg text-sm font-medium transition';
  }
}

async function resetScanState({ clearServer = false, preserveControls = true } = {}) {
  if (progressPollTimer) { clearInterval(progressPollTimer); progressPollTimer = null; }
  if (scanEventSource) { scanEventSource.close(); scanEventSource = null; }
  isScanning = false;

  if (clearServer) {
    try {
      await apiPost('/scan/reset');
    } catch (error) {
      console.warn('Falha ao limpar estado da varredura no backend:', error);
    }
  }

  clearLocalScanState({ preserveControls });
}

async function prepareNewScan() {
  await resetScanState({ clearServer: true });
  showSection('recovery');
}

async function startScan() {
  const scanSource = document.getElementById('scan-source')?.value || 'drive';
  let target;
  if (scanSource === 'folder') {
    target = document.getElementById('scan-folder-path')?.value?.trim();
    if (!target) { showToast(t('scan.enterFolder'), 'warning'); return; }
  } else {
    target = document.getElementById('scan-drive')?.value;
    if (!target) { showToast(t('scan.selectDriveFirst'), 'warning'); return; }
  }
  const mode      = document.getElementById('scan-mode')?.value || 'quick';
  const fileTypes = getSelectedFileTypes();

  try {
    await resetScanState({ clearServer: true });
    isScanning = true;
    disableScanControls();

    document.getElementById('scan-progress')?.classList.remove('hidden');

    const payload = { drive: target, mode, file_types: fileTypes };
    if (scanSource === 'folder') payload.folder_path = target;

    const response = await apiPost('/scan/start', payload);
    if (response.success) {
      state.currentJob = response.job_id || null;
      state.currentScanMeta = {
        drive: target,
        mode: response.effective_mode || mode,
        sourceKind: response.source_kind || scanSource,
        jobId: response.job_id || '',
        createdAt: '',
        scanContext: {
          source_kind: response.source_kind || scanSource,
          filesystem: response.filesystem || '',
          supports_deep_folder_scan: Boolean(response.supports_deep_folder_scan),
          requested_mode: response.requested_mode || mode,
          effective_mode: response.effective_mode || mode,
          strategy: response.scan_strategy || '',
          note_code: response.scan_note_code || '',
          path_selected: true,
        },
      };
      renderFolderScanLegend(state.currentScanMeta.scanContext);
      showToast(t('scan.started'), 'success');
      pollScanProgress(state.currentJob, activeScanViewToken);
    } else {
      throw new Error(response.error);
    }
  } catch (error) {
    isScanning = false;
    enableScanControls();
    showToast(t('scan.startError', { message: error.message }), 'error');
    document.getElementById('scan-progress')?.classList.add('hidden');
  }
}

function pollScanProgress(jobId = state.currentJob, viewToken = activeScanViewToken) {
  if (progressPollTimer) { clearInterval(progressPollTimer); progressPollTimer = null; }
  if (scanEventSource) { scanEventSource.close(); scanEventSource = null; }

  // Usando Server-Sent Events (SSE) ao invés de Polling (Resolvendo o bottleneck de requisições - ARCH-01)
  const streamSuffix = jobId ? `?job_id=${encodeURIComponent(jobId)}` : '';
  scanEventSource = new EventSource(`/api/scan/progress/stream${streamSuffix}`);

  scanEventSource.onmessage = function(event) {
    try {
      const res = JSON.parse(event.data);
      if (res.success) {
        if (viewToken !== activeScanViewToken) {
          return;
        }
        if (jobId && res.progress.job_id && res.progress.job_id !== jobId) {
          return;
        }
        updateScanUI(res.progress);
        updateDashboardScanBanner(res.progress);
        
        if (res.progress.status === 'completed') {
          if (scanEventSource) { scanEventSource.close(); scanEventSource = null; }
          isScanning = false;
          showToast(t('scan.completedToast', { count: res.progress.files_found || 0 }), 'success');
          loadScanResults(jobId, viewToken);
          enableScanControls();
          hideScanBanner();
          // Troca Pausar/Parar por Nova Varredura / Limpar
          const pauseBtn = document.getElementById('pause-btn');
          const stopBtn  = document.getElementById('stop-btn');
          if (pauseBtn) {
            pauseBtn.dataset.paused = 'false';
            pauseBtn.onclick = prepareNewScan;
            pauseBtn.innerHTML = `<i class="fas fa-redo mr-1"></i>${t('scan.newScan')}`;
            pauseBtn.className = 'px-4 py-2 bg-primary/20 hover:bg-primary/30 text-primary rounded-lg text-sm font-medium transition';
          }
          if (stopBtn)  {
            stopBtn.onclick  = () => { resetScanState({ clearServer: true }); };
            stopBtn.innerHTML  = `<i class="fas fa-trash mr-1"></i>${t('scan.clear')}`;
            stopBtn.className  = 'px-4 py-2 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded-lg text-sm font-medium transition';
          }
        } else if (res.progress.status === 'error') {
          if (scanEventSource) { scanEventSource.close(); scanEventSource = null; }
          isScanning = false;
          showToast(res.progress.message || t('common.error'), 'error');
          enableScanControls();
          hideScanBanner();
        } else if (res.progress.status === 'stopped') {
          if (scanEventSource) { scanEventSource.close(); scanEventSource = null; }
          isScanning = false;
          enableScanControls();
          hideScanBanner();
        }
      }
    } catch (err) {
      console.error('Erro ao decodificar SSE:', err);
    }
  };

  scanEventSource.onerror = function(err) {
    console.warn('Conexão SSE de progresso encerrada ou interrompida', err);
    if (scanEventSource && scanEventSource.readyState === EventSource.CLOSED) {
      scanEventSource.close();
      scanEventSource = null;
    }
  };
}

function updateDashboardScanBanner(progress) {
  const banner = document.getElementById('dashboard-scan-banner');
  const navBadges = document.querySelectorAll('[data-scan-indicator]');
  if (!banner) return;
  const active = progress.status === 'scanning' || progress.status === 'paused';
  if (active) {
    banner.classList.remove('hidden');
    const isPaused = progress.status === 'paused';

    navBadges.forEach(navBadge => {
      const label = navBadge.querySelector('[data-scan-indicator-label]');
      const icon = navBadge.querySelector('[data-scan-indicator-icon]');
      navBadge.classList.add('is-visible');
      navBadge.classList.remove('hidden', 'bg-primary/15', 'text-primary', 'border-primary/30', 'bg-warning/20', 'text-warning', 'border-warning/30');
      if (isPaused) {
        navBadge.classList.add('bg-warning/20', 'text-warning', 'border-warning/30');
        if (icon) icon.className = 'fas fa-pause-circle text-xs';
        if (label) label.textContent = t('nav.paused');
      } else {
        navBadge.classList.add('bg-primary/15', 'text-primary', 'border-primary/30');
        if (icon) icon.className = 'fas fa-spinner fa-spin text-xs';
        if (label) label.textContent = t('nav.scanning');
      }
    });

    banner.classList.remove('bg-primary/10', 'border-primary/30', 'bg-warning/10', 'border-warning/30');
    banner.classList.add(isPaused ? 'bg-warning/10' : 'bg-primary/10', isPaused ? 'border-warning/30' : 'border-primary/30');

    const titleEl = document.getElementById('dashboard-scan-title');
    if (titleEl) {
      titleEl.textContent = isPaused ? t('dashboard.scanPaused') : t('dashboard.scanRunning');
      titleEl.className = isPaused ? 'font-semibold text-warning' : 'font-semibold text-primary';
    }

    const iconContainer = document.getElementById('dashboard-scan-icon-container');
    const iconEl = document.getElementById('dashboard-scan-icon');
    if (iconContainer && iconEl) {
      if (isPaused) {
        iconContainer.className = 'w-10 h-10 bg-warning/20 rounded-full flex items-center justify-center text-warning shadow-lg shadow-warning/10';
        iconEl.className = 'fas fa-pause text-warning text-lg';
      } else {
        iconContainer.className = 'w-10 h-10 bg-primary/20 rounded-full flex items-center justify-center text-primary shadow-lg shadow-primary/10 animate-pulse';
        iconEl.className = 'fas fa-spinner text-primary text-lg fa-spin';
      }
    }

    const pct = progress.total > 0 ? Math.round((progress.current / progress.total) * 100) : 0;
    const clean = getLocalizedProgressMessage(progress);
    const msgEl = document.getElementById('dashboard-scan-msg');
    const pctEl = document.getElementById('dashboard-scan-pct');
    const btnEl = document.getElementById('dashboard-scan-btn');

    if (msgEl) msgEl.textContent = isPaused ? t('scan.waiting') : clean;
    if (pctEl) {
      pctEl.textContent = pct + '%';
      pctEl.className = isPaused ? 'text-2xl font-bold text-warning' : 'text-2xl font-bold text-primary';
    }
    
    if (btnEl) {
      btnEl.className = isPaused 
        ? 'px-4 py-2 bg-warning/20 hover:bg-warning/30 text-warning rounded-lg text-sm transition font-medium'
        : 'px-4 py-2 bg-primary/20 hover:bg-primary/30 text-primary rounded-lg text-sm transition font-medium';
    }
  } else {
    hideScanBanner();
  }
}

function hideScanBanner() {
  const banner = document.getElementById('dashboard-scan-banner');
  const navBadges = document.querySelectorAll('[data-scan-indicator]');
  if (banner) { banner.classList.add('hidden'); }
  navBadges.forEach(navBadge => {
    navBadge.classList.add('hidden');
    navBadge.classList.remove('is-visible', 'bg-primary/15', 'text-primary', 'border-primary/30', 'bg-warning/20', 'text-warning', 'border-warning/30');
  });
}

async function stopScan() {
  try {
    await apiPost('/scan/stop');
    if (progressPollTimer) { clearInterval(progressPollTimer); progressPollTimer = null; }
    if (scanEventSource) { scanEventSource.close(); scanEventSource = null; }
    isScanning = false;
    showToast(t('scan.stopped'), 'info');
    enableScanControls();
    clearLocalScanState();
  } catch (error) { showToast(t('scan.stopError', { message: error.message }), 'error'); }
}

async function pauseScan() {
  const btn = document.getElementById('pause-btn');
  // Check state via a data attribute to avoid relying on button text (which may vary by lang)
  const isPaused = btn?.dataset.paused === 'true';
  try {
    if (isPaused) {
      await apiPost('/scan/resume');
      btn.dataset.paused = 'false';
      btn.innerHTML = `<i class="fas fa-pause mr-1"></i>${t('recovery.pause')}`;
      showToast(t('scan.resumed'), 'success');
      pollScanProgress(state.currentJob, activeScanViewToken);
    } else {
      await apiPost('/scan/pause');
      btn.dataset.paused = 'true';
      btn.innerHTML = `<i class="fas fa-play mr-1"></i>${t('recovery.resume')}`;
      showToast(t('scan.pausedToast'), 'info');
      // Fecha a conexão contínua durante o pause
      if (progressPollTimer) { clearInterval(progressPollTimer); progressPollTimer = null; }
      if (scanEventSource) { scanEventSource.close(); scanEventSource = null; }
    }
  } catch (error) { showToast(t('scan.pauseError', { message: error.message }), 'error'); }
}

function updateScanUI(progress) {
  const bar = document.getElementById('progress-bar');
  const message = document.getElementById('progress-message');
  const percent = document.getElementById('progress-percent');
  if (bar && message && percent) {
    let pct = 0;
    if (progress.status === 'completed') {
      pct = 100;
    } else {
      pct = progress.total > 0 ? Math.round((progress.current / progress.total) * 100) : 0;
    }
    bar.style.width = `${pct}%`;
    percent.textContent = `${pct}%`;
    const clean = getLocalizedProgressMessage(progress);
    message.textContent = clean;
  }

  const counts = progress.file_counts || {};
  // Enriquece file_counts com dados dos resultados actuais se os contadores forem zero
  if (state.scanResults && state.scanResults.length > 0 && Object.values(counts).every(v => v === 0)) {
    state.scanResults.forEach(r => {
      const category = getCategoryByExtension(r.extension);
      if (category !== 'other') counts[category] = (counts[category] || 0) + 1;
    });
  }
  if (counts && Object.keys(counts).length > 0) {
    let countsEl = document.getElementById('scan-live-counts');
    if (!countsEl) {
      const progSection = document.getElementById('scan-progress');
      if (progSection) {
        countsEl = document.createElement('div');
        countsEl.id = 'scan-live-counts';
        countsEl.className = 'mt-4 grid grid-cols-3 md:grid-cols-5 gap-3';
        progSection.appendChild(countsEl);
      }
    }
    if (countsEl) {
      const cats = [
        { key:'image',    label:t('category.images'),    icon:'fa-image',       color:'text-blue-400' },
        { key:'video',    label:t('category.videos'),    icon:'fa-video',       color:'text-purple-400' },
        { key:'audio',    label:t('category.audio'),     icon:'fa-music',       color:'text-green-400' },
        { key:'document', label:t('category.documents'), icon:'fa-file-alt',    color:'text-yellow-400' },
        { key:'archive',  label:t('category.archives'),  icon:'fa-file-zipper', color:'text-orange-400' },
      ];
      countsEl.innerHTML = cats.map(c => `
        <div class="bg-gray-800/60 rounded-lg px-3 py-2 flex items-center gap-2">
          <i class="fas ${c.icon} ${c.color} text-xs"></i>
          <div>
            <div class="text-xs text-gray-400">${c.label}</div>
            <div class="text-sm font-bold">${counts[c.key] ?? 0}</div>
          </div>
        </div>
      `).join('');
    }
  }
}

async function loadScanResults(jobId = state.currentJob, viewToken = activeScanViewToken) {
  try {
    const suffix = jobId ? `?job_id=${encodeURIComponent(jobId)}&_=${Date.now()}` : `?_=${Date.now()}`;
    const response = await apiGet(`/scan/results${suffix}`);
    if (response.success) {
      if (viewToken !== activeScanViewToken) {
        return;
      }
      if (response.pending) return;
      if (jobId && response.job_id && response.job_id !== jobId) {
        return;
      }
      if (state.currentJob && jobId && state.currentJob !== jobId) {
        return;
      }
      state.scanResults = response.results;
      state.currentJob = response.job_id || jobId || null;
      state.currentScanMeta = {
        drive: response.drive || '',
        mode: response.mode || '',
        sourceKind: response.source_kind || '',
        scanContext: {
          ...(response.scan_context || {}),
          path_selected: Boolean(response.drive),
        },
        jobId: response.job_id || jobId || '',
        createdAt: response.created_at || '',
      };
      displayScanResults();
      document.getElementById('scan-results')?.classList.remove('hidden');
      renderFolderScanLegend(state.currentScanMeta.scanContext);
    }
  } catch (error) { showToast(`${t('common.error')}: ${error.message}`, 'error'); }
}

let currentSelectionFilter = 'all';
let currentSelectionSort = 'confidence_desc';

// Paginação local
let currentPage = 1;
const itemsPerPage = 50;

function applySelectionFilter(cat) {
  currentSelectionFilter = cat;
  currentPage = 1; // Reseta página
  closeResultsMenu();
  displayScanResults();
}

function applySelectionSort(sortType) {
  currentSelectionSort = sortType;
  currentPage = 1; // Reseta página
  closeResultsMenu();
  displayScanResults();
}

function changePage(delta) {
  currentPage += delta;
  displayScanResults();
}

function goToPage(page) {
  currentPage = page;
  displayScanResults();
}

function displayScanResults() {
  const tbody = document.getElementById('results-table-body');
  const resultsMeta = document.getElementById('scan-results-meta');
  if (!tbody) return;
  tbody.innerHTML = '';

  if (resultsMeta && state.currentScanMeta?.jobId) {
    const startedAt = state.currentScanMeta.createdAt
      ? new Date(state.currentScanMeta.createdAt).toLocaleString()
      : '';
    const filesystem = state.currentScanMeta.scanContext?.filesystem || '';
    const sourceLabel = state.currentScanMeta.sourceKind === 'folder'
      ? t('recovery.sourceFolder')
      : state.currentScanMeta.sourceKind === 'drive'
        ? t('recovery.sourceDrive')
        : '';
    const modeLabel = state.currentScanMeta.mode === 'deep'
      ? t('recovery.deep')
      : state.currentScanMeta.mode === 'quick'
        ? t('recovery.quick')
        : state.currentScanMeta.mode;
    const metaParts = [sourceLabel, filesystem, modeLabel, state.currentScanMeta.drive, startedAt, `Job ${state.currentScanMeta.jobId}`].filter(Boolean);
    resultsMeta.textContent = metaParts.join(' • ');
    resultsMeta.classList.remove('hidden');
  }
  
  if (!state.scanResults || state.scanResults.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" class="px-4 py-8 text-center text-gray-500">${t('scan.noFiles')}</td></tr>`;
    return;
  }

  const filtered = getFilteredResultsWithIndex();

  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" class="px-4 py-8 text-center text-gray-500">${t('scan.noFilterMatch')}</td></tr>`;
    renderPaginationControls(0, 0);
    return;
  }

  const totalItems = filtered.length;
  const totalPages = Math.ceil(totalItems / itemsPerPage);
  
  if (currentPage > totalPages) currentPage = totalPages;
  if (currentPage < 1) currentPage = 1;

  const startIndex = (currentPage - 1) * itemsPerPage;
  const paginatedItems = filtered.slice(startIndex, startIndex + itemsPerPage);

  paginatedItems.forEach(result => {
    const row = document.createElement('tr');
    row.className = 'hover:bg-gray-800/50 transition';
    const confColor = result.confidence >= 0.8 ? 'text-success' : result.confidence >= 0.5 ? 'text-warning' : 'text-danger';
    const statusIcon = result.confidence >= 0.8 ? '<i class="fas fa-check-circle text-success"></i>'
      : result.confidence >= 0.5 ? '<i class="fas fa-exclamation-circle text-warning"></i>'
      : '<i class="fas fa-times-circle text-danger"></i>';
      
    const isChecked = state.selectedFiles.has(result.originalIndex);
    
    row.innerHTML = `
      <td class="px-4 py-3"><input type="checkbox" class="file-checkbox rounded bg-gray-700 border-gray-600" data-index="${result.originalIndex}" onchange="toggleSingleFile(this, ${result.originalIndex})" ${isChecked ? 'checked' : ''}></td>
      <td class="px-4 py-3">
        <div class="flex items-center">
          <i class="fas ${getFileIcon(result.extension)} text-gray-400 mr-2 text-lg w-5 text-center"></i>
          <div>
            <div class="font-medium">${result.extension.toUpperCase() || 'RAW'}</div>
            <div class="text-xs text-gray-500">${translateCategory(result.category || getCategoryByExtension(result.extension))}</div>
          </div>
        </div>
      </td>
      <td class="px-4 py-3 text-sm">${formatBytes(result.size)}</td>
      <td class="px-4 py-3">
        <div class="flex items-center">
          ${statusIcon}
          <span class="ml-2 ${confColor} font-medium">${(result.confidence * 100).toFixed(0)}%</span>
        </div>
      </td>
      <td class="px-4 py-3 text-sm text-gray-400 font-mono text-xs">0x${result.offset.toString(16).toUpperCase()}</td>
      <td class="px-4 py-3">
        <button onclick="recoverSingleFile(${result.originalIndex})" class="p-2 bg-gray-700 hover:bg-gray-600 rounded text-gray-300 transition" title="${t('table.recover')}">
          <i class="fas fa-download"></i>
        </button>
      </td>
    `;
    tbody.appendChild(row);
  });

  // Checkbox de select-all baseia-se nos itens VISÍVEIS (da página atual)
  const selectAllCb = document.getElementById('select-all');
  if (selectAllCb) {
    selectAllCb.checked = paginatedItems.every(r => state.selectedFiles.has(r.originalIndex));
  }
  
  updateRecoverButton();
  renderPaginationControls(totalItems, totalPages);
}

function renderPaginationControls(totalItems, totalPages) {
  const infoEl = document.getElementById('pagination-info');
  const numbersEl = document.getElementById('pagination-numbers');
  const btnPrev = document.getElementById('btn-prev-page');
  const btnNext = document.getElementById('btn-next-page');
  
  if (!infoEl || !numbersEl || !btnPrev || !btnNext) return;

  if (totalItems === 0) {
    infoEl.textContent = t('pagination.empty');
    numbersEl.innerHTML = '';
    btnPrev.disabled = true;
    btnNext.disabled = true;
    return;
  }

  const startIdx = (currentPage - 1) * itemsPerPage + 1;
  const endIdx = Math.min(currentPage * itemsPerPage, totalItems);
  infoEl.textContent = t('pagination.range', { start: startIdx, end: endIdx, total: totalItems });

  btnPrev.disabled = currentPage === 1;
  btnNext.disabled = currentPage === totalPages;

  let pagesHtml = '';
  // Limitação simples para não explodir os botões numéricos
  const maxNavBtns = 5;
  let startPage = Math.max(1, currentPage - Math.floor(maxNavBtns / 2));
  let endPage = Math.min(totalPages, startPage + maxNavBtns - 1);
  
  if (endPage - startPage + 1 < maxNavBtns) {
    startPage = Math.max(1, endPage - maxNavBtns + 1);
  }

  if (startPage > 1) {
    pagesHtml += `<button onclick="goToPage(1)" class="px-3 py-1 bg-gray-800 hover:bg-gray-700 rounded-lg text-sm">1</button>`;
    if (startPage > 2) pagesHtml += `<span class="px-2 py-1 text-gray-500">...</span>`;
  }

  for (let i = startPage; i <= endPage; i++) {
    if (i === currentPage) {
      pagesHtml += `<button class="px-3 py-1 bg-primary text-white font-bold rounded-lg text-sm">${i}</button>`;
    } else {
      pagesHtml += `<button onclick="goToPage(${i})" class="px-3 py-1 bg-gray-800 hover:bg-gray-700 rounded-lg text-sm">${i}</button>`;
    }
  }

  if (endPage < totalPages) {
    if (endPage < totalPages - 1) pagesHtml += `<span class="px-2 py-1 text-gray-500">...</span>`;
    pagesHtml += `<button onclick="goToPage(${totalPages})" class="px-3 py-1 bg-gray-800 hover:bg-gray-700 rounded-lg text-sm">${totalPages}</button>`;
  }

  numbersEl.innerHTML = pagesHtml;
}

function formatBytes(bytes, decimals = 2) {
  if (bytes === 0) return '0 Bytes';
  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

function getFileIcon(ext) {
  return {'jpg':'fa-image','jpeg':'fa-image','png':'fa-image','gif':'fa-image',
          'mp4':'fa-video','avi':'fa-video','mkv':'fa-video',
          'pdf':'fa-file-pdf','doc':'fa-file-word','docx':'fa-file-word',
          'xls':'fa-file-excel','xlsx':'fa-file-excel',
          'mp3':'fa-music','wav':'fa-music',
          'zip':'fa-file-zipper','rar':'fa-file-zipper'}[ext] || 'fa-file';
}

function selectAllFiles() {
  toggleAllFilteredFiles();
}

function getFilteredResultsWithIndex() {
  let filtered = state.scanResults.map((result, idx) => ({ ...result, originalIndex: idx }));
  if (currentSelectionFilter !== 'all') {
    filtered = filtered.filter(result => getCategoryByExtension(result.extension) === currentSelectionFilter);
  }
  filtered.sort((a, b) => {
    if (currentSelectionSort === 'confidence_desc') {
      return b.confidence - a.confidence || b.size - a.size;
    } else if (currentSelectionSort === 'size_desc') {
      return b.size - a.size;
    } else if (currentSelectionSort === 'size_asc') {
      return a.size - b.size;
    }
    return 0;
  });
  return filtered;
}

function getPaginatedResults() {
  const filtered = getFilteredResultsWithIndex();
  const startIndex = (currentPage - 1) * itemsPerPage;
  return filtered.slice(startIndex, startIndex + itemsPerPage);
}

function setPageSelection(checked) {
  getPaginatedResults().forEach(result => {
    if (checked) state.selectedFiles.add(result.originalIndex);
    else state.selectedFiles.delete(result.originalIndex);
  });
  displayScanResults();
}

function togglePageSelection() {
  const pageItems = getPaginatedResults();
  const allChecked = pageItems.length > 0 && pageItems.every(item => state.selectedFiles.has(item.originalIndex));
  setPageSelection(!allChecked);
}

function toggleAllFilteredFiles() {
  const filteredItems = getFilteredResultsWithIndex();
  const allChecked = filteredItems.length > 0
    && filteredItems.every(item => state.selectedFiles.has(item.originalIndex));
  filteredItems.forEach(item => {
    if (allChecked) state.selectedFiles.delete(item.originalIndex);
    else state.selectedFiles.add(item.originalIndex);
  });
  displayScanResults();
}

function toggleSingleFile(checkbox, idx) {
  checkbox.checked ? state.selectedFiles.add(idx) : state.selectedFiles.delete(idx);
  updateRecoverButton();
  const selectAllCb = document.getElementById('select-all');
  if (selectAllCb) {
    const pageItems = getPaginatedResults();
    selectAllCb.checked = pageItems.length > 0 && pageItems.every(item => state.selectedFiles.has(item.originalIndex));
  }
}

function updateRecoverButton() {
  const btn = document.getElementById('btn-recover');
  if (btn) {
    if (state.selectedFiles.size > 0) {
      btn.innerHTML = `<i class="fas fa-life-ring mr-2"></i>${t('recovery.recoverSelected')} (${state.selectedFiles.size})`;
      btn.disabled = false;
      btn.classList.remove('opacity-50', 'cursor-not-allowed');
    } else {
      btn.innerHTML = `<i class="fas fa-life-ring mr-2"></i>${t('recovery.recoverSelected')}`;
      btn.disabled = true;
      btn.classList.add('opacity-50', 'cursor-not-allowed');
    }
  }

  const pageButton = document.getElementById('btn-select-page');
  if (pageButton) {
    const pageItems = getPaginatedResults();
    const pageSelected = pageItems.length > 0 && pageItems.every(item => state.selectedFiles.has(item.originalIndex));
    pageButton.textContent = pageSelected ? t('recovery.clearPage') : t('recovery.selectPage');
  }

  const allButton = document.getElementById('btn-select-all-results');
  if (allButton) {
    const filteredItems = getFilteredResultsWithIndex();
    const allSelected = filteredItems.length > 0
      && filteredItems.every(item => state.selectedFiles.has(item.originalIndex));
    const baseLabel = t('recovery.selectAll');
    allButton.textContent = allSelected ? t('recovery.clearSelection') : `${baseLabel} (${filteredItems.length})`;
  }
}

async function recoverSelected() {
  if (state.selectedFiles.size === 0) { showToast(t('recovery.selectAtLeastOne'), 'warning'); return; }
  const indices = Array.from(state.selectedFiles);
  resetRecoveryResultsPolling();
  try {
    const response = await apiPost('/recover/start', { indices });
    if (response.success) {
      showToast(response.message, 'success');
      pollRecoveryResults();
    } else throw new Error(response.error);
  } catch (error) { showToast(`${t('common.error')}: ${error.message}`, 'error'); }
}

function pollRecoveryResults() {
  resetRecoveryResultsPolling();
  recoveryResultsPollTimer = setTimeout(async () => {
    const response = await loadRecoveryResults();
    if (response?.pending) {
      pollRecoveryResults();
    }
  }, 1000);
}

async function loadRecoveryResults() {
  try {
    const response = await apiGet('/recover/results');
    if (response.success && !response.pending) {
      resetRecoveryResultsPolling();
      const successful = response.results.filter(r => r.success).length;
      showToast(t('recovery.resultsSuccess', { count: successful }), 'success');
    }
    return response;
  } catch (error) {
    resetRecoveryResultsPolling();
    showToast(`${t('common.error')}: ${error.message}`, 'error');
    return null;
  }
}

async function recoverSingleFile(index) {
  state.selectedFiles.clear();
  state.selectedFiles.add(index);
  updateRecoverButton();
  await recoverSelected();
}

// ============================================================
// SMART — Kaspersky-style display
// ============================================================
async function loadSmartData() {
  const container = document.getElementById('smart-container');
  if (!container) return;
  container.innerHTML = `
    <div class="text-center py-12">
      <i class="fas fa-circle-notch fa-spin text-4xl text-primary mb-4"></i>
      <p class="text-gray-400">${t('smart.loading')}</p>
    </div>`;
  try {
    const response = await apiGet('/smart');
    if (response.success && response.available) {
      displaySmartData(response.data);
    } else {
      container.innerHTML = `
        <div class="bg-dark rounded-xl p-8 border border-gray-800 text-center">
          <i class="fas fa-hard-drive text-4xl text-gray-600 mb-4"></i>
          <h3 class="text-lg font-semibold mb-2">${t('smart.unavailableTitle')}</h3>
          <p class="text-gray-400">${response.message || t('smart.unavailableMessage')}</p>
          <p class="text-sm text-gray-500 mt-2">${t('smart.installHint')}</p>
        </div>`;
    }
  } catch (error) {
    container.innerHTML = `
      <div class="bg-dark rounded-xl p-8 border border-gray-800 text-center">
        <i class="fas fa-exclamation-circle text-4xl text-danger mb-4"></i>
        <h3 class="text-lg font-semibold mb-2">${t('common.error')}</h3>
        <p class="text-gray-400">${error.message}</p>
      </div>`;
  }
}

function displaySmartData(data) {
  const container = document.getElementById('smart-container');
  if (!container) return;

  // Build drive-letter lookup from state.drives (mountpoint ↔ device)
  const mpByIdx = {};  // index → mountpoint  e.g. { 0: 'C:', 1: 'D:' }
  state.drives.forEach((d, i) => {
    if (d.mountpoint) {
      const mp = d.mountpoint.replace(/\\$/, '');
      mpByIdx[i] = mp;
    }
  });
  // Detect system/OS drive letter
  const sysDrive = (state.drives.find(d => d.is_system) || state.drives[0]);
  const sysMp = sysDrive?.mountpoint ? sysDrive.mountpoint.replace(/\\$/, '') : 'C:';

  // Summary bar
  let html = `
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
      <div class="bg-dark rounded-xl p-4 border border-gray-800 text-center">
        <div class="text-3xl font-bold">${data.total_drives}</div>
        <div class="text-xs text-gray-400 mt-1">${t('smart.totalDrives')}</div>
      </div>
      <div class="bg-dark rounded-xl p-4 border border-success/20 text-center">
        <div class="text-3xl font-bold text-success">${data.healthy}</div>
        <div class="text-xs text-gray-400 mt-1">${t('smart.healthy')}</div>
      </div>
      <div class="bg-dark rounded-xl p-4 border border-warning/20 text-center">
        <div class="text-3xl font-bold text-warning">${data.warning}</div>
        <div class="text-xs text-gray-400 mt-1">${t('smart.alerts')}</div>
      </div>
      <div class="bg-dark rounded-xl p-4 border border-danger/20 text-center">
        <div class="text-3xl font-bold text-danger">${data.critical}</div>
        <div class="text-xs text-gray-400 mt-1">${t('smart.criticals')}</div>
      </div>
    </div>`;

  data.drives.forEach((drive, idx) => {
    const sBorder = drive.overall_status === 'healthy' ? 'border-success/20'
      : drive.overall_status === 'warning' ? 'border-warning/20'
      : drive.overall_status === 'critical' ? 'border-danger/20' : 'border-gray-700';
    const sDot = drive.overall_status === 'healthy' ? 'status-healthy'
      : drive.overall_status === 'warning' ? 'status-warning'
      : drive.overall_status === 'critical' ? 'status-critical' : 'status-unknown';
    const sBadge = drive.overall_status === 'healthy' ? 'bg-success/20 text-success'
      : drive.overall_status === 'warning' ? 'bg-warning/20 text-warning'
      : drive.overall_status === 'critical' ? 'bg-danger/20 text-danger' : 'bg-gray-700 text-gray-400';
    const sLabel = {
      healthy: t('smart.healthy'),
      warning: t('smart.warning'),
      critical: t('smart.critical'),
    }[drive.overall_status] || t('smart.unknown');

    // Resolve drive letter: use index lookup as best available heuristic
    const mountpoint = drive.mountpoint || mpByIdx[idx] || null;
    const displayLetter = mountpoint ? mountpoint.replace(/\\$/, '') : null;

    // System drive detection: index 0 or flagged
    const isOs = drive.is_system === true ||
      (displayLetter && sysMp && displayLetter.toUpperCase() === sysMp.toUpperCase());

    // Subtitle: letter (C:) + device path
    const subtitle = displayLetter
      ? `${displayLetter} &nbsp;<span class="font-mono text-gray-600 text-xs">${drive.device || ''}</span>`
      : `<span class="font-mono text-gray-500">${drive.device || t('smart.diskUnknown')}</span>`;

    // Temperature
    const temp = drive.temperature;
    const tempLabel = temp != null ? `${temp}°C` : null;
    const tempColor = temp != null ? (temp >= 55 ? 'text-danger' : temp >= 45 ? 'text-warning' : 'text-success') : 'text-gray-500';
    const tempNote = temp != null ? (temp >= 55 ? `⚠️ ${t('smart.tempCritical')}` : temp >= 45 ? `⚡ ${t('smart.tempHigh')}` : `✅ ${t('smart.tempIdeal')}`) : t('common.notAvailable');

    // Integrity (SSDs Wear)
    const integrity = (drive.is_ssd && Number.isFinite(drive.estimated_life_percent))
      ? Math.max(0, Math.min(100, drive.estimated_life_percent))
      : null;
    const integrityRing = integrity != null ? buildGauge(integrity, integrity >= 70 ? '#10b981' : integrity >= 40 ? '#f59e0b' : '#ef4444') : null;

    // Power cycles
    const cycles = drive.power_cycle_count != null ? drive.power_cycle_count : null;
    const issueSummary = summarizeSmartIssues(drive);
    const diagnosis = buildSmartDiagnosis(drive);
    const severity = getSmartSeverity(drive);
    const recommendation = buildSmartRecommendation(drive);
    const severityClass = {
      critical: 'bg-danger/15 text-danger border border-danger/25',
      warning: 'bg-warning/15 text-warning border border-warning/25',
      watch: 'bg-primary/15 text-primary border border-primary/25',
      healthy: 'bg-success/15 text-success border border-success/25',
    }[severity.tone] || 'bg-gray-700 text-gray-300 border border-gray-600';

    // Ícone: fa-server — azul para drives comuns, laranja para SO
    const driveIcon = 'fa-server';
    const driveType = drive.is_ssd ? 'SSD' : 'HDD';
    const iconColor = isOs ? 'text-orange-400' : 'text-primary';
    const metricCols = integrity != null ? 5 : 4;

    html += `
    <div class="bg-dark rounded-xl border ${sBorder} overflow-hidden mb-4">
      <div class="p-6">
        <!-- Drive header -->
        <div class="flex items-start justify-between mb-5">
          <div class="flex items-center gap-4">
            <div class="w-14 h-14 bg-gray-800 rounded-xl flex items-center justify-center flex-shrink-0">
              <i class="fas ${driveIcon} ${iconColor} text-2xl"></i>
            </div>
            <div>
              <div class="flex items-center gap-2 flex-wrap mb-1">
                <span class="status-dot ${sDot}"></span>
                <h3 class="font-bold text-lg leading-tight">${drive.model || t('smart.diskUnknown')}</h3>
                ${isOs ? `<span class="text-xs px-2 py-0.5 bg-warning/20 text-warning rounded-full font-medium">&#9881;&#65039; ${t('smart.systemDrive')}</span>` : ''}
              </div>
              <div class="flex items-center gap-2 flex-wrap text-sm">
                ${subtitle}
                <span class="text-xs px-1.5 py-0.5 bg-gray-800 rounded text-gray-400">${driveType}</span>
              </div>
            </div>
          </div>
          <span class="px-3 py-1 rounded-full text-sm font-medium flex-shrink-0 ${sBadge}">${sLabel}</span>
        </div>

        <div class="mb-5 rounded-xl px-4 py-3 border ${drive.overall_status === 'critical' ? 'border-danger/25 bg-danger/8' : drive.overall_status === 'warning' ? 'border-warning/25 bg-warning/8' : 'border-primary/15 bg-primary/6'}">
          <div class="flex items-start justify-between gap-3 mb-2">
            <div class="text-xs uppercase tracking-wide text-gray-500">${t('smart.diagnosisTitle')}</div>
            <span class="px-2.5 py-1 rounded-full text-xs font-medium ${severityClass}">${severity.label}</span>
          </div>
          <div class="text-sm text-gray-200">${diagnosis}</div>
          <div class="text-xs text-gray-400 mt-2">${t('smart.nextAction')}: ${recommendation}</div>
        </div>

        <!-- Metrics -->
        <div class="${getMetricGridClass(metricCols)}">
          <!-- Capacity -->
          <div class="bg-gray-800/50 rounded-lg p-3">
            <div class="text-xs text-gray-500 mb-1 flex items-center gap-1.5">
              <i class="fas fa-database text-gray-600"></i> ${t('smart.capacity')}
            </div>
            <div class="font-bold">${drive.capacity_formatted || t('common.notAvailable')}</div>
          </div>
          <!-- Temperature -->
          <div class="bg-gray-800/50 rounded-lg p-3">
            <div class="text-xs text-gray-500 mb-1 flex items-center gap-1.5">
              <i class="fas fa-temperature-half text-gray-600"></i> ${t('smart.temperature')}
            </div>
            <div class="font-bold ${tempColor}">${tempLabel || t('common.notAvailable')}</div>
            <div class="text-xs text-gray-500 mt-0.5">${tempNote}</div>
          </div>
          <!-- Power on hours -->
          <div class="bg-gray-800/50 rounded-lg p-3">
            <div class="text-xs text-gray-500 mb-1 flex items-center gap-1.5">
              <i class="fas fa-clock text-gray-600"></i> ${t('smart.powerOn')}
            </div>
            <div class="font-bold">${drive.power_on_hours_formatted || t('common.notAvailable')}</div>
            <div class="text-xs text-gray-500 mt-0.5">${drive.power_on_hours_raw != null ? t('smart.totalHours', { hours: drive.power_on_hours_raw }) : t('common.notAvailable')}</div>
          </div>
          <!-- Power cycles -->
          <div class="bg-gray-800/50 rounded-lg p-3">
            <div class="text-xs text-gray-500 mb-1 flex items-center gap-1.5">
              <i class="fas fa-power-off text-gray-600"></i> ${t('smart.powerCycles')}
            </div>
            <div class="font-bold">${cycles != null ? cycles : t('common.notAvailable')}</div>
            <div class="text-xs text-gray-500 mt-0.5">${cycles == null ? t('smart.notSupported') : t('smart.onOff')}</div>
          </div>
          <!-- Integrity (only when available, SSDs) -->
        ${integrity != null ? `
          <div class="bg-gray-800/50 rounded-lg p-3 flex items-center gap-3">
            <div class="flex-shrink-0">${integrityRing}</div>
            <div>
              <div class="text-xs text-gray-500 mb-0.5 flex items-center gap-1.5">
                <i class="fas fa-heart-pulse text-gray-600"></i> ${t('smart.integrity')}
              </div>
              <div class="font-bold">${integrity}%</div>
              <div class="text-xs text-gray-500">${integrity >= 70 ? t('smart.integrityGood') : integrity >= 40 ? t('smart.integrityFair') : t('smart.integrityCritical')}</div>
            </div>
          </div>` : ''}
        </div>

        ${issueSummary.length > 0 ? `
        <div class="mt-5 pt-4 border-t border-gray-800">
          <h4 class="text-sm font-medium text-gray-400 mb-3">${t('smart.attentionFactors')}</h4>
          <div class="flex flex-wrap gap-2">
            ${issueSummary.map(issue => `
              <span class="px-2.5 py-1 rounded-full text-xs font-medium ${drive.overall_status === 'critical' ? 'bg-danger/15 text-danger border border-danger/25' : 'bg-warning/15 text-warning border border-warning/25'}">${issue}</span>
            `).join('')}
          </div>
        </div>` : ''}

        ${renderSmartExtraMetrics(drive)}
        ${drive.attributes && drive.attributes.length > 0 ? renderSmartAttributes(drive.attributes) : ''}
      </div>
    </div>`;
  });

  container.innerHTML = html;
}

function buildGauge(pct, color) {
  const r = 18, circ = 2 * Math.PI * r, filled = circ * (pct / 100);
  return `<svg width="48" height="48" viewBox="0 0 48 48">
    <circle cx="24" cy="24" r="${r}" stroke="#1e293b" stroke-width="4" fill="none"/>
    <circle cx="24" cy="24" r="${r}" stroke="${color}" stroke-width="4" fill="none"
      stroke-dasharray="${filled} ${circ}" class="gauge-ring" stroke-linecap="round"/>
    <text x="24" y="28" text-anchor="middle" fill="${color}" font-size="11" font-weight="bold" font-family="Inter,sans-serif">${pct}%</text>
  </svg>`;
}

function renderSmartAttributes(attrs) {
  const filtered = attrs.filter(a => a.is_critical || a.is_warning);
  if (filtered.length === 0) return '';
  return `
    <div class="mt-5 pt-4 border-t border-gray-800">
      <h4 class="text-sm font-medium text-gray-400 mb-3">${t('smart.relevantAttributes')}</h4>
      <div class="space-y-1">
        ${filtered.slice(0, 8).map(a => `
          <div class="flex items-center justify-between text-xs py-1 px-2 rounded ${a.is_critical ? 'bg-danger/10' : 'bg-warning/10'}">
            <span class="${a.is_critical ? 'text-danger' : 'text-warning'}">${formatSmartAttributeName(a.name)}</span>
            <span class="font-mono">${a.raw_value}</span>
          </div>`).join('')}
      </div>
    </div>`;
}

function formatSmartAttributeName(name) {
  const mapping = {
    Reallocated_Sector_Ct: t('smart.attr.reallocated'),
    Current_Pending_Sector: t('smart.attr.pending'),
    Offline_Uncorrectable: t('smart.attr.offlineUncorrectable'),
    UDMA_CRC_Error_Count: t('smart.attr.crcErrors'),
    Temperature_Celsius: t('smart.attr.temperature'),
    Airflow_Temperature_Cel: t('smart.attr.temperature'),
  };
  return mapping[name] || String(name || '').replaceAll('_', ' ');
}

function summarizeSmartIssues(drive) {
  const issues = [];
  const attrs = Array.isArray(drive.attributes) ? drive.attributes : [];

  attrs.forEach(attr => {
    if (!(attr.is_warning || attr.is_critical)) return;
    if (attr.name === 'Reallocated_Sector_Ct') {
      issues.push(t('smart.issue.reallocated', { count: attr.raw_value }));
    } else if (attr.name === 'Current_Pending_Sector') {
      issues.push(t('smart.issue.pending', { count: attr.raw_value }));
    } else if (attr.name === 'Offline_Uncorrectable') {
      issues.push(t('smart.issue.offlineUncorrectable', { count: attr.raw_value }));
    } else if (attr.name === 'UDMA_CRC_Error_Count') {
      issues.push(t('smart.issue.crcErrors', { count: attr.raw_value }));
    } else if (attr.name === 'Temperature_Celsius' || attr.name === 'Airflow_Temperature_Cel') {
      issues.push(t('smart.issue.temperature', { count: attr.raw_value }));
    } else {
      issues.push(`${formatSmartAttributeName(attr.name)}: ${attr.raw_value}`);
    }
  });

  if (drive.media_errors > 0) {
    issues.push(t('smart.issue.mediaErrors', { count: drive.media_errors }));
  }
  if (drive.is_ssd && drive.percentage_used != null && drive.percentage_used >= 80) {
    issues.push(t('smart.issue.percentageUsed', { count: drive.percentage_used }));
  }

  return issues.slice(0, 4);
}

function getSmartAttrRaw(drive, attrName) {
  const attrs = Array.isArray(drive.attributes) ? drive.attributes : [];
  const attr = attrs.find(item => item.name === attrName);
  return attr ? Number(attr.raw_value) || 0 : 0;
}

function buildSmartDiagnosis(drive) {
  const reallocated = getSmartAttrRaw(drive, 'Reallocated_Sector_Ct');
  const pending = getSmartAttrRaw(drive, 'Current_Pending_Sector');
  const offline = getSmartAttrRaw(drive, 'Offline_Uncorrectable');
  const crc = getSmartAttrRaw(drive, 'UDMA_CRC_Error_Count');
  const temp = Number.isFinite(drive.temperature) ? drive.temperature : null;
  const used = Number.isFinite(drive.percentage_used) ? drive.percentage_used : null;
  const powerHours = Number.isFinite(drive.power_on_hours_raw) ? drive.power_on_hours_raw : null;

  if (drive.overall_status === 'critical') {
    if (pending > 0 || offline > 0 || (drive.media_errors || 0) > 0) {
      return t('smart.diagnosis.criticalDataRisk');
    }
    return t('smart.diagnosis.criticalGeneral');
  }

  if (drive.overall_status === 'warning') {
    if (pending > 0 || offline > 0) {
      return t('smart.diagnosis.warningSurface');
    }
    if (reallocated > 0) {
      return t('smart.diagnosis.warningReallocated', { count: reallocated });
    }
    if (temp != null && temp >= 50) {
      return t('smart.diagnosis.warningTemperature', { temp });
    }
    if (drive.is_ssd && used != null && used >= 80) {
      return t('smart.diagnosis.warningWear', { used });
    }
    if (crc > 0) {
      return t('smart.diagnosis.warningCrc', { count: crc });
    }
    return t('smart.diagnosis.warningGeneral');
  }

  if (drive.overall_status === 'healthy') {
    if (drive.is_ssd && used != null) {
      return t('smart.diagnosis.healthySsd', { used });
    }
    if (powerHours != null && powerHours >= 50000) {
      return t('smart.diagnosis.healthyHighHours', { hours: powerHours });
    }
    return t('smart.diagnosis.healthyGeneral');
  }

  return t('smart.diagnosis.unknown');
}

function getSmartSeverity(drive) {
  const pending = getSmartAttrRaw(drive, 'Current_Pending_Sector');
  const offline = getSmartAttrRaw(drive, 'Offline_Uncorrectable');
  const mediaErrors = Number.isFinite(drive.media_errors) ? drive.media_errors : 0;
  const reallocated = getSmartAttrRaw(drive, 'Reallocated_Sector_Ct');
  const used = Number.isFinite(drive.percentage_used) ? drive.percentage_used : null;
  const temp = Number.isFinite(drive.temperature) ? drive.temperature : null;
  const crc = getSmartAttrRaw(drive, 'UDMA_CRC_Error_Count');
  const powerHours = Number.isFinite(drive.power_on_hours_raw) ? drive.power_on_hours_raw : null;

  if (drive.overall_status === 'critical' || pending > 0 || offline > 0 || mediaErrors > 0) {
    return { tone: 'critical', label: t('smart.severity.high') };
  }
  if (reallocated > 0 || (drive.is_ssd && used != null && used >= 80) || (temp != null && temp >= 50)) {
    return { tone: 'warning', label: t('smart.severity.moderate') };
  }
  if (crc > 0 || (powerHours != null && powerHours >= 50000)) {
    return { tone: 'watch', label: t('smart.severity.preventive') };
  }
  return { tone: 'healthy', label: t('smart.severity.low') };
}

function buildSmartRecommendation(drive) {
  const pending = getSmartAttrRaw(drive, 'Current_Pending_Sector');
  const offline = getSmartAttrRaw(drive, 'Offline_Uncorrectable');
  const mediaErrors = Number.isFinite(drive.media_errors) ? drive.media_errors : 0;
  const reallocated = getSmartAttrRaw(drive, 'Reallocated_Sector_Ct');
  const used = Number.isFinite(drive.percentage_used) ? drive.percentage_used : null;
  const temp = Number.isFinite(drive.temperature) ? drive.temperature : null;
  const crc = getSmartAttrRaw(drive, 'UDMA_CRC_Error_Count');
  const powerHours = Number.isFinite(drive.power_on_hours_raw) ? drive.power_on_hours_raw : null;

  if (drive.overall_status === 'critical' || pending > 0 || offline > 0 || mediaErrors > 0) {
    return t('smart.recommendation.backupNow');
  }
  if (reallocated > 0) {
    return t('smart.recommendation.monitorReallocated');
  }
  if (drive.is_ssd && used != null && used >= 80) {
    return t('smart.recommendation.planReplacement');
  }
  if (temp != null && temp >= 50) {
    return t('smart.recommendation.checkCooling');
  }
  if (crc > 0) {
    return t('smart.recommendation.checkCable');
  }
  if (powerHours != null && powerHours >= 50000) {
    return t('smart.recommendation.preventiveMonitor');
  }
  return t('smart.recommendation.keepMonitoring');
}

function renderSmartExtraMetrics(drive) {
  const items = [];
  if (drive.available_spare != null) {
    items.push({
      icon: 'fa-shield-halved',
      label: t('smart.availableSpare'),
      value: `${drive.available_spare}%`,
      note: drive.available_spare <= 10 ? t('smart.critical') : t('common.available'),
    });
  }
  if (drive.percentage_used != null) {
    items.push({
      icon: 'fa-chart-line',
      label: t('smart.percentageUsed'),
      value: `${drive.percentage_used}%`,
      note: t('smart.usedWear'),
    });
  }
  if (drive.unsafe_shutdowns != null) {
    items.push({
      icon: 'fa-power-off',
      label: t('smart.unsafeShutdowns'),
      value: `${drive.unsafe_shutdowns}`,
      note: t('smart.shutdownEvents'),
    });
  }
  if (drive.media_errors != null) {
    items.push({
      icon: 'fa-triangle-exclamation',
      label: t('smart.mediaErrors'),
      value: `${drive.media_errors}`,
      note: drive.media_errors > 0 ? t('smart.attentionRecommended') : t('smart.noneDetected'),
    });
  }
  if (drive.error_log_entries != null) {
    items.push({
      icon: 'fa-file-lines',
      label: t('smart.errorLogEntries'),
      value: `${drive.error_log_entries}`,
      note: t('smart.controllerHistory'),
    });
  }

  if (items.length === 0) return '';

  return `
    <div class="mt-5 pt-4 border-t border-gray-800">
      <h4 class="text-sm font-medium text-gray-400 mb-3">${t('smart.additionalMetrics')}</h4>
      <div class="${getMetricGridClass(Math.min(items.length, 5))}">
        ${items.map(item => `
          <div class="bg-gray-800/50 rounded-lg p-3">
            <div class="text-xs text-gray-500 mb-1 flex items-center gap-1.5">
              <i class="fas ${item.icon} text-gray-600"></i> ${item.label}
            </div>
            <div class="font-bold">${item.value}</div>
            <div class="text-xs text-gray-500 mt-0.5">${item.note}</div>
          </div>
        `).join('')}
      </div>
    </div>`;
}

// ============================================================
// Logs
// ============================================================
async function loadLogs() {
  const content = document.getElementById('logs-content');
  if (!content) return;
  content.innerHTML = `<div class="p-4 text-gray-500 text-sm">${t('logs.loading')}</div>`;
  try {
    const response = await apiGet('/logs');
    if (!response.success || !response.logs.length) {
      content.innerHTML = `<div class="p-6 text-gray-500 text-sm text-center"><i class="fas fa-folder-open text-2xl mb-2 block opacity-40"></i>${t('logs.noneAvailable')}</div>`;
      return;
    }
    let html = '';
    response.logs.forEach(log => {
      const lines = _parseLogs(log.content);
      html += `
        <div class="mb-4 border border-gray-800 rounded-xl overflow-hidden">
          <div class="flex items-center justify-between px-4 py-2.5 bg-gray-800/70 border-b border-gray-700">
            <span class="text-xs font-mono text-gray-400"><i class="fas fa-file-lines mr-1.5 text-gray-600"></i>${log.filename}</span>
            <button onclick="deleteLog('${log.filename}')" class="text-xs text-danger/70 hover:text-danger transition flex items-center gap-1">
              <i class="fas fa-trash-alt"></i> ${t('logs.delete')}
            </button>
          </div>
          <div class="overflow-x-auto">
            <table class="w-full text-xs">
              ${lines.slice(0, 200).map(l => `
              <tr class="border-b border-gray-800/60 hover:bg-gray-800/30">
                <td class="px-3 py-1.5 text-gray-600 whitespace-nowrap font-mono w-36">${l.time || '—'}</td>
                <td class="px-2 py-1.5 w-20">
                  <span class="px-1.5 py-0.5 rounded text-xs font-medium ${_levelClass(l.level)}">${l.level}</span>
                </td>
                <td class="px-3 py-1.5 text-gray-300 break-all">${escapeHtml(l.message)}</td>
              </tr>`).join('')}
            </table>
          </div>
          ${lines.length > 200 ? `<div class="px-4 py-2 text-xs text-gray-600 text-right">${t('logs.hiddenLines', { count: lines.length - 200 })}</div>` : ''}
        </div>`;
    });
    content.innerHTML = html;
  } catch (error) { content.innerHTML = `<p class="text-danger p-4">${t('common.error')}: ${error.message}</p>`; }
}

async function deleteLog(filename) {
  if (!confirm(t('logs.deleteConfirm', { filename }))) return;
  try {
    const res = await apiPost('/logs/delete', { filename });
    if (res.success) { showToast(t('logs.deleted'), 'success'); loadLogs(); }
    else showToast(res.error || `${t('common.error')}`, 'error');
  } catch (e) { showToast(`${t('common.error')}: ${e.message}`, 'error'); }
}

async function clearAllLogs() {
  if (!confirm(t('logs.clearConfirm'))) return;
  try {
    const res = await apiPost('/logs/clear');
    if (res.success) { showToast(t('logs.updated'), 'success'); loadLogs(); }
    else showToast(res.error || `${t('common.error')}`, 'error');
  } catch (e) { showToast(`${t('common.error')}: ${e.message}`, 'error'); }
}
function refreshLogs() { loadLogs(); showToast(t('logs.updated'), 'success'); }

function _parseLogs(raw) {
  return (raw || '').trim().split('\n').filter(Boolean).slice().reverse().map(line => {
    const m = line.match(/^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})[,.\d]*\s+-\s+\S+\s+-\s+(\w+)\s+-\s+(.+)$/);
    if (m) return { time: m[1], level: m[2].toUpperCase(), message: m[3] };
    return { time: '', level: 'INFO', message: line };
  });
}

function _levelClass(lvl) {
  return { ERROR:'text-red-400 bg-red-400/10', WARNING:'text-yellow-400 bg-yellow-400/10',
           CRITICAL:'text-red-400 bg-red-400/20', DEBUG:'text-gray-500 bg-gray-800',
           INFO:'text-sky-400 bg-sky-400/10' }[lvl] || 'text-gray-400 bg-gray-800';
}

// ============================================================
// Scan Source Mode
// ============================================================
function setScanSource(source) {
  document.getElementById('scan-source').value = source;
  const drivePanel  = document.getElementById('src-drive-panel');
  const folderPanel = document.getElementById('src-folder-panel');
  const btnDrive    = document.getElementById('src-btn-drive');
  const btnFolder   = document.getElementById('src-btn-folder');
  if (source === 'folder') {
    drivePanel?.classList.add('hidden');
    folderPanel?.classList.remove('hidden');
    btnDrive?.classList.replace('bg-primary/20', 'bg-gray-800');
    btnDrive?.classList.replace('text-primary', 'text-gray-400');
    btnFolder?.classList.replace('bg-gray-800', 'bg-primary/20');
    btnFolder?.classList.replace('text-gray-400', 'text-primary');
  } else {
    folderPanel?.classList.add('hidden');
    drivePanel?.classList.remove('hidden');
    btnFolder?.classList.replace('bg-primary/20', 'bg-gray-800');
    btnFolder?.classList.replace('text-primary', 'text-gray-400');
    btnDrive?.classList.replace('bg-gray-800', 'bg-primary/20');
    btnDrive?.classList.replace('text-gray-400', 'text-primary');
  }
  renderFolderScanLegend();
}

async function browseFolderNative() {
  try {
    showToast(t('browse.opening'), 'info');
    const res = await apiPost('/browse-folder', {});
    if (res.success && res.path) {
      const input = document.getElementById('scan-folder-path');
      if (input) input.value = res.path;
      renderFolderScanLegend();
    } else if (!res.cancelled) {
      showToast(res.error || t('browse.failed'), 'warning');
    }
  } catch (e) { showToast(`${t('common.error')}: ${e.message}`, 'error'); }
}

async function clearScanResults() {
  await resetScanState({ clearServer: true });
}

function escapeHtml(text) {
  const d = document.createElement('div'); d.textContent = text; return d.innerHTML;
}


function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  // Deduplicate: skip if same message is already showing
  const existing = Array.from(container.children).find(el => el.textContent.trim() === message.trim());
  if (existing) return;
  const toast = document.createElement('div');
  const colors = {success:'bg-success/90 border-success',error:'bg-danger/90 border-danger',
                  warning:'bg-warning/90 border-warning',info:'bg-primary/90 border-primary'};
  const icons = {success:'fa-check-circle',error:'fa-times-circle',warning:'fa-exclamation-triangle',info:'fa-info-circle'};
  toast.className = `${colors[type]} border text-white px-4 py-3 rounded-lg shadow-lg flex items-center slide-in`;
  toast.innerHTML = `<i class="fas ${icons[type]} mr-3"></i><span>${message}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0'; toast.style.transform = 'translateX(100%)'; toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

function disableScanControls() {
  const btn = document.getElementById('start-scan-btn');
  if (btn) { btn.disabled = true; btn.classList.add('opacity-50','cursor-not-allowed'); btn.innerHTML = `<i class="fas fa-spinner fa-spin mr-2"></i>${t('nav.scanning')}`; }
  const dsel = document.getElementById('scan-drive');
  const msel = document.getElementById('scan-mode');
  const fsel = document.getElementById('scan-folder-path');
  const browseBtn = document.getElementById('browse-folder-btn');
  const sourceDriveBtn = document.getElementById('src-btn-drive');
  const sourceFolderBtn = document.getElementById('src-btn-folder');
  if (dsel) dsel.disabled = true;
  if (msel) msel.disabled = true;
  if (fsel) fsel.disabled = true;
  if (browseBtn) browseBtn.disabled = true;
  if (sourceDriveBtn) sourceDriveBtn.disabled = true;
  if (sourceFolderBtn) sourceFolderBtn.disabled = true;
}

function enableScanControls() {
  const btn = document.getElementById('start-scan-btn');
  if (btn) { btn.disabled = false; btn.classList.remove('opacity-50','cursor-not-allowed'); btn.innerHTML = `<i class="fas fa-play mr-2"></i>${t('recovery.start')}`; }
  const dsel = document.getElementById('scan-drive');
  const msel = document.getElementById('scan-mode');
  const fsel = document.getElementById('scan-folder-path');
  const browseBtn = document.getElementById('browse-folder-btn');
  const sourceDriveBtn = document.getElementById('src-btn-drive');
  const sourceFolderBtn = document.getElementById('src-btn-folder');
  if (dsel) dsel.disabled = false;
  if (msel) msel.disabled = false;
  if (fsel) fsel.disabled = false;
  if (browseBtn) browseBtn.disabled = false;
  if (sourceDriveBtn) sourceDriveBtn.disabled = false;
  if (sourceFolderBtn) sourceFolderBtn.disabled = false;
  setScanSource(document.getElementById('scan-source')?.value || 'drive');
}
