// Atlas Móvil: la pantalla. Todo lo de red, llaves, micrófono y parlante lo hace la parte nativa (window.Nativo);
// esta página no tiene acceso a internet ni guarda secretos.
"use strict";
const $ = (id) => document.getElementById(id);
const ORDEN = ["cronos", "hermes", "fortuna", "baco", "atenea"];
const QUE = { baco: "Baco es tu música: lo que suena en el PC.", cronos: "Cronos guarda tu historia día por día.", hermes: "Hermes lleva tus gastos.", fortuna: "Fortuna sigue tus fondos mutuos.",
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
      "/p/hermes": { ciclos: [["abr", 352000], ["may", 418000], ["jun", 301500], ["jul", 466200], ["ago", 389000], ["sep", 342700], ["oct", 431000], ["nov", 384200]].map(([mes, total], i) => ({ mes, total, actual: i === 7 })), desde: "2026-10-24", hasta: "2026-11-23", total: 384200, anterior: 431000, dias_quedan: 0, presupuesto: 500000, semana: 41300, al: "2026-11-22",
        categorias: [{ nombre: "Comida", monto: 152300, presupuesto: 180000 }, { nombre: "Transporte", monto: 88400, presupuesto: 60000 }, { nombre: "Salidas", monto: 74500, presupuesto: null }, { nombre: "Suscripciones", monto: 69000, presupuesto: null }],
        ultimos: [{ fecha: "2026-11-22", comercio: "Supermercado Uno", monto: 23490, categoria: "Comida" }, { fecha: "2026-11-21", comercio: "Uber", monto: 6200, categoria: "Transporte" }, { fecha: "2026-11-20", comercio: "Cafetería del campus", monto: 3100, categoria: "Comida" }] },
      "/p/fortuna": { al: "2026-11-20", mio: { puesto: 1500000, ahora: 1583400, gano: 83400, pct: 5.56, mes: 12300, mes_pct: 0.78, posiciones: [{ nombre: "Fondo Moderado", adm: "BCI", puesto: 1000000, ahora: 1061200, pct: 6.12 }, { nombre: "Fondo Acciones USA", adm: "Scotia", puesto: 500000, ahora: 522200, pct: 4.44 }] },
        fondos: [{ nombre: "Fondo Moderado", adm: "BCI", mes: 0.8, anio: 6.4, mio: true, curva: [100, 100.2, 100.1, 100.5, 100.9, 100.7, 101.2, 101.6, 101.4, 102.1] }, { nombre: "Fondo Acciones USA", adm: "Scotia", mes: -1.2, anio: 11.9, mio: true, curva: [100, 101.5, 102.8, 102.1, 103.6, 102.2, 101.1, 101.9, 100.4, 99.8] }, { nombre: "Fondo Liquidez", adm: "Scotia", mes: 0.4, anio: 4.1, mio: false, curva: [100, 100.1, 100.2, 100.3, 100.4, 100.5, 100.6, 100.7, 100.8, 100.9] }] },
      "/p/cronos": { fecha: (() => { try { return JSON.parse(cuerpo).fecha; } catch (e) { return null; } })() || new Date().toISOString().slice(0, 10), parcial: false, bloques: [{ ini: "00:40", fin: "08:05", fila: "sueno", titulo: "Durmiendo", conf: "media" }, { ini: "08:05", fin: "08:50", fila: "lugar", titulo: "En su casa", conf: "alta", lugar: "casa" }, { ini: "08:50", fin: "09:25", fila: "viaje", titulo: "Metro a la universidad", conf: "alta" },
        { ini: "09:25", fin: "17:40", fila: "lugar", titulo: "En la U", conf: "alta", lugar: "U" }, { ini: "10:15", fin: "11:45", fila: "actividad", titulo: "Clase de Redes", conf: "alta" }, { ini: "13:10", fin: "13:50", fila: "actividad", titulo: "Almuerzo · Cafetería del campus", conf: "alta" },
        { ini: "17:40", fin: "18:20", fila: "viaje", titulo: "Vuelta a casa", conf: "media" }, { ini: "18:20", fin: "23:59", fila: "lugar", titulo: "En su casa", conf: "media", lugar: "casa" }, { ini: "21:00", fin: "23:30", fila: "actividad", titulo: "Música y videos", conf: "baja" }] },
      "/p/confirmar": { reply: "Hecho, señor." } }[ruta] || { ok: true };
      setTimeout(() => Atlas._cb(id, 200, JSON.stringify(r)), ruta === "/p/chat" ? 1200 : 150); },
    grabar: () => ev("grabando"), pararGrabacion: () => { ev("oyendo"); setTimeout(() => ev("oido", { text: "¿Qué tengo mañana?" }), 900); }, cancelarGrabacion: () => {},
    decir: () => setTimeout(() => ev("callado"), 2500), callar: () => {},
    avisos: () => JSON.stringify({ activo: !!window._av, permiso: !!window._av }), avisosPoner: (si) => { window._av = si; }, avisosApps: () => {},
    version: () => JSON.stringify({ app: "demo", ui: 0, appNueva: location.hash === "#app" }), actualizar: () => {}, buscar: () => setTimeout(() => Atlas._evento("buscado", JSON.stringify({ motivo: "ESTÁ AL DÍA" })), 600),
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
  _atras() { if (document.body.classList.contains("menu")) { menu(false); return true; } if (pantalla === "principal" || pantalla === "vincular") return false; if (pantalla === "app" && appAbierta === "cronos" && diaCronos) { abrirApp("cronos"); return true; }   // de un día se vuelve al calendario
    ir(pantalla === "baco" || pantalla === "app" ? "apps" : "principal"); return true; },
};

