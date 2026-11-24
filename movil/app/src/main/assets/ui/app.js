// Atlas Móvil: la pantalla. Todo lo de red, llaves, micrófono y parlante lo hace la parte nativa (window.Nativo);
// esta página no tiene acceso a internet ni guarda secretos.
"use strict";
const $ = (id) => document.getElementById(id);
const ORDEN = ["cronos", "hermes", "fortuna", "baco", "atenea"];
const QUE = { cronos: "Cronos guarda tu historia día por día.", hermes: "Hermes lleva tus gastos.", fortuna: "Fortuna sigue tus fondos mutuos.",
  atenea: "Atenea es tu espacio de aprendizaje." };

// ---- sin la app (navegador del PC): un Nativo de mentira para ver las pantallas
if (!window.Nativo) {
  const ev = (n, d) => setTimeout(() => Atlas._evento(n, JSON.stringify(d || {})), 400);
  let v = location.hash === "#nuevo" ? "" : JSON.stringify({ pc: "PC-DEMO", hosts: ["192.168.1.34"], host: "192.168.1.34" });
  window.Nativo = {
    vinculo: () => v, escanear: () => { v = JSON.stringify({ pc: "PC-DEMO", hosts: ["192.168.1.34"] }); ev("vinculado"); }, desvincular: () => { v = ""; },
    pedir: (id, m, ruta, cuerpo) => { const r = { "/p/estado": { listo: true, modo: "idle", apps: ["Cronos", "Hermes", "Fortuna", "Baco", "Atenea"], pc: "PC-DEMO",
        musica: { titulo: "BRAIN", artista: "Ado", estado: "Playing", pos: 37, fin: 156 },
        recordatorios: [{ id: "1", tipo: "recordatorio", texto: "Repasar Redes", hora: "08:00", en: 30000 }], tareas: [{ texto: "Tarea 5 · Redes", hora: "23:59", en: 90000 }],
        pendientes: [{ id: "p", texto: "Responder correo del curso" }] },
      "/p/chat": { reply: "Esta semana tiene cuatro cosas, señor.", vista: /horario|evento/i.test(cuerpo) || location.hash === "#vista" ? { tipo: "calendario", titulo: "Mi horario · esta semana", desde: "2026-11-23", dias: 7, pestana: "ambos", items: [
        { titulo: "Redes de computadores", dia: "2026-11-24", hora: "10:15", fin: "11:45", lugar: "B101", tipo: "clase" }, { titulo: "Auxiliar de Intro", dia: "2026-11-24", hora: "16:00", fin: "17:30", tipo: "auxiliar" },
        { titulo: "Control 2 de Lenguajes", dia: "2026-11-25", hora: "18:00", fin: "20:00", lugar: "F10", tipo: "evaluacion" }, { titulo: "Entrega T5", dia: "2026-11-26", tipo: "entrega" }, { titulo: "Cumpleaños de Ana", dia: "2026-11-28", hora: "20:00", tipo: "google" }] } : null, pendiente: /recu/i.test(cuerpo) ? "Crear recordatorio «Repasar Redes», mañana 08:00" : null },
      "/p/hermes": { desde: "2026-10-24", hasta: "2026-11-23", total: 384200, anterior: 431000, dias_quedan: 0, presupuesto: 500000, semana: 41300, al: "2026-11-22",
        categorias: [{ nombre: "Comida", monto: 152300, presupuesto: 180000 }, { nombre: "Transporte", monto: 88400, presupuesto: 60000 }, { nombre: "Salidas", monto: 74500, presupuesto: null }, { nombre: "Suscripciones", monto: 69000, presupuesto: null }],
        ultimos: [{ fecha: "2026-11-22", comercio: "Supermercado Uno", monto: 23490, categoria: "Comida" }, { fecha: "2026-11-21", comercio: "Uber", monto: 6200, categoria: "Transporte" }, { fecha: "2026-11-20", comercio: "Cafetería del campus", monto: 3100, categoria: "Comida" }] },
      "/p/fortuna": { al: "2026-11-20", mio: { puesto: 1500000, ahora: 1583400, gano: 83400, pct: 5.56, mes: 12300, mes_pct: 0.78, posiciones: [{ nombre: "Fondo Moderado", adm: "BCI", puesto: 1000000, ahora: 1061200, pct: 6.12 }, { nombre: "Fondo Acciones USA", adm: "Scotia", puesto: 500000, ahora: 522200, pct: 4.44 }] },
        fondos: [{ nombre: "Fondo Moderado", adm: "BCI", mes: 0.8, anio: 6.4, mio: true }, { nombre: "Fondo Acciones USA", adm: "Scotia", mes: -1.2, anio: 11.9, mio: true }, { nombre: "Fondo Liquidez", adm: "Scotia", mes: 0.4, anio: 4.1, mio: false }] },
      "/p/cronos": { fecha: (() => { try { return JSON.parse(cuerpo).fecha; } catch (e) { return null; } })() || new Date().toISOString().slice(0, 10), parcial: false, bloques: [{ ini: "00:40", fin: "08:05", fila: "sueno", titulo: "Durmiendo", conf: "media" }, { ini: "08:50", fin: "09:25", fila: "viaje", titulo: "Metro a la universidad", conf: "alta" },
        { ini: "10:15", fin: "11:45", fila: "lugar", titulo: "En la universidad · Redes", conf: "alta" }, { ini: "13:10", fin: "", fila: "actividad", titulo: "Almuerzo · Cafetería del campus", conf: "alta" }, { ini: "21:00", fin: "23:30", fila: "actividad", titulo: "Música y videos en casa", conf: "media" }] },
      "/p/confirmar": { reply: "Hecho, señor." } }[ruta] || { ok: true };
      setTimeout(() => Atlas._cb(id, 200, JSON.stringify(r)), ruta === "/p/chat" ? 1200 : 150); },
    grabar: () => ev("grabando"), pararGrabacion: () => { ev("oyendo"); setTimeout(() => ev("oido", { text: "¿Qué tengo mañana?" }), 900); }, cancelarGrabacion: () => {},
    decir: () => setTimeout(() => ev("callado"), 2500), callar: () => {},
    avisos: () => JSON.stringify({ activo: !!window._av, permiso: !!window._av }), avisosPoner: (si) => { window._av = si; }, avisosApps: () => {},
    version: () => JSON.stringify({ app: "demo", ui: 0, appNueva: location.hash === "#app" }), actualizar: () => {},
  };
}

