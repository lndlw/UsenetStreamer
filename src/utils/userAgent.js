// Mimic current real clients so indexers accept the requests. Keep these in
// step with the latest Prowlarr (search) / SABnzbd (download) releases.
//   - Prowlarr (Servarr) sends "{App}/{fullVersion} ({osName} {osVersion})".
//   - SABnzbd sends "SABnzbd/{version}" (no OS suffix).
const DEFAULT_SEARCH_UA = 'Prowlarr/2.5.2.5491 (ubuntu 24.04)';
const DEFAULT_DOWNLOAD_UA = 'SABnzbd/5.1.0';

function getDefaultSearchUserAgent() {
  return DEFAULT_SEARCH_UA;
}

function getDefaultDownloadUserAgent() {
  return DEFAULT_DOWNLOAD_UA;
}

// Backward-compatible alias — returns the download UA. Existing callers that
// download NZB payloads continue to work unchanged.
function getRandomUserAgent() {
  return DEFAULT_DOWNLOAD_UA;
}

module.exports = {
  getRandomUserAgent,
  getDefaultSearchUserAgent,
  getDefaultDownloadUserAgent,
  DEFAULT_SEARCH_UA,
  DEFAULT_DOWNLOAD_UA,
};
