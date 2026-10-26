// Página do 2º turno: lê dados/apuracao.json (gravado pelo coletor) e desenha tudo. D3 v7.
const ARQ = "dados/apuracao.json";
const INTERVALO = 60_000;
const B = ["PT", "PL"];
const NOME = { PT: "Lula", PL: "Flávio Bolsonaro" };
const REGIOES = { N: "AC AM AP PA RO RR TO", NE: "AL BA CE MA PB PE PI RN SE", CO: "DF GO MS MT", SE: "ES MG RJ SP", S: "PR RS SC", ZZ: "ZZ" };
const REG_DE = Object.fromEntries(Object.entries(REGIOES).flatMap(([r, ufs]) => ufs.split(" ").map((u) => [u, r])));
const fmt = (v, d = 1) => v == null || Number.isNaN(v) ? "–" : v.toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
const pp = (v, d = 1) => (v > 0 ? "+" : "") + fmt(v, d);
const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };

let dados = null, idx = -1, ordem = "margem", regiao = "todas", ufSel = null, zoom = "auto";

async function carregar() {
  try {
    const r = await fetch(`${ARQ}?t=${Date.now()}`, { cache: "no-store" });
    if (!r.ok) throw new Error(r.status);
    dados = await r.json(); dados.encerrada = fechar();
    idx = -1; desenhar();
  } catch (e) {
    document.getElementById("status").textContent = "Aguardando os primeiros dados da apuração…";
  }
}
const pontos = () => (dados?.pontos ?? []);
// Com o TSE em 100% das seções a apuração acabou: a série termina no primeiro ciclo em que nada mais mudou,
// em vez de seguir o relógio do coletor (que continua lendo o TSE por horas sem novidade).
function fechar() {
  const P = pontos(); if (P.length < 2 || !((dados.tse_pct_secoes ?? 0) >= 100)) return false;
  const f = P.at(-1); const igual = (p) => p.x === f.x && p.votos && f.votos && p.votos.PT === f.votos.PT && p.votos.PL === f.votos.PL;
  let i = P.length - 1; while (i > 0 && igual(P[i - 1])) i--;
  dados.pontos = P.slice(0, i + 1); return true;
}
const atual = () => pontos()[idx < 0 ? pontos().length - 1 : idx];

function desenhar() {
  const p = atual(); const vazio = p && p.x === 0 && p.votos && p.votos.PT + p.votos.PL === 0;
  if (!p || vazio) {
    document.getElementById("status").textContent = `Aguardando o início da apuração (urnas fecham às 17h) · coletor ativo, atualizado ${dados.atualizado}`;
    document.getElementById("ambiente").hidden = dados.ambiente === "oficial";
    document.getElementById("cartoes").replaceChildren(); document.getElementById("prob").replaceChildren();
    const s = document.getElementById("situacao"); s.className = "situacao aviso"; s.textContent = "Nenhuma seção totalizada ainda. A projeção aparece a partir de 2% do eleitorado apurado.";
    document.getElementById("rodape-atualizado").textContent = `Atualizado ${dados.atualizado}`; return;
  }
  const ultimo = pontos().at(-1); const fim = dados.encerrada ? ultimo : null;
  document.getElementById("ambiente").hidden = dados.ambiente === "oficial";
  document.getElementById("status").textContent = fim
    ? `Apuração encerrada às ${fim.t} · ${fmt(ultimo.x, 1)}% do eleitorado apurado · TSE: ${fmt(dados.tse_pct_secoes, 1)}% das seções`
    : ultimo.x > 0 || (ultimo.votos && ultimo.votos.PT + ultimo.votos.PL > 0)
    ? `${fmt(ultimo.x, 1)}% do eleitorado apurado · TSE: ${fmt(dados.tse_pct_secoes, 1)}% das seções · atualizado ${dados.atualizado}`
    : `Aguardando o início da apuração (urnas fecham às 17h) · coletor ativo, atualizado ${dados.atualizado}`;
  document.getElementById("rodape-atualizado").textContent = fim ? `Apuração encerrada às ${fim.t} · última leitura do TSE ${dados.atualizado}` : `Atualizado ${dados.atualizado}`;
  document.getElementById("voltar-agora").textContent = fim ? "Voltar ao final" : "Voltar ao agora";
  const mom = document.getElementById("momento"); mom.hidden = idx < 0;
  if (idx >= 0) document.getElementById("momento-texto").textContent = `Como estava às ${p.t}, com ${fmt(p.x, 1)}% apurado`;
  legenda(); cartoes(p); probabilidade(p); situacao(p); grafico(); graficoProb(); swing(); estados(); participacao(p);
  const s = document.getElementById("scrub"); s.max = pontos().length - 1; if (idx < 0) s.value = s.max;
}

