const { contextBridge, ipcRenderer } = require('electron');

let onLetteredImageChangedCallback = null;
ipcRenderer.on('lettered-image-changed', (_, storySlug, filename) => {
  if (onLetteredImageChangedCallback) onLetteredImageChangedCallback(storySlug, filename);
});

contextBridge.exposeInMainWorld('letteringApi', {
  getProjectRoot: () => ipcRenderer.invoke('get-project-root'),
  setProjectRoot: () => ipcRenderer.invoke('set-project-root'),
  listStories: () => ipcRenderer.invoke('list-stories'),
  listBoardImages: (storySlug) => ipcRenderer.invoke('list-board-images', storySlug),
  getImagePath: (storySlug, filename) => ipcRenderer.invoke('get-image-path', storySlug, filename),
  getLetteredImagePath: (storySlug, filename) => ipcRenderer.invoke('get-lettered-image-path', storySlug, filename),
  readLetteringJson: (storySlug, imageBasename) => ipcRenderer.invoke('read-lettering-json', storySlug, imageBasename),
  prefillLetteringFromScene: (storySlug, imageBasename) => ipcRenderer.invoke('prefill-lettering-from-scene', storySlug, imageBasename),
  writeLetteringJson: (storySlug, imageBasename, data) => ipcRenderer.invoke('write-lettering-json', storySlug, imageBasename, data),
  readDefinitions: (storySlug) => ipcRenderer.invoke('read-definitions', storySlug),
  runOverlay: (storySlug) => ipcRenderer.invoke('run-overlay', storySlug),
  watchLetteredFolder: (storySlug) => ipcRenderer.invoke('watch-lettered-folder', storySlug),
  onLetteredImageChanged: (cb) => { onLetteredImageChangedCallback = cb; },
});
