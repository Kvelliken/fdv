/* Bygger siden fra normtall.json. Ingen byggesteg, ingen avhengigheter:
   repoet skal kunne vedlikeholdes i mange år uten at et verktøykjede-oppsett
   ryker. All avrunding er allerede gjort i Python; her formateres den bare. */

/* Rekkefølgen i tidsserietabellen. */
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

/* Kalkulatorens tilstand. Lagres i nettleseren, slik at arealene står der
   neste gang. Ingenting sendes noe sted. */
const LAGER = "fdv-kalkulator-v1";
const tilstand = { areal: {}, modus: "fdv", budsjettaar: null, prisvekst: 0, kommune: null };
/* kommunenummer -> { navn, funksjoner: { "222": rad fra revisjonsfilen } } */
let kommuner = new Map();

const FLAGGTEKST = {
  areal_mangler: "areal er ikke rapportert",
  areal_for_lite: "arealet er under 500 m²",
  drift_mangler: "driftsutgifter er ikke rapportert",
  drift_null: "driftsutgifter er null",
  drift_urimelig_lav: "driftsutgiftene er urimelig lave",
  energi_urimelig_lav: "energiutgiftene er urimelig lave eller ikke skilt ut",
  renhold_urimelig_lav: "renhold er urimelig lavt eller ikke skilt ut",
  vedlikehold_negativ: "vedlikehold er negativt",
  drift_mindre_enn_delposter: "drift er mindre enn energi og renhold til sammen",
  DV_uteligger_lav: "drift og vedlikehold ligger langt under andre kommuner",
  DV_uteligger_hoy: "drift og vedlikehold ligger langt over andre kommuner",
};

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
  for (const el of document.querySelectorAll(".prisaar")) {
    el.textContent = data.grunnlag.siste_aargang;
  }
  lesTilstand();
  lagKnapper();
  lagKalkulator();
  visForbehold();
  visKodevalg();
  velg(Object.keys(data.funksjoner)[0]);
  await lastKommuner();
  oppdaterAlt();
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

/* Alt som avhenger av kalkulatorens tilstand. */
function oppdaterAlt() {
  visKalkulator();
  if (valgtFunksjon) {
    visHero(data.funksjoner[valgtFunksjon]);
    visNormtall(data.funksjoner[valgtFunksjon]);
  }
  lagreTilstand();
}

/* -- Tilstand og kommunedata ------------------------------------------- */

function lesTilstand() {
  tilstand.budsjettaar = data.grunnlag.siste_aargang;
  try {
    const lagret = JSON.parse(localStorage.getItem(LAGER) || "null");
    if (lagret && typeof lagret === "object") {
      if (lagret.areal && typeof lagret.areal === "object") tilstand.areal = lagret.areal;
      if (lagret.modus === "dv" || lagret.modus === "fdv") tilstand.modus = lagret.modus;
      if (Number.isFinite(lagret.budsjettaar)) tilstand.budsjettaar = lagret.budsjettaar;
      if (Number.isFinite(lagret.prisvekst)) tilstand.prisvekst = lagret.prisvekst;
      if (typeof lagret.kommune === "string") tilstand.kommune = lagret.kommune;
    }
  } catch (feil) {
    /* Privat modus eller blokkert lagring: kalkulatoren virker uansett. */
  }
  if (tilstand.budsjettaar < data.grunnlag.siste_aargang) {
    tilstand.budsjettaar = data.grunnlag.siste_aargang;
  }
}

function lagreTilstand() {
  try {
    localStorage.setItem(LAGER, JSON.stringify(tilstand));
  } catch (feil) {
    /* se lesTilstand */
  }
}

/* Revisjonsfilene for siste årgang har én rad per kommune. De er de samme
   filene som kan lastes ned nederst på siden, så det som vises som «egne
   tall» er nøyaktig det som ligger til grunn for normtallene. */
