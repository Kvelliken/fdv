/* Bygger siden fra normtall.json. Ingen byggesteg, ingen avhengigheter:
   repoet skal kunne vedlikeholdes i mange år uten at et verktøykjede-oppsett
   ryker. All avrunding er allerede gjort i Python; her formateres den bare. */

const POSTREKKEFOLGE = [
  ["forvaltning", "Forvaltning", "porteføljetall, likt for alle bygningstyper"],
  ["energi", "Energi", ""],
  ["renhold", "Renhold", ""],
  ["ovrig_drift", "Øvrig drift", "drift minus energi og renhold"],
  ["vedlikehold", "Vedlikehold", "faktisk forbruk, ikke normativt behov"],
  ["dv", "Drift og vedlikehold", "summen av de fire over"],
  ["fdv", "FDV samlet", "forvaltning, drift og vedlikehold"],
];

const VAREFARGER = ["#0c5c8a", "#4a8fae", "#8a5b00", "#3f7a5e", "#7a6a9b", "#a2493c"];

const nf = new Intl.NumberFormat("nb-NO");
const pf = new Intl.NumberFormat("nb-NO", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const kf = new Intl.NumberFormat("nb-NO", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

let data = null;
let valgtFunksjon = null;

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", start, { once: true });
} else {
  start();
}

let startet = false;

async function start() {
  if (startet) return;
  startet = true;
  try {
    const svar = await fetch("normtall.json", { cache: "no-cache" });
    if (!svar.ok) throw new Error(svar.status);
    data = await svar.json();
  } catch (feil) {
    document.getElementById("tom").hidden = false;
    document.getElementById("merking").textContent =
      "Fant ingen publiserte tall.";
    return;
  }
  document.getElementById("side").hidden = false;
  document.getElementById("merking").textContent = data.merking;
  lagKnapper();
  visForbehold();
  visKodevalg();
  velg(Object.keys(data.funksjoner)[0]);
}

function lagKnapper() {
  const rad = document.getElementById("bygg-knapper");
  for (const [kode, innhold] of Object.entries(data.funksjoner)) {
    const knapp = document.createElement("button");
    knapp.type = "button";
    knapp.textContent = innhold.navn;
    knapp.setAttribute("role", "tab");
    knapp.dataset.funksjon = kode;
    knapp.addEventListener("click", () => velg(kode));
    rad.appendChild(knapp);
  }
}

function velg(kode) {
  valgtFunksjon = kode;
  for (const knapp of document.querySelectorAll("#bygg-knapper button")) {
    knapp.setAttribute("aria-selected", knapp.dataset.funksjon === kode ? "true" : "false");
  }
  const f = data.funksjoner[kode];
  visHero(f);
  visNormtall(f);
  visTidsserie(f);
  visEnergi(f);
  visDekomponering(f);
  visKvalitet(kode);
  visNedlasting(kode);
}

/* -- Hjelpere -------------------------------------------------------- */

function avrundet(par) {
  return par && par.verdi_avrundet !== null && par.verdi_avrundet !== undefined
    ? nf.format(par.verdi_avrundet)
    : "–";
}

function tall(par) {
  return par && par.verdi !== null && par.verdi !== undefined ? par.verdi : null;
}

function celle(rad, tekst, klasse) {
  const td = document.createElement("td");
  td.textContent = tekst;
  if (klasse) td.className = klasse;
  rad.appendChild(td);
  return td;
}

function svgEl(navn, attributter) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", navn);
  for (const [nokkel, verdi] of Object.entries(attributter || {})) {
    el.setAttribute(nokkel, verdi);
  }
  return el;
}

/* Spennbar: lav til høy som flate, sannsynlig som strek. Dette er figuren
   siden er bygget rundt — et normtall uten spenn er en gjetning uten feilmargin. */
function spennbar(lav, sannsynlig, hoy, skala, medTekst) {
  const svg = svgEl("svg", {
    class: "spenn",
    viewBox: "0 0 400 34",
    preserveAspectRatio: "none",
    role: "img",
    "aria-label": `Fra ${nf.format(Math.round(lav))} til ${nf.format(Math.round(hoy))} kroner per kvadratmeter, sannsynlig ${nf.format(Math.round(sannsynlig))}`,
  });
  const x = (v) => Math.max(0, Math.min(400, (v / skala) * 400));
  const y = medTekst ? 14 : 10;
  const h = 12;
  svg.appendChild(svgEl("rect", { class: "bane", x: x(lav), y, width: Math.max(2, x(hoy) - x(lav)), height: h }));
  svg.appendChild(svgEl("line", { class: "tick", x1: x(sannsynlig), x2: x(sannsynlig), y1: y - 4, y2: y + h + 4 }));
  if (medTekst) {
    const venstre = svgEl("text", { class: "merke", x: Math.max(2, x(lav)), y: 10 });
    venstre.textContent = nf.format(Math.round(lav));
    const hoyre = svgEl("text", { class: "merke", x: Math.min(398, x(hoy)), y: 10, "text-anchor": "end" });
    hoyre.textContent = nf.format(Math.round(hoy));
    svg.appendChild(venstre);
    svg.appendChild(hoyre);
  }
  return svg;
}

