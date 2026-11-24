"use strict";
// Las animaciones de entrada de cada app: las mismas del HUD del PC (copiadas de hud.html; si cambian allá, se copian acá).
// Cada una mueve las piezas del logo de la app, que es el mismo dibujo de logos.js.
const INTRO_FX = (() => {
  const cl = (x) => Math.max(0, Math.min(1, x)), seg = (t, a, b) => cl((t - a) / (b - a));
  const out = (x) => 1 - Math.pow(1 - x, 3), io = (x) => x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
  const back = (x) => 1 + 2.70158 * Math.pow(x - 1, 3) + 1.70158 * Math.pow(x - 1, 2);
  const pop = (x) => x <= 0 ? 0 : x < .7 ? 1.5 * out(x / .7) : 1.5 - .5 * out((x - .7) / .3);
  const tf = (el, s) => el.setAttribute("transform", s);
  const at = (el, s) => `translate(${el.getAttribute("cx")} ${el.getAttribute("cy")}) scale(${s}) translate(${-el.getAttribute("cx")} ${-el.getAttribute("cy")})`;
  const draw = (el, p) => {   // dibuja un trazo de 0 a 1
    el.setAttribute("pathLength", 1);
    if (p <= 1e-3) { el.style.opacity = 0; return; }
    el.style.opacity = ""; el.style.strokeDasharray = p >= 1 ? "" : `${p} 2`;
  };
  // separa un trazo con varios subcaminos («M… M…») en trazos sueltos, en el mismo lugar
  const split = (el, ds) => { const r = ds.map((d) => { const c = el.cloneNode(); c.setAttribute("d", d); el.before(c); return c; }); el.remove(); return r; };
  return { cl, seg, out, io, back, pop, tf, at, draw, split };
})();

// Cronos «Órbita»: un cometa recorre la órbita del día dejando los puntos, las marcas salen desde el centro,
// se cierran los arcos, aparecen las agujas y queda el logo con el nombre.
function introCronos({ svg, els, mk, color }) {
  const { seg, out, io, back, pop, tf, at, draw } = INTRO_FX;
  // piezas del logo C7: 3 arcos, 12 marcas, 48 marcas finas, agujas, centro, órbita y 4 puntos
  const arcs = els.slice(0, 3), major = els.slice(3, 15), minor = els.slice(15, 63), center = els[64], orb = els[65], dots = els.slice(66, 70);
  els[63].remove();
  const hl = mk("path", { d: "M256 256 V168", stroke: "currentColor", "stroke-width": 18, "stroke-linecap": "round", fill: "none" });
  const hs = mk("path", { d: "M256 256 L314 286", stroke: "currentColor", "stroke-width": 18, "stroke-linecap": "round", fill: "none" });
  svg.appendChild(center);
  const flash = mk("circle", { cx: 256, cy: 256, r: 200, fill: "none", stroke: "currentColor", "stroke-width": 6, opacity: 0 });
  const comet = mk("circle", { cx: 0, cy: 0, r: 16, fill: "#fff", opacity: 0 });
  comet.style.filter = `drop-shadow(0 0 12px ${color})`;
  const L = orb.getTotalLength();
  const dotF = dots.map((d) => {   // en qué punto del recorrido queda cada punto
    const cx = +d.getAttribute("cx"), cy = +d.getAttribute("cy"); let best = 0, bd = 1e9;
    for (let i = 0; i <= 200; i++) { const p = orb.getPointAtLength(L * i / 200), dd = (p.x - cx) ** 2 + (p.y - cy) ** 2; if (dd < bd) { bd = dd; best = i / 200; } }
    return best;
  });
  return { nombre: [880, 1200], frame: (t) => {
    const k = io(seg(t, 140, 620));
    draw(orb, k);
    const p = orb.getPointAtLength(L * Math.max(.001, k));
    comet.setAttribute("cx", p.x); comet.setAttribute("cy", p.y); comet.setAttribute("r", 12 + 6 * Math.sin(t / 30));
    comet.style.opacity = k > 0 && k < 1 ? .95 : k >= 1 ? 1 - seg(t, 620, 720) : 0;
    dots.forEach((d, i) => tf(d, at(d, pop(seg(t, 120 + 480 * io(dotF[i]), 360 + 480 * dotF[i])))));
    major.forEach((el, i) => { el.style.opacity = seg(t, 420 + i * 12, 520 + i * 12); tf(el, `translate(256 256) scale(${.5 + .5 * back(seg(t, 420 + i * 12, 700 + i * 12))}) translate(-256 -256)`); });
    minor.forEach((el, i) => { const q = out(seg(t, 520 + i * 3, 760 + i * 3)); el.style.opacity = .35 * q; tf(el, `translate(256 256) scale(${.6 + .4 * q}) translate(-256 -256)`); });
    arcs.forEach((el, i) => draw(el, io(seg(t, 480 + i * 50, 900 + i * 50))));
    const s = back(seg(t, 640, 960)), r = out(seg(t, 640, 1000));
    hl.style.opacity = hs.style.opacity = seg(t, 640, 700);
    tf(hl, `translate(256 256) scale(${s}) rotate(${-90 * (1 - r)}) translate(-256 -256)`);
    tf(hs, `translate(256 256) scale(${s}) rotate(${-140 * (1 - r)}) translate(-256 -256)`);
    tf(center, at(center, pop(seg(t, 600, 840))));
    const f = seg(t, 960, 1300);
    flash.style.opacity = f > 0 && f < 1 ? .6 * (1 - f) : 0; flash.setAttribute("r", 200 + 60 * out(f)); flash.setAttribute("stroke-width", 8 * (1 - f) + 1);
  } };
}