async function lastKommuner() {
  const aar = data.grunnlag.siste_aargang;
  const funksjoner = Object.keys(data.funksjoner);
  const svar = await Promise.all(
    funksjoner.map((f) =>
      fetch(`nedlasting/${aar}/${f}.csv`)
        .then((r) => (r.ok ? r.text() : ""))
        .catch(() => "")
    )
  );
  svar.forEach((tekst, i) => {
    const linjer = tekst.replace(/^﻿/, "").split(/\r?\n/).filter(Boolean);
    if (linjer.length < 2) return;
    const felt = linjer[0].split(";");
    for (const linje of linjer.slice(1)) {
      const verdier = linje.split(";");
      const rad = {};
      felt.forEach((navn, j) => (rad[navn] = verdier[j] ?? ""));
      if (!kommuner.has(rad.kommune)) {
        kommuner.set(rad.kommune, { navn: rad.kommunenavn, funksjoner: {} });
      }
      kommuner.get(rad.kommune).funksjoner[funksjoner[i]] = rad;
    }
  });
  const liste = document.getElementById("kommuneliste");
  const sortert = [...kommuner.entries()].sort((a, b) => a[1].navn.localeCompare(b[1].navn, "nb"));
  for (const [nummer, k] of sortert) {
    const valg = document.createElement("option");
    valg.value = `${k.navn} (${nummer})`;
    liste.appendChild(valg);
  }
  const felt = document.getElementById("kommune");
  if (!kommuner.size) {
    felt.disabled = true;
    felt.placeholder = "Kommunetall er ikke tilgjengelige";
    tilstand.kommune = null;
    return;
  }
  if (tilstand.kommune && kommuner.has(tilstand.kommune)) {
    felt.value = `${kommuner.get(tilstand.kommune).navn} (${tilstand.kommune})`;
  } else {
    tilstand.kommune = null;
  }
}

function finnKommune(tekst) {
  const t = tekst.trim().toLowerCase();
  if (!t) return null;
  const nummer = t.match(/\((\d{4})\)\s*$/);
  if (nummer && kommuner.has(nummer[1])) return nummer[1];
  if (kommuner.has(t)) return t;
  const treff = [...kommuner.entries()].filter(([, k]) => k.navn.toLowerCase() === t);
  if (treff.length === 1) return treff[0][0];
  const starter = [...kommuner.entries()].filter(([, k]) => k.navn.toLowerCase().startsWith(t));
  return starter.length === 1 ? starter[0][0] : null;
}

function egenRad(funksjon) {
  if (!tilstand.kommune) return null;
  const k = kommuner.get(tilstand.kommune);
  return (k && k.funksjoner[funksjon]) || null;
}

function egetTall(funksjon, kolonne) {
  const rad = egenRad(funksjon);
  if (!rad || rad[kolonne] === "" || rad[kolonne] === undefined) return null;
  const v = Number(rad[kolonne]);
  return Number.isFinite(v) ? v : null;
}

function egneFlagg(funksjon) {
  const rad = egenRad(funksjon);
  if (!rad || !rad.flagg_kostnad) return [];
  return rad.flagg_kostnad.split("|").filter(Boolean);
}

function prisfaktor() {
  const aar = Math.max(0, (tilstand.budsjettaar || 0) - data.grunnlag.siste_aargang);
  return Math.pow(1 + (tilstand.prisvekst || 0) / 100, aar);
}

function prisaar() {
  return prisfaktor() === 1 ? data.grunnlag.siste_aargang : tilstand.budsjettaar;
}

/* Normtallet kalkulatoren bruker: det avrundede, publiserte tallet. Da kan
   hvert beløp etterregnes med en lommekalkulator fra tallene på siden. */
function norm(funksjon, post, nivaa) {
  const punkt = data.funksjoner[funksjon].kostnad.normtall_forankret[post];
  const par = punkt && punkt[nivaa];
  return par && par.verdi_avrundet !== null && par.verdi_avrundet !== undefined
    ? par.verdi_avrundet
    : null;
}

function kroner(v) {
  return v === null ? "–" : nf.format(Math.round(v / 1000) * 1000);
}