// ---- pedidos al PC (firmados por la parte nativa)
let nPedido = 0;
const espera = new Map();
function pedir(metodo, ruta, cuerpo) {
  return new Promise((ok) => { const id = ++nPedido; espera.set(id, ok); Nativo.pedir(id, metodo, ruta, cuerpo ? JSON.stringify(cuerpo) : ""); });
}
const Atlas = window.Atlas = {
  _cb(id, st, texto) { const ok = espera.get(id); if (!ok) return; espera.delete(id); let j = null; try { j = JSON.parse(texto); } catch (e) { /* no era JSON */ } ok({ st, j }); },
  _evento(nombre, texto) { let d = {}; try { d = JSON.parse(texto || "{}"); } catch (e) { /* vacío */ } (EVENTOS[nombre] || (() => {}))(d); },
  _atras() { if (document.body.classList.contains("menu")) { menu(false); return true; } if (pantalla === "principal" || pantalla === "vincular") return false; ir(pantalla === "baco" || pantalla === "app" ? "apps" : "principal"); return true; },
};

// ---- pantallas
let pantalla = "";
function ir(p) {
  pantalla = p;
  document.querySelectorAll(".pant").forEach((s) => s.classList.toggle("on", s.id === "p-" + p));
  document.documentElement.style.setProperty("--c", p === "baco" ? LOGOS.baco.c : p === "app" ? (LOGOS[appAbierta] || {}).c || "#4FE3FF" : "#4FE3FF");
  if (p === "hoy") pintarHoy(); if (p === "enlace") pintarEnlace(); if (p === "baco") pintarMusica();
}
document.addEventListener("click", (e) => { const b = e.target.closest("[data-ir]"); if (b) ir(b.dataset.ir); });

// ---- logos y nombres con su letra dibujada
let uid = 0;
const unico = (svg) => { const p = "u" + (uid++) + "_"; return svg.replace(/id="([^"]+)"/g, 'id="' + p + '$1"').replace(/url\(#([^)]+)\)/g, "url(#" + p + "$1)").replace(/href="#([^"]+)"/g, 'href="#' + p + '$1"'); };
function nombre(el, k) { const up = k.toUpperCase(), g = LOGOS[k]; el.style.setProperty("--k", g.c);
  el.innerHTML = up.slice(0, g.gi) + '<span class="eg">' + unico(g.glyph) + "</span>" + up.slice(g.gi + 1); el.setAttribute("aria-label", k); }
document.querySelectorAll("[data-marca]").forEach((e) => { e.innerHTML = unico(LOGOS.marca); });
document.querySelectorAll("[data-nm]").forEach((e) => nombre(e, e.dataset.nm));
let appAbierta = "";
function pintarApps(lista) {
  const box = $("aps"); box.textContent = "";
  const tiene = new Set((lista || []).map((n) => String(n).toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "")));
  for (const k of ORDEN) { if (lista && lista.length && !tiene.has(k)) continue;
    const b = document.createElement("button"); b.className = "ap"; b.style.setProperty("--k", LOGOS[k].c);
    b.innerHTML = '<span class="lg">' + unico(LOGOS[k].logo) + '</span><span class="nm"></span>'; nombre(b.querySelector(".nm"), k);
    b.onclick = () => { if (k === "baco") return ir("baco"); appAbierta = k; nombre($("appNm"), k); ir("app"); abrirApp(k); };
    box.appendChild(b); }
}

