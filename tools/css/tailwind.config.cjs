// The theme lives in web/static/tailwind-theme.json so the build here and the
// on-demand runtime used by plugin screens (tailwindRuntime.js) can never drift.
// Colors resolve to CSS variables defined in custom.css, so the light/dark
// switch (`html.dark`) re-themes everything without a rebuild.
const path = require('path');
const root = path.resolve(__dirname, '..', '..');
const theme = require(path.join(root, 'web/static/tailwind-theme.json'));

module.exports = {
  ...theme,
  content: [
    path.join(root, 'web/index.html'),
    path.join(root, 'web/static/js/**/*.js'),
    // Plugins shipped with the app. User/Store plugins are NOT scanned here:
    // their screens load the on-demand runtime instead (see tailwindRuntime.js).
    path.join(root, 'assets/plugin_examples/**/*.js'),
  ],
};