function millioner(v) {
  if (v === null) return "–";
  if (Math.abs(v) >= 1e6) return `${pf.format(v / 1e6)} mill. kr`;
  return `${nf.format(Math.round(v / 1000) * 1000)} kr`;
}

/* -- Kalkulator -------------------------------------------------------- */

function lagKalkulator() {
  const kropp = document.querySelector("#kalkulator tbody");
  kropp.textContent = "";
  for (const [kode, f] of Object.entries(data.funksjoner)) {
    const rad = document.createElement("tr");
    rad.dataset.funksjon = kode;
    const th = document.createElement("th");
    th.scope = "row";
    const etikett = document.createElement("label");
    etikett.htmlFor = `areal-${kode}`;
    etikett.textContent = f.navn;
    th.appendChild(etikett);
    rad.appendChild(th);

    const inn = document.createElement("td");
    inn.className = "tall";
    const felt = document.createElement("input");
    felt.type = "text";
    felt.inputMode = "numeric";
    felt.id = `areal-${kode}`;
    felt.className = "arealfelt";
    felt.autocomplete = "off";
    felt.placeholder = "0";
    if (tilstand.areal[kode]) felt.value = nf.format(tilstand.areal[kode]);
    felt.addEventListener("input", () => {
      const sifre = felt.value.replace(/[^\d]/g, "");
      tilstand.areal[kode] = sifre ? Number(sifre) : 0;
      oppdaterAlt();
    });
    felt.addEventListener("blur", () => {
      felt.value = tilstand.areal[kode] ? nf.format(tilstand.areal[kode]) : "";
    });
    inn.appendChild(felt);
    rad.appendChild(inn);
    for (const klasse of ["tall norm", "tall egen-kol egen", "tall lav", "tall sannsynlig", "tall hoy"]) {
      celle(rad, "", klasse);
    }
    kropp.appendChild(rad);
  }

  for (const radio of document.querySelectorAll('input[name="modus"]')) {
    radio.checked = radio.value === tilstand.modus;
    radio.addEventListener("change", () => {
      if (radio.checked) tilstand.modus = radio.value;
      oppdaterAlt();
    });
  }
  const aar = document.getElementById("budsjettaar");
  aar.min = data.grunnlag.siste_aargang;
  aar.max = data.grunnlag.siste_aargang + 15;
  aar.value = tilstand.budsjettaar;
  aar.addEventListener("input", () => {
    const v = Math.round(Number(aar.value));
    if (Number.isFinite(v) && v >= data.grunnlag.siste_aargang && v <= data.grunnlag.siste_aargang + 15) {
      tilstand.budsjettaar = v;
      oppdaterAlt();
    }
  });
  const vekst = document.getElementById("prisvekst");
  vekst.value = tilstand.prisvekst;
  vekst.addEventListener("input", () => {
    const v = Number(String(vekst.value).replace(",", "."));
    tilstand.prisvekst = Number.isFinite(v) ? Math.min(20, Math.max(0, v)) : 0;
    oppdaterAlt();
  });

  const kommune = document.getElementById("kommune");
  const velgKommune = () => {
    const nummer = finnKommune(kommune.value);
    if (nummer === tilstand.kommune) return;
    if (!nummer && kommune.value.trim()) return; // ufullstendig søk
    tilstand.kommune = nummer;
    if (nummer) {
      for (const kode of Object.keys(data.funksjoner)) {
        const areal = egetTall(kode, "eid_areal_m2");
        tilstand.areal[kode] = areal ? Math.round(areal) : 0;
        document.getElementById(`areal-${kode}`).value = areal ? nf.format(Math.round(areal)) : "";
      }
    }
    oppdaterAlt();
  };
  kommune.addEventListener("change", velgKommune);
  kommune.addEventListener("input", velgKommune);

  document.getElementById("nullstill").addEventListener("click", () => {
    tilstand.areal = {};
    tilstand.kommune = null;
    tilstand.prisvekst = 0;
    tilstand.modus = "fdv";
    for (const radio of document.querySelectorAll('input[name="modus"]')) {
      radio.checked = radio.value === "fdv";
    }
    tilstand.budsjettaar = data.grunnlag.siste_aargang;
    kommune.value = "";
    aar.value = tilstand.budsjettaar;
    vekst.value = 0;
    for (const felt of document.querySelectorAll(".arealfelt")) felt.value = "";
    oppdaterAlt();
  });
  document.getElementById("last-ned-budsjett").addEventListener("click", lastNedBudsjett);
}