// ---- estado de Atlas
let est = null, modo = "sinpc", ocupado = false, fallos = 0;
const ROTULO = { sinpc: "SIN CONEXIÓN CON EL PC", espera: "EN ESPERA", escuchando: "ESCUCHANDO", oyendo: "ENTENDIENDO", pensando: "PENSANDO", hablando: "HABLANDO" };
function ponModo(m, detalle) {
  modo = m; document.body.dataset.modo = m === "oyendo" ? "pensando" : m;
  $("estadoTx").textContent = detalle || ROTULO[m];
  $("pista").textContent = m === "espera" ? "TOCA LA ESFERA PARA HABLAR" : m === "escuchando" ? "TOCA PARA TERMINAR" : m === "sinpc" ? "" : "TOCA PARA DETENER";
  $("nucleo").disabled = m === "sinpc";
}
function dice(yo, atlas) {
  if (yo !== null) $("fraseYo").textContent = yo;
  if (atlas !== null) { const f = $("fraseAtlas"); f.textContent = atlas; f.classList.toggle("larga", atlas.length > 110); }
  hoja(atlas ? true : undefined);
}
function pendiente(p) { $("sino").classList.toggle("on", !!p); if (p && !$("fraseAtlas").textContent.includes(p)) dice(null, p); hoja(p ? true : undefined); }
// ---- la hoja del texto: aparece cuando hay algo que leer; arriba = abierta, abajo = solo el asa (la esfera queda libre)
function hoja(arriba) {
  const h = $("hoja"), hay = !!($("fraseYo").textContent || $("fraseAtlas").textContent) || $("sino").classList.contains("on") || $("escribir").classList.contains("on");
  h.classList.toggle("hay", hay);
  if (arriba !== undefined) h.classList.toggle("baja", !arriba);
  $("asa").setAttribute("aria-expanded", !h.classList.contains("baja"));
}
(() => {
  const h = $("hoja"); let y0 = null, dy = 0, movio = false;
  h.addEventListener("touchstart", (e) => { const enTexto = e.target.closest("#frases"), f = $("frases");
    // dentro del texto solo se arrastra la hoja si no hay nada que desplazar hacia arriba
    y0 = enTexto && f.scrollTop > 0 ? null : e.touches[0].clientY; dy = 0; movio = false; }, { passive: true });
  h.addEventListener("touchmove", (e) => { if (y0 === null) return; dy = e.touches[0].clientY - y0;
    const baja = h.classList.contains("baja"), f = $("frases");
    if (!baja && dy < 0) { if (f.scrollHeight > f.clientHeight) y0 = null; return; }   // hacia arriba y abierta: es leer, no arrastrar
    if (Math.abs(dy) < 8) return; movio = true; h.classList.add("arrastra");
    const base = baja ? h.offsetHeight - 40 : 0; h.style.transform = "translateY(" + Math.max(0, Math.min(h.offsetHeight - 40, base + dy)) + "px)"; }, { passive: true });
  const suelta = () => { h.classList.remove("arrastra"); h.style.transform = ""; if (y0 !== null && movio) { if (dy > 40) hoja(false); else if (dy < -30) hoja(true); deslizo = Date.now(); } y0 = null; };
  h.addEventListener("touchend", suelta, { passive: true }); h.addEventListener("touchcancel", suelta, { passive: true });
  $("asa").onclick = () => { if (Date.now() - deslizo < 400) return; hoja(h.classList.contains("baja")); };
})();

async function sondear() {
  if (!Nativo.vinculo() || document.hidden) return;
  const r = await pedir("GET", "/p/estado");
  if (r.st === 200 && r.j) {
    fallos = 0; est = r.j; pintarApps(est.apps);
    if (Nativo.avisosApps && Array.isArray(est.avisos_apps)) { const k = JSON.stringify(est.avisos_apps); if (k !== sondear.apps) { sondear.apps = k; Nativo.avisosApps(k); } }
    if (modo === "sinpc") { ponModo("espera"); if (!$("fraseAtlas").textContent) dice(null, saludo()); }
    if (!ocupado) pendiente(est.pendiente);
    if (modo === "pensando" && est.fase && est.fase.det) $("estadoTx").textContent = String(est.fase.det).toUpperCase().slice(0, 30);
    if (pantalla === "hoy") pintarHoy(); if (pantalla === "baco") pintarMusica();
  } else if (r.st === 401) { Nativo.desvincular(); $("vincErr").textContent = "Este celular fue desvinculado desde el PC."; ir("vincular"); }
  else if (++fallos >= 2 && !ocupado) { ponModo("sinpc"); }
}
const saludo = () => { const h = new Date().getHours(); return (h < 12 ? "Buenos días" : h < 20 ? "Buenas tardes" : "Buenas noches") + ", señor. ¿En qué puedo ayudarlo?"; };

