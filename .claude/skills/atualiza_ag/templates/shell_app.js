/* ============================================================
   NORMALIZATION
   ============================================================ */
function stripAccents(s){
  return String(s==null?'':s).normalize('NFD').replace(/[\u0300-\u036f]/g,'');
}
function norm(s){ return stripAccents(s).toLowerCase(); }
function escapeHtml(s){
  return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

var SEV_ORDER = ['critico','alto','medio','baixo','outro'];
var SEV_LABEL = { critico:'Crítico', alto:'Alto', medio:'Médio', baixo:'Baixo', outro:'Outro / N-A' };
var SEV_RANK  = { critico:4, alto:3, medio:2, baixo:1, outro:0 };

function severityInfo(raw){
  var n = norm(raw);
  var best = 'outro', bestRank = -1;
  var tests = [
    ['critico', /(critic)/],
    ['alto',    /(\balto\b|\balta\b|\bhigh\b)/],
    ['medio',   /(medi)/],
    ['baixo',   /(baix|\blow\b)/]
  ];
  for(var i=0;i<tests.length;i++){
    var key = tests[i][0], re = tests[i][1];
    if(re.test(n) && SEV_RANK[key] > bestRank){ best = key; bestRank = SEV_RANK[key]; }
  }
  return { bucket: best, label: SEV_LABEL[best], rank: SEV_RANK[best] };
}

var STATUS_LABEL = { aberto:'Aberto', fechado:'Fechado', outro:'Outro / N-A' };
function statusInfo(raw){
  var n = norm(raw).trim();
  var bucket = 'outro';
  if(n.indexOf('fechado') === 0) bucket = 'fechado';
  else if(n.indexOf('aberto') === 0) bucket = 'aberto';
  return { bucket: bucket, label: STATUS_LABEL[bucket] };
}

var FOUNDBY_LABEL = { manager:'Manager', agent:'Revisão independente', claude:'Claude (mesma sessão)', outro:'Outro' };
function foundByInfo(raw){
  var n = norm(raw);
  var bucket = 'outro';
  if(/(agent|auditoria|audit_engineering|project_assurance|stage_readiness|workflow|adversarial|independente)/.test(n)) bucket = 'agent';
  else if(/claude/.test(n)) bucket = 'claude';
  else if(/manager/.test(n)) bucket = 'manager';
  return { bucket: bucket, label: FOUNDBY_LABEL[bucket] };
}

function moduleOf(fileRaw){
  if(!fileRaw) return '(sem arquivo)';
  var first = String(fileRaw).split(',')[0].trim().replace(/^["'“‘]+/,'').trim();
  if(first.indexOf('/') === -1){
    return /\.md$/i.test(first) ? 'docs (raiz)' : (first || '(sem arquivo)');
  }
  var parts = first.split('/');
  if(parts[0] === 'src' || parts[0] === '.claude' || parts[0] === 'tools' || parts[0] === 'tests'){
    return parts.slice(0, Math.min(2, parts.length - (/\.[a-zA-Z0-9]+$/.test(parts[parts.length-1])?1:0) || 2)).join('/');
  }
  return parts.slice(0,1).join('/');
}

function parseDateSafe(s){
  if(!s) return null;
  var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(s));
  if(!m) return null;
  var d = new Date(Date.UTC(+m[1], +m[2]-1, +m[3]));
  return isNaN(d.getTime()) ? null : d;
}
function formatDateHuman(d){
  if(!d) return '—';
  var MESES = ['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'];
  return d.getUTCDate() + ' ' + MESES[d.getUTCMonth()] + ' ' + d.getUTCFullYear();
}

var KNOWN_FIELDS = ['id','date','file','related_file','found_by','gap','severity','layer','consequence','resolved_by_commit','resolution','status'];

function extractAgRefs(entry){
  var text = [];
  for(var k in entry){
    if(k === 'id') continue;
    var v = entry[k];
    if(typeof v === 'string') text.push(v);
  }
  var joined = text.join(' \n ');
  var re = /AG-\d{3,4}(?:-ADDENDUM)?/g;
  var found = joined.match(re) || [];
  var set = {};
  var out = [];
  for(var i=0;i<found.length;i++){
    var id = found[i].replace('-ADDENDUM','');
    if(id === entry.id) continue;
    if(!set[id]){ set[id] = true; out.push(id); }
  }
  return out;
}

/* ============================================================
   PREPARE DATASET
   ============================================================ */
var byId = {};
AGS.forEach(function(e){
  e._sev = severityInfo(e.severity);
  e._status = statusInfo(e.status);
  e._foundBy = foundByInfo(e.found_by);
  e._module = moduleOf(e.file);
  e._date = parseDateSafe(e.date);
  var extras = [];
  for(var k in e){
    if(k.charAt(0) === '_') continue;
    if(KNOWN_FIELDS.indexOf(k) === -1) extras.push(k);
  }
  e._extraKeys = extras;
  var searchParts = [];
  for(var k2 in e){
    if(k2.charAt(0) === '_') continue;
    var v = e[k2];
    if(typeof v === 'string') searchParts.push(v);
  }
  e._search = norm(searchParts.join(' \n '));
  byId[e.id] = e;
});
AGS.forEach(function(e){ e._refs = extractAgRefs(e); });
var refsIn = {};
AGS.forEach(function(e){
  e._refs.forEach(function(rid){
    if(!refsIn[rid]) refsIn[rid] = [];
    if(byId[e.id]) refsIn[rid].push(e.id);
  });
});

var DATE_MIN = null, DATE_MAX = null;
AGS.forEach(function(e){
  if(e._date){
    if(!DATE_MIN || e._date < DATE_MIN) DATE_MIN = e._date;
    if(!DATE_MAX || e._date > DATE_MAX) DATE_MAX = e._date;
  }
});

var MODULE_COUNTS = {};
AGS.forEach(function(e){ MODULE_COUNTS[e._module] = (MODULE_COUNTS[e._module]||0) + 1; });
var MODULE_LIST = Object.keys(MODULE_COUNTS).sort(function(a,b){ return MODULE_COUNTS[b]-MODULE_COUNTS[a]; });

/* ============================================================
   STATE
   ============================================================ */
var state = {
  query: '',
  sev: {},      // bucket -> true if active filter
  status: {},
  foundBy: {},
  module: '',
  sort: 'date_desc',
  selectedId: null,
  tab: 'painel'
};

function anyActive(map){ return Object.keys(map).some(function(k){return map[k];}); }

function getFiltered(){
  var q = norm(state.query).trim();
  var sevActive = anyActive(state.sev);
  var stActive = anyActive(state.status);
  var fbActive = anyActive(state.foundBy);
  var list = AGS.filter(function(e){
    if(sevActive && !state.sev[e._sev.bucket]) return false;
    if(stActive && !state.status[e._status.bucket]) return false;
    if(fbActive && !state.foundBy[e._foundBy.bucket]) return false;
    if(state.module && e._module !== state.module) return false;
    if(q && e._search.indexOf(q) === -1) return false;
    return true;
  });
  list.sort(function(a,b){
    switch(state.sort){
      case 'date_asc': return (a._date?a._date.getTime():0) - (b._date?b._date.getTime():0);
      case 'sev_desc': return b._sev.rank - a._sev.rank || idNum(b.id)-idNum(a.id);
      case 'id_asc': return idNum(a.id) - idNum(b.id);
      case 'id_desc': return idNum(b.id) - idNum(a.id);
      case 'date_desc':
      default: return (b._date?b._date.getTime():0) - (a._date?a._date.getTime():0);
    }
  });
  return list;
}
function idNum(id){ var m = /(\d+)/.exec(id||''); return m? +m[1] : 0; }

/* ============================================================
   TEXT FORMATTING (detail prose)
   ============================================================ */
function formatText(s){
  if(!s) return '<span style="color:var(--text-faint)">—</span>';
  var t = escapeHtml(s);
  t = t.replace(/`([^`]+)`/g, '<code>$1</code>');
  t = t.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  t = t.replace(/\b(AG-\d{3,4}(?:-ADDENDUM)?)\b/g, function(m){
    var id = m.replace('-ADDENDUM','');
    return '<a href="#" class="ag-ref" data-ag="' + id + '">' + m + '</a>';
  });
  return t;
}
function fieldLabel(key){
  var map = {
    addendum_de:'Addendum de', renumbered_from:'Renumerado de', numeracao:'Nota de numeração',
    status_final:'Status final', status_atualizado:'Status atualizado', status_runner_validacao:'Status (validação runner)',
    status_historico_pre_reabertura:'Status histórico (pré-reabertura)', resolution_final:'Resolução final',
    ressalva_de_proveniencia:'Ressalva de proveniência', hint_leitura_futura:'Nota para leitura futura',
    adendo_implementacao:'Adendo de implementação', metodo_e_uma_correcao_propria:'Método é correção própria',
    heterogeneidade_bnb_xrp_o_alvo_original:'Heterogeneidade BNB/XRP (alvo original)',
    custo_pendente_n_lifetime:'Custo pendente (N_lifetime)', achados_nao_reverificados:'Achados não reverificados',
    addendum_gate_principle:'Addendum (princípio de gate)'
  };
  return map[key] || key.replace(/_/g,' ');
}

/* ============================================================
   RENDER: KPI STRIP
   ============================================================ */
function renderKPIs(){
  var total = AGS.length;
  var abertos = AGS.filter(function(e){return e._status.bucket==='aberto';}).length;
  var criticosAbertos = AGS.filter(function(e){return e._status.bucket==='aberto' && e._sev.bucket==='critico';}).length;
  var independente = AGS.filter(function(e){return e._foundBy.bucket==='agent';}).length;
  var pctIndep = total? Math.round(independente/total*100) : 0;
  var cards = [
    { label:'Total de achados', value: total, sub: 'AG-001 … AG-' + Math.max.apply(null, AGS.map(function(e){return idNum(e.id);})), color:'var(--accent)' },
    { label:'Em aberto', value: abertos, sub: Math.round(abertos/total*100) + '% do total', color:'var(--sev-critico)' },
    { label:'Críticos ativos', value: criticosAbertos, sub: 'severidade crítica + status aberto', color:'var(--sev-alto)' },
    { label:'Achado por revisão independente', value: pctIndep + '%', sub: independente + ' de ' + total + ' entradas', color:'var(--ok)' }
  ];
  document.getElementById('kpi-strip').innerHTML = cards.map(function(c){
    return '<div class="kpi-card" style="--kpi-color:'+c.color+'"><div class="kpi-label">'+c.label+'</div><div class="kpi-value tabular">'+c.value+'</div><div class="kpi-sub">'+c.sub+'</div></div>';
  }).join('');
  var mr = document.getElementById('meta-range');
  if(DATE_MIN && DATE_MAX){
    mr.textContent = formatDateHuman(DATE_MIN) + ' — ' + formatDateHuman(DATE_MAX) + ' · ' + total + ' entradas';
  }
  document.getElementById('footer-count').textContent = total + ' achados de arquitetura registrados';
}

/* ============================================================
   RENDER: TOOLBAR (chips)
   ============================================================ */
function buildChip(cls, bucket, label, count, mapRef){
  return '<button type="button" class="chip '+cls+'" data-bucket="'+bucket+'" aria-pressed="'+(!!mapRef[bucket])+'">' +
    '<span class="dot"></span>' + label + ' <span class="tabular" style="opacity:.7">' + count + '</span></button>';
}
function renderToolbar(){
  var sevCounts = {}, stCounts = {}, fbCounts = {};
  AGS.forEach(function(e){
    sevCounts[e._sev.bucket] = (sevCounts[e._sev.bucket]||0)+1;
    stCounts[e._status.bucket] = (stCounts[e._status.bucket]||0)+1;
    fbCounts[e._foundBy.bucket] = (fbCounts[e._foundBy.bucket]||0)+1;
  });
  document.getElementById('chips-severity').innerHTML = SEV_ORDER.filter(function(b){return sevCounts[b];}).map(function(b){
    return buildChip('sev-'+b, b, SEV_LABEL[b], sevCounts[b]||0, state.sev);
  }).join('');
  document.getElementById('chips-status').innerHTML = ['aberto','fechado','outro'].filter(function(b){return stCounts[b];}).map(function(b){
    return buildChip('st-'+b, b, STATUS_LABEL[b], stCounts[b]||0, state.status);
  }).join('');
  document.getElementById('chips-foundby').innerHTML = ['manager','agent','claude','outro'].filter(function(b){return fbCounts[b];}).map(function(b){
    return buildChip('fb-generic', b, FOUNDBY_LABEL[b], fbCounts[b]||0, state.foundBy);
  }).join('');
  var sel = document.getElementById('select-module');
  sel.innerHTML = '<option value="">todos os módulos</option>' + MODULE_LIST.map(function(m){
    return '<option value="'+escapeHtml(m)+'"'+(state.module===m?' selected':'')+'>'+escapeHtml(m)+' ('+MODULE_COUNTS[m]+')</option>';
  }).join('');
  document.getElementById('select-sort').value = state.sort;
}

/* ============================================================
   RENDER: EXPLORER
   ============================================================ */
function highlightSnippet(text, q){
  if(!text) return '';
  var esc = escapeHtml(text.replace(/\s+/g,' ').trim()).slice(0,220);
  if(!q) return esc;
  try{
    var re = new RegExp('(' + q.replace(/[.*+?^${}()|[\]\\]/g,'\\$&') + ')', 'ig');
    return esc.replace(re, '<mark>$1</mark>');
  }catch(e){ return esc; }
}

function renderExplorer(){
  var list = getFiltered();
  document.getElementById('result-count').textContent = list.length + ' / ' + AGS.length + ' achados';
  var ul = document.getElementById('ag-list');
  if(!list.length){
    ul.innerHTML = '<div class="empty-state">Nenhum achado corresponde aos filtros atuais.</div>';
  } else {
    ul.innerHTML = list.map(function(e){
      var sevColor = 'var(--sev-'+e._sev.bucket+')';
      return '<li class="ag-row" data-id="'+e.id+'" style="--row-color:'+sevColor+'">' +
        '<div class="ag-main">' +
          '<div style="display:flex;justify-content:space-between;gap:8px;">' +
            '<span class="ag-id">'+e.id+'</span>' +
            '<span style="font-size:10.5px;color:var(--text-faint);font-family:var(--font-mono)">'+(e.date||'—')+'</span>' +
          '</div>' +
          '<div class="ag-file">'+escapeHtml(e.file||'—')+'</div>' +
          '<div class="ag-snippet">'+highlightSnippet(e.gap, state.query)+'</div>' +
          '<div class="ag-badges">' +
            '<span class="badge status-'+e._status.bucket+'">'+e._status.label+'</span>' +
            '<span class="badge" style="background:var(--sev-'+e._sev.bucket+'-soft);color:var(--sev-'+e._sev.bucket+')">'+e._sev.label+'</span>' +
          '</div>' +
        '</div>' +
      '</li>';
    }).join('');
  }
  Array.prototype.forEach.call(ul.querySelectorAll('.ag-row'), function(row){
    row.classList.toggle('selected', row.getAttribute('data-id') === state.selectedId);
  });
  if(state.selectedId && byId[state.selectedId]){
    renderDetail(state.selectedId);
  }
}

function renderDetail(id){
  var e = byId[id];
  var detail = document.getElementById('ag-detail');
  if(!e){ detail.innerHTML = '<div class="empty-state">Selecione um achado à esquerda para ver o registro completo.</div>'; return; }
  var refsOutHtml = e._refs.length ? e._refs.map(function(r){
    return '<a href="#" class="ag-ref" data-ag="'+r+'">'+r+'</a>';
  }).join(' ') : '<span style="color:var(--text-faint)">nenhuma</span>';
  var refsInList = refsIn[e.id] || [];
  var refsInHtml = refsInList.length ? refsInList.map(function(r){
    return '<a href="#" class="ag-ref" data-ag="'+r+'">'+r+'</a>';
  }).join(' ') : '<span style="color:var(--text-faint)">nenhuma</span>';

  var extraHtml = e._extraKeys.length ? e._extraKeys.map(function(k){
    return '<div class="extra-block"><div class="k">'+escapeHtml(fieldLabel(k))+'</div><div class="detail-prose">'+formatText(e[k])+'</div></div>';
  }).join('') : '';

  detail.innerHTML =
    '<div class="detail-head">' +
      '<div>' +
        '<div class="detail-id">'+e.id+'</div>' +
        '<div class="detail-pills">' +
          '<span class="pill" style="background:var(--sev-'+e._sev.bucket+'-soft);color:var(--sev-'+e._sev.bucket+')">'+e._sev.label+'</span>' +
          '<span class="pill" style="background:'+(e._status.bucket==='fechado'?'rgba(47,122,79,0.12)':'var(--sev-'+ (e._status.bucket==='aberto'?'critico':'outro') +'-soft)')+';color:'+(e._status.bucket==='fechado'?'var(--ok)':'var(--sev-'+(e._status.bucket==='aberto'?'critico':'outro')+')')+'">'+e._status.label+'</span>' +
          '<span class="pill" style="background:var(--surface-2);color:var(--text-muted)">'+escapeHtml(e._module)+'</span>' +
        '</div>' +
      '</div>' +
      '<button class="copy-btn" id="btn-copy-detail" type="button">Copiar registro</button>' +
    '</div>' +
    '<div class="detail-grid">' +
      '<div class="detail-field"><div class="k">Data</div><div class="v">'+(e.date||'—')+'</div></div>' +
      '<div class="detail-field"><div class="k">Arquivo</div><div class="v">'+escapeHtml(e.file||'—')+'</div></div>' +
      '<div class="detail-field"><div class="k">Arquivo relacionado</div><div class="v">'+escapeHtml(e.related_file||'—')+'</div></div>' +
      '<div class="detail-field"><div class="k">Camada declarada</div><div class="v">'+escapeHtml(e.layer||'—')+'</div></div>' +
      '<div class="detail-field"><div class="k">Achado por</div><div class="v">'+escapeHtml(e.found_by||'—')+'</div></div>' +
      '<div class="detail-field"><div class="k">Commit de resolução</div><div class="v">'+(e.resolved_by_commit? '<code>'+escapeHtml(e.resolved_by_commit)+'</code>' : '—')+'</div></div>' +
    '</div>' +
    '<div class="detail-section"><h4>O que foi encontrado</h4><div class="detail-prose">'+formatText(e.gap)+'</div></div>' +
    '<div class="detail-section"><h4>Consequência</h4><div class="detail-prose">'+formatText(e.consequence)+'</div></div>' +
    '<div class="detail-section"><h4>Resolução</h4><div class="detail-prose">'+formatText(e.resolution)+'</div></div>' +
    '<div class="detail-section"><h4>Status</h4><div class="detail-prose">'+formatText(e.status)+'</div></div>' +
    (extraHtml ? '<div class="detail-section"><h4>Notas adicionais do registro</h4>'+extraHtml+'</div>' : '') +
    '<div class="detail-section"><h4>Referências cruzadas</h4>' +
      '<div class="detail-field" style="margin-bottom:8px;"><div class="k">Este item menciona</div><div class="refs-row">'+refsOutHtml+'</div></div>' +
      '<div class="detail-field"><div class="k">Mencionado por</div><div class="refs-row">'+refsInHtml+'</div></div>' +
    '</div>';

  var copyBtn = document.getElementById('btn-copy-detail');
  if(copyBtn) copyBtn.addEventListener('click', function(){
    var txt = e.id+' — '+(e.file||'')+'\nStatus: '+(e.status||'')+'\nSeveridade: '+(e.severity||'')+
      '\n\nGAP:\n'+(e.gap||'')+'\n\nCONSEQUÊNCIA:\n'+(e.consequence||'')+'\n\nRESOLUÇÃO:\n'+(e.resolution||'');
    if(navigator.clipboard && navigator.clipboard.writeText){
      navigator.clipboard.writeText(txt).then(function(){ showToast('Registro copiado.'); }).catch(function(){ showToast('Não foi possível copiar.'); });
    }
  });
}

function selectEntry(id, switchToExplorer){
  state.selectedId = id;
  if(switchToExplorer) setTab('explorar');
  else renderActiveTab();
}

/* ============================================================
   CHARTS — shared helpers
   ============================================================ */
function donutSVG(data, size){
  size = size || 150;
  var r = size/2 - 8, cx = size/2, cy = size/2, circ = 2*Math.PI*r;
  var total = data.reduce(function(a,d){return a+d.value;},0) || 1;
  var offset = 0;
  var arcs = data.map(function(d){
    var frac = d.value/total;
    var dash = frac*circ;
    var el = '<circle cx="'+cx+'" cy="'+cy+'" r="'+r+'" fill="none" stroke="'+d.color+'" stroke-width="16" ' +
      'stroke-dasharray="'+dash.toFixed(2)+' '+(circ-dash).toFixed(2)+'" stroke-dashoffset="'+(-offset).toFixed(2)+'" transform="rotate(-90 '+cx+' '+cy+')"></circle>';
    offset += dash;
    return el;
  }).join('');
  return '<svg viewBox="0 0 '+size+' '+size+'" width="'+size+'" height="'+size+'">' + arcs +
    '<text x="'+cx+'" y="'+(cy-3)+'" text-anchor="middle" font-family="IBM Plex Sans Condensed" font-weight="700" font-size="22" fill="var(--text)">'+total+'</text>' +
    '<text x="'+cx+'" y="'+(cy+14)+'" text-anchor="middle" font-size="9.5" fill="var(--text-faint)">achados</text>' +
    '</svg>';
}

function hbarList(containerId, data, maxItems){
  var items = data.slice(0, maxItems||999);
  var max = Math.max.apply(null, items.map(function(d){return d.value;})) || 1;
  document.getElementById(containerId).innerHTML = items.map(function(d){
    var pct = (d.value/max*100).toFixed(1);
    return '<div class="hbar-row" title="'+escapeHtml(d.label)+'">' +
      '<div class="hbar-label">'+escapeHtml(d.label)+'</div>' +
      '<div class="hbar-track"><div class="hbar-fill" style="width:'+pct+'%;background:'+d.color+'"></div></div>' +
      '<div class="hbar-val tabular">'+d.value+'</div>' +
    '</div>';
  }).join('');
}

/* ============================================================
   RENDER: PAINEL (dashboard, always full dataset)
   ============================================================ */
function renderPainel(){
  var sevCounts = {};
  SEV_ORDER.forEach(function(b){ sevCounts[b]=0; });
  AGS.forEach(function(e){ sevCounts[e._sev.bucket]++; });
  var sevData = SEV_ORDER.filter(function(b){return sevCounts[b]>0;}).map(function(b){
    return { label: SEV_LABEL[b], value: sevCounts[b], color: 'var(--sev-'+b+')' };
  });

  var stCounts = { aberto:0, fechado:0, outro:0 };
  AGS.forEach(function(e){ stCounts[e._status.bucket]++; });

  var fbCounts = { manager:0, agent:0, claude:0, outro:0 };
  AGS.forEach(function(e){ fbCounts[e._foundBy.bucket]++; });
  var fbData = ['agent','manager','claude','outro'].map(function(b){
    return { label: FOUNDBY_LABEL[b], value: fbCounts[b], color: b==='agent' ? 'var(--ok)' : (b==='manager' ? 'var(--sev-alto)' : (b==='claude' ? 'var(--accent)' : 'var(--sev-outro)')) };
  });

  var modData = MODULE_LIST.slice(0,12).map(function(m){
    return { label: m, value: MODULE_COUNTS[m], color: 'var(--accent)' };
  });

  // weekly stacked (by ISO week bucket, using UTC monday-start weeks)
  var weekMap = {};
  AGS.forEach(function(e){
    if(!e._date) return;
    var d = new Date(e._date.getTime());
    var day = (d.getUTCDay()+6)%7; // 0=mon
    d.setUTCDate(d.getUTCDate()-day);
    var key = d.toISOString().slice(0,10);
    if(!weekMap[key]) weekMap[key] = { critico:0, alto:0, medio:0, baixo:0, outro:0, start:d };
    weekMap[key][e._sev.bucket]++;
  });
  var weekKeys = Object.keys(weekMap).sort();
  var weekMax = 1;
  weekKeys.forEach(function(k){
    var s = weekMap[k].critico+weekMap[k].alto+weekMap[k].medio+weekMap[k].baixo+weekMap[k].outro;
    if(s>weekMax) weekMax = s;
  });

  var pctIndep = Math.round(fbCounts.agent/AGS.length*100);

  var html = '<div class="painel-grid">' +
    '<div class="panel span-4"><h3>Severidade</h3><div class="panel-note">distribuição declarada em cada entrada (pior classificação quando o texto combina mais de uma)</div>' +
      '<div style="display:flex;align-items:center;gap:16px;">' + donutSVG(sevData,140) +
      '<div class="legend-list">' + sevData.map(function(d){
        return '<div class="legend-row"><span class="sw" style="background:'+d.color+'"></span><span class="lbl">'+d.label+'</span><span class="val">'+d.value+'</span></div>';
      }).join('') + '</div></div>' +
    '</div>' +
    '<div class="panel span-4"><h3>Status</h3><div class="panel-note">aberto vs. fechado (disciplina append-only — nada é removido, só marcado)</div>' +
      '<div id="chart-status"></div>' +
    '</div>' +
    '<div class="panel span-4"><h3>Saúde do processo</h3><div class="panel-note">quem encontrou o gap — a própria ledger diz que isso importa mais que qualquer achado isolado</div>' +
      '<div id="chart-foundby"></div>' +
      '<div class="callout"><strong>'+pctIndep+'%</strong> dos '+AGS.length+' achados vieram de revisão independente (Agent/auditoria), não do Manager nem da mesma sessão que escreveu o código — sinal de que o protocolo de revisão adversarial está pegando furos sozinho.</div>' +
    '</div>' +
    '<div class="panel span-6"><h3>Módulos mais citados</h3><div class="panel-note">top 12 por nº de achados com <code>file</code> nesse módulo</div>' +
      '<div id="chart-modules"></div>' +
    '</div>' +
    '<div class="panel span-6"><h3>Achados por semana</h3><div class="panel-note">volume de descoberta ao longo do projeto, empilhado por severidade</div>' +
      '<div id="chart-weekly" class="scroll-x"></div>' +
    '</div>' +
  '</div>';
  document.getElementById('view-painel').innerHTML = html;

  hbarList('chart-status', [
    { label:'Aberto', value: stCounts.aberto, color:'var(--sev-critico)' },
    { label:'Fechado', value: stCounts.fechado, color:'var(--ok)' },
    { label:'Outro / N-A', value: stCounts.outro, color:'var(--sev-outro)' }
  ]);
  hbarList('chart-foundby', fbData);
  hbarList('chart-modules', modData);

  // weekly stacked bar chart (svg)
  var barW = 22, gap = 6, chartH = 130;
  var svgW = Math.max(400, weekKeys.length*(barW+gap)+20);
  var bars = weekKeys.map(function(k, i){
    var wk = weekMap[k];
    var x = 10 + i*(barW+gap);
    var y = chartH;
    var segs = ['critico','alto','medio','baixo','outro'].map(function(b){
      var v = wk[b];
      var h = v/weekMax*(chartH-20);
      y -= h;
      if(v===0) return '';
      return '<rect x="'+x+'" y="'+y.toFixed(1)+'" width="'+barW+'" height="'+h.toFixed(1)+'" fill="var(--sev-'+b+')"><title>'+formatDateHuman(wk.start)+' · '+SEV_LABEL[b]+': '+v+'</title></rect>';
    }).join('');
    var label = (wk.start.getUTCMonth()+1)+'/'+wk.start.getUTCDate();
    return segs + '<text x="'+(x+barW/2)+'" y="'+(chartH+14)+'" text-anchor="middle" class="tl-axis-label">'+label+'</text>';
  }).join('');
  document.getElementById('chart-weekly').innerHTML =
    '<svg width="'+svgW+'" height="'+(chartH+24)+'" viewBox="0 0 '+svgW+' '+(chartH+24)+'">' +
    '<line x1="8" y1="'+chartH+'" x2="'+(svgW-6)+'" y2="'+chartH+'" class="tl-gridline"/>' + bars + '</svg>';
}

/* ============================================================
   RENDER: LINHA DO TEMPO (scatter by day / severity lane)
   ============================================================ */
function renderLinha(){
  var list = getFiltered();
  var legendHtml = SEV_ORDER.map(function(b){
    var n = list.filter(function(e){return e._sev.bucket===b;}).length;
    if(!n) return '';
    return '<span class="lg-item"><span class="sw" style="background:var(--sev-'+b+')"></span>'+SEV_LABEL[b]+' ('+n+')</span>';
  }).join('');
  document.getElementById('timeline-legend').innerHTML = legendHtml + '<span class="lg-item" style="color:var(--text-faint)">— eixo X: data · eixo Y: severidade · clique num ponto para abrir</span>';

  if(!DATE_MIN || !DATE_MAX || !list.length){
    document.getElementById('timeline-svg').outerHTML = '<svg id="timeline-svg"></svg>';
    document.getElementById('timeline-svg').innerHTML = '';
    return;
  }
  var dayMs = 86400000;
  var totalDays = Math.max(1, Math.round((DATE_MAX-DATE_MIN)/dayMs));
  var pxPerDay = 34;
  var marginL = 70, marginR = 40, marginT = 16, marginB = 34;
  var W = marginL + marginR + totalDays*pxPerDay;
  var lanes = ['critico','alto','medio','baixo','outro'];
  var laneH = 76, dotR = 5;
  var H = marginT + lanes.length*laneH + marginB;

  // group by day+lane for stacking
  var buckets = {};
  list.forEach(function(e){
    if(!e._date) return;
    var dayIdx = Math.round((e._date-DATE_MIN)/dayMs);
    var key = dayIdx+'|'+e._sev.bucket;
    if(!buckets[key]) buckets[key] = [];
    buckets[key].push(e);
  });

  var svgParts = [];
  // gridlines + week labels
  for(var d=0; d<=totalDays; d++){
    var dt = new Date(DATE_MIN.getTime()+d*dayMs);
    if(dt.getUTCDay()===1 || d===0){
      var gx = marginL + d*pxPerDay;
      svgParts.push('<line x1="'+gx+'" y1="'+marginT+'" x2="'+gx+'" y2="'+(H-marginB)+'" class="tl-gridline" stroke-dasharray="2,3"/>');
      svgParts.push('<text x="'+gx+'" y="'+(H-marginB+16)+'" class="tl-axis-label">'+(dt.getUTCMonth()+1)+'/'+dt.getUTCDate()+'</text>');
    }
  }
  // lane labels + baseline
  lanes.forEach(function(lb, li){
    var ly = marginT + li*laneH;
    svgParts.push('<text x="8" y="'+(ly+laneH/2+4)+'" class="tl-lane-label">'+SEV_LABEL[lb]+'</text>');
    svgParts.push('<line x1="'+marginL+'" y1="'+(ly+laneH)+'" x2="'+W+'" y2="'+(ly+laneH)+'" class="tl-gridline"/>');
  });
  // dots
  Object.keys(buckets).forEach(function(key){
    var parts = key.split('|');
    var dayIdx = +parts[0], lb = parts[1];
    var li = lanes.indexOf(lb);
    var items = buckets[key];
    var laneBaseY = marginT + li*laneH + laneH - dotR - 4;
    var cx = marginL + dayIdx*pxPerDay + pxPerDay/2;
    items.forEach(function(e, i){
      var row = Math.floor(i / 6);
      var col = i % 6;
      var cy = laneBaseY - row*(dotR*2+2);
      var dx = cx + (col - 2.5)*(dotR*2+2);
      svgParts.push('<circle class="tl-dot" data-id="'+e.id+'" cx="'+dx.toFixed(1)+'" cy="'+cy.toFixed(1)+'" r="'+dotR+'" fill="var(--sev-'+lb+')" data-tip="'+escapeHtml(e.id+' · '+(e.file||'')+' · '+(e.date||''))+'"></circle>');
    });
  });

  var svg = document.getElementById('timeline-svg');
  svg.setAttribute('viewBox','0 0 '+W+' '+H);
  svg.setAttribute('width', W);
  svg.setAttribute('height', H);
  svg.innerHTML = svgParts.join('');
}

/* ============================================================
   RENDER: REDE (force-directed module network)
   ============================================================ */
var netLayoutCache = null;
var NET_TOP_N = 24;
var NET_OTHER = '(outros módulos)';
function computeNetworkLayout(entries){
  var rawNodesMap = {};
  var rawEdgesMap = {};
  entries.forEach(function(e){
    var a = e._module;
    rawNodesMap[a] = (rawNodesMap[a]||0)+1;
    if(e.related_file){
      var b = moduleOf(e.related_file);
      if(b && b !== a){
        rawNodesMap[b] = rawNodesMap[b]||0;
        var key = a<b ? a+'::'+b : b+'::'+a;
        rawEdgesMap[key] = (rawEdgesMap[key]||0)+1;
      }
    }
  });
  var rawIds = Object.keys(rawNodesMap).sort(function(x,y){ return rawNodesMap[y]-rawNodesMap[x]; });
  var keep = {};
  rawIds.slice(0, NET_TOP_N).forEach(function(id){ keep[id] = true; });
  var nodesMap = {};
  rawIds.slice(0, NET_TOP_N).forEach(function(id){ nodesMap[id] = rawNodesMap[id]; });
  var otherCount = 0;
  rawIds.slice(NET_TOP_N).forEach(function(id){ otherCount += rawNodesMap[id]; });
  if(otherCount > 0) nodesMap[NET_OTHER] = otherCount;
  function remap(id){ return keep[id] ? id : NET_OTHER; }
  var edgesMap = {};
  Object.keys(rawEdgesMap).forEach(function(k){
    var pair = k.split('::');
    var a = remap(pair[0]), b = remap(pair[1]);
    if(a === b) return;
    var key2 = a < b ? a+'::'+b : b+'::'+a;
    edgesMap[key2] = (edgesMap[key2]||0) + rawEdgesMap[k];
  });
  var ids = Object.keys(nodesMap);
  var nodes = ids.map(function(id, i){
    var angle = (i/ids.length)*Math.PI*2;
    return { id:id, count:nodesMap[id], x: 450+Math.cos(angle)*220, y: 300+Math.sin(angle)*220, vx:0, vy:0 };
  });
  var idxOf = {}; nodes.forEach(function(n,i){ idxOf[n.id]=i; });
  var edges = Object.keys(edgesMap).map(function(k){
    var pair = k.split('::');
    return { a: idxOf[pair[0]], b: idxOf[pair[1]], w: edgesMap[k] };
  });
  // simple force simulation
  for(var iter=0; iter<300; iter++){
    for(var i=0;i<nodes.length;i++){
      for(var j=i+1;j<nodes.length;j++){
        var n1=nodes[i], n2=nodes[j];
        var dx=n1.x-n2.x, dy=n1.y-n2.y;
        var dist = Math.sqrt(dx*dx+dy*dy)||1;
        var force = 3200/(dist*dist);
        var fx = dx/dist*force, fy = dy/dist*force;
        n1.vx += fx; n1.vy += fy;
        n2.vx -= fx; n2.vy -= fy;
      }
    }
    edges.forEach(function(e){
      var n1=nodes[e.a], n2=nodes[e.b];
      var dx=n2.x-n1.x, dy=n2.y-n1.y;
      var dist = Math.sqrt(dx*dx+dy*dy)||1;
      var target = 140;
      var force = (dist-target)*0.02*Math.min(3,Math.sqrt(e.w));
      var fx = dx/dist*force, fy = dy/dist*force;
      n1.vx += fx; n1.vy += fy;
      n2.vx -= fx; n2.vy -= fy;
    });
    nodes.forEach(function(n){
      var dx = 450-n.x, dy = 300-n.y;
      n.vx += dx*0.002; n.vy += dy*0.002;
      n.x += n.vx*0.12; n.y += n.vy*0.12;
      n.vx *= 0.75; n.vy *= 0.75;
      n.x = Math.max(40, Math.min(860, n.x));
      n.y = Math.max(40, Math.min(560, n.y));
    });
  }
  return { nodes: nodes, edges: edges };
}

function renderRede(){
  var list = getFiltered();
  var layout = computeNetworkLayout(list);
  var maxCount = Math.max.apply(null, layout.nodes.map(function(n){return n.count;})) || 1;
  var maxW = Math.max.apply(null, layout.edges.map(function(e){return e.w;})) || 1;

  var parts = [];
  layout.edges.forEach(function(e, i){
    var n1 = layout.nodes[e.a], n2 = layout.nodes[e.b];
    var sw = 1 + (e.w/maxW)*5;
    parts.push('<line class="net-edge" data-edge-a="'+n1.id.replace(/"/g,'&quot;')+'" data-edge-b="'+n2.id.replace(/"/g,'&quot;')+'" x1="'+n1.x.toFixed(1)+'" y1="'+n1.y.toFixed(1)+'" x2="'+n2.x.toFixed(1)+'" y2="'+n2.y.toFixed(1)+'" stroke-width="'+sw.toFixed(1)+'"></line>');
  });
  layout.nodes.forEach(function(n){
    var r = 8 + Math.sqrt(n.count/maxCount)*26;
    var idAttr = n.id.replace(/"/g,'&quot;');
    parts.push('<g class="net-node" data-node="'+idAttr+'" transform="translate('+n.x.toFixed(1)+','+n.y.toFixed(1)+')">' +
      '<circle r="'+r.toFixed(1)+'" fill="var(--accent)" fill-opacity="0.75"></circle>' +
      '<text text-anchor="middle" dy="'+(r+12).toFixed(1)+'">'+escapeHtml(n.id)+'</text>' +
      '<text text-anchor="middle" dy="4" font-weight="700" fill="var(--surface)" font-size="'+(r>16?12:9)+'">'+n.count+'</text>' +
    '</g>');
  });
  var svg = document.getElementById('network-svg');
  svg.innerHTML = parts.join('');
  var hasOther = layout.nodes.some(function(n){ return n.id === NET_OTHER; });
  document.getElementById('network-info').innerHTML =
    '<h4>Rede de módulos</h4><p style="color:var(--text-muted)">'+layout.nodes.length+' módulos, '+layout.edges.length+' conexões, calculado sobre '+list.length+' achados '+(list.length!==AGS.length?'(filtrados)':'(todos)')+'. Cada nó é um módulo do repositório; o tamanho é o nº de achados originados ali; a espessura da linha é o nº de achados que ligam dois módulos. Passe o mouse para destacar; clique para abrir no Explorar.</p>' +
    (hasOther ? '<p style="color:var(--text-faint);font-size:11.5px;">Mostrando os top '+NET_TOP_N+' módulos por volume — o resto (achados com <code>file</code> em formato narrativo/lista, não um caminho único) foi agregado em <strong>'+NET_OTHER+'</strong> pra manter o grafo legível.</p>' : '');
}

/* ============================================================
   RENDER: CADEIAS (addendum / renumbered narrative chains)
   ============================================================ */
function extractRootRef(text){
  if(!text) return null;
  var m = /AG-\d{3,4}/.exec(text);
  return m ? m[0] : null;
}
function buildChains(){
  var chainOf = {}; // rootId -> [entry,...]
  AGS.forEach(function(e){
    var link = e.addendum_de || e.renumbered_from;
    if(!link) return;
    var root = extractRootRef(link);
    if(!root || root === e.id) return;
    if(!chainOf[root]) chainOf[root] = [];
    chainOf[root].push(e);
  });
  var chains = Object.keys(chainOf).map(function(root){
    var members = chainOf[root].slice().sort(function(a,b){ return idNum(a.id)-idNum(b.id); });
    var rootEntry = byId[root] || null;
    return { root: root, rootEntry: rootEntry, members: members };
  });
  chains.sort(function(a,b){ return b.members.length - a.members.length; });
  return chains;
}
function renderCadeias(){
  var filteredIds = {};
  getFiltered().forEach(function(e){ filteredIds[e.id] = true; });
  var chains = buildChains();
  var html = '<div class="panel" style="margin-bottom:16px;"><div class="panel-note" style="margin-bottom:0">Toda entrada marcada <code>addendum_de</code> ou <code>renumbered_from</code> aponta pra um AG anterior — isso reconstrói as '+chains.length+' cadeias narrativas do registro: achados que evoluíram em vez de fechar de primeira. O filtro ativo destaca (não remove) os elos que combinam com a busca.</div></div>';
  var filtersActive = anyActive(state.sev)||anyActive(state.status)||anyActive(state.foundBy)||state.module||state.query;
  var cardsHtml = chains.map(function(c){
    var allEntries = (c.rootEntry ? [c.rootEntry] : []).concat(c.members);
    var anyMatch = allEntries.some(function(e){ return filteredIds[e.id]; });
    if(!anyMatch && filtersActive) return '';
    var steps = allEntries.map(function(e, i){
      var dim = filteredIds[e.id] ? '' : 'opacity:0.45;';
      return '<div class="chain-step" data-id="'+e.id+'" style="--step-color:var(--sev-'+e._sev.bucket+');'+dim+'">' +
        '<div class="cs-top"><span class="cs-id">'+e.id+(i===0 && c.rootEntry ? ' <span style=\"font-weight:400;color:var(--text-faint)\">(origem)</span>' : '')+'</span><span class="cs-date">'+(e.date||'')+'</span></div>' +
        '<div class="cs-txt">'+escapeHtml((e.addendum_de||e.renumbered_from||e.gap||'').replace(/\s+/g,' ').slice(0,180))+'…</div>' +
      '</div>';
    }).join('');
    return '<div class="chain-card"><div class="chain-head">cadeia a partir de <strong>'+c.root+'</strong> · '+allEntries.length+' etapas</div><div class="chain-steps">'+steps+'</div></div>';
  }).join('');
  if(!cardsHtml) cardsHtml = '<div class="empty-state">Nenhuma cadeia tem um elo dentro dos filtros atuais.</div>';
  document.getElementById('chains-list').innerHTML = html + cardsHtml;
}

/* ============================================================
   TAB / VIEW SWITCHING
   ============================================================ */
function setTab(tab){
  state.tab = tab;
  Array.prototype.forEach.call(document.querySelectorAll('.tab'), function(btn){
    var active = btn.getAttribute('data-tab') === tab;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-selected', active ? 'true':'false');
  });
  ['painel','explorar','linha','rede','cadeias'].forEach(function(t){
    document.getElementById('view-'+t).hidden = (t!==tab);
  });
  document.getElementById('toolbar').hidden = (tab==='painel');
  renderActiveTab();
}
function renderActiveTab(){
  if(state.tab==='painel') renderPainel();
  else if(state.tab==='explorar') renderExplorer();
  else if(state.tab==='linha') renderLinha();
  else if(state.tab==='rede') renderRede();
  else if(state.tab==='cadeias') renderCadeias();
  renderToolbar();
}

/* ============================================================
   TOAST
   ============================================================ */
var toastTimer = null;
function showToast(msg){
  var t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(function(){ t.classList.remove('show'); }, 2200);
}

/* ============================================================
   EVENTS
   ============================================================ */
document.addEventListener('click', function(ev){
  var agRef = ev.target.closest && ev.target.closest('.ag-ref');
  if(agRef){
    ev.preventDefault();
    if(byId[agRef.getAttribute('data-ag')]) selectEntry(agRef.getAttribute('data-ag'), true);
    return;
  }
  var row = ev.target.closest && ev.target.closest('.ag-row');
  if(row){ selectEntry(row.getAttribute('data-id'), false); return; }
  var chip = ev.target.closest && ev.target.closest('.chip');
  if(chip){
    var bucket = chip.getAttribute('data-bucket');
    var map = chip.classList.contains('sev-critico')||chip.classList.contains('sev-alto')||chip.classList.contains('sev-medio')||chip.classList.contains('sev-baixo')||chip.classList.contains('sev-outro') ? state.sev
      : (chip.parentElement.id==='chips-status' ? state.status : state.foundBy);
    map[bucket] = !map[bucket];
    renderActiveTab();
    return;
  }
  var tabBtn = ev.target.closest && ev.target.closest('.tab');
  if(tabBtn){ setTab(tabBtn.getAttribute('data-tab')); return; }
  var chainStep = ev.target.closest && ev.target.closest('.chain-step');
  if(chainStep){ selectEntry(chainStep.getAttribute('data-id'), true); return; }
});

document.getElementById('global-search').addEventListener('input', function(ev){
  state.query = ev.target.value;
  renderActiveTab();
});
document.getElementById('select-module').addEventListener('change', function(ev){
  state.module = ev.target.value;
  renderActiveTab();
});
document.getElementById('select-sort').addEventListener('change', function(ev){
  state.sort = ev.target.value;
  renderActiveTab();
});
document.getElementById('btn-clear-filters').addEventListener('click', function(){
  state.sev = {}; state.status = {}; state.foundBy = {}; state.module = ''; state.query = '';
  document.getElementById('global-search').value = '';
  renderActiveTab();
});

document.addEventListener('keydown', function(ev){
  if(ev.key === '/' && document.activeElement !== document.getElementById('global-search')){
    ev.preventDefault();
    document.getElementById('global-search').focus();
  }
});

// timeline tooltip
(function(){
  var tip = null;
  document.addEventListener('mousemove', function(ev){
    var dot = ev.target.closest && ev.target.closest('.tl-dot');
    if(dot){
      if(!tip){ tip = document.createElement('div'); tip.className='tl-tooltip'; document.body.appendChild(tip); }
      tip.textContent = dot.getAttribute('data-tip');
      tip.style.left = (ev.clientX+14)+'px';
      tip.style.top = (ev.clientY+14)+'px';
      tip.style.display = 'block';
      dot.classList.add('hl');
    } else if(tip){
      tip.style.display = 'none';
    }
  });
  document.addEventListener('click', function(ev){
    var dot = ev.target.closest && ev.target.closest('.tl-dot');
    if(dot){ selectEntry(dot.getAttribute('data-id'), true); }
  });
})();

// network hover + click
(function(){
  document.addEventListener('mousemove', function(ev){
    var svg = document.getElementById('network-svg');
    if(!svg.contains(ev.target)) return;
    var node = ev.target.closest && ev.target.closest('.net-node');
    var allNodes = svg.querySelectorAll('.net-node');
    var allEdges = svg.querySelectorAll('.net-edge');
    if(node){
      var id = node.getAttribute('data-node');
      Array.prototype.forEach.call(allNodes, function(n){
        n.classList.toggle('net-dim', n.getAttribute('data-node')!==id);
      });
      Array.prototype.forEach.call(allEdges, function(e){
        var touches = e.getAttribute('data-edge-a')===id || e.getAttribute('data-edge-b')===id;
        e.classList.toggle('net-dim', !touches);
      });
    } else {
      Array.prototype.forEach.call(allNodes, function(n){ n.classList.remove('net-dim'); });
      Array.prototype.forEach.call(allEdges, function(e){ e.classList.remove('net-dim'); });
    }
  });
  document.addEventListener('click', function(ev){
    var node = ev.target.closest && ev.target.closest('.net-node');
    if(node){
      var id = node.getAttribute('data-node');
      if(id === NET_OTHER){ showToast('Esse nó agrega vários módulos pequenos — não dá pra filtrar por ele.'); return; }
      state.module = id;
      setTab('explorar');
    }
  });
})();

// theme toggle
(function(){
  var order = ['system','light','dark'];
  var labels = { system:'Sistema', light:'Claro', dark:'Escuro' };
  var current = 'system';
  try{ current = localStorage.getItem('agx-theme') || 'system'; }catch(e){}
  function apply(){
    if(current==='system') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', current);
    document.getElementById('theme-toggle-label').textContent = labels[current];
  }
  apply();
  document.getElementById('theme-toggle').addEventListener('click', function(){
    current = order[(order.indexOf(current)+1)%order.length];
    try{ localStorage.setItem('agx-theme', current); }catch(e){}
    apply();
  });
})();

/* ============================================================
   BOOT
   ============================================================ */
renderKPIs();
renderToolbar();
setTab('painel');
