const { app, BrowserWindow, ipcMain, dialog, protocol } = require('electron');
const path = require('path');
const fs = require('fs');

let mainWindow = null;
let projectRoot = null;
let letteredWatcher = null;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 900,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  mainWindow.loadFile('index.html');
  mainWindow.on('closed', () => { mainWindow = null; });
}

app.whenReady().then(() => {
  protocol.registerFileProtocol('project', (request, callback) => {
    if (!projectRoot) return callback({ error: -2 });
    const u = new URL(request.url);
    const subpath = decodeURIComponent(u.pathname.replace(/^\/+/, '')).replace(/%5C/g, '\\');
    const target = path.join(projectRoot, subpath);
    const normalized = path.normalize(target);
    if (!normalized.startsWith(path.normalize(projectRoot)) || !fs.existsSync(normalized)) return callback({ error: -2 });
    callback({ path: normalized });
  });
  createWindow();
});
app.on('window-all-closed', () => app.quit());
app.on('activate', () => { if (!mainWindow) createWindow(); });

// Try to detect project root when started from repo (e.g. lettering-editor is inside dev-jesus)
const defaultRoot = path.resolve(__dirname, '..');
if (fs.existsSync(path.join(defaultRoot, 'stories')) && fs.existsSync(path.join(defaultRoot, 'scripts', 'overlay_storyboard_text.py'))) {
  projectRoot = defaultRoot;
}

ipcMain.handle('get-project-root', () => projectRoot);

ipcMain.handle('set-project-root', async () => {
  const { canceled, filePaths } = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory'],
    title: 'Select dev-jesus project root (folder containing stories/ and scripts/)',
  });
  if (canceled || !filePaths.length) return projectRoot;
  const root = filePaths[0];
  if (fs.existsSync(path.join(root, 'stories')) && fs.existsSync(path.join(root, 'scripts', 'overlay_storyboard_text.py'))) {
    projectRoot = root;
    return projectRoot;
  }
  return null;
});

ipcMain.handle('list-stories', async () => {
  if (!projectRoot) return [];
  const storiesPath = path.join(projectRoot, 'stories');
  if (!fs.existsSync(storiesPath)) return [];
  const entries = fs.readdirSync(storiesPath, { withFileTypes: true });
  return entries.filter(e => e.isDirectory() && !e.name.startsWith('.')).map(e => e.name).sort();
});

ipcMain.handle('list-board-images', async (_, storySlug) => {
  if (!projectRoot || !storySlug) return [];
  const boardsPath = path.join(projectRoot, 'stories', storySlug, 'boards');
  if (!fs.existsSync(boardsPath)) return [];
  const files = fs.readdirSync(boardsPath);
  const images = files.filter(f => /\.(jpg|jpeg|png)$/i.test(f) && !f.includes('-lettered'));
  return images.sort();
});

ipcMain.handle('get-image-path', (_, storySlug, filename) => {
  if (!projectRoot || !storySlug || !filename) return null;
  const p = path.join(projectRoot, 'stories', storySlug, 'boards', filename);
  if (!fs.existsSync(p)) return null;
  const relative = path.relative(projectRoot, p).split(path.sep).join('/');
  return 'project:///' + relative;
});

ipcMain.handle('get-lettered-image-path', (_, storySlug, filename) => {
  if (!projectRoot || !storySlug || !filename) return null;
  const base = path.basename(filename, path.extname(filename)).replace(/-lettered$/, '');
  const letteredName = base + '-lettered.jpg';
  const p = path.join(projectRoot, 'stories', storySlug, 'boards', 'lettered', letteredName);
  if (!fs.existsSync(p)) return null;
  const relative = path.relative(projectRoot, p).split(path.sep).join('/');
  return 'project:///' + relative;
});

ipcMain.handle('watch-lettered-folder', (_, storySlug) => {
  if (letteredWatcher) {
    try { letteredWatcher.close(); } catch (_) {}
    letteredWatcher = null;
  }
  if (!projectRoot || !storySlug || !mainWindow) return;
  const letteredDir = path.join(projectRoot, 'stories', storySlug, 'boards', 'lettered');
  if (!fs.existsSync(letteredDir)) return;
  letteredWatcher = fs.watch(letteredDir, (eventType, filename) => {
    if (filename && mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('lettered-image-changed', storySlug, filename);
    }
  });
});

ipcMain.handle('read-lettering-json', async (_, storySlug, imageBasename) => {
  if (!projectRoot || !storySlug || !imageBasename) return null;
  const name = imageBasename.replace(/\.(jpg|jpeg|png)$/i, '');
  const letteringPath = path.join(projectRoot, 'stories', storySlug, 'lettering', name + '.json');
  if (!fs.existsSync(letteringPath)) return null;
  try {
    const data = fs.readFileSync(letteringPath, 'utf8');
    return JSON.parse(data);
  } catch {
    return null;
  }
});