// ---- hablar
async function enviar(texto) {
  ocupado = true; $("avisoPc").hidden = true; dice(texto, ""); pendiente(null); vista = null; $("verVista").hidden = true; ponModo("pensando");
  const r = await pedir("POST", "/p/chat", { text: texto });
  if (modo !== "pensando") { ocupado = false; return; }   // lo detuvieron mientras pensaba
  if (r.st !== 200 || !r.j) { ocupado = false; dice(null, r.st ? "Atlas tuvo un problema con ese pedido." : "No pude llegar al PC."); ponModo(r.st ? "espera" : "sinpc"); return; }
  if (r.j.detenido) { ocupado = false; ponModo("espera"); return; }
  $("avisoPc").hidden = "vista" in r.j || !/horario|evento|clase|agenda|semana|calendario/i.test(texto);
  responder(r.j.reply, r.j.pendiente, r.j.vista);
}
function responder(texto, pend, v) {
  dice(null, texto || ""); pendiente(pend); ocupado = false;
  ponVista(v && v.items && v.items.length ? v : null);
  if (texto) { ponModo("hablando"); Nativo.decir(texto); } else ponModo("espera");
}
async function confirmar(si) {
  $("sino").classList.remove("on"); Nativo.callar(); ocupado = true; ponModo("pensando");
  const r = await pedir("POST", "/p/confirmar", { accept: si });
  responder(r.j ? r.j.reply : "No pude llegar al PC.", null);
}
function detener() { Nativo.callar(); Nativo.cancelarGrabacion(); pedir("POST", "/p/detener"); ocupado = false; ponModo("espera"); }
$("nucleo").onclick = () => {
  if (Date.now() - deslizo < 500) return;   // el gesto de abrir el menú no cuenta como toque
  if (modo === "espera") { Nativo.callar(); Nativo.grabar(); }
  else if (modo === "escuchando") Nativo.pararGrabacion();
  else if (modo === "hablando") { Nativo.callar(); ponModo("espera"); }
  else if (modo === "pensando" || modo === "oyendo") detener();
};
$("btnSi").onclick = () => confirmar(true);
$("btnNo").onclick = () => confirmar(false);
// ---- menú lateral
function menu(abrir) { document.body.classList.toggle("menu", abrir); $("btnMenu").setAttribute("aria-expanded", abrir); $("menu").setAttribute("aria-hidden", !abrir); }
$("btnMenu").onclick = () => menu(true);
$("velo").onclick = () => menu(false);
document.querySelectorAll("[data-menu]").forEach((b) => { b.onclick = () => { menu(false); const d = b.dataset.menu;
  if (d === "escribir") { ir("principal"); $("escribir").classList.add("on"); hoja(true); setTimeout(() => $("msg").focus(), 250); } else ir(d); }; });
// Deslizar hacia la derecha en cualquier parte de la pantalla principal abre el menú; hacia la izquierda lo cierra.
// Se decide mientras el dedo se mueve, para que el menú salga sin esperar a soltar.
let x0 = null, y0 = 0, deslizo = 0;
document.addEventListener("touchstart", (e) => { if (e.touches.length !== 1) { x0 = null; return; } x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; }, { passive: true });
document.addEventListener("touchmove", (e) => { if (x0 === null) return;
  const dx = e.touches[0].clientX - x0, dy = e.touches[0].clientY - y0;
  if (Math.abs(dx) < 45 || Math.abs(dx) < 1.5 * Math.abs(dy)) return;
  const abierto = document.body.classList.contains("menu");
  if (dx > 0 && !abierto && pantalla === "principal") menu(true); else if (dx < 0 && abierto) menu(false); else return;
  x0 = null; deslizo = Date.now(); }, { passive: true });
document.addEventListener("touchend", () => { x0 = null; }, { passive: true });
document.addEventListener("touchcancel", () => { x0 = null; }, { passive: true });
$("escribir").onsubmit = (e) => { e.preventDefault(); const t = $("msg").value.trim(); if (!t || modo === "sinpc") return; $("msg").value = ""; $("msg").blur(); $("escribir").classList.remove("on"); hoja(); Nativo.callar(); enviar(t); };

// ---- actualizaciones: la interfaz nueva se aplica sola cuando Atlas está en reposo; la app nueva se ofrece en el menú
let recargar = false;
function hayApp(si) { $("btnApp").hidden = !si; $("btnMenu").classList.toggle("nueva", si); }
function versiones() { let v = {}; try { v = JSON.parse(Nativo.version ? Nativo.version() : "{}"); } catch (e) { /* app antigua */ }
  $("verN").textContent = v.app ? "APP " + v.app + " · PANTALLA " + (v.ui || 0) : ""; hayApp(!!v.appNueva); }
$("btnApp").onclick = () => { menu(false); dice("", "Instalando la versión nueva. Atlas se cerrará un momento; ábralo de nuevo al terminar."); Nativo.actualizar(); };
function siToca() { if (recargar && !ocupado && (modo === "espera" || modo === "sinpc")) location.reload(); }
const EVENTOS = {
  uinueva() { recargar = true; siToca(); },
  appnueva() { hayApp(true); },
  apperror() { dice(null, "No pude instalar la actualización. Puede intentarlo de nuevo desde el menú."); },
  grabando() { ocupado = true; dice("", ""); pendiente(null); ponModo("escuchando"); },
  oyendo() { ponModo("oyendo"); },
  oido(d) { if (modo !== "oyendo") { ocupado = false; return; } if (d.text) enviar(d.text); else { ocupado = false; dice("", d.error || "No le escuché, señor."); ponModo(d.sinpc ? "sinpc" : "espera"); } },
  sinpermiso() { ocupado = false; dice("", "Necesito permiso para usar el micrófono."); ponModo("espera"); },
  nada() { if (modo === "escuchando" || modo === "oyendo") { ocupado = false; ponModo("espera"); } },
  callado() { if (modo === "hablando") ponModo("espera"); },
  vinculado() { $("vincErr").textContent = ""; arrancar(); },
  vincerror(d) { $("vincErr").textContent = d.error || "No pude vincular. Pide otro código en el PC."; },
  visible() { sondear(); if (pantalla === "enlace") pintarAvisos(); },
};