function legenda() {
  const l = document.getElementById("legenda"); l.replaceChildren();
  const item = (cls, tipo, txt) => { const s = el("span", cls); const i = el("i", tipo); s.append(i, document.createTextNode(txt)); l.append(s); };
  item("PT", "", "Lula · apurado"); item("PT", "tracejada", "Lula · projeção"); item("PL", "", "Flávio · apurado"); item("PL", "tracejada", "Flávio · projeção"); item("", "area", "faixa de 90%");
}
const meia = (p, b) => p.faixa ? (p.faixa[b][1] - p.faixa[b][0]) / 2 : null;
function cartoes(p) {
  const c = document.getElementById("cartoes"); c.replaceChildren();
  for (const b of B) {
    const k = el("div", `cartao ${b}`);
    const nome = el("div", "nome"); nome.append(el("span", "ponto"), document.createTextNode(NOME[b])); k.append(nome);
    const proj = p.projecao ? p.projecao[b] : p.preliminar ? p.preliminar[b] : null;
    k.append(el("div", "valor", proj == null ? "–" : fmt(proj, 1) + "%"));
    k.append(el("div", "faixa", p.faixa ? `± ${fmt(meia(p, b), 1)} p.p. (faixa de 90%)` : p.preliminar ? "projeção preliminar (menos de 2% apurado)" : "sem projeção ainda"));
    const ap = el("div", "apurado"); ap.append("nos votos já contados: ", Object.assign(el("b"), { textContent: fmt(p.apurado[b], 1) + "%" })); k.append(ap);
    c.append(k);
  }
}
function probabilidade(p) {
  const d = document.getElementById("prob"); d.replaceChildren();
  if (!p.p_vitoria) { d.append(el("div", "titulo", "Probabilidade de vitória: disponível a partir de 2% apurado.")); return; }
  const pt = p.p_vitoria.PT, pl = p.p_vitoria.PL;
  d.append(el("div", "titulo", "Probabilidade de vitória"));
  const barra = el("div", "barra"); const a = el("span", "PT"); a.style.width = `${pt * 100}%`; const b = el("span", "PL"); b.style.width = `${pl * 100}%`; barra.append(a, b); d.append(barra);
  const r = el("div", "rotulos"); r.innerHTML = `<span><b>${fmt(pt * 100, pt > .99 || pt < .01 ? 1 : 0)}%</b> Lula</span><span>Flávio <b>${fmt(pl * 100, pl > .99 || pl < .01 ? 1 : 0)}%</b></span>`; d.append(r);
}
function situacao(p) {
  const s = document.getElementById("situacao"); s.className = "situacao";
  if (p.definido_mat) { const v = p.votos.PT > p.votos.PL ? "Lula" : "Flávio Bolsonaro"; s.textContent = `Matematicamente definido: ${v} tem mais votos do que o eleitorado que ainda falta apurar.`; s.classList.add("ok"); return; }
  if (!p.p_vitoria) { s.textContent = "Poucas urnas apuradas: a projeção ainda é preliminar e imprecisa."; s.classList.add("aviso"); return; }
  const m = Math.max(p.p_vitoria.PT, p.p_vitoria.PL); const v = p.p_vitoria.PT >= p.p_vitoria.PL ? "Lula" : "Flávio Bolsonaro";
  if (m >= .99) { s.textContent = `Provável vencedor: ${v} (probabilidade acima de 99%).`; s.classList.add("ok"); }
  else if (m >= .9) s.textContent = `${v} é favorito, mas a disputa ainda não está definida.`;
  else { s.textContent = "Disputa indefinida."; s.classList.add("aviso"); }
}

