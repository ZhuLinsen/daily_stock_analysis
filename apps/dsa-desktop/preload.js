const { contextBridge } = require('electron');

contextBridge.exposeInMainWorld('dsaDesktop', {
  version: '0.1.0',
});