// ---- CRONOS, HERMES y FORTUNA: un resumen de solo lectura que el PC calcula y manda por el Puente
const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt !== undefined) e.textContent = txt; return e; };
const plata = (n) => "$" + Math.round(Math.abs(n || 0)).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
const pct = (n) => (n > 0 ? "+" : n < 0 ? "−" : "") + Math.abs(n || 0).toFixed(1).replace(".", ",") + " %";
const fechaC = (iso) => { const p = String(iso || "").split("-").map(Number); return p.length === 3 ? p[2] + " " + MESES_V[p[1] - 1] : ""; };
const isoDe = (d) => d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
let diaCronos = null, turnoApp = 0;
function cifra(box, n, nota) { const c = el("div", "cifra"); c.append(el("small", "", "$"), plata(n).slice(1)); box.appendChild(c); if (nota) box.appendChild(nota); }
function fila(box, izq, der, sub, clsDer) { const f = el("div", "fl"), r = el("div", "r"); r.append(el("span", "", izq), el("span", clsDer || "", der)); f.appendChild(r);
  if (sub) f.appendChild(el("small", "", sub)); box.appendChild(f); return f; }
function medida(f, v, tope) { const m = el("div", "medida" + (tope && v > tope ? " pas" : "")), i = el("i"); i.style.width = Math.min(100, tope ? v / tope * 100 : 0) + "%"; m.appendChild(i); f.appendChild(m); }
async function abrirApp(k, extra) {
  const box = $("appCaja"), turno = ++turnoApp; box.style.setProperty("--k", (LOGOS[k] || {}).c || "#4FE3FF");
  if (!["cronos", "hermes", "fortuna"].includes(k)) { box.textContent = ""; box.appendChild(el("div", "vacio", (QUE[k] || "") + " Todavía no tiene pantalla en el celular.")); return; }
  if (!extra) { box.textContent = ""; box.appendChild(el("div", "vacio", "Pidiéndoselo al PC…")); }
  const r = await pedir("POST", "/p/" + k, extra || {});
  if (turno !== turnoApp || pantalla !== "app" || appAbierta !== k) return;
  box.textContent = ""; box.scrollTop = 0; const d = r.j || {};
  if (r.st === 404) return box.appendChild(el("div", "vacio", "Tu PC necesita la versión nueva del puente para mostrar " + k.charAt(0).toUpperCase() + k.slice(1) + " aquí."));
  if (r.st !== 200 || d.error) return box.appendChild(el("div", "vacio", r.st ? d.error || "Atlas no pudo leer esos datos." : "No pude llegar al PC."));
  if (d.vacio) return box.appendChild(el("div", "vacio", "Todavía no hay datos. Pídele a Atlas «actualiza " + k.charAt(0).toUpperCase() + k.slice(1) + "»."));
  ({ hermes: pintaHermes, fortuna: pintaFortuna, cronos: pintaCronos })[k](box, d);
}
function pintaHermes(box, d) {
  const n = el("div", "nota"); n.append("GASTADO · CICLO " + fechaC(d.desde) + " – " + fechaC(d.hasta) + " · QUEDAN " + d.dias_quedan + " DÍAS");
  if (d.anterior > 0) { const dif = (d.total / d.anterior - 1) * 100, b = el("b", dif > 0 ? "mal" : "", Math.abs(dif).toFixed(0) + " % " + (dif > 0 ? "MÁS" : "MENOS")); n.append(el("br"), b, " QUE EL CICLO ANTERIOR A ESTA ALTURA"); }
  cifra(box, d.total, n);
  if (d.presupuesto) { const f = el("div"); medida(f, d.total, d.presupuesto); box.appendChild(f); box.appendChild(el("div", "nota", "PRESUPUESTO " + plata(d.presupuesto) + " · ESTA SEMANA " + plata(d.semana))); }
  else box.appendChild(el("div", "nota", "ESTA SEMANA " + plata(d.semana)));
  if (d.categorias.length) box.appendChild(el("div", "dia", "EN QUÉ"));
  const tope = Math.max(1, ...d.categorias.map((c) => c.monto));
  for (const c of d.categorias) { const f = fila(box, c.nombre, plata(c.monto), c.presupuesto ? "DE " + plata(c.presupuesto) : ""); medida(f, c.monto, c.presupuesto || tope); if (!c.presupuesto) f.lastChild.classList.remove("pas"); }
  if (d.ultimos.length) box.appendChild(el("div", "dia", "ÚLTIMOS GASTOS"));
  for (const u of d.ultimos) fila(box, u.comercio || "Sin nombre", plata(u.monto), (fechaC(u.fecha) + (u.categoria ? " · " + u.categoria : "")).toUpperCase());
  box.appendChild(el("div", "nota", "DATOS HASTA EL " + fechaC(d.al))).style.margin = "18px 0";
}
function pintaFortuna(box, d) {
  if (d.mio) { const m = d.mio, n = el("div", "nota"); n.append("LO SUYO HOY · ", el("b", m.gano < 0 ? "mal" : "", (m.gano < 0 ? "PERDIÓ " : "GANÓ ") + plata(m.gano) + " (" + pct(m.pct) + ")"), el("br"), "PUESTO " + plata(m.puesto) + " · ÚLTIMOS 30 DÍAS ", el("b", m.mes < 0 ? "mal" : "", pct(m.mes_pct)));
    cifra(box, m.ahora, n); box.appendChild(el("div", "dia", "MIS FONDOS"));
    for (const p of m.posiciones) fila(box, p.nombre, plata(p.ahora), (p.adm + " · PUESTO " + plata(p.puesto) + " · " + pct(p.pct)).toUpperCase()); }
  else box.appendChild(el("div", "nota", "SIN APORTES ANOTADOS. SE ANOTAN EN FORTUNA, EN EL PC.")).style.marginTop = "18px";
  box.appendChild(el("div", "dia", "FONDOS · 30 DÍAS"));
  for (const f of d.fondos) fila(box, f.nombre, f.mes === null ? "—" : pct(f.mes), (f.adm + (f.anio === null ? "" : " · EN EL AÑO " + pct(f.anio)) + (f.mio ? " · SUYO" : "")).toUpperCase(), f.mes > 0 ? "sube" : f.mes < 0 ? "baja" : "");
  box.appendChild(el("div", "nota", "VALORES CUOTA DE LA CMF AL " + fechaC(d.al))).style.margin = "18px 0";
}
const FILA_C = { sueno: ["#8E86C9", "SUEÑO"], lugar: ["#B7A6FF", "LUGAR"], viaje: ["#FFB86B", "VIAJE"], actividad: ["#7CF0C8", "ACTIVIDAD"], quieto: ["#6B7F8C", "SIN ACTIVIDAD"], dicho: ["#4FE3FF", "LO DIJO"] };
function pintaCronos(box, d) {
  diaCronos = d.fecha; const p = d.fecha.split("-").map(Number), f = new Date(p[0], p[1] - 1, p[2]), hoy = isoDe(new Date());
  const nav = el("div", "nav"), a = el("button", "", "‹"), s = el("button", "", "›"); a.setAttribute("aria-label", "Día anterior"); s.setAttribute("aria-label", "Día siguiente");
  const mover = (n) => { const x = new Date(p[0], p[1] - 1, p[2] + n); abrirApp("cronos", { fecha: isoDe(x) }); };
  a.onclick = () => mover(-1); s.onclick = () => mover(1); s.disabled = d.fecha >= hoy;
  nav.append(a, el("span", "", (d.fecha === hoy ? "HOY · " : "") + DIAS_V[f.getDay()] + " " + p[2] + " " + MESES_V[p[1] - 1]), s); box.appendChild(nav);
  for (const b of d.bloques) { const c = FILA_C[b.fila] || ["#4FE3FF", String(b.fila || "").toUpperCase()], it = el("div", "it ev"); it.style.setProperty("--k", c[0]);
    const tm = el("time", "", b.ini || "—"); if (b.fin) tm.appendChild(el("i", "", b.fin));
    const tx = el("div", "", b.titulo); tx.appendChild(el("small", "", c[1] + (b.conf && b.conf !== "alta" ? " · NO ES SEGURO" : ""))); it.append(tm, tx); box.appendChild(it); }
  if (!d.bloques.length) box.appendChild(el("div", "vacio", "No hay nada registrado ese día."));
  if (d.parcial) box.appendChild(el("div", "nota", "FALTAN LOS VIAJES DEL CORREO: EL PC TODAVÍA LOS ESTÁ BUSCANDO.")).style.margin = "18px 0";
}

