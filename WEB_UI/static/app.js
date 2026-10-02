const pageMeta = {
  dashboard: ["治理总览", "核心指标、治理事件与设备状态一屏掌握"],
  monitor: ["实时监控", "图片、视频、摄像头与网络流的实时 AI 分析"],
  events: ["事件中心", "异常事件自动记录、截图留证与结果导出"],
  devices: ["设备管理", "统一管理摄像头、RTSP / HTTP 视频源与安装位置"],
  rules: ["规则配置", "配置禁行区域、逆行方向和滞留阈值"],
  settings: ["系统设置", "平台路径、模型能力与运行信息"],
};
let devices = [];
let eventsCache = [];
let lastLogId = 0;
let previewStarted = false;
let selectedDeviceId = null;

const $ = (id) => document.getElementById(id);
const qs = (s) => document.querySelector(s);
const qsa = (s) => [...document.querySelectorAll(s)];

function escapeHtml(v) {
  return String(v ?? "").replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
}
function toast(message, type="info") {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  $("toastContainer").appendChild(el);
  setTimeout(() => el.remove(), 3800);
}
async function api(url, options={}) {
  const response = await fetch(url, options);
  const text = await response.text();
  let data;
  try { data = JSON.parse(text); } catch { data = {ok:false, error:text || `HTTP ${response.status}`}; }
  if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}
function goPage(name) {
  qsa(".page").forEach(p => p.classList.toggle("active", p.id === `page-${name}`));
  qsa(".nav-item").forEach(n => n.classList.toggle("active", n.dataset.page === name));
  $("pageTitle").textContent = pageMeta[name][0];
  $("pageSubtitle").textContent = pageMeta[name][1];
  $("sidebar").classList.remove("open");
  if (name === "dashboard") loadDashboard();
  if (name === "events") loadEvents();
  if (name === "devices") loadDevices();
  if (name === "rules") loadRules();
  if (name === "settings") loadSystem();
}
qsa(".nav-item").forEach(btn => btn.addEventListener("click", () => goPage(btn.dataset.page)));
qsa("[data-jump]").forEach(btn => btn.addEventListener("click", () => goPage(btn.dataset.jump)));
$("mobileMenu").addEventListener("click", () => $("sidebar").classList.toggle("open"));

function updateClock() {
  const d = new Date();
  $("clock").textContent = d.toLocaleString("zh-CN", {hour12:false});
}
setInterval(updateClock, 1000); updateClock();

async function loadDashboard() {
  try {
    const data = await api("/api/dashboard");
    const m = data.metrics;
    $("metricFlow").textContent = m.flow_count ?? 0;
    $("metricEvents").textContent = m.event_count ?? 0;
    $("metricDevices").textContent = m.online_devices ?? 0;
    $("metricFps").textContent = Number(m.fps || 0).toFixed(1);
    const tbody = $("dashboardEventsBody");
    tbody.innerHTML = (data.recent_events || []).map(e => `<tr><td>${escapeHtml((e.timestamp || "").slice(11,19))}</td><td>${escapeHtml(e.device)}</td><td><span class="event-type">${escapeHtml(e.event_type)}</span></td><td>${escapeHtml(e.target_label)}</td><td>${Math.round(Number(e.confidence || 0)*100)}%</td></tr>`).join("");
    $("dashboardEmpty").style.display = data.recent_events?.length ? "none" : "block";
    drawTrend(data.weekly || []);
  } catch (err) { console.error(err); }
}
function drawTrend(rows) {
  const canvas = $("trendCanvas");
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(320, rect.width) * dpr;
  canvas.height = 220 * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr,dpr);
  const w = canvas.width/dpr, h = 220, pad = {l:34,r:12,t:14,b:28};
  ctx.clearRect(0,0,w,h);
  ctx.strokeStyle = "#e8edf4"; ctx.lineWidth = 1;
  for (let i=0;i<4;i++){ const y=pad.t+(h-pad.t-pad.b)*i/3; ctx.beginPath();ctx.moveTo(pad.l,y);ctx.lineTo(w-pad.r,y);ctx.stroke(); }
  const maxFlow = Math.max(1,...rows.map(r=>Number(r.flow||0)));
  const maxEvents = Math.max(1,...rows.map(r=>Number(r.events||0)));
  const slot=(w-pad.l-pad.r)/Math.max(rows.length,1);
  rows.forEach((r,i)=>{
    const x=pad.l+i*slot+slot*.2, bw=Math.max(5,slot*.24);
    const fh=(h-pad.t-pad.b)*Number(r.flow||0)/maxFlow;
    const eh=(h-pad.t-pad.b)*Number(r.events||0)/maxEvents;
    ctx.fillStyle="#2563eb"; ctx.fillRect(x,h-pad.b-fh,bw,fh);
    ctx.fillStyle="#e11d48"; ctx.fillRect(x+bw+3,h-pad.b-eh,bw,eh);
    ctx.fillStyle="#94a3b8"; ctx.font="10px sans-serif"; ctx.textAlign="center"; ctx.fillText(r.label || "",x+bw,h-9);
  });
}
window.addEventListener("resize", ()=>{ if ($("page-dashboard").classList.contains("active")) loadDashboard(); });