/* -- Hero ------------------------------------------------------------ */

function visHero(f) {
  const dv = f.kostnad.normtall_forankret.dv;
  document.getElementById("hero-aar").textContent = data.grunnlag.siste_aargang;
  document.getElementById("hero-verdi").textContent = avrundet(dv.sannsynlig);
  document.getElementById("hero-kvartil").textContent =
    `${avrundet(dv.lav)} og ${avrundet(dv.hoy)} kr/m²`;
  document.getElementById("hero-n").textContent = nf.format(f.kostnad.n_kjerne);
  const boks = document.getElementById("hero-spenn");
  boks.textContent = "";
  boks.appendChild(spennbar(tall(dv.lav), tall(dv.sannsynlig), tall(dv.hoy), tall(dv.hoy) * 1.12, true));
}

/* -- Normtallstabell -------------------------------------------------- */

function visNormtall(f) {
  const kropp = document.querySelector("#normtall tbody");
  kropp.textContent = "";
  const forankret = f.kostnad.normtall_forankret;
  const portefolje = data.forvaltning;

  let skala = 0;
  for (const [nokkel] of POSTREKKEFOLGE) {
    const punkt = nokkel === "forvaltning" ? portefolje.tre_punkt : forankret[nokkel];
    if (punkt && tall(punkt.hoy)) skala = Math.max(skala, tall(punkt.hoy));
  }
  skala *= 1.05;

  for (const [nokkel, navn, merke] of POSTREKKEFOLGE) {
    const punkt = nokkel === "forvaltning" ? portefolje.tre_punkt : forankret[nokkel];
    if (!punkt) continue;
    const rad = document.createElement("tr");
    if (nokkel === "dv" || nokkel === "fdv") rad.className = "sum";
    if (nokkel === "forvaltning") rad.className = "portefolje";

    const th = document.createElement("th");
    th.scope = "row";
    const navnEl = document.createElement("span");
    navnEl.className = "postnavn";
    navnEl.textContent = navn;
    th.appendChild(navnEl);
    if (merke) {
      const merkeEl = document.createElement("span");
      merkeEl.className = "postmerke";
      merkeEl.textContent = merke;
      th.appendChild(merkeEl);
    }
    rad.appendChild(th);

    celle(rad, avrundet(punkt.lav), "tall");
    celle(rad, avrundet(punkt.sannsynlig), "tall");
    celle(rad, avrundet(punkt.hoy), "tall");

    const grafisk = document.createElement("td");
    grafisk.className = "spennkol";
    grafisk.appendChild(spennbar(tall(punkt.lav), tall(punkt.sannsynlig), tall(punkt.hoy), skala, false));
    rad.appendChild(grafisk);
    kropp.appendChild(rad);
  }

  document.getElementById("forvaltning-note").textContent =
    `${portefolje.forklaring} Beregnet på ${nf.format(portefolje.n_kjerne)} kommuner.`;

  const egen = f.kostnad.fordeling_egen.vedlikehold;
  document.getElementById("vedlikehold-sentralmaal").textContent = egen
    ? `${avrundet(egen.trimmet_snitt)} kr/m², mot ${avrundet(egen.median)} for medianen og ` +
      `${avrundet(egen.arealvektet_snitt)} arealvektet`
    : "ikke beregnet";
}

/* -- Tidsserie -------------------------------------------------------- */