/* Én rad per bygningstype, med alt kalkulatoren viser. Brukes både av
   tabellen og av CSV-eksporten, slik at de ikke kan komme i utakt. */
function budsjettrader() {
  const faktor = prisfaktor();
  const post = tilstand.modus;
  return Object.entries(data.funksjoner).map(([kode, f]) => {
    const areal = tilstand.areal[kode] || 0;
    const kr = (nivaa) => {
      const n = norm(kode, post, nivaa);
      return n === null ? null : n * faktor * areal;
    };
    return {
      kode,
      navn: f.navn,
      areal,
      norm: norm(kode, post, "sannsynlig"),
      normLav: norm(kode, post, "lav"),
      normHoy: norm(kode, post, "hoy"),
      egen: egetTall(kode, post === "fdv" ? "fdv_kr_m2" : "dv_kr_m2"),
      flagg: egneFlagg(kode),
      lav: kr("lav"),
      sannsynlig: kr("sannsynlig"),
      hoy: kr("hoy"),
    };
  });
}

function vurderEgen(r) {
  if (r.egen === null) return { tekst: "–", merke: "", tittel: "" };
  const tekst = nf.format(Math.round(r.egen));
  if (r.flagg.length) {
    return {
      tekst,
      merke: "usikkert",
      klasse: "usikker",
      tittel: "Holdt utenfor normtallet fordi " + r.flagg.map((f) => FLAGGTEKST[f] || f).join(", ") + ".",
    };
  }
  if (r.normLav !== null && r.egen < r.normLav) return { tekst, merke: "under lav", klasse: "utenfor" };
  if (r.normHoy !== null && r.egen > r.normHoy) return { tekst, merke: "over høy", klasse: "utenfor" };
  if (r.norm !== null) {
    const avvik = (r.egen / r.norm - 1) * 100;
    if (Math.abs(avvik) < 5) return { tekst, merke: "som typisk" };
    return { tekst, merke: `${avvik > 0 ? "+" : "−"}${Math.abs(Math.round(avvik))} %` };
  }
  return { tekst, merke: "" };
}