// ---------- gráfico principal: apurado x projeção, com scrubber ----------
function grafico() {
  const cont = document.getElementById("grafico"); cont.replaceChildren();
  const P = pontos().filter((p) => p.x > 0); if (P.length < 2) return;
  const W = cont.clientWidth, H = cont.clientHeight, m = { t: 10, r: 12, b: 26, l: 34 };
  const svg = d3.select(cont).append("svg").attr("viewBox", `0 0 ${W} ${H}`);
  const xmax = zoom === "100" ? 100 : Math.min(100, Math.max(5, Math.ceil(d3.max(P, (p) => p.x) * 1.15 / 5) * 5));
  const x = d3.scaleLinear().domain([0, xmax]).range([m.l, W - m.r]);
  const vals = P.flatMap((p) => [p.apurado.PT, p.apurado.PL, ...(p.projecao ? [p.projecao.PT, p.projecao.PL] : []), ...(p.faixa ? [...p.faixa.PT, ...p.faixa.PL] : [])]);
  const y = d3.scaleLinear().domain([Math.max(0, d3.min(vals) - 2), Math.min(100, d3.max(vals) + 2)]).nice().range([H - m.b, m.t]);
  svg.append("g").attr("class", "grade").call(d3.axisLeft(y).ticks(5).tickSize(-(W - m.l - m.r)).tickFormat("")).attr("transform", `translate(${m.l},0)`).select(".domain").remove();
  svg.append("g").attr("class", "eixo").attr("transform", `translate(0,${H - m.b})`).call(d3.axisBottom(x).ticks(6).tickFormat((d) => d + "%"));
  svg.append("g").attr("class", "eixo").attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(5).tickFormat((d) => d + "%"));
  if (y.domain()[0] < 50 && y.domain()[1] > 50) svg.append("line").attr("class", "meta50").attr("x1", m.l).attr("x2", W - m.r).attr("y1", y(50)).attr("y2", y(50));
  const PP = P.filter((p) => p.projecao);
  for (const b of B) {
    const k = b.toLowerCase();
    svg.append("path").datum(PP.filter((p) => p.faixa)).attr("class", `faixa-${k}`).attr("d", d3.area().x((p) => x(p.x)).y0((p) => y(p.faixa[b][0])).y1((p) => y(p.faixa[b][1])).curve(d3.curveMonotoneX));
    svg.append("path").datum(P).attr("class", `linha-${k}`).attr("fill", "none").attr("stroke-width", 2).attr("d", d3.line().x((p) => x(p.x)).y((p) => y(p.apurado[b])).curve(d3.curveMonotoneX));
    svg.append("path").datum(PP).attr("class", `proj-${k}`).attr("fill", "none").attr("stroke-width", 2).attr("d", d3.line().x((p) => x(p.x)).y((p) => y(p.projecao[b])).curve(d3.curveMonotoneX));
  }
  const cruz = svg.append("line").attr("class", "cruz").attr("y1", m.t).attr("y2", H - m.b).style("display", "none");
  const marc = svg.append("g").style("display", "none"); B.forEach(() => marc.append("circle").attr("class", "marcador").attr("r", 4));
  const dica = document.getElementById("dica");
  const mostrar = (p, clientX, clientY) => {
    cruz.attr("x1", x(p.x)).attr("x2", x(p.x)).style("display", null); marc.style("display", null);
    marc.selectAll("circle").data(B).attr("cx", x(p.x)).attr("cy", (b) => y(p.projecao ? p.projecao[b] : p.apurado[b]));
    dica.replaceChildren(el("div", "dica-topo", `${p.t} · ${fmt(p.x, 1)}% apurado`));
    for (const b of B) {
      const r = el("div", "dica-linha"); r.textContent = `${NOME[b]}: ${fmt(p.apurado[b], 1)}% dos votos contados` + (p.projecao ? ` · projeção ${fmt(p.projecao[b], 1)}% ± ${fmt(meia(p, b), 1)}` : ""); dica.append(r);
    }
    if (p.p_vitoria) dica.append(el("div", "dica-linha", `P(vitória): Lula ${fmt(p.p_vitoria.PT * 100, 0)}% · Flávio ${fmt(p.p_vitoria.PL * 100, 0)}%`));
    dica.hidden = false; const bx = dica.getBoundingClientRect();
    dica.style.left = `${Math.max(8, Math.min(window.innerWidth - bx.width - 8, clientX - bx.width / 2))}px`;
    dica.style.top = `${Math.max(8, clientY - bx.height - 18)}px`;
  };
  const bis = d3.bisector((p) => p.x).center;
  const seleciona = (ev) => {
    const [mx] = d3.pointer(ev, svg.node()); const xv = x.invert(mx);
    const i = bis(P, xv); const p = P[i]; idx = pontos().indexOf(p);
    mostrar(p, ev.clientX, ev.clientY); desenharParcial(p);
  };
  // passar o mouse só mostra a dica; clicar ou arrastar fixa o momento (barra "Voltar ao agora")
  const espiar = (ev) => { const [mx] = d3.pointer(ev, svg.node()); mostrar(P[bis(P, x.invert(mx))], ev.clientX, ev.clientY); };
  svg.on("pointerdown", (ev) => { ev.target.setPointerCapture?.(ev.pointerId); seleciona(ev); })
     .on("pointermove", (ev) => { if (ev.pressure > 0 || ev.buttons) seleciona(ev); else if (ev.pointerType === "mouse") espiar(ev); })
     .on("pointerup pointerleave", () => { dica.hidden = true; });
  if (idx >= 0) { const p = atual(); if (p.x > 0) { cruz.attr("x1", x(p.x)).attr("x2", x(p.x)).style("display", null); marc.style("display", null); marc.selectAll("circle").data(B).attr("cx", x(p.x)).attr("cy", (b) => y(p.projecao ? p.projecao[b] : p.apurado[b])); } }
}
// atualiza só o que depende do momento escolhido (sem redesenhar os gráficos)
function desenharParcial(p) {
  cartoes(p); probabilidade(p); situacao(p); participacao(p);
  const mom = document.getElementById("momento"); mom.hidden = false;
  document.getElementById("momento-texto").textContent = `Como estava às ${p.t}, com ${fmt(p.x, 1)}% apurado`;
  document.getElementById("scrub").value = pontos().indexOf(p);
}
function graficoProb() {
  const cont = document.getElementById("grafico-prob"); cont.replaceChildren();
  const P = pontos().filter((p) => p.p_vitoria); if (P.length < 2) return;
  const W = cont.clientWidth, H = cont.clientHeight, m = { t: 6, r: 12, b: 18, l: 34 };
  const svg = d3.select(cont).append("svg").attr("viewBox", `0 0 ${W} ${H}`);
  const xmax = zoom === "100" ? 100 : Math.min(100, Math.max(5, Math.ceil(d3.max(pontos(), (p) => p.x) * 1.15 / 5) * 5));
  const x = d3.scaleLinear().domain([0, xmax]).range([m.l, W - m.r]), y = d3.scaleLinear().domain([0, 1]).range([H - m.b, m.t]);
  svg.append("g").attr("class", "eixo").attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(y).tickValues([0, .5, 1]).tickFormat((d) => d * 100 + "%"));
  svg.append("g").attr("class", "eixo").attr("transform", `translate(0,${H - m.b})`).call(d3.axisBottom(x).ticks(6).tickFormat((d) => d + "%"));
  svg.append("path").datum(P).attr("class", "faixa-pt").attr("opacity", .25).attr("d", d3.area().x((p) => x(p.x)).y0(y(0)).y1((p) => y(p.p_vitoria.PT)).curve(d3.curveStepAfter));
  svg.append("path").datum(P).attr("class", "faixa-pl").attr("opacity", .25).attr("d", d3.area().x((p) => x(p.x)).y0((p) => y(p.p_vitoria.PT)).y1(y(1)).curve(d3.curveStepAfter));
  svg.append("path").datum(P).attr("class", "linha-pt").attr("fill", "none").attr("stroke-width", 2).attr("d", d3.line().x((p) => x(p.x)).y((p) => y(p.p_vitoria.PT)).curve(d3.curveStepAfter));
}