function visTidsserie(f) {
  const aargang = data.grunnlag.aargang_vist;
  const tabell = document.getElementById("tidsserie");
  const hode = tabell.querySelector("thead");
  hode.textContent = "";
  const hoderad = document.createElement("tr");
  const forste = document.createElement("th");
  forste.scope = "col";
  forste.textContent = "Post";
  hoderad.appendChild(forste);
  for (const aar of aargang) {
    const th = document.createElement("th");
    th.scope = "col";
    th.className = "tall";
    th.textContent = aar;
    hoderad.appendChild(th);
  }
  for (const navn of ["Endring, panel", "Per år"]) {
    const th = document.createElement("th");
    th.scope = "col";
    th.className = "tall";
    th.textContent = navn;
    hoderad.appendChild(th);
  }
  hode.appendChild(hoderad);

  const kropp = tabell.querySelector("tbody");
  kropp.textContent = "";
  let panelnotat = [];

  for (const [nokkel, navn] of POSTREKKEFOLGE) {
    const hist = nokkel === "forvaltning" ? data.forvaltning.historikk : f.kostnad.historikk[nokkel];
    if (!hist) continue;
    const rad = document.createElement("tr");
    if (nokkel === "dv" || nokkel === "fdv") rad.className = "sum";
    const th = document.createElement("th");
    th.scope = "row";
    th.textContent = navn;
    rad.appendChild(th);

    const punkter = new Map(hist.nivaaserie.punkter.map((p) => [p.aargang, p]));
    for (const aar of aargang) {
      const p = punkter.get(aar);
      const td = celle(rad, p && p.median !== null ? nf.format(rund5(p.median)) : "–", "tall");
      if (p && p.median !== null) {
        td.title =
          `P10 ${nf.format(rund5(p.p10))} – P90 ${nf.format(rund5(p.p90))} kr/m², ` +
          `${p.n_kommuner} kommuner i nivåutvalget`;
      }
    }

    const vekst = hist.vekst;
    if (!vekst) {
      celle(rad, "–", "tall");
      celle(rad, "–", "tall");
    } else if (vekst.skjult_grunnet_brudd) {
      celle(rad, "brudd", "tall brudd");
      celle(rad, "brudd", "tall brudd");
      for (const b of vekst.brudd) {
        panelnotat.push(`Brudd i ${b.aar}: ${b.beskrivelse || b.gjelder}. Vekstraten er skjult over bruddpunktet.`);
      }
    } else {
      celle(rad, `${pf.format(vekst.nominell_endring_prosent)} %`, "tall");
      celle(rad, `${pf.format(vekst.aarlig_gjennomsnittlig_endring_prosent)} %`, "tall");
    }
    kropp.appendChild(rad);

    if (nokkel === "vedlikehold") {
      const under = document.createElement("tr");
      const merke = document.createElement("th");
      merke.scope = "row";
      merke.className = "postmerke";
      merke.textContent = "– arealvektet snitt";
      under.appendChild(merke);
      for (const aar of aargang) {
        const p = punkter.get(aar);
        celle(under, p && p.arealvektet_snitt ? nf.format(rund5(p.arealvektet_snitt)) : "–", "tall postmerke");
      }
      celle(under, "", "tall");
      celle(under, "", "tall");
      kropp.appendChild(under);
    }
  }

  const dv = f.kostnad.historikk.dv;
  const nivaa = dv.nivaaserie.punkter.map((p) => `${p.aargang}: ${p.n_kommuner}`).join(", ");
  panelnotat.unshift(
    `Kommuner i nivåutvalget for drift og vedlikehold (${nivaa}). ` +
      `Panelet, som vekstratene regnes på, består av ${dv.n_panel} kommuner som er rene i alle årene. ` +
      "Vedlikehold er periodisk, så årlige utslag i medianen kan skyldes syklus framfor prisvekst."
  );
  document.getElementById("panel-note").textContent = panelnotat.join(" ");
}

function rund5(v) {
  return Math.round(v / 5) * 5;
}

/* -- Energi ----------------------------------------------------------- */