async function loadDevices() {
  try {
    const data = await api("/api/devices");
    devices = data.devices || [];
    const select = $("monitorDevice");
    const current = select.value;
    select.innerHTML = `<option value="">手动输入视频源</option>` + devices.map(d=>`<option value="${d.id}">${escapeHtml(d.name)} · ${escapeHtml(d.location || "未设置位置")}</option>`).join("");
    if ([...select.options].some(o=>o.value===current)) select.value=current;
    $("devicesBody").innerHTML = devices.map(d=>`<tr data-id="${d.id}"><td>${d.id}</td><td><b>${escapeHtml(d.name)}</b></td><td>${escapeHtml(d.source)}</td><td>${escapeHtml(d.location || "-")}</td><td><span class="status-badge ${d.status === '在线' ? 'online':''}">${escapeHtml(d.status)}</span></td><td>${escapeHtml(d.created_at)}</td><td><button class="table-action" data-edit="${d.id}">编辑</button><button class="table-action" data-monitor="${d.id}">监控</button></td></tr>`).join("");
    qsa("[data-edit]").forEach(b=>b.addEventListener("click",()=>editDevice(Number(b.dataset.edit))));
    qsa("[data-monitor]").forEach(b=>b.addEventListener("click",()=>monitorDevice(Number(b.dataset.monitor))));
  } catch(err) { toast(err.message,"error"); }
}
$("monitorDevice").addEventListener("change", e=>{
  const id=Number(e.target.value||0); const d=devices.find(x=>Number(x.id)===id); if(d) $("monitorSource").value=d.source;
});
function editDevice(id){
  const d=devices.find(x=>Number(x.id)===id); if(!d)return; selectedDeviceId=id; $("deviceEditId").value=id; $("deviceName").value=d.name; $("deviceSource").value=d.source; $("deviceLocation").value=d.location||""; $("saveDeviceBtn").textContent="更新设备";
}
function resetDeviceForm(){ selectedDeviceId=null; $("deviceEditId").value=""; $("deviceName").value=""; $("deviceSource").value=""; $("deviceLocation").value=""; $("saveDeviceBtn").textContent="新增设备"; }
function monitorDevice(id){ const d=devices.find(x=>Number(x.id)===id); if(!d)return; goPage("monitor"); $("monitorDevice").value=String(id); $("monitorSource").value=d.source; toast(`已选择设备：${d.name}`); }
$("saveDeviceBtn").addEventListener("click", async()=>{
  const body={name:$("deviceName").value.trim(),source:$("deviceSource").value.trim(),location:$("deviceLocation").value.trim()};
  try { if(selectedDeviceId) await api(`/api/devices/${selectedDeviceId}`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}); else await api("/api/devices",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}); toast(selectedDeviceId?"设备已更新":"设备已新增","success"); resetDeviceForm(); await loadDevices(); } catch(err){toast(err.message,"error");}
});
$("resetDeviceBtn").addEventListener("click",resetDeviceForm);
$("deleteDeviceBtn").addEventListener("click", async()=>{ if(!selectedDeviceId){toast("请先选择设备","error");return;} if(!confirm("确定删除该设备吗？"))return; try{await api(`/api/devices/${selectedDeviceId}`,{method:"DELETE"});toast("设备已删除","success");resetDeviceForm();await loadDevices();}catch(err){toast(err.message,"error");} });
$("refreshDevicesBtn").addEventListener("click",loadDevices);