// ---------- mudança desde o 1º turno ----------
function swing() {
  const k = document.getElementById("kpis-swing"); k.replaceChildren();
  const p = atual(); const b1 = dados.base_1t; if (!b1) return;
  const proj = p.projecao ?? p.preliminar;
  const add = (rot, val, sub, cls) => { const d = el("div", "kpi"); d.append(el("div", "rot", rot)); const v = el("div", "val", val); if (cls) v.classList.add(cls); d.append(v); if (sub) d.append(el("div", "sub", sub)); k.append(d); };
  add("Lula no 1º turno → projeção", `${fmt(b1.PT, 1)} → ${fmt(proj?.PT, 1)}`, "% dos válidos entre os dois", "PT");
  add("Flávio no 1º turno → projeção", `${fmt(b1.PL, 1)} → ${fmt(proj?.PL, 1)}`, "% dos válidos entre os dois", "PL");
  add("Votos nos eliminados no 1º turno", `${fmt(b1.outros, 1)}%`, "Cury, Renan, Caiado e outros");
  const c = dados.coef_outros;
  const nota = document.getElementById("nota-outros");
  if (c != null && p.projecao) {
    const fator = Math.exp(c * 0.10); const quem = fator > 1 ? "Lula" : "Flávio";
    nota.textContent = `Onde os candidatos eliminados tiveram 10 pontos a mais no 1º turno, a razão Lula/Flávio ${fator > 1 ? "sobe" : "cai"} ${fmt(Math.abs(fator - 1) * 100, 0)}% em relação ao 1º turno — o voto deles está migrando mais para ${quem}. (Padrão agregado estimado pela regressão; não é inferência individual.)`;
  } else nota.textContent = "";
  // gráfico: swing por UF (pontos), ordenado
  const cont = document.getElementById("grafico-swing"); cont.replaceChildren();
  const E = (dados.estados ?? []).filter((e) => e.x > 0 && e.uf !== "ZZ").sort((a, b) => a.swing - b.swing); if (!E.length) return;
  const W = cont.clientWidth, H = Math.max(260, E.length * 14 + 30); cont.style.height = H + "px"; const m = { t: 8, r: 16, b: 24, l: 30 };
  const svg = d3.select(cont).append("svg").attr("viewBox", `0 0 ${W} ${H}`);
  const ext = d3.max(E, (e) => Math.abs(e.swing)) || 1; const x = d3.scaleLinear().domain([-ext, ext]).nice().range([m.l, W - m.r]);
  const y = d3.scalePoint().domain(E.map((e) => e.uf)).range([m.t, H - m.b]).padding(.5);
  svg.append("g").attr("class", "eixo").attr("transform", `translate(0,${H - m.b})`).call(d3.axisBottom(x).ticks(5).tickFormat((d) => pp(d, 0)));
  svg.append("line").attr("class", "meta50").attr("x1", x(0)).attr("x2", x(0)).attr("y1", m.t).attr("y2", H - m.b);
  const g = svg.append("g").selectAll("g").data(E).join("g").attr("transform", (e) => `translate(0,${y(e.uf)})`);
  g.append("line").attr("x1", x(0)).attr("x2", (e) => x(e.swing)).attr("stroke", (e) => e.swing > 0 ? "var(--pt)" : "var(--pl)").attr("stroke-width", 2).attr("opacity", .5);
  g.append("circle").attr("cx", (e) => x(e.swing)).attr("r", (e) => 3 + Math.min(3, e.x / 34)).attr("fill", (e) => e.swing > 0 ? "var(--pt)" : "var(--pl)").attr("opacity", (e) => .35 + .65 * Math.min(1, e.x / 50));
  g.append("text").attr("x", (e) => x(e.swing) + (e.swing > 0 ? 8 : -8)).attr("dy", "0.35em").attr("text-anchor", (e) => e.swing > 0 ? "start" : "end").attr("fill", "var(--texto2)").attr("font-size", 10).text((e) => `${e.uf} ${pp(e.swing, 1)}`);
  const nac = proj ? proj.PT - b1.PT : null;
  document.getElementById("nota-swing").textContent = `Pontos percentuais de Lula (entre os dois) na projeção do estado vs. 1º turno. Para a direita, Lula ganhou; para a esquerda, Flávio. Pontos mais fortes = estado mais apurado.${nac != null ? ` Brasil: ${pp(nac, 1)} p.p.` : ""}`;
  svg.on("click", (ev) => { const [, my] = d3.pointer(ev); const uf = E.reduce((a, e) => Math.abs(y(e.uf) - my) < Math.abs(y(a.uf) - my) ? e : a).uf; ufSel = uf; estados(); document.getElementById("detalhe").scrollIntoView({ behavior: "smooth", block: "nearest" }); });
}