// Entradas elegidas (18-11-2026): Hermes «Vuelo», Fortuna «Giro»
function introHermes1({ svg, els, mk }) {   // «Vuelo» con barras de gasto: la vara sube, las serpientes se enroscan y las alas se abren con dos aleteos
  const { seg, out, io, back, tf, draw, pop, at } = INTRO_FX;
  const [a1, a2, a3, vara, pomo, alaI, alaD, sA, sB, cA, cB] = els, arcs = [a1, a2, a3];
  const brillo = mk("circle", { cx: 256, cy: 404, r: 10, fill: "#fff", opacity: 0 });
  // barras de gasto por categoría (idea C, 18-11-2026): crecen detrás del caduceo y se van al abrir las alas
  const NSb = "http://www.w3.org/2000/svg", nb = (padre, tag, a) => { const e = document.createElementNS(NSb, tag); for (const k in a) e.setAttribute(k, a[k]); padre.appendChild(e); return e; };
  const gb = nb(svg, "g", {}); svg.insertBefore(gb, vara);
  const barras = [120, 190, 90, 150, 60, 110].map((h, i) => ({ r: nb(gb, "rect", { x: 128 + i * 44, y: 380, width: 30, height: 0, rx: 4, fill: "currentColor", "fill-opacity": .35 }), h, t0: 160 + i * 60 }));
  const piso = nb(gb, "path", { d: "M116 384 H396", stroke: "currentColor", "stroke-opacity": .5, "stroke-width": 4, "stroke-linecap": "round", pathLength: 1 });
  return { nombre: [900, 1220], frame: (t) => {
    piso.style.strokeDasharray = `${out(seg(t, 100, 360)).toFixed(3)} 2`;
    barras.forEach(({ r, h, t0 }) => { const k = Math.max(0, back(seg(t, t0, t0 + 380))) * h; r.setAttribute("y", (380 - k).toFixed(1)); r.setAttribute("height", k.toFixed(1)); });
    gb.setAttribute("opacity", (1 - seg(t, 900, 1120)).toFixed(3));
    draw(vara, io(seg(t, 120, 420)));                               // la vara sube desde abajo
    vara.setAttribute("d", "M256 404 V168");
    const b = seg(t, 120, 420); brillo.style.opacity = b > 0 && b < 1 ? 1 : (t >= 420 && t < 560 ? 1 - seg(t, 420, 560) : 0);
    brillo.setAttribute("cy", 404 - 236 * io(b)); brillo.setAttribute("r", 8 + 10 * seg(t, 420, 520));
    pomo.style.opacity = t < 400 ? 0 : 1; tf(pomo, at(pomo, pop(seg(t, 400, 620))));
    [sA, sB].forEach((s) => { s.setAttribute("d", s.getAttribute("d")); draw(s, out(seg(t, 300, 820))); });   // se enroscan subiendo
    [cA, cB].forEach((c) => { c.style.opacity = t < 780 ? 0 : 1; tf(c, at(c, pop(seg(t, 780, 960)))); });
    // alas: plegadas (escala 0 en x) → se abren con rebote y dan dos aleteos que se apagan
    const q = seg(t, 560, 860), fl = t > 860 ? .14 * Math.exp(-(t - 860) / 220) * Math.sin((t - 860) / 1000 * 2 * Math.PI * 4) : 0;
    const sx = Math.max(0, back(q)) * (1 - fl), sy = 1 - fl * .6;
    alaI.style.opacity = alaD.style.opacity = t < 560 ? 0 : 1;
    tf(alaI, `translate(246 176) scale(${sx} ${sy}) translate(-246 -176)`); tf(alaD, `translate(266 176) scale(${sx} ${sy}) translate(-266 -176)`);
    arcs.forEach((el, i) => draw(el, io(seg(t, 260 + i * 70, 760 + i * 70))));
  } };
}
function introFortuna1({ svg, els, mk }) {   // «Giro»: la rueda entra girando rápido y frena; al detenerse da media vuelta de canto y queda una moneda (18-11-2026)
  const { seg, out, io, tf, draw, back } = INTRO_FX;
  const arcs = els.slice(0, 3), rueda = els.slice(3);
  const NS = "http://www.w3.org/2000/svg", nuevo = (padre, tag, a) => { const e = document.createElementNS(NS, tag); for (const k in a) e.setAttribute(k, a[k]); padre.appendChild(e); return e; };
  const g = nuevo(svg, "g", {}); rueda.forEach((e) => g.appendChild(e));
  // la moneda: disco del color de Fortuna, canto con estrías, aro interior y «$» calado
  const moneda = nuevo(svg, "g", { opacity: 0 });
  const cid = "mc" + Math.random().toString(36).slice(2);
  nuevo(nuevo(nuevo(svg, "defs", {}), "clipPath", { id: cid }), "circle", { cx: 256, cy: 256, r: 124 });
  nuevo(moneda, "circle", { cx: 256, cy: 256, r: 124, fill: "currentColor" });
  for (let k = 0; k < 48; k++) { const a = k / 48 * 2 * Math.PI, c = Math.cos(a), si = Math.sin(a);
    nuevo(moneda, "path", { d: `M${(256 + 112 * c).toFixed(1)} ${(256 + 112 * si).toFixed(1)} L${(256 + 122 * c).toFixed(1)} ${(256 + 122 * si).toFixed(1)}`, stroke: "#01040A", "stroke-opacity": .45, "stroke-width": 4 }); }
  nuevo(moneda, "circle", { cx: 256, cy: 256, r: 98, fill: "none", stroke: "#01040A", "stroke-opacity": .55, "stroke-width": 7 });
  const signo = nuevo(moneda, "text", { x: 256, y: 258, "text-anchor": "middle", "dominant-baseline": "central", fill: "#01040A", "fill-opacity": .78,
    style: 'font:700 150px "Bahnschrift","Segoe UI",sans-serif' }); signo.textContent = "$";
  const brillo = nuevo(nuevo(moneda, "g", { "clip-path": `url(#${cid})` }), "rect", { x: 0, y: 80, width: 46, height: 352, fill: "#fff", opacity: .55, transform: "skewX(-20)" });
  const destello = mk("circle", { cx: 256, cy: 256, r: 30, fill: "#fff", opacity: 0 });
  const ancho = (el, sx) => tf(el, `translate(256 256) scale(${sx.toFixed(4)} 1) translate(-256 -256)`);
  return { nombre: [900, 1220], frame: (t) => {
    const p = seg(t, 120, 820), ang = -720 * Math.pow(1 - p, 3);
    const s = .35 + .65 * out(seg(t, 120, 520));
    g.style.opacity = out(seg(t, 120, 300)) * (t < 940 ? 1 : 0);
    // media vuelta de canto: la rueda se angosta hasta ser una línea (840–940) y del otro lado sale la moneda (940–1060)
    const v1 = io(seg(t, 840, 940)), v2 = Math.max(0, back(seg(t, 940, 1080)));
    tf(g, `translate(256 256) scale(${(s * (1 - v1) + .001).toFixed(4)} ${s}) rotate(${ang}) translate(-256 -256)`);
    moneda.setAttribute("opacity", t < 940 ? 0 : 1); ancho(moneda, v2 + .001);
    const b = seg(t, 1080, 1280); brillo.setAttribute("x", (90 + 360 * io(b)).toFixed(1)); brillo.setAttribute("opacity", (b > 0 && b < 1 ? .55 * Math.sin(Math.PI * b) : 0).toFixed(3));
    const d = seg(t, 1040, 1240); destello.style.opacity = d > 0 && d < 1 ? .45 * (1 - d) : 0; destello.setAttribute("r", 60 + 120 * out(d));
    arcs.forEach((el, i) => draw(el, io(seg(t, 300 + i * 70, 820 + i * 70))));
  } };
}
// Entradas elegidas (18-11-2026): Baco «Telón» (B3) y Atenea «Despierta» (A1)
const INTRO_BA = (() => {   // piezas que comparten las dos (curvas propias de las propuestas B3/A1)
  const { out, io } = INTRO_FX, NS = "http://www.w3.org/2000/svg";
  const pop = (x) => x <= 0 ? 0 : x < .6 ? 1.18 * out(x / .6) : 1.18 - .18 * io((x - .6) / .4);
  const back = (x) => 1 + 2.9 * Math.pow(x - 1, 3) + 1.9 * Math.pow(x - 1, 2);
  const sc = (cx, cy, sx, sy = sx) => `translate(${cx} ${cy}) scale(${sx.toFixed(4)} ${sy.toFixed(4)}) translate(${-cx} ${-cy})`;
  const op = (e, v) => e.setAttribute("opacity", Math.max(0, Math.min(1, v)).toFixed(3));
  const nuevo = (padre, tag, at, antes) => { const e = document.createElementNS(NS, tag); for (const k in at) e.setAttribute(k, at[k]); padre.insertBefore(e, antes || null); return e; };
  const uid = (p) => p + Math.random().toString(36).slice(2);
  return { pop, back, sc, op, nuevo, uid };
})();
function introBaco1({ svg, els }) {   // «Telón»: el telón se abre a los lados, un foco ilumina el cuerno, se enciende el «play» y el foco se apaga del todo
  const { seg, out, io, tf } = INTRO_FX, { pop, sc, op, nuevo, uid } = INTRO_BA;
  const arcs = els.slice(0, 3), g = els[3], ps = [...g.querySelectorAll("path")], tri = ps[49];
  const todo = nuevo(g, "g", {}); ps.slice(0, 49).forEach((e) => todo.appendChild(e));   // cuerno: 48 tramos y el borde de la boca
  const play = nuevo(todo, "g", {}); play.appendChild(tri);
  const defs = nuevo(svg, "defs", {}, svg.firstChild);
  const cp = nuevo(defs, "clipPath", { id: uid("tc") }); nuevo(cp, "circle", { cx: 256, cy: 262, r: 178 });
  const rg = nuevo(defs, "radialGradient", { id: uid("fo"), cx: .5, cy: .5, r: .5 });
  nuevo(rg, "stop", { offset: 0, "stop-color": "#fff", "stop-opacity": .55 }); nuevo(rg, "stop", { offset: 1, "stop-color": "#fff", "stop-opacity": 0 });
  const foco = nuevo(svg, "circle", { cx: 256, cy: 262, r: 178, fill: `url(#${rg.id})`, opacity: 0 }, arcs[0]);
  const tel = nuevo(svg, "g", { "clip-path": `url(#${cp.id})` });
  const panel = (x0, w) => { const pg = nuevo(tel, "g", {}); nuevo(pg, "rect", { x: x0, y: 70, width: w, height: 390, style: "fill:color-mix(in srgb, currentColor 34%, #01040A)" });
    for (let i = 1; i < 6; i++) nuevo(pg, "path", { d: `M${x0 + w * i / 6} 70 V460`, stroke: "#01040A", "stroke-opacity": .55, "stroke-width": 5 }); return pg; };
  const izq = panel(76, 180), der = panel(256, 180);
  const banda = nuevo(tel, "rect", { x: 70, y: 70, width: 372, height: 34, fill: "currentColor", opacity: .55 });
  return { nombre: [900, 1220], frame: (t) => {
    const q = io(seg(t, 300, 780));
    tf(izq, `translate(${-150 * q} 0) ${sc(76, 0, 1 - .55 * q, 1)}`); tf(der, `translate(${150 * q} 0) ${sc(436, 0, 1 - .55 * q, 1)}`);
    op(tel, (t < 100 ? 0 : 1) * (1 - seg(t, 760, 980))); op(banda, .55 * (1 - seg(t, 600, 860)));
    op(foco, .9 * out(seg(t, 420, 760)) * (1 - io(seg(t, 860, 1220))));   // al final el foco queda en 0: sin luz de fondo
    tf(todo, sc(70, 70, .9 + .1 * out(seg(t, 380, 820))));
    op(play, t < 760 ? 0 : 1); tf(play, sc(69, 70, pop(seg(t, 760, 960))));
    arcs.forEach((e, i) => { const r = out(seg(t, 640 + i * 60, 1080 + i * 60)); op(e, r); tf(e, `rotate(${(-100 * (1 - r)).toFixed(2)} 256 256)`); });
  } };
}
function introAtenea1({ svg, els }) {   // «Despierta»: el libro se abre desde el lomo, la lechuza asoma con los ojos cerrados, los abre, parpadea y le brilla la mirada
  const { seg, out, io, tf, draw } = INTRO_FX, { back, sc, op, nuevo, uid } = INTRO_BA;
  const arcs = els.slice(0, 3), g = els[3], libro = g.children[0], inn = g.children[1];
  const cs = [...inn.querySelectorAll("circle")];
  const ojos = nuevo(inn, "g", {}, cs[0]); cs.forEach((c) => ojos.appendChild(c));
  const cp = nuevo(nuevo(svg, "defs", {}, svg.firstChild), "clipPath", { id: uid("lc") }); nuevo(cp, "rect", { x: -20, y: -90, width: 160, height: 113.6 });
  const lech = nuevo(nuevo(g, "g", { "clip-path": `url(#${cp.id})` }), "g", {}); lech.appendChild(inn);   // asoma por detrás de las páginas
  const AX = (x) => 256 + 1.75 * (x - 60), AY = (y) => 262 + 1.75 * (y + 1.5), bx = AX(60 + 1.7 * 9) + 8, by = AY(20 + 1.7 * -20) - 8;
  const br = nuevo(svg, "path", { d: `M${bx} ${by - 14} L${bx + 3} ${by - 3} L${bx + 14} ${by} L${bx + 3} ${by + 3} L${bx} ${by + 14} L${bx - 3} ${by + 3} L${bx - 14} ${by} L${bx - 3} ${by - 3} Z`, fill: "#fff", opacity: 0 });
  return { nombre: [900, 1220], frame: (t) => {
    op(libro, t < 120 ? 0 : 1); tf(libro, sc(60, 0, Math.max(0, back(seg(t, 120, 480))), 1));
    const r = out(seg(t, 380, 740)); tf(lech, `translate(0 ${(78 * (1 - r)).toFixed(2)})`); op(lech, t < 380 ? 0 : 1);
    const abre = out(seg(t, 860, 960)), parp = t > 1080 && t < 1180 ? 1 - Math.sin(Math.PI * seg(t, 1080, 1180)) : 1;
    tf(ojos, sc(60, 4, 1, Math.max(.08, abre * parp)));
    const b = seg(t, 960, 1240); op(br, b > 0 && b < 1 ? Math.sin(Math.PI * b) : 0);
    tf(br, `rotate(${(90 * b).toFixed(1)} ${bx} ${by}) ${sc(bx, by, .4 + .8 * Math.sin(Math.PI * b))}`);
    arcs.forEach((e, i) => draw(e, io(seg(t, 300 + i * 70, 820 + i * 70))));
  } };
}
const INTRO_APPS = { cronos: introCronos, hermes: introHermes1, fortuna: introFortuna1, baco: introBaco1, atenea: introAtenea1 };