function visEnergi(f) {
  const kropp = document.querySelector("#energi tbody");
  kropp.textContent = "";
  for (const aar of data.grunnlag.aargang_vist) {
    const e = f.energi.per_aargang[String(aar)];
    if (!e) continue;
    const rad = document.createElement("tr");
    const th = document.createElement("th");
    th.scope = "row";
    th.textContent = aar;
    rad.appendChild(th);
    celle(rad, avrundet(e.kwh_per_m2.lav), "tall");
    celle(rad, avrundet(e.kwh_per_m2.sannsynlig), "tall");
    celle(rad, avrundet(e.kwh_per_m2.hoy), "tall");
    celle(rad, avrundet(e.kwh_per_m2.arealvektet_snitt), "tall");
    celle(
      rad,
      e.fornybarandel_median !== null ? `${pf.format(e.fornybarandel_median * 100)} %` : "–",
      "tall"
    );
    celle(
      rad,
      e.implisitt_energipris && e.implisitt_energipris.median
        ? kf.format(e.implisitt_energipris.median)
        : "–",
      "tall"
    );
    kropp.appendChild(rad);
  }

  const boks = document.getElementById("energivarer");
  boks.textContent = "";
  const fordeling = Object.entries(f.energi.siste.energivarefordeling || {}).sort((a, b) => b[1] - a[1]);
  if (!fordeling.length) {
    boks.textContent = "Ingen energivarefordeling i grunnlaget.";
    return;
  }
  const stabel = document.createElement("div");
  stabel.className = "varestabel";
  stabel.setAttribute("role", "img");
  stabel.setAttribute(
    "aria-label",
    fordeling.map(([navn, andel]) => `${navn} ${pf.format(andel * 100)} prosent`).join(", ")
  );
  const legende = document.createElement("ul");
  legende.className = "varelegende";
  fordeling.forEach(([navn, andel], i) => {
    const del = document.createElement("span");
    del.style.width = `${andel * 100}%`;
    del.style.background = VAREFARGER[i % VAREFARGER.length];
    stabel.appendChild(del);

    const li = document.createElement("li");
    const prikk = document.createElement("span");
    prikk.className = "prikk";
    prikk.style.background = VAREFARGER[i % VAREFARGER.length];
    li.appendChild(prikk);
    li.appendChild(document.createTextNode(`${navn} ${pf.format(andel * 100)} %`));
    legende.appendChild(li);
  });
  boks.appendChild(stabel);
  boks.appendChild(legende);
}

/* -- Dekomponering ---------------------------------------------------- */

function visDekomponering(f) {
  const boks = document.getElementById("dekomponering");
  boks.textContent = "";
  const aargang = data.grunnlag.aargang_vist;

  const energiKr = f.kostnad.historikk.energi;
  const kwh = f.energi.historikk;
  const priser = aargang.map((aar) => {
    const e = f.energi.per_aargang[String(aar)];
    return e && e.implisitt_energipris ? e.implisitt_energipris.median : null;
  });

  boks.appendChild(
    lagKort("Energikostnad", "kr/m²", serieFra(energiKr, aargang), aargang, energiKr.vekst)
  );
  boks.appendChild(lagKort("Energibruk", "kWh/m²", serieFra(kwh, aargang), aargang, kwh.vekst));
  boks.appendChild(lagKort("Implisitt pris", "kr/kWh", priser, aargang, null));
}

function serieFra(hist, aargang) {
  const punkter = new Map(hist.panelserie.punkter.map((p) => [p.aargang, p.median]));
  return aargang.map((aar) => punkter.get(aar) ?? null);
}

function lagKort(tittel, enhet, verdier, aargang, vekst) {
  const kort = document.createElement("div");
  kort.className = "kort";
  const h = document.createElement("h3");
  h.textContent = `${tittel} (${enhet})`;
  kort.appendChild(h);
  kort.appendChild(linjekart(verdier, aargang, enhet));

  const under = document.createElement("p");
  under.className = "endring";
  const gyldige = verdier.filter((v) => v !== null);
  if (vekst && !vekst.skjult_grunnet_brudd && vekst.nominell_endring_prosent !== null) {
    under.textContent = `${pf.format(vekst.nominell_endring_prosent)} % fra ${vekst.fra_aargang} til ${vekst.til_aargang}, regnet på panelet.`;
  } else if (gyldige.length >= 2) {
    const endring = (gyldige[gyldige.length - 1] / gyldige[0] - 1) * 100;
    under.textContent = `${pf.format(endring)} % fra ${aargang[0]} til ${aargang[aargang.length - 1]}.`;
  } else {
    under.textContent = "For få årganger til å vise endring.";
  }
  kort.appendChild(under);
  return kort;
}