// ---- VISTA: el horario de la semana (o una lista) que Atlas manda junto con su respuesta, igual que en el PC
let vista = null, vTab = "ambos";
const COLOR = { clase: "#8FB6FF", auxiliar: "#5FF2C0", evaluacion: "#FFC93C", entrega: "#FF9F43", recordatorio: "#F2C36B", google: "#B49CFF", evento: "#4FE3FF" };
const ES_CLASE = (it) => it.tipo === "clase" || it.tipo === "auxiliar";
const DIAS_V = ["DOMINGO", "LUNES", "MARTES", "MIÉRCOLES", "JUEVES", "VIERNES", "SÁBADO"];
const MESES_V = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"];
function ponVista(v) {
  vista = v; const b = $("verVista"); b.hidden = !v;
  if (!v) { if (pantalla === "vista") ir("principal"); return; }
  const cal = v.tipo === "calendario";
  b.textContent = (cal ? "VER HORARIO" : "VER LISTA") + " ›";
  vTab = cal && ["eventos", "clases", "ambos"].includes(v.pestana) ? v.pestana : "ambos";
  pintarVista(); ir("vista");
}
function pintarVista() {
  if (!vista) return;
  const cal = vista.tipo === "calendario", box = $("vLista"); box.textContent = ""; box.scrollTop = 0;
  $("vTitulo").textContent = "‹ " + (vista.titulo || (cal ? "Horario" : "Lista")).toUpperCase().slice(0, 34);
  $("vTabs").classList.toggle("on", cal);
  document.querySelectorAll("#vTabs button").forEach((t) => t.classList.toggle("on", t.dataset.t === vTab));
  const items = vista.items.filter((it) => !cal || vTab === "ambos" || (vTab === "clases") === ES_CLASE(it))
    .slice().sort((a, b) => (a.dia || "").localeCompare(b.dia || "") || (a.hora || "").localeCompare(b.hora || ""));
  const hoy = new Date(); const hoyIso = hoy.getFullYear() + "-" + String(hoy.getMonth() + 1).padStart(2, "0") + "-" + String(hoy.getDate()).padStart(2, "0");
  let ultimo = null;
  for (const it of items) {
    if (it.dia && it.dia !== ultimo) { ultimo = it.dia; const p = it.dia.split("-").map(Number), f = new Date(p[0], p[1] - 1, p[2]);
      const d = document.createElement("div"); d.className = "dia"; d.textContent = DIAS_V[f.getDay()] + " " + p[2] + " " + MESES_V[p[1] - 1];
      if (it.dia === hoyIso) { const h = document.createElement("b"); h.textContent = "HOY"; d.appendChild(h); } box.appendChild(d); }
    const fila = document.createElement("div"); fila.className = "it ev"; fila.style.setProperty("--k", COLOR[it.tipo] || "#4FE3FF");
    const tm = document.createElement("time"); tm.textContent = it.hora || "—"; if (it.fin) { const f = document.createElement("i"); f.textContent = it.fin; tm.appendChild(f); }
    const tx = document.createElement("div"); tx.textContent = it.titulo || "";
    const sub = [it.detalle, it.lugar, !it.hora && it.dia ? "todo el día" : "", it.tipo && it.tipo !== "evento" && it.tipo !== "item" ? it.tipo : ""].filter(Boolean).join(" · ");
    if (sub) { const sm = document.createElement("small"); sm.textContent = sub.toUpperCase(); tx.appendChild(sm); }
    fila.append(tm, tx); box.appendChild(fila);
  }
  if (!items.length) { const v = document.createElement("div"); v.className = "vacio"; v.textContent = vTab === "clases" ? "Sin clases en estos días." : vTab === "eventos" ? "Sin eventos en estos días." : "Nada en estos días."; box.appendChild(v); }
}
document.querySelectorAll("#vTabs button").forEach((t) => { t.onclick = () => { vTab = t.dataset.t; pintarVista(); }; });