// ---- pantallas
let pantalla = "";
function ir(p) {
  pantalla = p;
  document.querySelectorAll(".pant").forEach((s) => s.classList.toggle("on", s.id === "p-" + p));
  document.documentElement.style.setProperty("--c", p === "baco" ? LOGOS.baco.c : p === "app" ? (LOGOS[appAbierta] || {}).c || "#4FE3FF" : "#4FE3FF");
  if (p === "hoy") pintarHoy(); if (p === "apps") requestAnimationFrame(centrarApps); if (p === "enlace") pintarEnlace(); if (p === "baco") pintarMusica();
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
// dónde va cada estrella del menú (en % del panel) y cuáles se unen
const ESTRELLAS = { apps: [50, 33], hoy: [24, 62], escribir: [76, 62], enlace: [50, 82] };
const UNIONES = [["apps", "hoy"], ["apps", "escribir"], ["hoy", "enlace"], ["escribir", "enlace"], ["hoy", "escribir"]];
// los planetas del sol «Aplicaciones»: uno por app que exista, con su color
// [radio de la órbita, tamaño, segundos por vuelta, fracción de vuelta en que parte]
const PLANETAS = [[30, 3.4, 26, .12], [42, 3.6, 44, .5], [30, 3, 26, .62], [42, 3, 44, .85], [42, 3.2, 44, .2], [30, 3, 26, .37], [42, 3, 44, .68]];
function abrirLaApp(k) { if (k === "baco") return ir("baco"); appAbierta = k; nombre($("appNm"), k); ir("app"); abrirApp(k); }
{ const lin = $("consLineas");
  for (const [a, b] of UNIONES) { const p = ESTRELLAS[a], q = ESTRELLAS[b], l = document.createElementNS("http://www.w3.org/2000/svg", "line");
    l.setAttribute("x1", p[0]); l.setAttribute("y1", p[1]); l.setAttribute("x2", q[0]); l.setAttribute("y2", q[1]); lin.appendChild(l); } }
let appsPintadas = null;
function pintarApps(lista) {
  // el PC manda la lista en cada consulta: solo se redibuja si cambió (redibujar siempre hacía parpadear los íconos)
  const clave = JSON.stringify(lista || null); if (clave === appsPintadas) return; appsPintadas = clave;
  const box = $("aps"), pts = $("apts"), mini = $("solPlanetas"), hay = []; box.textContent = ""; pts.textContent = ""; mini.textContent = "";
  const tiene = new Set((lista || []).map((n) => String(n).toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "")));
  for (const k of ORDEN) { if (lista && lista.length && !tiene.has(k)) continue;
    const b = document.createElement("button"); b.className = "ap"; b.dataset.k = k; b.style.setProperty("--k", LOGOS[k].c);
    b.innerHTML = '<span class="lg">' + unico(LOGOS[k].logo) + '</span><span class="nm"></span>'; nombre(b.querySelector(".nm"), k);
    b.onclick = () => { if (!b.classList.contains("cen")) return b.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" }); abrirLaApp(k); };
    box.appendChild(b); const p = document.createElement("i"); p.style.setProperty("--k", LOGOS[k].c); pts.appendChild(p);
    hay.push(k); }
  const ns = "http://www.w3.org/2000/svg";
  hay.forEach((k, n) => { const q = PLANETAS[n % PLANETAS.length], g = document.createElementNS(ns, "g"), c = document.createElementNS(ns, "circle");
    c.setAttribute("cx", 50); c.setAttribute("cy", 50 - q[0]); c.setAttribute("r", q[1]); c.setAttribute("fill", LOGOS[k].c);
    g.setAttribute("class", "pl"); g.style.setProperty("--d", q[2] + "s"); g.style.setProperty("--r", -(q[2] * q[3]) + "s"); g.appendChild(c); mini.appendChild(g); });
  centrarApps();
}
// la app que queda al centro del carrusel se agranda, muestra su descripción y tiñe el cielo
function centrarApps() {
  const box = $("aps"), medio = box.scrollLeft + box.clientWidth / 2; let mejor = null, dist = 1e9;
  for (const a of box.children) { const d = Math.abs(a.offsetLeft + a.offsetWidth / 2 - medio); if (d < dist) { dist = d; mejor = a; } }
  [...box.children].forEach((a, i) => { const on = a === mejor; a.classList.toggle("cen", on); if ($("apts").children[i]) $("apts").children[i].classList.toggle("on", on); });
  if (mejor && pantalla === "apps") document.documentElement.style.setProperty("--c", LOGOS[mejor.dataset.k].c);
}
$("aps").addEventListener("scroll", () => requestAnimationFrame(centrarApps), { passive: true });
// tocar en cualquier parte del selector abre la app del centro (los botones y los íconos de los lados siguen haciendo lo suyo)
$("p-apps").addEventListener("click", (e) => { if (e.target.closest("button")) return; const c = document.querySelector("#aps .ap.cen"); if (c) abrirLaApp(c.dataset.k); });
function pintarMenu() {
  const n = est ? (est.recordatorios || []).length + (est.tareas || []).length : 0;
  $("mHoy").textContent = n ? n + (n === 1 ? " pendiente" : " pendientes") : "";
  $("mEnl").textContent = modo === "sinpc" ? "sin conexión" : (est && est.pc) || "";
}
$("menu").addEventListener("click", (e) => { if (e.target === $("menu") || e.target.closest(".cl")) menu(false); });   // tocar el cielo vacío cierra

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
function menu(abrir) { if (abrir) pintarMenu(); document.body.classList.toggle("menu", abrir); $("btnMenu").setAttribute("aria-expanded", abrir); $("menu").setAttribute("aria-hidden", !abrir); }
$("btnMenu").onclick = () => menu(true);
$("velo").onclick = () => menu(false);
document.querySelectorAll("[data-menu]").forEach((b) => { b.onclick = () => { menu(false); const d = b.dataset.menu;
  if (d === "escribir") { ir("principal"); $("escribir").classList.add("on"); hoja(true); setTimeout(() => $("msg").focus(), 250); } else ir(d); }; });
// Gestos de lado, pensados como un mapa: el menú vive a la izquierda de todo y las apps a la derecha.
//  · pantalla principal: deslizar a la derecha abre el menú.
//  · selector de apps: deslizar pasa de una app a otra; estando en la primera, seguir tirando a la derecha abre el menú.
//  · dentro de una app (o de Baco): deslizar de lado vuelve al selector de apps.
//  · Hoy, Enlace y el horario: deslizar a la derecha vuelve a la pantalla principal.
//  · con el menú abierto: deslizar a la izquierda lo cierra.
// Se decide mientras el dedo se mueve, para que responda sin esperar a soltar.
let x0 = null, y0 = 0, deslizo = 0, apsIni = 0;
document.addEventListener("touchstart", (e) => { if (e.touches.length !== 1) { x0 = null; return; } x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; apsIni = $("aps").scrollLeft; }, { passive: true });
document.addEventListener("touchmove", (e) => { if (x0 === null) return;
  const dx = e.touches[0].clientX - x0, dy = e.touches[0].clientY - y0;
  if (Math.abs(dx) < 45 || Math.abs(dx) < 1.5 * Math.abs(dy)) return;
  const abierto = document.body.classList.contains("menu");
  if (abierto) { if (dx > 0) return; $("aps").style.overflow = "hidden"; menu(false); }   // el resto del gesto no debe mover el carrusel de abajo
  else if (pantalla === "principal") { if (dx < 0) return; menu(true); }
  else if (pantalla === "apps") { if (dx < 0 || apsIni > 8) return; menu(true); }
  else if (pantalla === "app" || pantalla === "baco") ir("apps");
  else if (["hoy", "enlace", "vista"].includes(pantalla)) { if (dx < 0) return; ir("principal"); }
  else return;
  x0 = null; deslizo = Date.now(); }, { passive: true });
const sueltaLado = () => { x0 = null; if ($("aps").style.overflow) setTimeout(() => { $("aps").style.overflow = ""; }, 400); };
document.addEventListener("touchend", sueltaLado, { passive: true });
document.addEventListener("touchcancel", sueltaLado, { passive: true });
$("escribir").onsubmit = (e) => { e.preventDefault(); const t = $("msg").value.trim(); if (!t || modo === "sinpc") return; $("msg").value = ""; $("msg").blur(); $("escribir").classList.remove("on"); hoja(); Nativo.callar(); enviar(t); };

// ---- actualizaciones: la interfaz nueva se aplica sola cuando Atlas está en reposo; la app nueva se ofrece en el menú
let recargar = false;
function hayApp(si) { $("btnApp").hidden = !si; $("btnMenu").classList.toggle("nueva", si); }
// La versión de esta pantalla: al publicar se escribe aquí el número de movil/VERSION (la misma cuenta del PC).
const ATLAS_V = "@ATLAS_V@".replace(/^@.*/, "DE PRUEBA");
function versiones() { let v = {}; try { v = JSON.parse(Nativo.version ? Nativo.version() : "{}"); } catch (e) { /* app antigua */ }
  $("verN").textContent = !v.app ? "APP ANTIGUA · SIN ACTUALIZACIÓN AUTOMÁTICA" : "ATLAS " + ATLAS_V + (Nativo.buscar ? " · BUSCAR ACTUALIZACIÓN" : ""); hayApp(!!v.appNueva); }
// tocar la versión busca una actualización ahora y dice qué pasó
let tVer = 0;
$("verN").onclick = (e) => { e.stopPropagation(); if (!Nativo.buscar) return; clearTimeout(tVer); $("verN").textContent = "BUSCANDO…"; Nativo.buscar(); };
$("btnApp").onclick = () => { menu(false); dice("", "Instalando la versión nueva. Atlas se cerrará un momento; ábralo de nuevo al terminar."); Nativo.actualizar(); };
const libre = () => !ocupado && (modo === "espera" || modo === "sinpc") && !document.body.classList.contains("menu");
function siToca() { if (recargar && libre()) { recargar = false; if (Nativo.recargar) Nativo.recargar(); else location.reload(); } }
Atlas._libre = libre;
const EVENTOS = {
  uinueva() { recargar = true; siToca(); },
  appnueva() { hayApp(true); },
  buscado(d) { $("verN").textContent = (d && d.motivo) || "ESTÁ AL DÍA"; clearTimeout(tVer); tVer = setTimeout(versiones, 6000); },
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
function panel(box, titulo, sub) { const p = el("div", "panel"), h = el("h3", "", titulo); if (sub) h.appendChild(el("span", "", sub)); p.appendChild(h); box.appendChild(p); return p; }
function seg(v, tope, pasable) { const m = el("div", "seg" + (pasable && tope && v > tope ? " pas" : "")), i = el("i"); i.style.width = Math.min(100, tope ? v / tope * 100 : 0) + "%"; m.appendChild(i); return m; }
function pie(box, texto, cielo) { const p = el("div", "pie", texto); if (cielo) p.appendChild(el("em", "", cielo)); box.appendChild(p); }
async function abrirApp(k, extra) {
  const box = $("appCaja"), turno = ++turnoApp; $("p-app").dataset.app = k;
  if (!["cronos", "hermes", "fortuna"].includes(k)) { box.textContent = ""; box.appendChild(el("div", "vacio", (QUE[k] || "") + " Todavía no tiene pantalla en el celular.")); return; }
  if (k === "cronos" && !extra) return pintaCronosInicio(box);   // igual que en el PC: primero se elige el día
  if (!extra || extra.nuevo) { box.textContent = ""; box.appendChild(el("div", "vacio", "Pidiéndoselo al PC…")); }
  if (extra) extra = { fecha: extra.fecha };
  const r = await pedir("POST", "/p/" + k, extra || {});
  if (turno !== turnoApp || pantalla !== "app" || appAbierta !== k) return;
  box.textContent = ""; box.scrollTop = 0; const d = r.j || {};
  if (r.st === 404) return box.appendChild(el("div", "vacio", "Tu PC necesita la versión nueva del puente para mostrar " + k.charAt(0).toUpperCase() + k.slice(1) + " aquí."));
  if (r.st !== 200 || d.error) return box.appendChild(el("div", "vacio", r.st ? d.error || "Atlas no pudo leer esos datos." : "No pude llegar al PC."));
  if (d.vacio) return box.appendChild(el("div", "vacio", "Todavía no hay datos. Pídele a Atlas «actualiza " + k.charAt(0).toUpperCase() + k.slice(1) + "»."));
  ({ hermes: pintaHermes, fortuna: pintaFortuna, cronos: pintaCronos })[k](box, d);
}
function pintaHermes(box, d) {
  const r = panel(box, "Resumen", "CICLO " + fechaC(d.desde) + " – " + fechaC(d.hasta));
  r.appendChild(el("div", "rot", "Salió"));
  r.appendChild(el("div", "cifra", plata(d.total)));
  const tope = d.presupuesto || Math.max(d.anterior, d.total, 1), t = el("div", "tramo");
  t.append(el("span", "rot", d.presupuesto ? "Presupuesto" : "Ciclo anterior"), seg(d.total, tope, !!d.presupuesto), el("span", "num rot", plata(tope))); r.appendChild(t);
  const n = el("div", "rot"); n.style.cssText = "margin-top:12px;line-height:1.8";
  if (d.anterior > 0) { const dif = (d.total / d.anterior - 1) * 100; n.append(el("b", dif > 0 ? "mal" : "", Math.abs(dif).toFixed(0) + " % " + (dif > 0 ? "más" : "menos")), " que el ciclo anterior a esta altura", el("br")); }
  n.append("Esta semana " + plata(d.semana) + " · quedan " + d.dias_quedan + " días"); r.appendChild(n);
  if (d.ciclos && d.ciclos.some((c) => c.total > 0)) { const p = panel(box, "Últimos ciclos de la tarjeta"), bs = el("div", "barras"), ms = el("div", "meses"), mx = Math.max(1, ...d.ciclos.map((c) => c.total));
    for (const c of d.ciclos) { const col = el("div", c.actual ? "act" : ""), i = el("i"); i.style.height = Math.max(c.total ? 4 : 0, c.total / mx * 92) + "%"; col.appendChild(i); bs.appendChild(col); ms.appendChild(el("span", c.actual ? "act" : "", c.mes)); }
    p.append(bs, ms); }
  if (d.categorias.length) { const p = panel(box, "Por categoría"), mx = Math.max(1, ...d.categorias.map((c) => c.monto));
    for (const c of d.categorias) { const f = el("div", "cat"); f.append(el("span", "", c.nombre), el("span", "num", plata(c.monto)));
      if (c.presupuesto) f.appendChild(el("small", "", "DE " + plata(c.presupuesto))); f.appendChild(seg(c.monto, c.presupuesto || mx, !!c.presupuesto)); p.appendChild(f); } }
  if (d.ultimos.length) { const p = panel(box, "Movimientos", "SALIDAS");
    for (const u of d.ultimos) { const f = el("div", "mov"); f.append(el("time", "", fechaC(u.fecha)), el("span", "", u.comercio || "Sin nombre"), el("span", "num sale", "−" + plata(u.monto)));
      if (u.categoria) f.appendChild(el("small", "", u.categoria.toUpperCase())); p.appendChild(f); } }
  pie(box, "DATOS HASTA EL " + fechaC(d.al), "ARIES · EL CARNERO DE ORO");
}
let pestFortuna = "mios";
function chispa(pts, cls) { const ns = "http://www.w3.org/2000/svg", s = document.createElementNS(ns, "svg"); s.setAttribute("viewBox", "0 0 64 22"); if (!pts || pts.length < 2) return s;
  const mn = Math.min(...pts), mx = Math.max(...pts), al = mx - mn || 1, p = document.createElementNS(ns, "polyline");
  p.setAttribute("points", pts.map((v, i) => (i / (pts.length - 1) * 64).toFixed(1) + "," + (20 - (v - mn) / al * 18).toFixed(1)).join(" "));
  p.setAttribute("fill", "none"); p.setAttribute("stroke-width", "1.6"); p.setAttribute("stroke", cls === "baja" ? "var(--amal)" : cls === "sube" ? "var(--abien)" : "var(--ap)"); s.appendChild(p); return s; }
function pintaFortuna(box, d) {
  const m = d.mio, r = panel(box, "Mis inversiones", m ? "HOY" : "");
  if (m) { r.appendChild(el("div", "cifra", plata(m.ahora)));
    const n = el("div", "rot"); n.style.cssText = "margin-top:10px;line-height:1.8";
    n.append(el("b", m.gano < 0 ? "mal" : "", (m.gano < 0 ? "Perdió " : "Ganó ") + plata(m.gano) + " (" + pct(m.pct) + ")"), el("br"), "Puso " + plata(m.puesto) + " · 30 días ", el("b", m.mes < 0 ? "mal" : "", pct(m.mes_pct))); r.appendChild(n); }
  else r.appendChild(el("div", "rot", "Sin aportes anotados. Se anotan en Fortuna, en el PC."));
  if (!m && pestFortuna === "mios") pestFortuna = "todos";
  const ps = el("div", "pest"); for (const [k, t] of [["mios", "Míos"], ["todos", "Todos"]]) { const b = el("button", pestFortuna === k ? "on" : "", t); b.onclick = () => { pestFortuna = k; box.textContent = ""; pintaFortuna(box, d); }; ps.appendChild(b); } box.appendChild(ps);
  const p = panel(box, pestFortuna === "mios" ? "Lo suyo" : "Fondos", pestFortuna === "mios" ? "VALOR HOY" : "ÚLTIMOS 30 DÍAS");
  if (pestFortuna === "mios") for (const x of (m ? m.posiciones : [])) { const f = el("div", "fondo"), cu = (d.fondos.find((y) => y.nombre === x.nombre) || {}).curva;
    f.append(el("span", "", x.nombre), el("span", "num", plata(x.ahora)), el("small", "", (x.adm + " · PUSO " + plata(x.puesto) + " · " + pct(x.pct)).toUpperCase()), chispa(cu, x.pct < 0 ? "baja" : "sube")); p.appendChild(f); }
  else for (const x of d.fondos) { const c = x.mes > 0 ? "sube" : x.mes < 0 ? "baja" : "", f = el("div", "fondo");
    f.append(el("span", "", x.nombre), el("span", "num " + c, x.mes === null ? "—" : pct(x.mes)), el("small", "", (x.adm + (x.anio === null ? "" : " · EN EL AÑO " + pct(x.anio)) + (x.mio ? " · SUYO" : "")).toUpperCase()), chispa(x.curva, c)); p.appendChild(f); }
  pie(box, "VALORES CUOTA DE LA CMF AL " + fechaC(d.al) + " · SOLO INFORMATIVO", "AURIGA · CAPELLA, LA CORNUCOPIA");
}
// Cronos: el día como la esfera de 24 horas del PC (medianoche arriba). Anillo de afuera = dónde estuvo, anillo de adentro = qué hacía.
const COLOR_RELOJ = (b) => b.fila === "sueno" ? "#6F5FD0" : b.fila === "viaje" ? "#FFB86B" : b.fila === "actividad" ? "#E9A6FF"
  : b.lugar === "casa" || /su casa/i.test(b.titulo) ? "#8FD3C4" : b.lugar === "U" || /la U\b/.test(b.titulo) ? "#B7A6FF" : "#F7D488";
const TIPOS_RELOJ = [["#6F5FD0", "SUEÑO"], ["#8FD3C4", "SU CASA"], ["#B7A6FF", "LA U"], ["#F7D488", "OTRO LUGAR"], ["#FFB86B", "VIAJE"], ["#E9A6FF", "QUÉ HACÍA"]];
const minsDe = (h) => { const p = String(h || "").split(":").map(Number); return p.length === 2 && !isNaN(p[0]) ? p[0] * 60 + p[1] : NaN; };
function esferaSVG(bl) {
  const C = 256, f1 = (n) => n.toFixed(1), P = (r, m) => { const t = Math.min(m, 1439.9) / 1440 * 2 * Math.PI; return [C + r * Math.sin(t), C - r * Math.cos(t)]; };
  const arco = (r, a, b, rev) => { b = Math.max(b, a + 6); const [x0, y0] = P(r, a), [x1, y1] = P(r, b);
    return rev ? `M${f1(x1)} ${f1(y1)} A${r} ${r} 0 ${b - a > 720 ? 1 : 0} 0 ${f1(x0)} ${f1(y0)}` : `M${f1(x0)} ${f1(y0)} A${r} ${r} 0 ${b - a > 720 ? 1 : 0} 1 ${f1(x1)} ${f1(y1)}`; };
  const linea = (r0, r1, m, w, op, col = "#B7A6FF") => { const [x0, y0] = P(r0, m), [x1, y1] = P(r1, m);
    return `<line x1="${f1(x0)}" y1="${f1(y0)}" x2="${f1(x1)}" y2="${f1(y1)}" stroke="${col}" stroke-width="${w}" stroke-linecap="round" opacity="${op}"/>`; };
  let g = '<defs><filter id="esfBrillo" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="7"/></filter>'
    + '<radialGradient id="esfFondo"><stop offset="0" stop-color="#33266A" stop-opacity=".95"/><stop offset=".7" stop-color="#170F33" stop-opacity=".7"/><stop offset="1" stop-color="#0B0818" stop-opacity="0"/></radialGradient></defs>'
    + '<circle cx="256" cy="256" r="262" fill="url(#esfFondo)"/>';
  [[25, 110], [145, 215], [250, 290]].forEach(([a, b]) => { g += `<path d="${arco(250, a * 4, b * 4)}" fill="none" stroke="#B7A6FF" stroke-width="10" stroke-linecap="round" opacity=".6"/>`; });
  g += '<circle cx="256" cy="256" r="236" fill="none" stroke="#B7A6FF" stroke-opacity=".25"/>';
  let fondo = '<circle cx="256" cy="256" r="200" fill="none" stroke="#B7A6FF" stroke-opacity=".1" stroke-width="40"/><circle cx="256" cy="256" r="128" fill="none" stroke="#B7A6FF" stroke-opacity=".08" stroke-width="18"/>';
  for (let q = 0; q < 96; q++) if (q % 4) fondo += linea(163, 169, q * 15, 2, .28);
  for (let h = 0; h < 24; h++) fondo += linea(h % 2 ? 158 : 150, 171, h * 60, h % 2 ? 4 : 8, h % 2 ? .4 : .9);
  for (let h = 0; h < 24; h++) { const [x, y] = P(h % 6 ? 266 : 272, h * 60), fuerte = h % 6 === 0;
    fondo += `<text x="${f1(x)}" y="${f1(y + (fuerte ? 7 : 4))}" fill="#B7A6FF" fill-opacity="${fuerte ? 1 : .6}" font-size="${fuerte ? 21 : 12}" text-anchor="middle" font-family="monospace" font-weight="${fuerte ? 700 : 400}">${String(h).padStart(2, "0")}</text>`; }
  let brillo = "", arcos = "", textos = "", bordes = "", ult = -999; const tot = {};
  bl.forEach((b, i) => {
    const a = Math.max(0, minsDe(b.ini)), z = Math.min(1440, minsDe(b.fin || b.ini)); if (isNaN(a) || isNaN(z) || (z <= a && b.fila !== "viaje")) return;
    const dentro = b.fila === "actividad", r = dentro ? 128 : 200, w = dentro ? 18 : b.fila === "viaje" ? 26 : 40, col = COLOR_RELOJ(b), baja = b.conf === "baja";
    if (!dentro && z > a) tot[col] = (tot[col] || 0) + z - a;
    const d = dentro ? arco(r, a, z) : arco(r, a + 3, z - 3);
    brillo += `<path d="${d}" fill="none" stroke="${col}" stroke-width="${w}" opacity="${baja ? .2 : .5}" filter="url(#esfBrillo)"/>`;
    arcos += `<path class="arco" d="${d}" stroke="${col}" stroke-width="${w}" stroke-linecap="${dentro ? "round" : "butt"}" opacity="${baja ? .45 : b.conf === "media" ? .85 : 1}"${baja ? ' stroke-dasharray="5 4"' : ""}/>`;
    if (!dentro && b.fila !== "viaje" && a - ult >= 50) { ult = a; const [x, y] = P(214, a); bordes += linea(176, 224, a, 2, .9, col) + `<circle cx="${f1(x)}" cy="${f1(y)}" r="3.5" fill="${col}"/>`; }
    if (!dentro && z - a >= 100) { const medio = (a + z) / 2, abajo = medio > 360 && medio < 1080, id = "esfT" + i;
      const nom = b.fila === "sueno" ? "SUEÑO" : col === "#8FD3C4" ? "SU CASA" : col === "#B7A6FF" ? "LA U" : b.fila === "viaje" ? "VIAJE" : String(b.titulo).replace(/^En /, "").toUpperCase().slice(0, 16).replace(/[<>&"]/g, "");
      textos += `<path id="${id}" d="${arco(abajo ? 194 : 206, a, z, abajo)}" fill="none"/><text font-size="15" font-weight="700" letter-spacing="3" fill="#120C26"><textPath href="#${id}" startOffset="50%" text-anchor="middle">${nom}</textPath></text>`; } });
  const mayor = Object.entries(tot).filter((x) => x[0] !== "#6F5FD0" && x[0] !== "#FFB86B").sort((x, y) => y[1] - x[1])[0];
  const nomMayor = mayor ? (TIPOS_RELOJ.find((t) => t[0] === mayor[0]) || [])[1] : "";
  g += brillo + fondo + arcos + textos + bordes + '<circle cx="256" cy="256" r="98" fill="#0B0818" fill-opacity=".92" stroke="#B7A6FF" stroke-opacity=".35" stroke-width="1.5"/>';
  if (mayor) g += `<text x="256" y="244" text-anchor="middle" font-family="monospace" font-size="13" letter-spacing="3" fill="#A99BD8">MÁS TIEMPO EN</text><text x="256" y="276" text-anchor="middle" font-size="26" font-weight="700" letter-spacing="2" fill="${mayor[0]}">${nomMayor}</text><text x="256" y="302" text-anchor="middle" font-family="monospace" font-size="15" fill="#EEEAFF">${Math.floor(mayor[1] / 60)} h ${String(mayor[1] % 60).padStart(2, "0")}</text>`;
  else g += '<text x="256" y="262" text-anchor="middle" font-family="monospace" font-size="14" letter-spacing="3" fill="#A99BD8">SIN DATOS</text>';
  return `<svg class="esfera" viewBox="-34 -34 580 580" role="img" aria-label="Esfera de 24 horas del día">${g}</svg>`;
}
// inicio de Cronos, como en el PC: su logo, «¿Qué día quiere ver?», el calendario y los atajos
let calMes = null;
const MESES_L = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"];
function pintaCronosInicio(box) {
  diaCronos = null; box.textContent = ""; box.scrollTop = 0;
  const hoy = new Date(), ini = el("div", "cini"), lg = el("span", "clogo"), cal = el("div", "cal"), at = el("div", "atajos");
  lg.innerHTML = unico(LOGOS.cronos.logo); if (!calMes) calMes = [hoy.getFullYear(), hoy.getMonth()];
  const ver = (f) => abrirApp("cronos", { fecha: isoDe(f), nuevo: true });
  const pinta = () => { cal.textContent = ""; const [y, m] = calMes, ct = el("div", "ct"), a = el("button", "", "◂"), s = el("button", "", "▸"), g = el("div", "g");
    a.setAttribute("aria-label", "Mes anterior"); s.setAttribute("aria-label", "Mes siguiente");
    a.onclick = () => { calMes = m ? [y, m - 1] : [y - 1, 11]; pinta(); }; s.onclick = () => { calMes = m === 11 ? [y + 1, 0] : [y, m + 1]; pinta(); };
    s.disabled = y > hoy.getFullYear() || (y === hoy.getFullYear() && m >= hoy.getMonth());
    ct.append(a, el("span", "", MESES_L[m] + " " + y), s); cal.appendChild(ct);
    for (const l of "LMMJVSD") g.appendChild(el("i", "", l));
    const vacios = (new Date(y, m, 1).getDay() + 6) % 7, dias = new Date(y, m + 1, 0).getDate();
    for (let i = 0; i < vacios; i++) g.appendChild(el("span"));
    for (let n = 1; n <= dias; n++) { const f = new Date(y, m, n), b = el("button", isoDe(f) === isoDe(hoy) ? "hoy" : "", String(n)); b.disabled = f > hoy; b.onclick = () => ver(f); g.appendChild(b); }
    cal.appendChild(g); };
  pinta();
  for (const [t, n] of [["HOY", 0], ["AYER", 1], ["HACE UNA SEMANA", 7]]) { const b = el("button", "", t); b.onclick = () => ver(new Date(Date.now() - n * 864e5)); at.appendChild(b); }
  ini.append(lg, el("p", "", "¿Qué día quiere ver?"), cal, at); box.appendChild(ini);
  pie(box, "TODO QUEDA EN SU PC", "CAPRICORNIO");
}
function pintaCronos(box, d) {
  diaCronos = d.fecha; const p = d.fecha.split("-").map(Number), f = new Date(p[0], p[1] - 1, p[2]), hoy = isoDe(new Date());
  const nav = el("div", "nav"), a = el("button", "", "◂"), s = el("button", "", "▸"); a.setAttribute("aria-label", "Día anterior"); s.setAttribute("aria-label", "Día siguiente");
  const mover = (n) => { const x = new Date(p[0], p[1] - 1, p[2] + n); abrirApp("cronos", { fecha: isoDe(x) }); };
  a.onclick = () => mover(-1); s.onclick = () => mover(1); s.disabled = d.fecha >= hoy;
  const medio = el("button", "dia", (d.fecha === hoy ? "HOY · " : "") + DIAS_V[f.getDay()] + " " + p[2] + " " + MESES_V[p[1] - 1] + " ▾"); medio.setAttribute("aria-label", "Elegir otro día");
  medio.onclick = () => { calMes = [p[0], p[1] - 1]; abrirApp("cronos"); };
  nav.append(a, medio, s); box.appendChild(nav);
  const bl = d.bloques.filter((b) => b.ini && ["sueno", "lugar", "viaje", "actividad"].includes(b.fila));
  const caja = el("div"); caja.style.cssText = "display:flex;flex:none"; caja.innerHTML = esferaSVG(bl); box.appendChild(caja);   // solo números y nombres ya limpiados: nada del PC entra como HTML
  const usados = new Set(bl.map(COLOR_RELOJ)), ley = el("div", "ley");
  for (const [c, n] of TIPOS_RELOJ) if (usados.has(c)) { const s2 = el("span", ""), i = el("i"); i.style.background = c; s2.append(i, n); ley.appendChild(s2); }
  if (ley.children.length) box.appendChild(ley);
  if (d.bloques.length) { const pn = panel(box, "Mi día", d.bloques.length + " TRAMOS");
    for (const b of d.bloques) { const r = el("div", "blo"), i = el("i"); i.style.background = COLOR_RELOJ(b); const tx = el("span", "", b.titulo);
      if (b.conf && b.conf !== "alta") tx.appendChild(el("small", "", b.conf === "baja" ? "NO ES SEGURO" : "PROBABLE"));
      r.append(i, el("time", "", (b.ini || "—") + (b.fin ? "–" + b.fin : "")), tx); pn.appendChild(r); } }
  else box.appendChild(el("div", "vacio", "No hay nada registrado ese día."));
  if (d.parcial) { box.appendChild(el("div", "pie", "BUSCANDO LOS VIAJES DEL CORREO EN EL PC…"));
    // el PC sigue armando el día completo: se le vuelve a preguntar un par de veces sin borrar lo que ya se ve
    pintaCronos.n = pintaCronos.dia === d.fecha ? pintaCronos.n + 1 : 1; pintaCronos.dia = d.fecha;
    if (pintaCronos.n <= 5) setTimeout(() => { if (pantalla === "app" && appAbierta === "cronos" && diaCronos === d.fecha) abrirApp("cronos", { fecha: d.fecha }); }, 4000); }
  else pintaCronos.dia = null;
  pie(box, "TODO QUEDA EN SU PC", "CAPRICORNIO");
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
  let ap = {}; try { ap = JSON.parse(Nativo.version ? Nativo.version() : "{}"); } catch (e) { /* app antigua */ }
  fila("Este celular", "ATLAS " + ATLAS_V + (ap.app && ap.app !== ATLAS_V ? " · APP " + ap.app : "") + " · VINCULADO", true);
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
