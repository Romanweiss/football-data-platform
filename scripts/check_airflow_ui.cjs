// Actual Airflow UI check using the project's existing Playwright dependency.
// Operator logs in interactively. No passwords/tokens/storage state are read,
// printed or persisted by this script; no DAG triggers/task state mutations.
const { chromium } = require('../frontend/node_modules/playwright');

let server;
(async () => {
  // Isolated temporary browser, loopback only; control endpoint lives only while
  // this manual check runs. It never attaches to the operator's normal profile.
  server = await chromium.launchServer({ channel: 'msedge', headless: false,
    host: '127.0.0.1', port: 19222, wsPath: 'airflow-stage6c2-ui' });
  const browser = await chromium.connect(server.wsEndpoint());
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  await page.goto('http://127.0.0.1:18080/dags/statsbomb_context_pipeline');
  console.log('Airflow UI opened. Waiting for operator login; no credentials are collected.');
  const deadline = Date.now() + 40 * 60 * 1000;
  let authenticated = false;
  while (Date.now() < deadline) {
    if (!page.url().includes('login') && await page.getByText('statsbomb_context_pipeline', { exact: true }).count()) {
      authenticated = true;
      break;
    }
    await page.waitForTimeout(2000);
  }
  if (!authenticated) throw new Error('Operator login not completed');
  console.log('Authenticated DAG UI visible. Waiting for operator/replay verification.');
  // Keep the authenticated window available for read-only UI inspection.
  // Enter in this terminal completes the check after inspecting graph/params/logs.
  process.stdin.resume();
  await new Promise(resolve => process.stdin.once('data', resolve));
  console.log('UI session finished; browser context discarded.');
  await browser.close();
})().catch(error => {
  console.error('Airflow UI check incomplete: exception=' + error.constructor.name);
  process.exitCode = 1;
}).finally(async () => { if (server) await server.close(); });