// ---- HOY
function pintarHoy() {
  const box = $("hoyLista"); box.textContent = "";
  if (!est) { box.innerHTML = '<div class="vacio">Sin conexión con el PC.</div>'; return; }
  const filas = (est.recordatorios || []).map((r) => ({ en: r.en, hora: r.hora, t: r.texto, s: r.tipo || "recordatorio" }))
    .concat((est.tareas || []).map((t) => ({ en: t.en, hora: t.hora || "—", t: t.texto, s: "entrega" }))).sort((a, b) => a.en - b.en);
  const DIAS = ["DOMINGO", "LUNES", "MARTES", "MIÉRCOLES", "JUEVES", "VIERNES", "SÁBADO"], hoy0 = new Date(); hoy0.setHours(0, 0, 0, 0);
  let ultimo = "";
  const fila = (cls, html) => { const d = document.createElement("div"); d.className = cls; box.appendChild(d); return d; };
  for (const f of filas) { const cuando = new Date(Date.now() + f.en * 1000), dd = Math.round((new Date(cuando).setHours(0, 0, 0, 0) - hoy0) / 864e5);
    const rot = dd <= 0 ? "HOY" : dd === 1 ? "MAÑANA" : DIAS[cuando.getDay()] + " " + cuando.getDate();
    if (rot !== ultimo) { fila("dia").textContent = rot; ultimo = rot; }
    const it = fila("it"), tm = document.createElement("time"); tm.textContent = f.hora; const tx = document.createElement("div"); tx.textContent = f.t;
    const sm = document.createElement("small"); sm.textContent = String(f.s).toUpperCase(); tx.appendChild(sm); it.append(tm, tx); }
  if ((est.pendientes || []).length) { fila("dia").textContent = "PENDIENTES"; for (const p of est.pendientes) fila("it").textContent = p.texto; }
  if (!box.children.length) fila("vacio").textContent = "Nada agendado ni pendiente.";
}

// ---- música (Baco)
function pintarMusica() {
  const m = est && est.musica;
  $("mTitulo").textContent = m ? m.titulo : "Nada suena en el PC";
  $("mArtista").textContent = m ? (m.artista || "") : "";
  $("mBarra").style.width = m && m.fin > 0 ? Math.min(100, (m.pos / m.fin) * 100) + "%" : "0";
  $("mIcono").innerHTML = m && m.estado === "Playing" ? '<path d="M7 5h4v14H7zM13 5h4v14h-4z"/>' : '<path d="M7 4v16l13-8z"/>';
}
document.querySelectorAll("[data-m]").forEach((b) => { b.onclick = async () => { await pedir("POST", "/p/musica", { accion: b.dataset.m }); setTimeout(sondear, 600); }; });