function visKalkulator() {
  const rader = budsjettrader();
  const harKommune = Boolean(tilstand.kommune);
  document.getElementById("kalkulator").classList.toggle("med-egen", harKommune);
  document.getElementById("normtall").classList.toggle("med-egen", harKommune);

  const sum = { areal: 0, lav: 0, sannsynlig: 0, hoy: 0 };
  let usikre = 0;
  for (const r of rader) {
    const tr = document.querySelector(`#kalkulator tbody tr[data-funksjon="${r.kode}"]`);
    tr.querySelector(".norm").textContent = r.norm === null ? "–" : nf.format(r.norm);
    const egen = tr.querySelector(".egen");
    egen.textContent = "";
    const v = vurderEgen(r);
    egen.appendChild(document.createTextNode(v.tekst));
    if (v.merke) {
      const merke = document.createElement("span");
      merke.className = `postmerke egenmerke ${v.klasse || ""}`;
      merke.textContent = v.merke;
      if (v.tittel) merke.title = v.tittel;
      egen.appendChild(merke);
    }
    if (v.klasse === "usikker") usikre += 1;
    for (const nivaa of ["lav", "sannsynlig", "hoy"]) {
      tr.querySelector(`.${nivaa}`).textContent = r.areal ? kroner(r[nivaa]) : "–";
      if (r.areal && r[nivaa] !== null) sum[nivaa] += r[nivaa];
    }
    sum.areal += r.areal;
  }

  const fot = document.querySelector("#kalkulator tfoot");
  fot.textContent = "";
  const sumrad = document.createElement("tr");
  sumrad.className = "sum";
  const th = document.createElement("th");
  th.scope = "row";
  th.textContent = "Sum";
  sumrad.appendChild(th);
  celle(sumrad, sum.areal ? nf.format(sum.areal) : "–", "tall");
  celle(sumrad, sum.areal ? nf.format(Math.round(sum.sannsynlig / prisfaktor() / sum.areal)) : "–", "tall");
  celle(sumrad, "", "tall egen-kol");
  for (const nivaa of ["lav", "sannsynlig", "hoy"]) {
    celle(sumrad, sum.areal ? kroner(sum[nivaa]) : "–", "tall");
  }
  fot.appendChild(sumrad);

  const hva = tilstand.modus === "fdv" ? "FDV" : "drift og vedlikehold";
  const siste = data.grunnlag.siste_aargang;
  const hode = document.querySelectorAll("#kalkulator thead th");
  hode[2].textContent = `Normtall ${siste}, kr/m²`;
  hode[3].textContent = `Egne tall ${siste}, kr/m²`;
  document.getElementById("res-merke").textContent =
    `Sannsynlig årlig kostnad til ${hva}, ${prisaar()}-kroner`;
  document.getElementById("res-sannsynlig").textContent = sum.areal ? millioner(sum.sannsynlig) : "–";
  document.getElementById("res-spenn").textContent = sum.areal
    ? `Mellom ${millioner(sum.lav)} og ${millioner(sum.hoy)} for ${nf.format(sum.areal)} m², ` +
      `altså ${nf.format(Math.round(sum.sannsynlig / sum.areal))} kr/m² i snitt.`
    : "Legg inn areal for å se årsbeløpet.";

  const faktor = prisfaktor();
  document.getElementById("pris-note").textContent =
    faktor === 1
      ? `Normtallene er i ${siste}-kroner. Skal de brukes i et senere budsjettår, ` +
        "velg året og legg inn prisveksten dere selv forutsetter, for eksempel kommunal deflator."
      : `Normtallene i ${siste}-kroner er ganget med ${kf.format(faktor)} ` +
        `(${pf.format(tilstand.prisvekst)} % per år i ${tilstand.budsjettaar - siste} år). ` +
        "Prisveksten er deres egen forutsetning, ikke en del av normtallet.";

  const egenNote = document.getElementById("egen-note");
  egenNote.hidden = !harKommune;
  if (harKommune) {
    const navn = kommuner.get(tilstand.kommune).navn;
    egenNote.textContent =
      `Egne tall er det ${navn} rapporterte til KOSTRA for ${siste}: kroner delt på eid areal, ` +
      `i ${siste}-kroner. Merket viser avstanden til det sannsynlige normtallet.` +
      (usikre
        ? ` ${usikre} av tallene er merket usikre fordi rapporteringen ser ufullstendig ut; ` +
          "hold musepekeren over merket for å se hvorfor."
        : "");
  }
}