function showPreviews(){ previewStarted=true; $("originalPreview").classList.add("visible"); $("resultPreview").classList.add("visible"); $("originalEmpty").style.display="none"; $("resultEmpty").style.display="none"; }
function refreshPreview(){ showPreviews(); const v=Date.now(); $("originalPreview").src=`/stream/original.mjpg?v=${v}`; $("resultPreview").src=`/stream/result.mjpg?v=${v}`; }
function setTaskMessage(text){ $("taskMessage").textContent=text; }
async function uploadModel(file){
  if(!file)return; const fd=new FormData();fd.append("model",file);setTaskMessage("正在上传并加载模型…");
  try{const d=await api("/api/model",{method:"POST",body:fd});toast("模型加载成功","success");setTaskMessage(`模型已切换：${d.model_path}`);await loadSystem();}
  catch(err){toast(err.message,"error");setTaskMessage(err.message);}
}
$("chooseModelBtn").addEventListener("click",()=>$("quickModelInput").click());
$("quickModelInput").addEventListener("change",e=>uploadModel(e.target.files[0]));
$("imageDetectBtn").addEventListener("click",()=>$("imageInput").click());
$("imageInput").addEventListener("change",async e=>{
  const file=e.target.files[0];if(!file)return;const fd=new FormData();fd.append("image",file);setTaskMessage("正在执行图片 AI 检测…");
  try{const d=await api("/api/detect/image",{method:"POST",body:fd});refreshPreview();$("streamTargets").textContent=d.count;$("streamTracks").textContent="-";$("streamEvents").textContent="0";setTaskMessage(`检测完成：${d.count} 个目标`);toast("图片检测完成","success");}
  catch(err){toast(err.message,"error");setTaskMessage(err.message);} finally{e.target.value="";}
});
$("batchDetectBtn").addEventListener("click",()=>$("folderInput").click());
$("folderInput").addEventListener("change",async e=>{
  const files=[...e.target.files];if(!files.length)return;const fd=new FormData();files.forEach(f=>fd.append("images",f,f.webkitRelativePath||f.name));setTaskMessage(`正在批量检测 ${files.length} 张图片…`);
  try{const d=await api("/api/detect/batch",{method:"POST",body:fd});refreshPreview();setTaskMessage(`批量检测完成：${d.processed} 张 / ${d.total_targets} 个目标`);toast("批量检测完成，正在下载结果","success");window.location.href=d.download_url;}
  catch(err){toast(err.message,"error");setTaskMessage(err.message);} finally{e.target.value="";}
});
$("videoDetectBtn").addEventListener("click",()=>$("videoInput").click());
$("videoInput").addEventListener("change",async e=>{
  const file=e.target.files[0];if(!file)return;const fd=new FormData();fd.append("video",file);setTaskMessage("正在上传视频并启动 AI 分析…");
  try{await api("/api/stream/video",{method:"POST",body:fd});refreshPreview();setTaskMessage(`视频分析中：${file.name}`);toast("视频分析已启动","success");}
  catch(err){toast(err.message,"error");setTaskMessage(err.message);} finally{e.target.value="";}
});
$("cameraStartBtn").addEventListener("click",async()=>{
  const deviceId=$("monitorDevice").value; const payload=deviceId?{device_id:Number(deviceId)}:{source:$("monitorSource").value.trim()||"0",device_name:"手动视频源"};
  try{await api("/api/stream/start",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});refreshPreview();setTaskMessage("实时治理分析已启动");toast("实时监控已启动","success");}
  catch(err){toast(err.message,"error");setTaskMessage(err.message);}
});
$("stopStreamBtn").addEventListener("click",async()=>{try{await api("/api/stream/stop",{method:"POST"});setTaskMessage("停止指令已发送");toast("正在停止任务");}catch(err){toast(err.message,"error");}});
$("saveResultBtn").addEventListener("click",async()=>{try{const d=await api("/api/save-current",{method:"POST"});toast(`已保存：${d.saved_path}`,"success");}catch(err){toast(err.message,"error");}});
$("clearLogBtn").addEventListener("click",()=>$("logBox").innerHTML="");

