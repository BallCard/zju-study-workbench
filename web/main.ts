import './style.css';
import {layoutGraph, type Commit} from './graph';

type Stage = 'empty'|'draft'|'review'|'done';
interface Course {id:string; title:string; course_id?:string; zhiyun_id?:string}
interface Lesson {id:string; course_id:string; title:string; relative:string; status:Stage; files:string[]; selected:string[]; sub_id:string; has_note:boolean; has_pdf:boolean; note_file:string; missing:Record<string,string>}
interface Material {id:string; name:string; suffix:string; size:number; range:string; relative:string; root:'notes'|'downloads'; lesson_id:string; course_id:string}
interface Job {id:string; title:string; status:string; error?:string; result?:{partial?:boolean;message?:string}}
interface Assignment {id:string; title:string; deadline:string|null; submission_status:string|boolean|null; source:string; cached?:boolean}
interface State {settings:Record<string,string>; lessons:Record<string,{format?:string}>; library:{courses:Course[];lessons:Lesson[];files:Material[]}; assignments:Record<string,Assignment[]>; assignment_sync?:Record<string,{partial:boolean}>; git:{available:boolean;commits:Commit[]}; demo:boolean; jobs:Job[]; library_error?:string}

const app = document.querySelector<HTMLDivElement>('#app')!;
const stageLabels:Record<Stage,string>={empty:'待整理',draft:'草稿',review:'待核对',done:'完成'};
const token=document.querySelector<HTMLMetaElement>('meta[name=workbench-token]')?.content || '';
let data:State, courseId='', lessonId='', fileId='', tab:'materials'|'notes'='materials';
let draft='', note='', extracted='', message='', error='', modal=false, format='md', route='api';
let instruction='按本课概念顺序整理，解释适用条件并展开关键推导。';
let editing=false, dirty=false, busy=false, acting=false;
let selected:string[]=[], ranges:Record<string,string>={}, lastJobs='';

const esc=(value:unknown)=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));
const lesson=()=>data?.library.lessons.find(l=>l.id===lessonId);
const course=()=>data?.library.courses.find(c=>c.id===courseId);
const material=()=>data?.library.files.find(f=>f.id===fileId);
const button=(label:string, action:string, cls='', attrs='')=>`<button type="button" data-action="${action}" class="${cls}" ${attrs}>${label}</button>`;

