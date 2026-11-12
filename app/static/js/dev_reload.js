// The development server gets a new version after each source-triggered restart.
let loadedVersion;

async function checkForReload() {
  try {
    const response = await fetch('/__dev/reload', { cache: 'no-store' });
    if (!response.ok) return;
    const { version } = await response.json();
    if (loadedVersion && version !== loadedVersion) {
      window.location.reload();
      return;
    }
    loadedVersion = version;
  } catch {
    // The server is briefly unavailable while Uvicorn restarts.
  }
}

checkForReload();
setInterval(checkForReload, 1000);