// ---------- estados ----------
function estados() {
  const ol = document.getElementById("estados"); ol.replaceChildren();
  const regs = document.getElementById("regioes");
  if (!regs.children.length) {
    for (const r of ["todas", "N", "NE", "CO", "SE", "S"]) { const b = el("button", r === regiao ? "ativo" : "", r === "todas" ? "Todas" : r); b.type = "button"; b.onclick = () => { regiao = r; estados(); }; regs.append(b); }
  }
  [...regs.children].forEach((b, i) => b.classList.toggle("ativo", ["todas", "N", "NE", "CO", "SE", "S"][i] === regiao));
  let E = (dados.estados ?? []).filter((e) => regiao === "todas" || REG_DE[e.uf] === regiao);
  const key = { margem: (e) => -(e.PT - e.PL), swing: (e) => -e.swing, x: (e) => -e.x, uf: (e) => e.uf };
  E.sort((a, b) => d3.ascending(key[ordem](a), key[ordem](b)));
  for (const e of E) {
    const li = el("li"); li.onclick = () => { ufSel = e.uf; detalhe(); };
    const uf = el("div", "uf", e.uf); uf.append(el("small", null, `${fmt(e.x, 0)}% apurado`)); li.append(uf);
    const barra = el("div", "barra"); const a = el("span", "PT"); a.style.width = `${e.PT}%`; const b = el("span", "PL"); b.style.width = `${e.PL}%`; barra.append(a, b);
    const m1 = el("span", "marca1t"); m1.style.left = `${e.PT_1t}%`; m1.title = `1º turno: Lula ${fmt(e.PT_1t, 1)}%`; barra.append(m1);
    const nao = el("span", "nao"); nao.style.width = `${100 - Math.min(100, e.x)}%`; barra.append(nao); li.append(barra);
    const num = el("div", "num", `${e.PT >= e.PL ? "L" : "F"} ${pp(Math.abs(e.PT - e.PL), 1).replace("+", "+")}`); num.append(el("small", null, `mud. ${pp(e.swing, 1)}`)); li.append(num);
    ol.append(li);
  }
  detalhe();
}
function detalhe() {
  const d = document.getElementById("detalhe"); const e = (dados.estados ?? []).find((s) => s.uf === ufSel);
  if (!e) { d.hidden = true; return; }
  d.hidden = false; d.replaceChildren(el("h3", null, `${e.uf} · ${fmt(e.x, 1)}% do eleitorado apurado`));
  const t = el("table"); const linha = (a, b) => { const tr = el("tr"); tr.append(el("td", null, a), el("td", null, b)); t.append(tr); };
  linha("Projeção", `Lula ${fmt(e.PT, 1)}% · Flávio ${fmt(e.PL, 1)}%`);
  linha("Apurado até agora", `Lula ${fmt(e.apurado_PT, 1)}%`);
  linha("1º turno (entre os dois)", `Lula ${fmt(e.PT_1t, 1)}%`);
  linha("Mudança desde o 1º turno", `${pp(e.swing, 1)} p.p. para Lula`);
  linha("Comparecimento vs. 1º turno", `${pp(e.comparecimento_vs_1t, 1)}%`);
  d.append(t);
}