// En el celular la entrada cubre la pantalla, se abre desde el centro y se desvanece sobre la app ya abierta.
function playAppIntro(k) {
  const build = INTRO_APPS[k], look = LOGOS[k];
  if (!build || !look) return;
  if (window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const old = document.getElementById("appIntro"); if (old) old.remove();
  const NS = "http://www.w3.org/2000/svg";
  const o = document.createElement("div"); o.id = "appIntro"; o.setAttribute("aria-hidden", "true"); o.style.setProperty("--c", look.c);
  const svg = document.createElementNS(NS, "svg"); svg.setAttribute("viewBox", "0 0 512 512"); svg.setAttribute("class", "ilogo");
  const src = new DOMParser().parseFromString(look.logo, "image/svg+xml").documentElement;
  const els = [...src.children].map((c) => svg.appendChild(document.importNode(c, true)));
  const nm = document.createElement("div"); nm.className = "inm"; nombre(nm, k);
  o.append(svg, nm); document.body.appendChild(o);
  const mk = (tag, at) => { const e = document.createElementNS(NS, tag); for (const a in at) e.setAttribute(a, at[a]); svg.appendChild(e); return e; };
  const { seg, out } = INTRO_FX;
  let anim; try { anim = build({ svg, els, mk, color: look.c }); } catch (e) { o.remove(); return; }
  const [n0, n1] = anim.nombre;
  const frame = (t) => {
    o.style.clipPath = `circle(${(out(seg(t, 0, 260)) * 150).toFixed(2)}% at 50% 50%)`;
    o.style.opacity = 1 - seg(t, 1300, 1460);
    anim.frame(t);
    const n = out(seg(t, n0, n1));
    nm.style.opacity = n; nm.style.transform = `translateY(${(1 - n) * 10}px)`; nm.style.letterSpacing = `${.6 - .3 * n}em`;
  };
  const t0 = performance.now();
  const tick = (now) => { const t = now - t0; if (!o.isConnected) return; if (t >= 1460) { o.remove(); return; } try { frame(t); } catch (e) { o.remove(); return; } requestAnimationFrame(tick); };
  frame(0); requestAnimationFrame(tick);
}