function linjekart(verdier, aargang, enhet) {
  const b = 300;
  const h = 120;
  const svg = svgEl("svg", {
    class: "linjekart",
    viewBox: `0 0 ${b} ${h}`,
    preserveAspectRatio: "none",
    role: "img",
    "aria-label": aargang
      .map((aar, i) => `${aar}: ${verdier[i] === null ? "mangler" : nf.format(Math.round(verdier[i]))} ${enhet}`)
      .join(", "),
  });
  const gyldige = verdier.filter((v) => v !== null);
  if (gyldige.length < 2) return svg;
  const min = Math.min(...gyldige);
  const maks = Math.max(...gyldige);
  const spenn = maks - min || maks || 1;
  const topp = 18;
  const bunn = h - 26;
  const x = (i) => (verdier.length === 1 ? b / 2 : 24 + (i * (b - 34)) / (verdier.length - 1));
  const y = (v) => bunn - ((v - min) / spenn) * (bunn - topp);

  svg.appendChild(svgEl("line", { class: "akse", x1: 0, x2: b, y1: bunn + 6, y2: bunn + 6 }));
  const d = verdier
    .map((v, i) => (v === null ? null : `${i === 0 ? "M" : "L"}${x(i)},${y(v)}`))
    .filter(Boolean)
    .join(" ");
  svg.appendChild(svgEl("path", { d }));

  verdier.forEach((v, i) => {
    if (v === null) return;
    const merke = svgEl("text", {
      x: x(i),
      y: i === 0 ? y(v) - 8 : y(v) - 8,
      "text-anchor": i === 0 ? "start" : i === verdier.length - 1 ? "end" : "middle",
    });
    merke.textContent = nf.format(Math.round(v));
    svg.appendChild(merke);
  });
  aargang.forEach((aar, i) => {
    const merke = svgEl("text", {
      x: x(i),
      y: h - 6,
      "text-anchor": i === 0 ? "start" : i === aargang.length - 1 ? "end" : "middle",
    });
    merke.textContent = aar;
    svg.appendChild(merke);
  });
  return svg;
}

/* -- Datakvalitet ------------------------------------------------------ */

function visKvalitet(funksjon) {
  const kropp = document.querySelector("#kvalitet tbody");
  kropp.textContent = "";
  for (const aar of data.grunnlag.aargang_vist) {
    const k = data.datakvalitet.per_aargang[String(aar)].kostnad[funksjon];
    const rad = document.createElement("tr");
    const th = document.createElement("th");
    th.scope = "row";
    th.textContent = aar;
    rad.appendChild(th);
    celle(rad, nf.format(k.n_grunnlag), "tall");
    celle(rad, nf.format(k.n_kjerne), "tall");
    const arsaker = Object.entries(k.frafall_per_aarsak || {})
      .sort((a, b) => b[1] - a[1])
      .map(([navn, antall]) => `${navn.replace(/_/g, " ")} ${antall}`)
      .join(", ");
    celle(rad, arsaker || "ingen", "postmerke");
    kropp.appendChild(rad);
  }

  const siste = String(data.grunnlag.siste_aargang);
  const pris = data.datakvalitet.per_aargang[siste].energi[funksjon].implisitt_energipris;
  const felt = document.getElementById("prisfordeling");
  if (pris && pris.median) {
    felt.textContent =
      `Energiutgift delt på energibruk: ${kf.format(pris.p10)} kr/kWh i 10. persentil, ` +
      `${kf.format(pris.median)} i medianen og ${kf.format(pris.p90)} i 90. persentil. ` +
      `${pf.format(pris.andel_utenfor_intervall * 100)} % av kommunene faller utenfor det ` +
      `plausible intervallet ${kf.format(pris.intervall[0])}–${kf.format(pris.intervall[1])} kr/kWh, ` +
      "og der ligger feilen enten i kronene eller i kilowattimene.";
  } else {
    felt.textContent = "Implisitt pris er ikke beregnet for denne bygningstypen.";
  }
}

/* -- Forbehold, nedlasting, kodevalg ----------------------------------- */

function visForbehold() {
  const liste = document.getElementById("forbehold");
  liste.textContent = "";
  for (const tekst of data.forbehold) {
    const li = document.createElement("li");
    li.textContent = tekst;
    liste.appendChild(li);
  }
}

function visNedlasting(funksjon) {
  const liste = document.getElementById("nedlasting");
  liste.textContent = "";
  for (const aar of data.grunnlag.aargang_frosne) {
    const li = document.createElement("li");
    const lenke = document.createElement("a");
    lenke.href = `nedlasting/${aar}/${funksjon}.csv`;
    lenke.textContent = `${data.funksjoner[funksjon].navn} ${aar} (CSV)`;
    li.appendChild(lenke);
    liste.appendChild(li);
  }
}

function visKodevalg() {
  const linje = data.kodevalg
    .map((v) => `${v.formaal} = ${v.kode} (${v.kilde})`)
    .join(" · ");
  document.getElementById("kodevalg-fot").textContent =
    `Verdikoder brukt i uttrekket: ${linje}. Tabeller: ` +
    Object.entries(data.grunnlag.tabeller)
      .map(([navn, nummer]) => `${navn} ${nummer}`)
      .join(", ") +
    `. Frosne årganger: ${data.grunnlag.aargang_frosne.join(", ")}.`;
}
