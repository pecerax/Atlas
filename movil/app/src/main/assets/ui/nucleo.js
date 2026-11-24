"use strict";
// La esfera de Atlas: el mismo dibujo vivo del HUD del PC (globo «Eclipse» con las Pléyades), copiado de hud.html.
// En espera el borde gira lento y las estrellas titilan; al escuchar se pone verde y la estrella de Atlas late;
// al pensar, ámbar, el borde gira rápido y la constelación se dibuja; al responder, blanca. Si cambia allá, se copia acá.
(function () {
  const host = $("nucleo"); if (!host) return;
  const reduceMotion = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  const MODOS = { escuchando: "listening", oyendo: "thinking", pensando: "thinking", hablando: "speaking" };
  const ST = [[252.8, 289.8, 12.7, 30.5], [365.8, 288.2, 10, 24.1], [324.6, 239.9, 9.5, 22.8], [303, 319.6, 8.5, 20.4],
    [351.4, 221, 8.1, 19.5], [179.1, 283.8, 5.7, 13.7], [368.9, 254.8, 4.4, 10.7], [321.1, 204.4, 3.4, 8.3]];
  const LN = [[180.1, 299.6, 179.1, 283.8], [180.1, 299.6, 252.8, 289.8], [252.8, 289.8, 303, 319.6], [303, 319.6, 365.8, 288.2],
    [365.8, 288.2, 368.9, 254.8], [368.9, 254.8, 351.4, 221], [351.4, 221, 324.6, 239.9], [324.6, 239.9, 252.8, 289.8], [351.4, 221, 321.1, 204.4]];
  const COLS = { idle: ["#4FE3FF", "#9C7BFF"], speaking: ["#FFFFFF", "#CFEFFF"], listening: ["#5FF2C0", "#4FE3FF"], thinking: ["#FFB04F", "#FF6E8A"] };
  const ARC = "M324.7 98.6 A170 170 0 0 0 131.6 374.4";
  const mer = Array.from({ length: 6 }, () => '<ellipse cx="256" cy="256" rx="1" ry="170"/>').join("");
  const par = [[143.8, 127.7, 10.2], [199.9, 160.5, 12.8], [256, 170, 13.6], [312.1, 160.5, 12.8], [368.2, 127.7, 10.2]].map(([cy, rx, ry]) => `<ellipse cx="256" cy="${cy}" rx="${rx}" ry="${ry}"/>`).join("");
  host.innerHTML = `<svg viewBox="56 56 400 400"><defs>
<filter id="nu_g" x="-40%" y="-40%" width="180%" height="180%"><feGaussianBlur stdDeviation="5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
<filter id="nu_gg" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="16"/></filter>
<radialGradient id="nu_halo" cx="50%" cy="50%" r="50%"><stop offset="0" class="hc" stop-color="#4FE3FF" stop-opacity=".35"/><stop offset="1" class="hc" stop-color="#4FE3FF" stop-opacity="0"/></radialGradient>
<clipPath id="nu_c"><circle cx="256" cy="256" r="170"/></clipPath>
<radialGradient id="nu_body" cx="22%" cy="20%" r="95%"><stop offset="0" stop-color="#0E4A62"/><stop offset=".35" stop-color="#062332"/><stop offset=".75" stop-color="#030E16"/><stop offset="1" stop-color="#01060A"/></radialGradient>
<radialGradient id="nu_atm" cx="28%" cy="26%" r="70%"><stop offset="0" class="a2" stop-color="#8F7BFF" stop-opacity=".45"/><stop offset=".6" class="a2" stop-color="#8F7BFF" stop-opacity=".08"/><stop offset="1" class="a2" stop-color="#8F7BFF" stop-opacity="0"/></radialGradient>
<linearGradient id="nu_gd" gradientUnits="userSpaceOnUse" x1="325" y1="99" x2="132" y2="374"><stop offset="0" class="c1" stop-color="#4FE3FF" stop-opacity="0"/><stop offset=".22" class="c1" stop-color="#4FE3FF"/><stop offset=".5" stop-color="#FFFFFF"/><stop offset=".8" class="c2" stop-color="#9C7BFF"/><stop offset="1" class="c2" stop-color="#9C7BFF" stop-opacity="0"/></linearGradient>
</defs>
<circle cx="216" cy="216" r="210" fill="url(#nu_halo)" opacity=".45"/>
<circle cx="256" cy="256" r="170" fill="url(#nu_body)"/>
<g class="grid" clip-path="url(#nu_c)" fill="none" stroke="#4FE3FF" stroke-width="1.6" opacity=".16"><g transform="rotate(-18 256 256)">${mer}${par}</g></g>
<circle cx="256" cy="256" r="170" fill="url(#nu_atm)"/>
<g class="rim"><path d="${ARC}" fill="none" stroke="url(#nu_gd)" stroke-width="32" stroke-linecap="round" filter="url(#nu_gg)" opacity=".7"/><path d="${ARC}" fill="none" stroke="url(#nu_gd)" stroke-width="8" stroke-linecap="round" filter="url(#nu_g)"/></g>
<g class="lin" stroke="#4FE3FF" stroke-opacity=".4" stroke-width="3">${LN.map(([a, b, c, d]) => `<line x1="${a}" y1="${b}" x2="${c}" y2="${d}" pathLength="1"/>`).join("")}</g>
${ST.map(([x, y, r, h]) => `<circle class="sh" cx="${x}" cy="${y}" r="${h}" fill="url(#nu_halo)"/><circle class="sc" cx="${x}" cy="${y}" r="${r}" fill="#BFF6FF"/>`).join("")}
<circle cx="180.1" cy="299.6" r="42" fill="url(#nu_halo)"/>
<g class="ondas" fill="none" stroke-width="2">${'<circle cx="180.1" cy="299.6" r="0" opacity="0"/>'.repeat(3)}</g>
<g class="atl" filter="url(#nu_g)"><path d="M180.1 269.6 Q183.85 295.85 210.1 299.6 Q183.85 303.35 180.1 329.6 Q176.35 303.35 150.1 299.6 Q176.35 295.85 180.1 269.6 Z" fill="#E6FCFF"/></g>
</svg>`;
  const q = (sel) => Array.from(host.querySelectorAll(sel));
  const el = { c1: q("stop.c1"), c2: q("stop.c2"), hc: q("stop.hc"), a2: q("stop.a2"), grid: host.querySelector(".grid"), rim: host.querySelector(".rim"),
    lin: host.querySelector(".lin"), lines: q(".lin line"), sh: q(".sh"), sc: q(".sc"), ondas: q(".ondas circle"), atl: host.querySelector(".atl"), atlP: host.querySelector(".atl path") };
  // giro del globo (17-11-2026, elegido: «con la voz + Pléyades fijas»): giran los meridianos; las estrellas quedan quietas delante
  const mers = Array.from(host.querySelectorAll(".grid ellipse")).filter((e) => e.getAttribute("ry") === "170");
  let giro = 0, velGiro = 10;
  const hex = (h) => [1, 3, 5].map((i) => parseInt(h.substr(i, 2), 16));
  const css = (c) => "#" + c.map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");
  const lerp = (a, b, k) => a.map((v, i) => v + (b[i] - v) * k);
  let c1 = hex(COLS.idle[0]), c2 = hex(COLS.idle[1]), rot = 0, vel = 40, nivel = 0, tThink = 0, last = 0, ultMode = "";
  function paso(now) {
    requestAnimationFrame(paso);
    const dt = Math.min(0.1, (now - (last || now)) / 1000); last = now;
    if (document.hidden || pantalla !== "principal" || document.body.classList.contains("menu")) return;   // si no se ve, no se dibuja
    const mode = MODOS[modo] || "idle";
    // el celular no oye la voz del PC: al hablar, la estrella late con un pulso parecido al de una voz
    window.nucleoNivel = mode === "speaking" ? .16 + .14 * Math.sin(now / 111) * Math.sin(now / 270) : 0;
    const m = COLS[mode] ? mode : "idle", quieto = reduceMotion;
    if (m !== ultMode) { if (m === "thinking") tThink = now; ultMode = m; }
    const k = Math.min(1, dt * 5);   // los colores cambian en ~0,3 s
    c1 = lerp(c1, hex(COLS[m][0]), k); c2 = lerp(c2, hex(COLS[m][1]), k);
    const C1 = css(c1), C2 = css(c2), blanco = [255, 255, 255];
    el.c1.forEach((s) => s.setAttribute("stop-color", C1)); el.c2.forEach((s) => s.setAttribute("stop-color", C2));
    el.hc.forEach((s) => s.setAttribute("stop-color", C1)); el.a2.forEach((s) => s.setAttribute("stop-color", css(lerp(c2, hex("#8F7BFF"), .5))));
    el.grid.setAttribute("stroke", C1); el.lin.setAttribute("stroke", C1);
    // borde: gira lento; al procesar, rápido (una vuelta cada 1,1 s). Siempre del mismo grosor.
    vel += ((m === "thinking" ? 327 : 40) - vel) * Math.min(1, dt * 4);
    if (!quieto) rot = (rot + vel * dt) % 360;
    el.rim.setAttribute("transform", `rotate(${rot.toFixed(2)} 256 256)`);
    // voz de Atlas (real) suavizada
    const v = Math.min(1, (window.nucleoNivel || 0) * 2.5);
    nivel += (v - nivel) * Math.min(1, dt * 12);
    // globo: una vuelta cada 36 s en espera; más rápido al escuchar o procesar y con el volumen al hablar
    const vObj = m === "speaking" ? 10 * (1.5 + 5 * nivel) : m === "thinking" ? 40 : m === "listening" ? 16 : 10;
    velGiro += (vObj - velGiro) * Math.min(1, dt * 3);
    if (!quieto) giro = (giro + velGiro * dt) % 360;
    mers.forEach((e, i) => e.setAttribute("rx", Math.max(.5, 170 * Math.abs(Math.sin((giro + i * 30) * Math.PI / 180))).toFixed(1)));
    // estrellas
    const sCol = css(lerp(c1, blanco, .7));
    el.sc.forEach((c, i) => { const b = quieto || m !== "idle" ? 1 : .7 + .3 * Math.sin(now / 500 + i * 1.7), [, , r, h] = ST[i];
      c.setAttribute("r", (r * (.55 + .45 * b)).toFixed(2)); c.setAttribute("opacity", (.25 + .75 * b).toFixed(3)); c.setAttribute("fill", sCol);
      el.sh[i].setAttribute("r", (h * (.5 + .7 * b)).toFixed(2)); el.sh[i].setAttribute("opacity", b.toFixed(3)); });
    // constelación: al procesar se dibuja tramo a tramo, una y otra vez
    const lp = m === "thinking" && !quieto ? ((now - tThink) / 1400) % 1.25 : 1, n = el.lines.length;
    el.lines.forEach((l, i) => { const f = Math.max(0, Math.min(1, lp * n - i)); l.style.strokeDasharray = f >= 1 ? "" : `${f} 2`; l.style.opacity = f > 0 ? 1 : 0; });
    el.lin.setAttribute("stroke-opacity", m === "thinking" ? .8 : .4);
    // estrella de Atlas: late al escuchar y con la voz al hablar, y suelta ondas finas
    const habla = m === "speaking", oye = m === "listening";
    const esc = quieto ? 1 : oye ? 1 + .12 * (.5 + .5 * Math.sin(now / 260)) : habla ? 1 + .35 * nivel : 1;
    el.atl.setAttribute("transform", `translate(180.1 299.6) scale(${esc.toFixed(3)}) translate(-180.1 -299.6)`);
    el.atlP.setAttribute("fill", css(lerp(c1, blanco, .85)));
    el.ondas.forEach((o, i) => {
      if (quieto || !(oye || habla)) { o.setAttribute("opacity", 0); return; }
      const f = (now / 1100 + i / 3) % 1;
      o.setAttribute("r", (20 + 90 * f).toFixed(1)); o.setAttribute("stroke", C1);
      o.setAttribute("opacity", ((habla ? .25 + .75 * nivel : 1) * .7 * (1 - f)).toFixed(3));
    });
  }
  requestAnimationFrame(paso);
})();