ipcMain.handle('prefill-lettering-from-scene', async (_, storySlug, imageBasename) => {
  if (!projectRoot || !storySlug || !imageBasename) return null;
  const scriptPath = path.join(projectRoot, 'scripts', 'overlay_storyboard_text.py');
  const storiesDir = path.join(projectRoot, 'stories', storySlug);
  const scenesDir = path.join(storiesDir, 'scenes');
  if (!fs.existsSync(scriptPath) || !fs.existsSync(scenesDir)) return null;
  const base = path.basename(imageBasename, path.extname(imageBasename)).replace(/-lettered$/, '');
  const sceneMatch = base.match(/^scene-(\d+)-/);
  const sceneNum = sceneMatch ? sceneMatch[1] : null;
  let scenePath;
  if (sceneNum) {
    const candidate = path.join(scenesDir, `scene-${sceneNum.padStart(4, '0')}.md`);
    scenePath = fs.existsSync(candidate) ? candidate : null;
  }
  if (!scenePath) {
    const sceneFiles = fs.readdirSync(scenesDir).filter(f => /^scene-\d+\.md$/.test(f)).sort();
    if (!sceneFiles.length) return null;
    scenePath = path.join(scenesDir, sceneFiles[0]);
  }
  const boardsDir = path.join(storiesDir, 'boards');
  return new Promise((resolve) => {
    const args = ['--scene', scenePath, '--boards-dir', boardsDir, '--print-lettering', '--for-image', imageBasename];
    const proc = require('child_process').spawn('python3', [scriptPath, ...args], { cwd: projectRoot, stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = '';
    let stderr = '';
    proc.stdout.on('data', (c) => { stdout += c.toString(); });
    proc.stderr.on('data', (c) => { stderr += c.toString(); });
    proc.on('close', (code) => {
      try {
        const data = JSON.parse(stdout);
        resolve(data && data.panels ? data : null);
      } catch {
        resolve(null);
      }
    });
  });
});

ipcMain.handle('write-lettering-json', async (_, storySlug, imageBasename, data) => {
  if (!projectRoot || !storySlug || !imageBasename) return false;
  const name = imageBasename.replace(/\.(jpg|jpeg|png)$/i, '');
  const letteringDir = path.join(projectRoot, 'stories', storySlug, 'lettering');
  fs.mkdirSync(letteringDir, { recursive: true });
  const letteringPath = path.join(letteringDir, name + '.json');
  try {
    fs.writeFileSync(letteringPath, JSON.stringify(data, null, 2), 'utf8');
    return true;
  } catch {
    return false;
  }
});

ipcMain.handle('read-definitions', async (_, storySlug) => {
  if (!projectRoot || !storySlug) return null;
  const p = path.join(projectRoot, 'stories', storySlug, 'definitions.json');
  if (!fs.existsSync(p)) return null;
  try {
    return JSON.parse(fs.readFileSync(p, 'utf8'));
  } catch {
    return null;
  }
});

ipcMain.handle('run-overlay', async (_, storySlug) => {
  if (!projectRoot || !storySlug) return { ok: false, error: 'No project or story' };
  const { spawn } = require('child_process');
  const scriptPath = path.join(projectRoot, 'scripts', 'overlay_storyboard_text.py');
  const storiesDir = path.join(projectRoot, 'stories', storySlug);
  const scenesDir = path.join(storiesDir, 'scenes');
  if (!fs.existsSync(scriptPath) || !fs.existsSync(scenesDir)) return { ok: false, error: 'Script or scenes not found' };
  const sceneFiles = fs.readdirSync(scenesDir).filter(f => /^scene-\d+\.md$/.test(f)).sort();
  if (!sceneFiles.length) return { ok: false, error: 'No scene markdown found' };
  const boardsDir = path.join(storiesDir, 'boards');
  const outputDir = path.join(boardsDir, 'lettered');
  const letteringDir = path.join(storiesDir, 'lettering');
  const definitionsPath = path.join(storiesDir, 'definitions.json');
  if (!fs.existsSync(outputDir)) fs.mkdirSync(outputDir, { recursive: true });

  const errors = [];
  let processed = 0;
  for (const sceneFile of sceneFiles) {
    const scenePath = path.join(scenesDir, sceneFile);
    const exitCode = await new Promise((resolve) => {
      const args = ['--scene', scenePath, '--boards-dir', boardsDir, '--output-dir', outputDir, '--lettering-dir', letteringDir];
      if (fs.existsSync(definitionsPath)) args.push('--definitions-file', definitionsPath);
      const proc = spawn('python3', [scriptPath, ...args], { cwd: projectRoot, stdio: 'pipe' });
      let stderr = '';
      proc.stderr.on('data', (c) => { stderr += c.toString(); });
      proc.on('close', (code) => {
        if (code !== 0 && !stderr.includes('No storyboard images found')) {
          errors.push(sceneFile + ': ' + (stderr || `Exit ${code}`));
        }
        if (code === 0) processed++;
        resolve(code);
      });
    });
  }
  if (errors.length) return { ok: false, error: errors.join('\n') };
  return { ok: true, processed };
});
