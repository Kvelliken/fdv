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

// Vargvinds kategoriske skala, i fast rekkefølge.
const VAREFARGER = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)", "var(--chart-6)"];

const nf = new Intl.NumberFormat("nb-NO");
const pf = new Intl.NumberFormat("nb-NO", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const kf = new Intl.NumberFormat("nb-NO", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const pfs = new Intl.NumberFormat("nb-NO", { minimumFractionDigits: 1, maximumFractionDigits: 1, signDisplay: "exceptZero" });
// Endring skrives med fortegn og ekte minustegn: +4,2 %, −1,8 %.
const endring = (v) => pfs.format(v).replace("-", "−").replace("\u2212", "−");

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
    const svar = await fetch("../normtall.json", { cache: "no-cache" });
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
  const fraUrl = new URLSearchParams(location.search).get("bygg");
  velg(fraUrl && data.funksjoner[fraUrl] ? fraUrl : Object.keys(data.funksjoner)[0], false);
  if (window.vvByggToc) window.vvByggToc();
}

function lagKnapper() {
  const rad = document.getElementById("bygg-knapper");
  for (const [kode, innhold] of Object.entries(data.funksjoner)) {
    const knapp = document.createElement("button");
    knapp.type = "button";
    knapp.textContent = innhold.navn;
    knapp.setAttribute("role", "tab");
    knapp.dataset.funksjon = kode;
    knapp.addEventListener("click", () => velg(kode, true));
    rad.appendChild(knapp);
  }
  // Piltaster flytter mellom bygningstypene, som i en vanlig faneliste.
  rad.addEventListener("keydown", (e) => {
    const knapper = [...rad.querySelectorAll("button")];
    const i = knapper.indexOf(document.activeElement);
    if (i < 0) return;
    let j = null;
    if (e.key === "ArrowRight") j = (i + 1) % knapper.length;
    if (e.key === "ArrowLeft") j = (i - 1 + knapper.length) % knapper.length;
    if (e.key === "Home") j = 0;
    if (e.key === "End") j = knapper.length - 1;
    if (j === null) return;
    e.preventDefault();
    knapper[j].focus();
    velg(knapper[j].dataset.funksjon, true);
  });
}

function velg(kode, oppdaterUrl) {
  valgtFunksjon = kode;
  for (const knapp of document.querySelectorAll("#bygg-knapper button")) {
    const valgt = knapp.dataset.funksjon === kode;
    knapp.setAttribute("aria-selected", valgt ? "true" : "false");
    knapp.tabIndex = valgt ? 0 : -1;
  }
  if (oppdaterUrl) {
    // Valget står i adressen, så lenken kan deles og tilbake-knappen lander riktig.
    const url = new URL(location.href);
    url.searchParams.set("bygg", kode);
    history.replaceState(null, "", url);
  }
  const f = data.funksjoner[kode];
  document.getElementById("hero-navn").textContent = f.navn;
  document.getElementById("til-dekning").href = `../dekning/?bygg=${encodeURIComponent(kode)}`;
  document.getElementById("til-dekning").textContent =
    `Har kommunen nok ${f.navn.toLowerCase()}? Se dekningen per kommune`;
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
function spennbar(lav, sannsynlig, hoy, skala, etiketter) {
  const svg = svgEl("svg", {
    class: "spenn",
    viewBox: "0 0 400 20",
    preserveAspectRatio: "none",
    role: "img",
    "aria-label": `Fra ${nf.format(Math.round(lav))} til ${nf.format(Math.round(hoy))} kroner per kvadratmeter, sannsynlig ${nf.format(Math.round(sannsynlig))}`,
  });
  const x = (v) => Math.max(0, Math.min(400, (v / skala) * 400));
  svg.appendChild(svgEl("rect", { class: "bane", x: x(lav), y: 5, width: Math.max(2, x(hoy) - x(lav)), height: 10, rx: 1 }));
  svg.appendChild(svgEl("line", { class: "tick", x1: x(sannsynlig), x2: x(sannsynlig), y1: 0, y2: 20, "vector-effect": "non-scaling-stroke" }));
  if (!etiketter) return svg;
  // Etikettene står i HTML, så teksten ikke strekkes sammen med figuren.
  const boks = document.createElement("div");
  boks.className = "spenn-boks";
  const pst = (v) => `${(x(v) / 4).toFixed(2)}%`;
  for (const [verdi, tekst, klasse] of [[lav, etiketter[0], "lav"], [hoy, etiketter[1], "hoy"]]) {
    const el = document.createElement("span");
    el.className = `spenn-merke ${klasse}`;
    el.style.left = pst(verdi);
    el.textContent = tekst;
    boks.appendChild(el);
  }
  boks.appendChild(svg);
  return boks;
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
  boks.appendChild(spennbar(tall(dv.lav), tall(dv.sannsynlig), tall(dv.hoy), tall(dv.hoy) * 1.08,
    [`Lav ${avrundet(dv.lav)}`, `Høy ${avrundet(dv.hoy)}`]));

  const fdv = f.kostnad.normtall_forankret.fdv;
  document.getElementById("fdv-verdi").textContent = fdv ? avrundet(fdv.sannsynlig) : "–";
  const siste = f.energi.per_aargang[String(data.grunnlag.siste_aargang)];
  document.getElementById("kwh-verdi").textContent = siste ? avrundet(siste.kwh_per_m2.sannsynlig) : "–";
  document.getElementById("kwh-under").textContent = siste
    ? `Spenn ${avrundet(siste.kwh_per_m2.lav)}–${avrundet(siste.kwh_per_m2.hoy)} kWh/m². Ikke temperaturkorrigert.`
    : "";
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
    if (nokkel === "dv" || nokkel === "fdv") rad.className = "vv-table__sum";
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

    celle(rad, avrundet(punkt.lav), "vv-num");
    celle(rad, avrundet(punkt.sannsynlig), "vv-num");
    celle(rad, avrundet(punkt.hoy), "vv-num");

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
    th.className = "vv-num";
    th.textContent = aar;
    hoderad.appendChild(th);
  }
  for (const navn of ["Endring, panel", "Per år"]) {
    const th = document.createElement("th");
    th.scope = "col";
    th.className = "vv-num";
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
    if (nokkel === "dv" || nokkel === "fdv") rad.className = "vv-table__sum";
    const th = document.createElement("th");
    th.scope = "row";
    th.textContent = navn;
    rad.appendChild(th);

    const punkter = new Map(hist.nivaaserie.punkter.map((p) => [p.aargang, p]));
    for (const aar of aargang) {
      const p = punkter.get(aar);
      const td = celle(rad, p && p.median !== null ? nf.format(rund5(p.median)) : "–", "vv-num");
      if (p && p.median !== null) {
        td.title =
          `P10 ${nf.format(rund5(p.p10))} – P90 ${nf.format(rund5(p.p90))} kr/m², ` +
          `${p.n_kommuner} kommuner i nivåutvalget`;
      }
    }

    const vekst = hist.vekst;
    if (!vekst) {
      celle(rad, "–", "vv-num");
      celle(rad, "–", "vv-num");
    } else if (vekst.skjult_grunnet_brudd) {
      celle(rad, "brudd", "vv-num brudd");
      celle(rad, "brudd", "vv-num brudd");
      for (const b of vekst.brudd) {
        panelnotat.push(`Brudd i ${b.aar}: ${b.beskrivelse || b.gjelder}. Vekstraten er skjult over bruddpunktet.`);
      }
    } else {
      celle(rad, `${endring(vekst.nominell_endring_prosent)} %`, "vv-num");
      celle(rad, `${endring(vekst.aarlig_gjennomsnittlig_endring_prosent)} %`, "vv-num");
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
        celle(under, p && p.arealvektet_snitt ? nf.format(rund5(p.arealvektet_snitt)) : "–", "vv-num postmerke");
      }
      celle(under, "", "vv-num");
      celle(under, "", "vv-num");
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
    celle(rad, avrundet(e.kwh_per_m2.lav), "vv-num");
    celle(rad, avrundet(e.kwh_per_m2.sannsynlig), "vv-num");
    celle(rad, avrundet(e.kwh_per_m2.hoy), "vv-num");
    celle(rad, avrundet(e.kwh_per_m2.arealvektet_snitt), "vv-num");
    celle(
      rad,
      e.fornybarandel_median !== null ? `${pf.format(e.fornybarandel_median * 100)} %` : "–",
      "vv-num"
    );
    celle(
      rad,
      e.implisitt_energipris && e.implisitt_energipris.median
        ? kf.format(e.implisitt_energipris.median)
        : "–",
      "vv-num"
    );
    kropp.appendChild(rad);
  }

  const boks = document.getElementById("energivarer");
  boks.textContent = "";
  // Energivarer under 0,05 % vises ikke; de ville bare stått som 0,0 %.
  const fordeling = Object.entries(f.energi.siste.energivarefordeling || {})
    .filter(([, andel]) => andel >= 0.0005)
    .sort((a, b) => b[1] - a[1]);
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
    li.appendChild(document.createTextNode(`${navn} `));
    const b = document.createElement("b");
    b.textContent = `${pf.format(andel * 100)} %`;
    li.appendChild(b);
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
  kort.className = "vv-kort smaakart-kort";
  const h = document.createElement("h4");
  h.textContent = tittel;
  kort.appendChild(h);
  const e = document.createElement("span");
  e.className = "enhet";
  e.textContent = `Median, ${enhet}`;
  kort.appendChild(e);
  kort.appendChild(linjekart(verdier, aargang, enhet));

  const under = document.createElement("p");
  under.className = "endring";
  const gyldige = verdier.filter((v) => v !== null);
  if (vekst && !vekst.skjult_grunnet_brudd && vekst.nominell_endring_prosent !== null) {
    under.textContent = `${endring(vekst.nominell_endring_prosent)} % fra ${vekst.fra_aargang} til ${vekst.til_aargang}, regnet på panelet.`;
  } else if (gyldige.length >= 2) {
    const prosent = (gyldige[gyldige.length - 1] / gyldige[0] - 1) * 100;
    under.textContent = `${endring(prosent)} % fra ${aargang[0]} til ${aargang[aargang.length - 1]}.`;
  } else {
    under.textContent = "For få årganger til å vise endring.";
  }
  kort.appendChild(under);
  return kort;
}

/* Tall under 10 får to desimaler (kr/kWh), resten heltall. */
function kortTall(v) {
  return Math.abs(v) < 10 ? kf.format(v) : nf.format(Math.round(v));
}

function linjekart(verdier, aargang, enhet) {
  const b = 300;
  const h = 130;
  const svg = svgEl("svg", {
    class: "linjekart",
    viewBox: `0 0 ${b} ${h}`,
    role: "img",
    "aria-label": aargang
      .map((aar, i) => `${aar}: ${verdier[i] === null ? "mangler" : kortTall(verdier[i])} ${enhet}`)
      .join(", "),
  });
  const gyldige = verdier.filter((v) => v !== null);
  if (gyldige.length < 2) return svg;
  const min = Math.min(...gyldige);
  const maks = Math.max(...gyldige);
  const spenn = maks - min || maks || 1;
  const topp = 26;
  const bunn = h - 30;
  const x = (i) => (verdier.length === 1 ? b / 2 : 28 + (i * (b - 56)) / (verdier.length - 1));
  const y = (v) => bunn - ((v - min) / spenn) * (bunn - topp);

  svg.appendChild(svgEl("line", { class: "akse", x1: 0, x2: b, y1: bunn + 10, y2: bunn + 10 }));
  const d = verdier
    .map((v, i) => (v === null ? null : `${i === 0 ? "M" : "L"}${x(i)},${y(v)}`))
    .filter(Boolean)
    .join(" ");
  svg.appendChild(svgEl("path", { d }));

  verdier.forEach((v, i) => {
    if (v === null) return;
    svg.appendChild(svgEl("circle", { cx: x(i), cy: y(v), r: 3.5 }));
    const merke = svgEl("text", { x: x(i), y: y(v) - 10, "text-anchor": "middle" });
    if (i === verdier.length - 1) merke.setAttribute("class", "verdi");
    merke.textContent = kortTall(v);
    svg.appendChild(merke);
  });
  aargang.forEach((aar, i) => {
    const merke = svgEl("text", { x: x(i), y: h - 4, "text-anchor": "middle" });
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
    celle(rad, nf.format(k.n_grunnlag), "vv-num");
    celle(rad, nf.format(k.n_kjerne), "vv-num");
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
    lenke.href = `../nedlasting/${aar}/${funksjon}.csv`;
    lenke.textContent = `${data.funksjoner[funksjon].navn} ${aar}, CSV`;
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
