// Provera unosa i čuvanja kroz funkcije formulara iz aplikacije.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync(require('node:path').join(__dirname, '../index.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const nodes = new Map();
function element(name) {
  if (!nodes.has(name)) nodes.set(name, {
    innerHTML: '', disabled: false, classList: {add(){}, remove(){}},
    querySelector: element, querySelectorAll: () => [], addEventListener(){}, focus(){}
  });
  return nodes.get(name);
}
let disk = null;
const context = vm.createContext({
  URL, console, crypto: require('node:crypto').webcrypto,
  document: {querySelector: element, addEventListener(){}}, window: {addEventListener(){}},
  setInterval(){}, setTimeout(){}, localStorage: {getItem: () => null},
  FormData: class {constructor(form){this.values=form.values}get(name){return this.values[name] ?? ''}},
  fetch: async (url, options) => {
    if (url === '/api/save-state') disk = JSON.parse(options.body);
    return {ok:true, json:async()=>url === '/api/state' ? disk : url === '/api/servers' ? [] : {ok:'true'}};
  }
});
const run = code => vm.runInContext(code, context);
(async () => {
  run(script);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(run("validIp('203.0.113.10')"), true);
  assert.equal(run("validIp('2001:db8::1')"), true);
  assert.equal(run("validIp('999.0.0.1')"), false);
  assert.equal(run("validIp('example.com')"), false);
  run('hostForm()');
  assert.ok(!element('#modal').innerHTML.includes('name="user"'));
  for (const name of ['label', 'panelUrl', 'address']) assert.ok(!element('#modal').innerHTML.includes(`name="${name}"`));
  const form = element('#hostForm');
  form.values = {host:'203.0.113.10', port:''};
  await form.onsubmit({preventDefault(){}, target:form, currentTarget:form});
  assert.equal(disk.hosts.length, 1);
  assert.equal(disk.hosts[0].port, '22');
  assert.ok(element('#hostList').innerHTML.includes('203.0.113.10:22'));
  assert.equal(run("serverAddress({host:'203.0.113.10',port:'2222'})"), '203.0.113.10:2222');
  assert.equal(run("serverAddress({host:'2001:db8::1',port:'22'})"), '[2001:db8::1]:22');
  assert.equal(disk.hosts[0].accounts.length, 0);
  run('accountForm(data[0].id)');
  const account = element('#accountForm');
  account.values = {user:'deploy'};
  await account.onsubmit({preventDefault(){}, target:account, currentTarget:account});
  assert.equal(disk.hosts[0].accounts[0].user, 'deploy');
  assert.equal(disk.hosts[0].accounts[0].key, 'none');
  run('data=[];savedHosts=[];savedUsers=[];savedPanelUrls={}');
  await run('loadSavedState().then(loadRepositoryTargets)');
  assert.equal(run('data[0].accounts[0].user'), 'deploy');
  assert.ok(element('#hostList').innerHTML.includes('203.0.113.10:22'));
  run("data[0].label='stara-oznaka';data[0].panelUrl='https://panel.example.com';data[0].address='https://example.com';render()");
  assert.ok(!element('#hostList').innerHTML.includes('stara-oznaka'));
  assert.ok(element('#hostList').innerHTML.includes('href="https://panel.example.com"'));
  assert.ok(!element('#hostList').innerHTML.includes('data-panel-url')); 
  console.log('Unos IP-a i porta, prikaz :22, klikabilan URL i čuvanje korisnika: OK');
})().catch(error => {console.error(error);process.exitCode=1});