async function pollStream(){
  try{
    const s=await api("/api/stream/status");
    $("streamTargets").textContent=s.targets??0;$("streamTracks").textContent=s.tracks??0;$("streamEvents").textContent=s.events??0;$("streamFps").textContent=Number(s.fps||0).toFixed(1);$("streamFrames").textContent=s.frames??0;
    $("metricFps").textContent=Number(s.fps||0).toFixed(1);
    $("sideStatusText").textContent=s.active?"实时分析中":"AI 引擎就绪";$("sideDeviceText").textContent=s.active?(s.device_name||s.source):"等待分析任务";$("sideStatusDot").classList.toggle("busy",!!s.active);
    qs(".engine-badge")?.classList.toggle("active",!!s.active);$("engineBadgeText").textContent=s.active?"AI 实时分析中":"AI 引擎已加载";
    $("sourceLivePill").textContent=s.active?"LIVE":"画面预览";$("resultLivePill").textContent=s.active?"AI LIVE":"检测结果";$("sourceLivePill").classList.toggle("muted",!s.active);$("resultLivePill").classList.toggle("muted",!s.active);
    if(s.active && !previewStarted) refreshPreview();
  }catch(err){console.error(err);}
}
async function pollLogs(){
  try{const d=await api(`/api/logs?after=${lastLogId}`);if(!d.logs?.length)return;const box=$("logBox");d.logs.forEach(item=>{lastLogId=Math.max(lastLogId,item.id);const line=document.createElement("div");line.className=`log-line ${item.level||"info"}`;line.innerHTML=`<span class="log-time">[${escapeHtml(item.time)}]</span><span class="log-message">${escapeHtml(item.message)}</span>`;box.appendChild(line);});while(box.children.length>500)box.firstChild.remove();box.scrollTop=box.scrollHeight;}catch(err){console.error(err);}
}

async function loadEvents(){
  try{const d=await api("/api/events?limit=500");eventsCache=d.events||[];renderEvents();}catch(err){toast(err.message,"error");}
}
function renderEvents(){
  const q=$("eventSearch").value.trim().toLowerCase();const rows=eventsCache.filter(e=>!q||[e.device,e.event_type,e.target_label,e.track_id].some(v=>String(v??"").toLowerCase().includes(q)));
  $("eventCountLabel").textContent=`${rows.length} 条记录`;
  $("eventsBody").innerHTML=rows.map(e=>`<tr><td>${escapeHtml(e.timestamp)}</td><td>${escapeHtml(e.device)}</td><td><span class="event-type">${escapeHtml(e.event_type)}</span></td><td>${escapeHtml(e.target_label)}</td><td>${escapeHtml(e.track_id??"-")}</td><td>${(Number(e.confidence||0)*100).toFixed(1)}%</td><td>${e.has_snapshot?`<a class="table-action" href="/api/events/${e.id}/snapshot" target="_blank">查看截图</a>`:"-"}</td></tr>`).join("");
}
$("eventSearch").addEventListener("input",renderEvents);$("refreshEventsBtn").addEventListener("click",loadEvents);