function lastNedBudsjett() {
  const rader = budsjettrader();
  const siste = data.grunnlag.siste_aargang;
  const linjer = [
    ["bygningstype", "funksjon", "eid_areal_m2", "normtall_lav_kr_m2", "normtall_sannsynlig_kr_m2",
     "normtall_hoy_kr_m2", "prisfaktor", "lav_kr", "sannsynlig_kr", "hoy_kr"].join(";"),
  ];
  const faktor = prisfaktor();
  for (const r of rader) {
    linjer.push(
      [r.navn, r.kode, r.areal, r.normLav ?? "", r.norm ?? "", r.normHoy ?? "",
       faktor.toFixed(4).replace(".", ","),
       r.areal ? Math.round(r.lav) : "", r.areal ? Math.round(r.sannsynlig) : "",
       r.areal ? Math.round(r.hoy) : ""].join(";")
    );
  }
  linjer.push("");
  linjer.push(`# ${tilstand.modus === "fdv" ? "FDV samlet" : "Drift og vedlikehold"}. ${data.merking}`);
  linjer.push(`# Normtall i ${siste}-kroner. Beløp i ${prisaar()}-kroner.`);
  const blob = new Blob(["﻿" + linjer.join("\r\n")], { type: "text/csv;charset=utf-8" });
  const lenke = document.createElement("a");
  lenke.href = URL.createObjectURL(blob);
  lenke.download = `fdv-budsjett-${prisaar()}.csv`;
  document.body.appendChild(lenke);
  lenke.click();
  lenke.remove();
  setTimeout(() => URL.revokeObjectURL(lenke.href), 1000);
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
function spennbar(lav, sannsynlig, hoy, skala, medTekst, egen) {
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
    venstre.textContent = nf.format(rund5(lav));
    const hoyre = svgEl("text", { class: "merke", x: Math.min(398, x(hoy)), y: 10, "text-anchor": "end" });
    hoyre.textContent = nf.format(rund5(hoy));
    svg.appendChild(venstre);
    svg.appendChild(hoyre);
  }
  if (egen !== null && egen !== undefined) {
    /* Kommunens eget tall. Ligger det utenfor skalaen, settes merket i
       kanten: da er poenget at det er langt unna, ikke nøyaktig hvor. */
    const ex = Math.max(3, Math.min(397, x(egen)));
    svg.appendChild(svgEl("line", { class: "egenprikk", x1: ex, x2: ex, y1: y + 1, y2: y + h - 1 }));
  }
  return svg;
}

/* -- Hero ------------------------------------------------------------ */

function visHero(f) {
  const post = tilstand.modus;
  const punkt = f.kostnad.normtall_forankret[post] || f.kostnad.normtall_forankret.dv;
  const dv = f.kostnad.normtall_forankret.dv;
  document.getElementById("hero-hva").textContent =
    `${f.navn}: ${post === "fdv" ? "forvaltning, drift og vedlikehold" : "drift og vedlikehold"}`;
  document.getElementById("hero-aar").textContent = data.grunnlag.siste_aargang;
  document.getElementById("hero-verdi").textContent = avrundet(punkt.sannsynlig);
  document.getElementById("hero-kvartil").textContent =
    `${avrundet(punkt.lav)} og ${avrundet(punkt.hoy)} kr/m²`;
  document.getElementById("hero-deler").textContent =
    post === "fdv"
      ? `Av dette er ${avrundet(dv.sannsynlig)} drift og vedlikehold, resten forvaltning.`
      : "";
  const n = f.kostnad.fordeling_egen[post] ? f.kostnad.fordeling_egen[post].n : f.kostnad.n_kjerne;
  document.getElementById("hero-n").textContent = nf.format(n);

  const egen = egetTall(valgtFunksjon, post === "fdv" ? "fdv_kr_m2" : "dv_kr_m2");
  const egenTekst = document.getElementById("hero-egen");
  if (egen !== null && tilstand.kommune) {
    const flagg = egneFlagg(valgtFunksjon);
    egenTekst.textContent =
      `${kommuner.get(tilstand.kommune).navn} rapporterte ${nf.format(Math.round(egen))} kr/m² (det brune merket)` +
      (flagg.length ? ", men tallet er usikkert." : ".");
  } else {
    egenTekst.textContent = "";
  }
  const boks = document.getElementById("hero-spenn");
  boks.textContent = "";
  boks.appendChild(
    spennbar(tall(punkt.lav), tall(punkt.sannsynlig), tall(punkt.hoy), tall(punkt.hoy) * 1.12, true, egen)
  );
}

/* -- Normtallstabell -------------------------------------------------- */

const TABELLRADER = [
  ["energi", "Energi", "", "energi_kr_m2"],
  ["renhold", "Renhold", "", "renhold_kr_m2"],
  ["ovrig_drift", "Øvrig drift", "drift minus energi og renhold, blant annet vaktmester og kommunale avgifter", "ovrig_drift_kr_m2"],
  ["vedlikehold", "Vedlikehold", "faktisk forbruk, ikke behov", "vedlikehold_kr_m2"],
  ["dv", "= Drift og vedlikehold", "summen av de fire over", "dv_kr_m2"],
  ["forvaltning", "+ Forvaltning", "likt for alle bygningstyper", "forvaltning_kr_m2"],
  ["fdv", "= FDV samlet", "regnet direkte, se merknaden under", "fdv_kr_m2"],
];

