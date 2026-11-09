// Execute the actual emitted discussion script; no browser-library dependency.
const fs = require('fs');
const vm = require('vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(process.argv[2], 'utf8');
const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)]
  .map(match => match[1]).filter(script => script.trim());
assert.equal(scripts.length, 1);

class Element {
  constructor(tag = 'div') {
    this.tag = tag; this.children = []; this.attributes = {}; this.events = {};
    this.value = ''; this.checked = false; this.disabled = true; this.textContent = '';
  }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren() { this.children = []; this.innerHTML = ''; }
  setAttribute(name, value) { this.attributes[name] = value; }
  getAttribute(name) { return this.attributes[name]; }
  addEventListener(name, callback) { this.events[name] = callback; }
  focus() { this.focused = true; }
  querySelectorAll() {
    return this.children.flatMap(child => [
      ...(child.tag === 'input' && child.type === 'checkbox' ? [child] : []),
      ...child.querySelectorAll(),
    ]);
  }
}

function run(data, metrics) {
  const elements = new Map();
  const get = id => {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  };
  const document = {
    baseURI: 'https://fixture.invalid/app/discussions/',
    getElementById: get,
    createElement: tag => new Element(tag),
    createTextNode: text => Object.assign(new Element('#text'), {textContent: text}),
    querySelectorAll: () => get('facets').querySelectorAll(),
  };
  if (metrics === undefined && Array.isArray(data)) metrics = {
    total_discussions: data.length,
    total_knowledge_gaps: data.filter(row => row && row.is_gap === 'Knowledge gap').length,
    total_source_entries: data.length,
  };
  const window = {location: {reload() {}}, searchMetrics: metrics, repoName: 'FixtureMech'};
  if (data !== undefined) window.searchData = data;
  vm.runInNewContext(scripts[0], {document, window, URL});
  return {get};
}

for (const data of [undefined, null, {}, [null],
    [{attaches_to: 'not-an-array'}], [{evidence_refs: {}}], [{evidence_refs: [null]}]]) {
  const {get} = run(data);
  assert.match(get('count').textContent, /could not be loaded/);
  assert.equal(get('q').disabled, true);
  assert.equal(get('results').children[0].textContent, 'Retry loading discussions');
}
for (const metrics of [{}, null,
    {total_discussions: -1, total_knowledge_gaps: 0, total_source_entries: 1},
    {total_discussions: 0, total_knowledge_gaps: 0, total_source_entries: 1},
    {total_discussions: 1, total_knowledge_gaps: 1, total_source_entries: 1},
    {total_discussions: 1, total_knowledge_gaps: 0, total_source_entries: 0},
    {total_discussions: 1, total_knowledge_gaps: 0, total_source_entries: 2}]) {
  const {get} = run([{prompt: 'Needle'}], metrics);
  assert.match(get('count').textContent, /could not be loaded/);
  assert.equal(get('metrics').textContent, 'Discussion counts unavailable');
  assert.equal(get('q').disabled, true);
}
{
  const {get} = run([]);
  assert.equal(get('count').textContent, '0 of 0 shown');
  assert.equal(get('q').disabled, false);
}
const rows = [
  {prompt: 'Needle <b>biology</b>', source_name: 'Alpha', kind: '<img src=x>',
    status: 'OPEN', is_gap: 'Knowledge gap', page_url: 'javascript:alert(1)', evidence_refs: ['PMID:1']},
  {prompt: 'Other', source_name: 'Beta', kind: 'DISCUSSION', status: 'CLOSED',
    page_url: 'record.html?term="quoted"', evidence_refs: []},
];
const {get} = run(rows);
assert.equal(get('count').textContent, '2 of 2 shown');
assert(!get('results').innerHTML.includes('href="javascript:'));
assert(get('results').innerHTML.includes('term=&quot;quoted&quot;'));
assert(get('results').innerHTML.includes('&lt;b&gt;biology&lt;/b&gt;'));
const labels = get('facets').children.flatMap(facet => facet.children);
assert(labels.some(label => label.children.some(child => child.textContent.includes('<img src=x>'))));
assert(labels.every(label => label.children.every(child => ['input', '#text'].includes(child.tag))));
get('q').value = 'needle'; get('q').events.input();
assert.equal(get('count').textContent, '1 of 2 shown');
get('q').value = 'absent'; get('q').events.input();
assert.equal(get('count').textContent, '0 of 2 shown');
const checkbox = get('facets').querySelectorAll().find(input => input.getAttribute('data-v') === 'OPEN');
checkbox.checked = true; checkbox.events.change();
get('clear-filters').events.click();
assert.equal(get('count').textContent, '2 of 2 shown');
assert.equal(checkbox.checked, false);
assert.equal(get('q').focused, true);
