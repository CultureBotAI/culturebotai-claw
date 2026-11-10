// Execute the theme scripts a generated page actually emits (#668); no browser
// dependency. Usage: node shared_html_theme_harness.cjs <page.html>
const fs = require('fs');
const vm = require('vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(process.argv[2], 'utf8');

function script(role) {
  const found = [...html.matchAll(/<script data-mech-theme="([a-z]+)">([\s\S]*?)<\/script>/g)]
    .filter(match => match[1] === role);
  assert.equal(found.length, 1, `exactly one ${role} script`);
  return found[0][2];
}
const INIT = script('init');
const TOGGLE = script('toggle');
// The toggle finds its button as the element just before it.
assert.match(html, /<button type="button" class="theme-toggle" aria-pressed="false" hidden>Dark theme<\/button>\n<script data-mech-theme="toggle">/);

// storage: 'ok', 'get' (getItem throws), 'set' (setItem throws) or 'denied'
// (touching localStorage at all throws, as blocked site data does).
function load({saved = null, osDark = false, storage = 'ok'} = {}) {
  const attributes = new Map();
  const root = {
    getAttribute: name => (attributes.has(name) ? attributes.get(name) : null),
    setAttribute: (name, value) => attributes.set(name, String(value)),
  };
  const items = new Map(saved === null ? [] : [['mech-theme', saved]]);
  const store = {
    getItem(key) { if (storage === 'get') throw new Error('blocked'); return items.has(key) ? items.get(key) : null; },
    setItem(key, value) { if (storage === 'set') throw new Error('blocked'); items.set(key, String(value)); },
  };
  const listeners = {};
  const button = {
    hidden: true, attributes: new Map(),
    setAttribute(name, value) { this.attributes.set(name, String(value)); },
    addEventListener(name, callback) { listeners[name] = callback; },
  };
  const media = {matches: osDark, addEventListener(name, callback) { this[name] = callback; }};
  const context = {
    document: {documentElement: root, currentScript: {previousElementSibling: button}},
    window: {matchMedia(query) { assert.equal(query, '(prefers-color-scheme: dark)'); return media; }},
  };
  Object.defineProperty(context, 'localStorage', {
    get() { if (storage === 'denied') throw new Error('denied'); return store; },
  });
  vm.runInNewContext(INIT, context);
  const beforeBody = root.getAttribute('data-theme');
  vm.runInNewContext(TOGGLE, context);
  return {
    beforeBody, items, media, button,
    theme: () => root.getAttribute('data-theme'),
    pressed: () => button.attributes.get('aria-pressed'),
    click: () => listeners.click(),
  };
}

// A saved choice is on <html> before the body exists, and wins over the OS.
for (const [saved, osDark] of [['dark', false], ['dark', true], ['light', true], ['light', false]]) {
  const page = load({saved, osDark});
  assert.equal(page.beforeBody, saved);
  assert.equal(page.pressed(), saved === 'dark' ? 'true' : 'false');
  assert.equal(page.button.hidden, false);
}
// Anything else is ignored, leaving the OS preference to the stylesheet.
for (const saved of [null, 'sepia', '']) {
  const page = load({saved, osDark: true});
  assert.equal(page.beforeBody, null);
  assert.equal(page.pressed(), 'true');
}
// The toggle flips from whatever is showing, and remembers the choice.
{
  const page = load({osDark: true});
  page.click();
  assert.equal(page.theme(), 'light');
  assert.equal(page.items.get('mech-theme'), 'light');
  assert.equal(page.pressed(), 'false');
  page.click();
  assert.equal(page.theme(), 'dark');
  assert.equal(page.items.get('mech-theme'), 'dark');
  assert.equal(page.pressed(), 'true');
}
// Without a choice, an OS switch is reflected in the control's state.
{
  const page = load({osDark: false});
  assert.equal(page.pressed(), 'false');
  page.media.matches = true;
  page.media.change();
  assert.equal(page.pressed(), 'true');
}
// Storage that refuses never breaks the page or the toggle.
for (const storage of ['get', 'set', 'denied']) {
  const page = load({saved: 'dark', storage});
  assert.equal(page.beforeBody, storage === 'set' ? 'dark' : null);
  const before = page.theme() || 'light';
  page.click();
  assert.equal(page.theme(), before === 'dark' ? 'light' : 'dark');
}
