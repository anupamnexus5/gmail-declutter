const $ = (id) => document.getElementById(id);
let subscriptions = [];
let connected = false;
let busy = false;
async function api(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || 'Something went wrong. Please try again.');
  return data;
}
function message(text) { $('message').textContent = text; }
function render() {
  const query = $('search').value.toLowerCase();
  const visible = subscriptions.filter(s => `${s.sender} ${s.address} ${s.list_id || ''} ${s.latest_subject}`.toLowerCase().includes(query));
  $('rows').replaceChildren();
  for (const s of visible) {
    const row = document.createElement('tr');
    const sender = document.createElement('td');
    const name = document.createElement('strong'); name.textContent = s.sender;
    const detail = document.createElement('small'); detail.textContent = s.list_id || s.address;
    sender.append(name, detail);
    const subject = document.createElement('td'); subject.textContent = s.latest_subject;
    const count = document.createElement('td'); count.textContent = s.count;
    const method = document.createElement('td');
    const badge = document.createElement('span'); badge.className = 'badge' + (s.unsubscribe_method === 'One-click advertised' ? '' : ' manual');
    badge.textContent = s.unsubscribe_method; method.append(badge);
    row.append(sender, subject, count, method); $('rows').append(row);
  }
  $('empty').hidden = visible.length > 0;
  if (!visible.length) $('empty').textContent = query ? 'No subscriptions match your filter.' : 'No promotional subscriptions found in this scan.';
  $('count').textContent = `${visible.length} of ${subscriptions.length} subscriptions`;
}
function show(data) {
  subscriptions = data.subscriptions;
  $('emails').textContent = data.scanned;
  $('lists').textContent = subscriptions.length;
  $('supported').textContent = subscriptions.filter(s => s.unsubscribe_method === 'One-click advertised').length;
  $('mode').textContent = data.demo ? 'Sample data' : 'Your Gmail';
  message(data.demo ? 'Demo workspace: these are fictional subscriptions. No Gmail account has been accessed.' : `Scanned ${data.scanned} promotional emails from the last 90 days.${data.limited ? ' Scan limit reached; older messages are not included.' : ''} Nothing has been unsubscribed.`);
  render();
}
async function load(url, options = {}) {
  if (busy) return;
  busy = true; $('demo').disabled = true; $('scan').disabled = true;
  message('Loading subscriptions…');
  try { show(await api(url, options)); } catch (error) { message(error.message); }
  finally { busy = false; $('demo').disabled = false; $('scan').disabled = !connected; }
}
$('demo').onclick = () => load('/api/demo');
$('scan').onclick = () => load('/api/scan', {method:'POST'});
$('search').oninput = render;
$('disconnect').onclick = async () => {
  if (busy) return;
  try { await api('/api/disconnect', {method:'POST'}); location.replace('/'); }
  catch (error) { message(error.message); }
};
(async () => {
  try {
    const status = await api('/api/status'); connected = status.connected;
    $('scan').disabled = !connected; $('disconnect').hidden = !connected; $('connect').hidden = connected;
    $('mode').textContent = connected ? 'Gmail connected' : 'Not connected';
    $('setup').hidden = status.configured;
    const notice = new URLSearchParams(location.search).get('notice');
    const notices = {setup:'Complete the Google OAuth setup below to connect Gmail.',cancelled:'Sign-in was cancelled. You can try again whenever you’re ready.',failed:'Google sign-in failed. Check your OAuth configuration and try again.'};
    if (notices[notice]) message(notices[notice]);
  } catch (error) { message(error.message); }
})();