async function request(path:string, body?:unknown) {
  const response=await fetch('/api/'+path, {method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json','X-Workbench-Token':token},body:body===undefined?undefined:JSON.stringify(body)});
  const result=await response.json();
  if(!response.ok) throw new Error(result.error || '本机服务不可用');
  return result;
}
async function load(keepText=false) {
  data=await request('state');
  if(!data.library.courses.some(c=>c.id===courseId)) courseId=data.library.courses[0]?.id||'';
  if(!data.library.lessons.some(l=>l.id===lessonId&&l.course_id===courseId)) lessonId=data.library.lessons.find(l=>l.course_id===courseId)?.id||'';
  const l=lesson(); selected=l?.selected.slice()||[];
  ranges=Object.fromEntries(data.library.files.filter(f=>l?.files.includes(f.id)).map(f=>[f.id,f.range||'']));
  if(!l?.files.includes(fileId)) fileId=l?.files[0]||'';
  if(l&&!keepText) {const text=await request('note/'+l.id); draft=text.draft;note=text.note;format=data.lessons[l.id]?.format||(l.note_file.endsWith('.tex')?'tex':'md');dirty=false;}
  busy=data.jobs.some(j=>j.status==='queued'||j.status==='running');
  render();
}
function selectControl(name:string, values:{value:string;label:string}[], value:string) {
  return `<select name="${name}" aria-label="${name==='route'?'整理方式':name==='format'?'笔记格式':esc(name)}">${values.map(v=>`<option value="${esc(v.value)}" ${v.value===value?'selected':''}>${esc(v.label)}</option>`).join('')}</select>`;
}
function submission(value:Assignment['submission_status']) {
  if(value===true || ['submitted','已提交','true'].includes(String(value))) return '平台已提交';
  if(value===false || ['unsubmitted','not_submitted','false'].includes(String(value))) return '平台未提交';
  return value===null || value===undefined ? '平台状态未知' : `平台状态：${esc(value)}`;
}
function graph() {
  const commits=data.git.commits;
  if(!data.git.available) return '<p class="muted">笔记目录尚无 Git 历史。初始化笔记仓库后即可显示。</p>';
  if(!commits.length) return '<p class="muted">还没有 commit。</p>';
  const layout=layoutGraph(commits);
  const width=layout.lanes*14+8, height=commits.length*48;
  const paths=layout.edges.map(e=>`<path d="M ${e.from.lane*14+7} ${e.from.row*48+20} L ${e.from.lane*14+7} ${e.to.row*48+10} L ${e.to.lane*14+7} ${e.to.row*48+20}"/>`).join('');
  const dots=layout.nodes.map(n=>`<circle cx="${n.lane*14+7}" cy="${n.row*48+20}" r="3.5"/>`).join('');
  return `<div class="git-graph"><svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" aria-label="真实 Git commit 与父节点关系" role="img"><g class="git-edges">${paths}</g><g class="git-dots">${dots}</g></svg><ol>${commits.map(c=>`<li class="${c.subject.includes('['+lessonId+']')?'current-commit':''}"><strong>${esc(c.subject)}</strong><span>${esc(c.sha.slice(0,7))} · ${esc(c.date.slice(0,10))}</span></li>`).join('')}</ol></div>`;
}
function settingsPanel() {
  if(!modal)return '';
  const s=data.settings, c=course(), l=lesson();
  const fields=[['notes_root','笔记根目录'],['downloads_root','下载根目录'],['scholar_root','zju-scholar 源码目录'],['scholar_python','zju-scholar 的 Python 路径'],['api_base','兼容 API 地址（含 /v1）'],['api_model','API 模型名称'],['pi_model','Pi 模型（留空沿用默认）'],['codex_model','Codex 模型（留空沿用默认）']];
  return `<dialog aria-labelledby="settings-title"><div class="dialog-heading"><h2 id="settings-title">工作台设置</h2>${button('关闭','close-settings')}</div><p class="muted">目录与模型可迁移。API 密钥存入系统密钥环，不写入仓库。</p><div class="settings-fields">${fields.map(([key,label])=>`<label>${label}<input name="${key}" value="${esc(s[key])}" autocomplete="off"></label>`).join('')}<label>API 密钥（留空保留已有）<input name="api_key" type="password" autocomplete="new-password"></label></div>${l?`<h3>当前课程与课次的明确关联</h3><div class="settings-fields"><label>学在浙大课程 ID<input name="lms_id" value="${esc(c?.course_id)}"></label><label>智云课程 ID<input name="zhiyun_id" value="${esc(c?.zhiyun_id)}"></label><label>本课次录像 ID<input name="sub_id" value="${esc(l.sub_id)}"></label></div>`:''}<div class="dialog-actions">${button('保存设置','save-settings','primary')}</div></dialog>`;
}

function markdown(text:string) {
  // Deliberately small: headings, paragraphs and lists; raw HTML stays inert.
  return text.split(/\n\s*\n/).map(block=>{
    if(/^#{1,3} /.test(block)){const [heading,...body]=block.split('\n');const level=heading.match(/^#+/)![0].length;return `<h${level}>${esc(heading.slice(level+1))}</h${level}>${body.length?`<p>${esc(body.join('\n')).replace(/\n/g,'<br>')}</p>`:''}`;}
    if(block.split('\n').every(line=>/^[-*] /.test(line)))return `<ul>${block.split('\n').map(line=>`<li>${esc(line.slice(2))}</li>`).join('')}</ul>`;
    return `<p>${esc(block).replace(/\n/g,'<br>')}</p>`;
  }).join('');
}
function filePane() {
  const l=lesson(), f=material();
  return `<section class="references"><div class="section-title"><h2>参考资料</h2><span>${selected.length} 份已选</span></div><div class="source-list">${data.library.files.filter(f=>l?.files.includes(f.id)).map(f=>`<article class="source ${f.id===fileId?'active':''}"><div class="source-meta"><span>${esc(f.suffix.slice(1).toUpperCase())}</span><span>已在本地</span></div>${button(esc(f.name),'preview-file','file-name',`data-id="${f.id}"`)}<p>${(f.size/1024).toFixed(0)} KiB · ${f.root==='notes'?'笔记资料库':'下载资料库'}</p><label class="source-check"><input type="checkbox" data-select="${f.id}" ${selected.includes(f.id)?'checked':''} aria-label="将${esc(f.name)}用于笔记">用于笔记</label>${f.suffix==='.pdf'?`<label class="range">使用页码<input name="range-${f.id}" placeholder="全文 / 1-3,5" value="${esc(ranges[f.id])}" aria-label="${esc(f.name)}使用页码"></label>`:''}</article>`).join('')||'<p class="empty-hint">此课次暂没有本地资料。可以先采集字幕，或在设置的资料目录放入原件后刷新。</p>'}</div><details class="absence"><summary>从本课程其他目录添加参考</summary>${data.library.files.filter(f=>f.course_id===courseId&&f.lesson_id!==lessonId).map(f=>button(esc(f.name)+' · 复制原件','import-reference','text-button',`data-id="${f.id}"`)).join('')||'<p class="small-note">本课程没有其他目录的资料。</p>'}</details><details class="absence"><summary>记录缺少的资料</summary>${['教师课件','智云 PPT','手写笔记'].map(name=>`<label>${name}${selectControl('missing-'+name,[{value:'unknown',label:'待检查'},{value:'none',label:'本课未提供'},{value:'pending',label:'存在，待补充'}],l?.missing[name]||'unknown')}</label>`).join('')}</details></section>
  <section class="reader"><div class="reader-heading"><div><span class="eyebrow">${tab==='materials'?'资料预览':'电子笔记'} / ${tab==='notes'?(dirty?'有未保存修改':'草稿与正式笔记'):f?.suffix.slice(1).toUpperCase()||'等待资料'}</span><h2>${tab==='materials'?esc(f?.name||'先选择一份资料'):'把资料整理成理解'}</h2></div>${tab==='notes'?button(editing?'阅读预览':'编辑正文','toggle-edit'):''}</div>${tab==='materials'?materialView():noteView()}<div class="file-location"><strong>文件位置</strong><p>${tab==='materials'?esc(f?data.settings[f.root+'_root']+'/'+f.relative:'尚未选择资料'):esc(l?data.settings.notes_root+'/'+l.relative+'/notes.'+format:'尚未选择课次')}</p></div></section>`;
}
function materialView() {
  const f=material();
  if(!f)return '<div class="document empty-document"><h3>以这节课实际存在的资料为准</h3><p>课件缺失时可以记录缺口，并选择字幕或教材节选作为参考。</p></div>';
  if(f.suffix==='.pdf') return `<iframe class="pdf-preview" src="/api/file/${f.id}#toolbar=1" title="${esc(f.name)} PDF 预览"></iframe>`;
  if(['.txt','.md','.tex','.srt','.vtt'].includes(f.suffix)) return `<article class="document"><div class="running-header"><span>${esc(course()?.title)}</span><span>资料原文</span></div><pre class="prose">${esc(extracted||'点击下方读取原文')}</pre>${button('读取原文','read-file')}</article>`;
  return `<div class="document empty-document"><h3>${esc(f.name)}</h3><p>本类文件可以在本地打开。PPTX / DOCX 可作为文字参考；视频使用字幕，图片与扫描 PDF 请先 OCR。</p>${['.pptx','.docx'].includes(f.suffix)?button('提取文字预览','read-file'):''}<pre class="prose">${esc(extracted)}</pre></div>`;
}
function noteView() {
  const l=lesson();
  const text=dirty?draft:draft||note;
  if(!text)return '<div class="document empty-document"><h3>这节课的笔记从这里开始</h3><p>勾选资料、填写要求，再点击“开始整理”。模型回稿先进入草稿，由你核对后保存。</p></div>';
  return `${editing?`<label class="editor"><span>可编辑正文 · ${format==='tex'?'LaTeX':'Markdown'}</span><textarea name="note-text" aria-label="电子笔记正文" spellcheck="false">${esc(text)}</textarea></label>`:`<article class="document"><div class="running-header"><span>${esc(course()?.title)} / ${esc(l?.title)}</span><span>${draft?'草稿':'已保存笔记'}</span></div>${format==='md'?`<div class="markdown prose">${markdown(text)}</div>`:`<pre class="prose note-prose">${esc(text)}</pre>`}</article>`}<div class="reference-links"><span>返回资料核对</span><div>${selected.map(id=>{const f=data.library.files.find(f=>f.id===id);return f?button(esc(f.name),'preview-file','text-button',`data-id="${f.id}"`):'';}).join('')}</div></div><div class="note-actions">${button('保留草稿','draft')}${button('保存正式笔记','save')}${button('保存并 Git 提交源稿','commit','primary')}${format==='tex'?button('保存并编译 PDF','compile','',busy?'disabled':''):''}${l?.has_pdf?button('查看 PDF（请核对版本）','show-pdf'):''}</div>`;
}
function render() {
  if(!data) {app.innerHTML='<p class="loading">正在打开本地工作台…</p>';return;}
  const l=lesson(), lessons=data.library.lessons.filter(l=>l.course_id===courseId);
  const done=lessons.filter(l=>l.status==='done').length;
  const assignments=data.assignments[courseId]||[];
  app.innerHTML=`<header class="app-header"><div class="brand"><span class="brand-mark">Z</span><div>ZJU Study Workbench<small>课程资料与电子笔记</small></div></div><div class="header-actions">${data.demo?'<span class="demo-label">合成演示库</span>':''}${button('刷新资料库','refresh')}${button('设置','settings')}</div></header><div class="layout"><aside class="navigation"><div class="eyebrow">我的课程</div>${selectControl('course',data.library.courses.map(c=>({value:c.id,label:c.title})),courseId)}<div class="nav-title"><h2>课次</h2><span>${done}/${lessons.length} 完成</span></div><nav aria-label="选择课次">${lessons.map(l=>button(`<strong>${esc(l.title)}</strong><span>${stageLabels[l.status]||'待检查'}${l.has_pdf?' · 有 PDF':''}</span>`,'choose-lesson',`lesson-link ${l.id===lessonId?'active':''}`,`data-id="${l.id}" aria-pressed="${l.id===lessonId}"`)).join('')}</nav>${button('新建课次','new-lesson','add-lesson',!courseId?'disabled':'')}<div class="project-label"><span>本地笔记库</span><p>${esc(data.settings.notes_root||'在设置中连接你的笔记项目')}</p></div></aside><main><div class="lesson-heading"><div><span class="eyebrow">${esc(course()?.title||'先连接笔记库')} / 课次工作台</span><h1>${esc(l?.title||'欢迎回来')}</h1></div>${l?selectControl('stage',Object.entries(stageLabels).map(([value,label])=>({value,label})),l.status):''}</div><div class="tabs"><div>${button('资料筛选','materials',tab==='materials'?'active':'',`aria-pressed="${tab==='materials'}"`)}${button('电子笔记','notes',tab==='notes'?'active':'',`aria-pressed="${tab==='notes'}"`)}</div><span>先预览，再选择本次参考</span></div>${data.library_error?`<p class="notice">${esc(data.library_error)}</p>`:''}${l?`<div class="work-area">${filePane()}</div><section class="compose"><label>本次整理要求<textarea name="instruction" rows="2">${esc(instruction)}</textarea></label><div class="compose-actions">${selectControl('route',[{value:'api',label:'Gemini / 兼容 API'},{value:'pi',label:'Pi 整理'},{value:'codex',label:'Codex 整理'}],route)}${selectControl('format',[{value:'md',label:'Markdown'},{value:'tex',label:'LaTeX'}],format)}${button(busy?'任务进行中':'开始整理','generate','primary',busy||!selected.length?'disabled':'')}</div><p>本次将提供已选 ${selected.length} 份资料的提取文字。${data.demo?'演示模式不会调用真实模型。':'回稿先存入私有草稿。'}</p></section>`:'<div class="welcome"><h2>把资料、笔记和版本放在一起</h2><p>在设置里连接已有笔记项目，或用 --demo 打开合成示例库。</p></div>'}<p class="message" aria-live="polite">${esc(message)}</p>${error?`<p class="error" role="alert">${esc(error)}</p>`:''}</main><aside class="progress-panel"><section><div class="section-title"><h2>本课进度</h2><span>${l?stageLabels[l.status]:''}</span></div><p class="muted">笔记阶段由你确认，已有文件不自动标记为完成。</p><div class="status-steps">${Object.entries(stageLabels).map(([key,label])=>`<span class="${l?.status===key?'active':''}">${label}</span>`).join('')}</div></section><section><div class="section-title"><h2>作业提交</h2>${button('同步','sync-assignments','text-button',!l?'disabled':'')}</div>${assignments.map(a=>`<article class="assignment"><strong>${esc(a.title)}</strong><span>${submission(a.submission_status)}${a.cached?' · 旧缓存':''}</span><small>${a.deadline?'截止：'+esc(a.deadline):'截止时间未返回'}</small></article>`).join('')||'<p class="muted">尚未同步个人作业记录。平台字段缺失会保留“未知”。</p>'}<p class="small-note">平台提交与 Git commit 分开记录。${data.assignment_sync?.[courseId]?.partial?'本次同步不完整，未返回的作业保留缓存。':''}</p></section><section><div class="section-title"><h2>资料采集</h2></div><div class="download-actions">${[['courseware','本课程课件'],['ppt','本课智云 PPT'],['subtitle','本课字幕'],['video','本课录像']].map(([key,label])=>button(label,'download','',`data-kind="${key}" ${!l?'disabled':''}`)).join('')}</div><p class="small-note">课程 ID / 录像 ID 在设置中明确关联。</p></section><section><div class="section-title"><h2>Git 版本图</h2><span>最近 60 次</span></div>${graph()}</section><section><div class="section-title"><h2>后台任务</h2></div>${data.jobs.slice(-5).reverse().map(j=>`<p class="job ${j.status}"><strong>${esc(j.title)}</strong><span>${{queued:'排队中',running:'处理中',done:'完成',error:'失败'}[j.status]||j.status}</span>${j.error?`<small>${esc(j.error)}</small>`:j.result?.message?`<small class="job-result">${esc(j.result.message)}</small>`:''}</p>`).join('')||'<p class="muted">暂时没有任务</p>'}</section></aside></div>${settingsPanel()}`;
  const dialog=app.querySelector<HTMLDialogElement>('dialog');
  if(dialog){dialog.showModal();dialog.addEventListener('cancel',()=>{modal=false;});}
}
async function selectSources() {await request('select',{lesson_id:lessonId,selected,ranges});}
async function preview(id:string) {fileId=id;tab='materials';extracted='';render(); const f=material();if(f&&['.txt','.md','.tex','.srt','.vtt'].includes(f.suffix)){extracted=(await request('text/'+id)).text;render();}}
function readFields() {return Object.fromEntries(Array.from(app.querySelectorAll<HTMLInputElement>('dialog input[name]')).map(i=>[i.name,i.value]));}
async function action(name:string, el:HTMLElement) {
  error='';
  if(['choose-lesson','refresh','materials','preview-file','settings','new-lesson','generate','compile'].includes(name)&&dirty) await preserveDraft();
  if(name==='settings') {modal=true;render();return;}
  if(name==='close-settings') {modal=false;render();return;}
  if(name==='toggle-edit') {editing=!editing;render();return;}
  if(name==='choose-lesson') {lessonId=el.dataset.id!;editing=false;extracted='';await load();}
  else if(name==='refresh') await load(true);
  else if(name==='materials'||name==='notes') {tab=name;render();}
  else if(name==='preview-file') await preview(el.dataset.id!);
  else if(name==='read-file') {extracted=(await request('text/'+fileId)).text;render();}
  else if(name==='import-reference') {await request('import',{lesson_id:lessonId,file_id:el.dataset.id});message='参考资料已复制到本课次，原件保留。';await load(true);}
  else if(name==='show-pdf') {const win=window.open('/api/pdf/'+lessonId,'_blank','noopener');if(!win)message='PDF 已请求打开。';}
  else if(name==='save-settings') {
    const fields=readFields();
    await preserveDraft();
    if(lesson())await request('lesson',{lesson_id:lessonId,course_id:fields.lms_id,zhiyun_id:fields.zhiyun_id,sub_id:fields.sub_id});
    await request('settings',fields);
    modal=false;message='设置已保存；密钥仅存于系统密钥环。';await load();
  }
  else if(['draft','save','commit'].includes(name)) {
    if(!dirty)draft=draft||note;
    const result=await request(name==='draft'?'draft':'save',{lesson_id:lessonId,text:draft,format,commit:name==='commit'});
    dirty=false;message=name==='commit'?(result.git.unchanged?'内容未变，无需新增 commit。':'源稿已保存并生成本地 commit。'):'笔记已'+(name==='draft'?'保留为草稿。':'保存，等待核对。');await load();
  }
  else if(name==='generate') {
    await selectSources();
    const result=await request('generate',{lesson_id:lessonId,route,instruction,format});
    busy=true;message='整理任务已排队：'+result.job_id.slice(0,8);tab='notes';editing=false;await load(true);
  }
  else if(name==='download'||name==='sync-assignments') {
    await request('scholar',{lesson_id:lessonId,action:name==='download'?el.dataset.kind:'assignments'});message='任务已加入队列。';await load(true);
  }
  else if(name==='compile') {
    await request('save',{lesson_id:lessonId,text:draft||note,format});
    await request('compile',{lesson_id:lessonId});message='源稿已保存，正在双遍编译。';await load(true);
  }
  else if(name==='new-lesson') {
    const title=window.prompt('课次目录名（日期不明确时使用可靠课次编号，如 lecture-03）');
    if(title){const result=await request('create-lesson',{course_id:courseId,title});lessonId=result.lesson_id;await load();}
  }
  render();
}
async function preserveDraft() {
  if(dirty){await request('draft',{lesson_id:lessonId,text:draft,format});dirty=false;message='未保存的修改已保留为私有草稿。';}
}
app.addEventListener('click',event=>{const el=(event.target as HTMLElement).closest<HTMLElement>('[data-action]');if(el&&!acting){acting=true;action(el.dataset.action!,el).catch(e=>{error=e.message;render();}).finally(()=>{acting=false;});}});
app.addEventListener('input',event=>{
  const el=event.target as HTMLInputElement;
  if(el.name==='note-text'){draft=el.value;dirty=true;}
  else if(el.name==='instruction')instruction=el.value;
  else if(el.name.startsWith('range-'))ranges[el.name.slice(6)]=el.value;
});
app.addEventListener('change',event=>{
  const el=event.target as HTMLInputElement;
  (async()=>{
    if(el.dataset.select){selected=el.checked?[...selected,el.dataset.select]:selected.filter(x=>x!==el.dataset.select);await selectSources();render();}
    else if(el.name==='course'){if(dirty){await request('draft',{lesson_id:lessonId,text:draft,format});dirty=false;}courseId=el.value;lessonId='';await load();}
    else if(el.name==='route')route=el.value;
    else if(el.name==='format'){format=el.value;render();}
    else if(el.name==='stage'){await request('lesson',{lesson_id:lessonId,status:el.value});await load(true);}
    else if(el.name.startsWith('missing-')){const missing={...lesson()?.missing,[el.name.slice(8)]:el.value};await request('lesson',{lesson_id:lessonId,missing});}
    else if(el.name.startsWith('range-'))await selectSources();
  })().catch(e=>{error=e.message;render();});
});
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
setInterval(async()=>{
  if(!data||modal)return;
  try {
    const jobs:Job[]=await request('jobs');
    const signature=JSON.stringify(jobs);
    busy=jobs.some(j=>j.status==='queued'||j.status==='running');
    if(signature!==lastJobs){lastJobs=signature;data.jobs=jobs;if(!busy&&jobs.length){await load(dirty);message='后台任务结束，可核对结果。';}else if(!dirty)render();}
  }catch{/* The foreground action will report a service failure. */}
},1500);
load().catch(e=>{app.innerHTML=`<p class="error">${esc(e.message)}</p>`;});
