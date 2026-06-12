const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('launcherApi', {
  getProfiles: () => ipcRenderer.invoke('profiles:get'),
  saveProfiles: (profiles) => ipcRenderer.invoke('profiles:save', profiles),
  validateProfiles: () => ipcRenderer.invoke('profiles:validate'),
  launchProfile: (profileId) => ipcRenderer.invoke('profile:launch', profileId),
  launchItem: (profileId, itemId) => ipcRenderer.invoke('item:launch', profileId, itemId),
  revealItem: (profileId, itemId) => ipcRenderer.invoke('item:reveal', profileId, itemId),
  choosePath: (kind) => ipcRenderer.invoke('dialog:choose-path', kind),
  revealConfig: () => ipcRenderer.invoke('config:reveal'),
  getConfigPath: () => ipcRenderer.invoke('config:path'),
  getConfigInfo: () => ipcRenderer.invoke('config:info')
});
