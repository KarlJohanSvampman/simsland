export function emojiForEmotion(e) {
  return {calm:'🙂',playful:'😄',warm:'😊',awkward:'😬',annoyed:'😒',angry:'😠',furious:'🤬',fearful:'😨',sad:'😢',smug:'😏',curious:'🤔',suspicious:'🧐'}[e] || '🙂';
}
export async function showHousehold(id) {
  const res = await fetch(`/api/household/${id}`);
  const h = await res.json();
  document.getElementById('panelContent').innerHTML = `<h3>${h.name || id}</h3><pre>${JSON.stringify(h,null,2)}</pre>`;
}
export function updateOverlay(state) {

  const cal = state.calendar || {};

  const time = `${String(cal.hour).padStart(2,'0')}:${String(cal.minute).padStart(2,'0')}:${String(cal.second).padStart(2,'0')}`;
  const date = `${cal.weekday}, ${cal.year}-${cal.month}-${cal.day}`;

  const news = (state.news || []).slice(-3).map(n=>`• ${n.headline}`).join('<br>');

  document.getElementById('overlay').innerHTML = `
    <div style="font-size:18px;font-weight:bold">🕒 ${time}</div>
    <div style="margin-bottom:6px">${date}</div>
    <b>Tick:</b> ${state.tick}<br>
    <b>Jobs:</b> ${(state.job_listings||[]).filter(j=>j.open).length}<br>
    <b>News</b><br>${news || 'No news yet'}
  `;
}