async function loadRules(){
  try{const d=await api("/api/rules");const r=d.rules;$("ruleForbidden").checked=!!r.forbidden_enabled;$("ruleWrongWay").checked=!!r.wrong_way_enabled;$("ruleDwell").checked=!!r.dwell_enabled;$("zoneX").value=(Number(r.forbidden_x)*100).toFixed(1);$("zoneY").value=(Number(r.forbidden_y)*100).toFixed(1);$("zoneW").value=(Number(r.forbidden_w)*100).toFixed(1);$("zoneH").value=(Number(r.forbidden_h)*100).toFixed(1);$("expectedDirection").value=r.expected_direction||"ltr";$("dwellSeconds").value=r.dwell_seconds||10;$("motionPx").value=r.min_motion_px||35;$("eventCooldown").value=r.event_cooldown||8;updateZonePreview();}catch(err){toast(err.message,"error");}
}
function updateZonePreview(){ const x=Math.max(0,Math.min(100,Number($("zoneX").value)||0));const y=Math.max(0,Math.min(100,Number($("zoneY").value)||0));const w=Math.max(1,Math.min(100-x,Number($("zoneW").value)||1));const h=Math.max(1,Math.min(100-y,Number($("zoneH").value)||1));Object.assign($("zoneRect").style,{left:`${x}%`,top:`${y}%`,width:`${w}%`,height:`${h}%`}); }
["zoneX","zoneY","zoneW","zoneH"].forEach(id=>$(id).addEventListener("input",updateZonePreview));
$("applyRulesBtn").addEventListener("click",async()=>{
  const payload={forbidden_enabled:$("ruleForbidden").checked,wrong_way_enabled:$("ruleWrongWay").checked,dwell_enabled:$("ruleDwell").checked,forbidden_x:Number($("zoneX").value)/100,forbidden_y:Number($("zoneY").value)/100,forbidden_w:Number($("zoneW").value)/100,forbidden_h:Number($("zoneH").value)/100,expected_direction:$("expectedDirection").value,dwell_seconds:Number($("dwellSeconds").value),min_motion_px:Number($("motionPx").value),event_cooldown:Number($("eventCooldown").value)};
  try{await api("/api/rules",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});toast("治理规则已应用","success");}catch(err){toast(err.message,"error");}
});

async function loadSystem(){
  try{const d=await api("/api/system");$("settingModel").textContent=d.model_path;$("settingOutput").textContent=d.output_dir;$("settingDb").textContent=d.database;$("settingSnapshots").textContent=d.snapshot_dir;$("modelNote").textContent=d.model_note;$("monitorModelName").textContent=(d.model_path||"").split(/[\\/]/).pop()||"model.pt";const text=d.model_loaded?"AI 引擎已加载":"模型未加载";$("engineBadgeText").textContent=text;$("sideStatusText").textContent=d.model_loaded?"AI 引擎就绪":"等待模型权重";}catch(err){console.error(err);}
}
$("settingModelBtn").addEventListener("click",()=>$("settingModelInput").click());$("settingModelInput").addEventListener("change",e=>uploadModel(e.target.files[0]));

async function initialLoad(){ await Promise.allSettled([loadDashboard(),loadDevices(),loadEvents(),loadRules(),loadSystem(),pollStream(),pollLogs()]); }
initialLoad();
setInterval(pollStream,1000);setInterval(pollLogs,900);setInterval(()=>{if($("page-dashboard").classList.contains("active"))loadDashboard();},5000);setInterval(()=>{if($("page-events").classList.contains("active"))loadEvents();},6000);