// ---------- participação ----------
function participacao(p) {
  const k = document.getElementById("kpis-part"); k.replaceChildren(); const b1 = dados.base_1t ?? {};
  const add = (rot, val, sub) => { const d = el("div", "kpi"); d.append(el("div", "rot", rot), el("div", "val", val)); if (sub) d.append(el("div", "sub", sub)); k.append(d); };
  add("Comparecimento projetado", p.comparecimento_proj != null ? `${fmt(p.comparecimento_proj, 1)}%` : "–", b1.comparecimento != null ? `1º turno: ${fmt(b1.comparecimento, 1)}% (${pp(p.comparecimento_proj - b1.comparecimento, 1)})` : "");
  add("Brancos e nulos (apurado)", p.brancos_nulos_pct != null ? `${fmt(p.brancos_nulos_pct, 1)}%` : "–", b1.brancos_nulos_pct != null ? `1º turno: ${fmt(b1.brancos_nulos_pct, 1)}%` : "");
  add("Votos já contados", `${fmt((p.votos.PT + p.votos.PL) / 1e6, 1)} mi`, `Lula ${fmt(p.votos.PT / 1e6, 1)} mi · Flávio ${fmt(p.votos.PL / 1e6, 1)} mi`);
  if (p.eleitores_pendentes != null) add("Eleitores ainda não apurados", `${fmt(p.eleitores_pendentes / 1e6, 1)} mi`, `vantagem atual: ${fmt(Math.abs(p.votos.PT - p.votos.PL) / 1e6, 2)} mi votos`);
}

function iniciar() {
  document.getElementById("scrub").addEventListener("input", (ev) => { idx = +ev.target.value; if (idx >= pontos().length - 1) idx = -1; const p = atual(); if (p) { desenharParcial(p); if (idx < 0) document.getElementById("momento").hidden = true; } });
  document.getElementById("voltar-agora").onclick = () => { idx = -1; desenhar(); };
  document.querySelectorAll("#zoom button").forEach((b) => b.onclick = () => { zoom = b.dataset.z; document.querySelectorAll("#zoom button").forEach((x) => x.classList.toggle("ativo", x === b)); grafico(); graficoProb(); });
  document.querySelectorAll("#ordem button").forEach((b) => b.onclick = () => { ordem = b.dataset.k; document.querySelectorAll("#ordem button").forEach((x) => x.classList.toggle("ativo", x === b)); estados(); });
  window.addEventListener("resize", () => { if (dados && pontos().some((p) => p.x > 0)) { grafico(); graficoProb(); swing(); } });
  carregar(); setInterval(() => { if (idx < 0 && !dados?.encerrada) carregar(); }, INTERVALO);
}
iniciar();