// ---- ENLACE
function pintarEnlace() {
  const box = $("enlLista"); box.textContent = ""; let v = {}; try { v = JSON.parse(Nativo.vinculo() || "{}"); } catch (e) { /* sin vínculo */ }
  const fila = (t, s, on, fut) => { const it = document.createElement("div"); it.className = "it" + (fut ? " fut" : ""); const d = document.createElement("div"); d.textContent = t;
    const sm = document.createElement("small"); sm.textContent = s; d.appendChild(sm); it.appendChild(d); if (on !== null) { const p = document.createElement("span"); p.className = "pt"; if (!on) p.style.cssText = "background:var(--mal);box-shadow:none"; it.appendChild(p); } box.appendChild(it); };
  const tailscale = /^100\.|\.ts\.net$/.test(v.host || "");
  fila(v.pc || "PC", modo === "sinpc" ? "SIN RESPUESTA" : "ATLAS " + ((est && est.version) || "") + " · " + (tailscale ? "POR TAILSCALE" : "POR WI‑FI DE CASA"), modo !== "sinpc");
  fila("Este celular", "VINCULADO", true);
  pintarAvisos();
  fila("Visor", "MÁS ADELANTE", null, true); fila("Cámara para las manos", "MÁS ADELANTE", null, true);
}
// ---- avisos: el celular le cuenta al PC los mensajes (WhatsApp, Telegram y las apps que pida el PC) y las llamadas
function pintarAvisos() {
  if (!Nativo.avisos) return; let a = {}; try { a = JSON.parse(Nativo.avisos()); } catch (e) { return; }
  $("avisosCaja").hidden = false; const b = $("btnAvisos"), falta = a.activo && !a.permiso;
  b.classList.toggle("on", a.activo && a.permiso); b.dataset.activo = a.activo ? "1" : "";
  b.textContent = falta ? "FALTA EL PERMISO · TOCA PARA DARLO" : a.activo ? "AVISOS AL PC: ACTIVADOS" : "AVISAR AL PC DE MENSAJES Y LLAMADAS";
  $("avisosTx").textContent = falta ? "En la pantalla de Android, activa «Atlas: avisos al PC». Si aparece bloqueado, entra a Ajustes › Apps › Atlas › ⋮ › Permitir ajustes restringidos."
    : a.activo ? "Atlas en tu PC se entera de tus mensajes de WhatsApp y Telegram y de tus llamadas. Toca para apagarlo."
    : "Apagado. Si lo activas, este celular le envía a tu PC, y solo a tu PC, quién te escribe o llama y un resumen corto.";
}
$("btnAvisos").onclick = () => { const b = $("btnAvisos"); let a = {}; try { a = JSON.parse(Nativo.avisos()); } catch (e) { /* nada */ }
  Nativo.avisosPoner(!(a.activo && a.permiso)); setTimeout(pintarAvisos, 300); };
document.addEventListener("visibilitychange", () => { if (!document.hidden && pantalla === "enlace") pintarAvisos(); });
$("btnDesv").onclick = () => { const b = $("btnDesv"); if (b.dataset.seguro) { Nativo.desvincular(); delete b.dataset.seguro; b.textContent = "DESVINCULAR ESTE CELULAR"; est = null; ir("vincular"); }
  else { b.dataset.seguro = "1"; b.textContent = "¿SEGURO? TOCA OTRA VEZ"; setTimeout(() => { delete b.dataset.seguro; b.textContent = "DESVINCULAR ESTE CELULAR"; }, 4000); } };
$("btnEscanear").onclick = () => { $("vincErr").textContent = ""; Nativo.escanear(); };

// ---- cielo
(function cielo() { const c = $("cielo"), w = c.width = innerWidth * 2, h = c.height = innerHeight * 2, x = c.getContext("2d"); let s = 7;
  const r = () => (s = (s * 16807) % 2147483647) / 2147483647;
  for (let i = 0; i < 70; i++) { const p = r(); x.fillStyle = "rgba(190,235,255," + (.2 + p * .5) + ")"; x.beginPath(); x.arc(r() * w, r() * h, .8 + p * 1.6, 0, 7); x.fill(); } })();

// ---- arranque
function arrancar() {
  if (!Nativo.vinculo()) { ir("vincular"); return; }
  pintarApps(null); ponModo("sinpc", "BUSCANDO EL PC"); ir("principal"); sondear();
}
setInterval(sondear, 2500);
document.addEventListener("visibilitychange", () => { if (!document.hidden) sondear(); });
arrancar();
if (location.hash === "#menu") setTimeout(() => menu(true), 600);
if (location.hash === "#vista") setTimeout(() => enviar("mi horario"), 600);   // solo para ver la pantalla en un navegador
versiones(); setInterval(siToca, 3000);
if (/^#(cronos|hermes|fortuna)$/.test(location.hash)) setTimeout(() => { appAbierta = location.hash.slice(1); nombre($("appNm"), appAbierta); ir("app"); abrirApp(appAbierta); }, 700);
