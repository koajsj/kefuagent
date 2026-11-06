import { el, button, label, input, select, panel, form, empty, date, message } from './ui.js';

const priorities = [{id:'low',name:'低'}, {id:'normal',name:'普通'}, {id:'high',name:'高'}, {id:'urgent',name:'紧急'}];
export function operationFilters(operators, apply) {
  const q = input('q', '', {placeholder:'搜索标题', maxLength:100});
  const queue = select('queue', ['all','pending','unassigned','mine','human','ai','resolved'].map((id, i) => ({id, name:['全部','待处理','未分配','我的','人工','AI','已解决'][i]})));
  const assignee = select('assignee_id', [{id:'',name:'全部负责人'}, ...operators.map(o => ({id:o.id,name:o.display_name}))]);
  const priority = select('priority', [{id:'',name:'全部优先级'}, ...priorities]);
  const sort = select('sort', [{id:'newest',name:'最新优先'},{id:'oldest',name:'最早优先'}]);
  const node = el('form', {class:'operation-filters'}, q, queue, assignee, priority, sort, el('button',{type:'submit'},'筛选'));
  node.addEventListener('submit', e => { e.preventDefault(); apply(Object.fromEntries(new FormData(node))); });
  return node;
}
export async function operationsPanel(ctx, conversation, operators, isCurrent, refresh) {
  const cid = conversation.id;
  const editable = (ctx.role === 'admin' || conversation.assignee_id === ctx.user.id) && (ctx.role !== 'admin' || operators !== null);
  operators = operators || [];
  const fields = [
    label('优先级', select('priority', priorities, conversation.priority, {disabled:!editable})),
    label('标签（逗号分隔）', input('tags', (conversation.tags || []).join(', '), {disabled:!editable})),
    label('分类', input('category', conversation.category || '', {disabled:!editable})),
  ];
  if (ctx.role === 'admin') fields.unshift(label('负责人', select('assignee_id', [{id:'',name:'未分配'}, ...operators.map(o => ({id:o.id,name:o.display_name}))], conversation.assignee_id || '')));
  const sla = conversation.sla || {};
  const duration = v => v == null ? '未知' : `${Math.round(v)} 秒`;
  const info = el('p', {class:'note'}, `SLA：${{ok:'正常',due_soon:'即将超时',overdue:'已超时'}[sla.state] || '未知'} · 首次响应 ${duration(sla.first_response_seconds)} · 人工等待 ${duration(sla.human_wait_seconds)} · 解决 ${duration(sla.resolution_seconds)}`);
  const settings = editable ? form(fields, async v => {
    const body = {expected_version:conversation.version, priority:v.get('priority'), tags:String(v.get('tags')).split(',').map(s => s.trim()).filter(Boolean), category:String(v.get('category')).trim() || null};
    if (ctx.role === 'admin') body.assignee_id = v.get('assignee_id') || null;
    try {
      await ctx.api(`/conversations/${cid}/operations`, {method:'PATCH',body});
    } catch (error) {
      if (error.code === 'version_conflict') throw new Error('会话已被其他人更新，请重新打开会话后再保存。');
      throw error;
    }
    if (isCurrent()) await refresh();
  }, '保存运营信息') : el('div', {}, ...fields, message(ctx.role === 'admin' ? '负责人列表暂不可用，加载成功后请重新打开会话。' : '只有负责人或管理员可修改运营信息。'));
  const notes = el('div', {'aria-live':'polite'}, message('正在加载协作记录…'));
  const summaryArea = el('div', {'aria-live':'polite'}, message('正在加载摘要…'));
  let firstNotes = true;
  const seen = new Set();
  let lastId = null, loading = false;
  const more = button('加载更早记录', loadNotes);
  async function loadNotes() {
    if (loading || !isCurrent()) return;
    loading = true; more.disabled = true;
    try {
      const params = new URLSearchParams({limit:'30'});
      if (lastId) params.set('before', lastId);
      const rows = await ctx.api(`/conversations/${cid}/collaboration?${params}`);
      if (!isCurrent()) return;
      notes.querySelector('.note-error')?.remove();
      if (firstNotes) { notes.replaceChildren(); firstNotes = false; }
      for (const h of rows) {
        if (seen.has(h.id)) continue;
        seen.add(h.id); lastId = h.id;
        notes.append(el('article', {class:'collaboration-entry'}, el('strong', {}, h.kind), el('small', {}, ' · ' + date(h.created_at)), h.actor_id ? el('small', {}, ' · ' + (operators.find(o => o.id === h.actor_id)?.display_name || h.actor_id)) : null, h.content ? el('p', {}, h.content) : null, h.details && Object.keys(h.details).length ? el('pre', {}, JSON.stringify(h.details, null, 2)) : null));
      }
      if (!seen.size) notes.append(empty('暂无协作记录。'));
      more.hidden = rows.length < 30;
    } catch (error) {
      if (isCurrent()) { if (firstNotes) notes.replaceChildren(); notes.querySelector('.note-error')?.remove(); notes.append(el('div', {class:'note-error'}, message(error.message, 'error'), button('重试', () => loadNotes()))); }
    } finally { loading = false; more.disabled = false; }
  }
  async function loadSummary() {
    try {
      const summary = await ctx.api(`/conversations/${cid}/summary`);
      if (!isCurrent()) return;
      summaryArea.replaceChildren(summary ? el('div', {}, el('ul', {}, ...JSON.parse(summary.content).map(item => el('li', {}, item.quote))), el('small', {}, `来源：${summary.source_start_id} 至 ${summary.source_end_id}`), el('small', {}, `版本 ${summary.version} · ${summary.source_count} 条来源消息 · ${date(summary.created_at)}`)) : empty('尚无摘要。'));
    } catch (error) { if (isCurrent()) summaryArea.replaceChildren(message(error.message, 'error'), button('重试', loadSummary)); }
  }
  const noteForm = form([label('内部备注', el('textarea', {name:'content', required:true, maxLength:4000, rows:3}))], async v => {
    await ctx.api(`/conversations/${cid}/collaboration`, {method:'POST',body:{content:v.get('content')}});
    if (isCurrent()) await refresh();
  }, '添加内部备注');
  loadNotes(); loadSummary();
  return el('div', {class:'operations'}, panel('运营信息', info, settings), panel('协作记录', notes, more, noteForm), panel('会话摘要（只读）', summaryArea));
}