function visNormtall(f) {
  const kropp = document.querySelector("#normtall tbody");
  kropp.textContent = "";
  const forankret = f.kostnad.normtall_forankret;
  const portefolje = data.forvaltning;
  const areal = tilstand.areal[valgtFunksjon] || 0;
  const faktor = prisfaktor();
  document.getElementById("normtall").classList.toggle("med-kr", areal > 0);
  document.querySelector("#normtall .kr-kol").textContent =
    `Sannsynlig, kr/år (${prisaar()})`;

  let skala = 0;
  for (const [nokkel] of TABELLRADER) {
    const punkt = nokkel === "forvaltning" ? portefolje.tre_punkt : forankret[nokkel];
    if (punkt && tall(punkt.hoy)) skala = Math.max(skala, tall(punkt.hoy));
  }
  skala *= 1.05;

  for (const [nokkel, navn, merke, kolonne] of TABELLRADER) {
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

    const egen = egetTall(valgtFunksjon, kolonne);
    celle(rad, egen === null ? "–" : nf.format(Math.round(egen)), "tall egen-kol");
    const sannsynlig = punkt.sannsynlig ? punkt.sannsynlig.verdi_avrundet : null;
    celle(
      rad,
      sannsynlig === null || sannsynlig === undefined ? "–" : kroner(sannsynlig * faktor * areal),
      "tall kr-kol"
    );

    const grafisk = document.createElement("td");
    grafisk.className = "spennkol";
    grafisk.appendChild(
      spennbar(tall(punkt.lav), tall(punkt.sannsynlig), tall(punkt.hoy), skala, false,
               tilstand.kommune ? egen : null)
    );
    rad.appendChild(grafisk);
    kropp.appendChild(rad);
  }

  const fdv = forankret.fdv;
  document.getElementById("sum-note").textContent = fdv
    ? "FDV samlet er regnet direkte på kommunene som har rapportert alle tre leddene " +
      `(${nf.format(f.kostnad.fordeling_egen.fdv.n)} kommuner). Sannsynlig FDV er derfor omtrent, ` +
      "men ikke nøyaktig, drift og vedlikehold pluss forvaltning. Lav og høy kan ikke legges " +
      "sammen på tvers av radene: en kommune som ligger lavt på drift ligger sjelden lavt på alt."
    : "";
  document.getElementById("forvaltning-note").textContent =
    `Forvaltning er ledelse og administrasjon av hele eiendomsmassen, delt på alt eid ` +
    `areal. Beregnet på ${nf.format(portefolje.n_kjerne)} kommuner. Tallet er hentet som korrigerte ` +
    "brutto driftsutgifter og inneholder avskrivninger, så det ligger noe høyere enn det som " +
    "belaster driftsbudsjettet direkte.";

  const egen = f.kostnad.fordeling_egen.vedlikehold;
  document.getElementById("vedlikehold-sentralmaal").textContent = egen
    ? `${avrundet(egen.trimmet_snitt)} kr/m² i gjennomsnitt når ytterpunktene er tatt ut, og ` +
      `${avrundet(egen.arealvektet_snitt)} kr/m² når store kommuner teller mer, mot ` +
      `${avrundet(egen.median)} kr/m² i det typiske året`
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
      fornybar(e) !== null ? `${pf.format(fornybar(e) * 100)} %` : "–",
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

/* Andel av samlet kWh. Medianen over kommuner er 100 % så snart over
   halvparten bare bruker strøm, og sier da ingenting. */
function fornybar(e) {
  const v = e.fornybarandel_vektet ?? e.fornybarandel_median;
  return v === null || v === undefined ? null : v;
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
