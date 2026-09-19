# Metode

Dette dokumentet beskriver hvordan tallene på nettsiden er regnet, og hvorfor
de er regnet slik. Alle terskler og verdikoder står i `config.yaml`; ingen av
dem er hardkodet i Python-koden.

Kort om formålet: et FDV-normtall er et budsjettall. Det skal kunne
etterprøves. Hvert publiserte tall kan spores til et kronebeløp, et kWh-tall,
et areal, et kommuneutvalg og en grunnlagsårgang, via revisjonsfilen under
`data/revisjon/<år>/<funksjon>.csv`.

## 1. Kilder

| Ledd | Kilde | Tabell | Nevner |
|---|---|---|---|
| Drift | art for driftsaktiviteter | 12905 | eid areal for byggfunksjonen (11906) |
| Vedlikehold | art for vedlikeholdsaktiviteter | 12905 | eid areal for byggfunksjonen |
| Renhold | art for renhold | 12905 | eid areal for byggfunksjonen |
| Energiutgifter | art for energi | 12905 | eid areal for byggfunksjonen |
| Forvaltning | korrigerte brutto driftsutgifter, funksjon 121 | 12367 | eid areal, alle seks funksjoner |
| Energibruk | skjema 35A/35B | 12150 | eid areal for byggfunksjonen |

Byggfunksjoner: 130 administrasjonslokaler, 221 barnehagelokaler, 222
skolelokaler, 261 institusjonslokaler, 381 idrettsbygg, 386 kulturbygg.

Verdikodene slås opp ved tekstsøk i tabellens metadata, ikke fra en
hardkodet liste. Treffet må være entydig, ellers stopper jobben og skriver ut
alle gyldige koder. Hvert valg logges med `kilde: automatisk` eller
`kilde: overstyrt` og følger med i `normtall.json`. Slik blir en feilaktig
antakelse synlig ved første kjøring i stedet for å forplante seg til
publiserte tall.

Regionsdimensjonen inneholder også landet, fylker og KOSTRA-grupper.
Aggregatene filtreres bort før beregning; de ville ellers telt med i både
medianen og det arealvektede snittet. Landsaggregatet brukes kun av
avstemmingstesten.

## 2. Kostnadskolonnene er nøstet

```
Drift = energi + renhold + øvrig drift
Drift + vedlikehold = de to eneste postene som kan summeres
```

Å summere energi + renhold + drift er dobbelttelling. «Øvrig drift» er en
restpost: `drift − energi − renhold`. En negativ restpost betyr feil i
uttrekket, ikke en billig kommune, og flagges.

Indikatoren «Utgifter til kommunal eiendomsforvaltning» er ikke brukt. Den er
korrigerte brutto driftsutgifter: den inneholder avskrivninger og mva-utgift,
og mangler funksjon 121. Den er verken FDV eller FDVU.

Mva er ikke noe problem for drift og vedlikehold. Vedlikeholdsaktiviteter er
artene 070, 230 og 250, alle i artsgruppe 0–2, så arten for mva-utgift kan
ikke inngå.

## 3. Forvaltning er et porteføljetall

Funksjon 121 dekker forvaltning av hele eiendomsmassen — ledelse, forsikring,
årsgebyrer, systemlisenser — og har ikke eget areal. Leddet deles derfor på
eid areal for alle seks funksjonene, og blir identisk for alle bygningstyper i
samme kommune. Dette er en egenskap ved KOSTRA, ikke en mangel ved
implementasjonen, og det står eksplisitt på nettsiden.

Fordi tallet er likt per kommune, publiseres det **én gang**, som ett
porteføljetall med eget kjerneutvalg, og ikke som seks nesten like tall. Seks
varianter ville bare skilt seg fordi kjerneutvalget varierer per bygningstype,
og det ville vært en forskjell uten innhold.

Energibruk har ikke denne begrensningen: skjema 35 fordeler kWh på de samme
seks funksjonene som arealskjemaet. Se kapittel 9 om hva som gjenstår å
verifisere.

## 4. Sektor: alltid kommunekonsern

Areal rapporteres via skjema 34A (kommunen) og 34B (kommunale foretak), energi
tilsvarende via 35A og 35B. Brukes kommunekasse på kostnadssiden, får man en
teller uten foretak delt på et areal med foretak. Det er enkeltfeilen som
produserer verdier som 7 kr/m².

Sektordimensjonen må løses til nøyaktig én kode. Er den uavklart, feiler
jobben med en liste over gyldige koder. Den summerer aldri over sektor.

## 5. Årgangsvalg

KOSTRA publiserer ureviderte tall 15. mars og reviderte 15. juni. I
marspubliseringen imputerer SSB fjorårets data for kommuner som ikke har
rapportert. Imputerte verdier ser normale ut og passerer alle kvalitetsfiltre.

Derfor: bruk revidert årgang. En ny årgang adopteres først når systemdatoen er
etter 15. juni i publiseringsåret. Flagget `tillat_forelopig` kan overstyre,
men da merkes både JSON og nettside med at grunnlaget er foreløpig og
inneholder imputerte verdier. Foreløpig og revidert årgang blandes aldri i
samme tidsserie: revisjonen flytter tall, og en knekk mellom nest siste og
siste år ville da vært et rent artefakt.

De fem siste reviderte årgangene hentes og fryses. De tre siste vises. Å lagre
flere enn man viser koster ingenting og gjør flerårig pooling mulig uten ny
henting.

## 6. Kvalitetsflagg og uteliggere

Flaggene settes på råstørrelsene, ikke på forholdstallet. Formålet er å skille
*billig kommune* fra *kommune som ikke har rapportert kostnaden*.

| Flagg | Regel |
|---|---|
| `areal_mangler` | eid areal tomt |
| `areal_for_lite` | eid areal < 500 m² |
| `drift_mangler` | kroner tom |
| `drift_null` | kroner ≤ 0 |
| `drift_urimelig_lav` | < 200 kr/m² |
| `energi_urimelig_lav` | < 40 kr/m² |
| `renhold_urimelig_lav` | < 50 kr/m² |
| `vedlikehold_negativ` | < 0 |
| `drift_mindre_enn_delposter` | drift − energi − renhold < 0 |
| `DV_uteligger_lav` / `DV_uteligger_hoy` | utenfor Tukey-gjerde i log-rom |

Fordelingene av kr/m² er lognormale, så Tukey-gjerdet (k = 1,5) regnes på
`ln(x)` og transformeres tilbake. Gjerdet beregnes **etter** at de øvrige
flaggene er satt, slik at rapporteringsfeil ikke trekker kvartilene nedover og
dermed beskytter seg selv.

Asymmetrien er reell. Lavhalen er nesten alltid rapporteringsfeil, fordi
mekanismene virker én vei: kostnad ført på tjenestefunksjon, foretak utenfor
sektorvalget, internhusleie. Høyhalen er ofte ekte — et stort takarbeid er en
faktisk kostnad. Et gjerde i log-rom ligger høyere i høyhalen enn et lineært
gjerde på de samme tallene, og det er testdekket.

Ved en degenerert fordeling, der alle verdier er praktisk talt like, settes
gjerdet åpent. Ellers ville flyttallsstøy blitt klassifisert som uteliggere.

## 7. Tre-punktsmodell og nedbryting

Lav = P10, sannsynlig = median, høy = P90, beregnet på kjernedatasettet.

Delpostene er nesten ukorrelerte mellom kommuner. Summen av delpostenes egne
P10 blir derfor lavere enn P10 for totalen, og summen av P90 høyere. Å
publisere delpostenes egne P10/P90 som et samlet spenn gir et kunstig vidt
intervall.

Derfor settes lav/sannsynlig/høy på **D+V**, og brytes ned med medianandeler.
Begge sett publiseres: `normtall_forankret` er det som skal summeres,
`fordeling_egen` er delpostenes egne fordelinger. Feltet `skal_summeres` i
JSON sier hvilket som er hvilket. Medianandelene normaliseres slik at
nedbrytingen summerer eksakt til D+V.

### Vedlikehold krever eget sentralmål

Vedlikehold er periodisk. Samme kommune kan ligge på 30 kr/m² tre år på rad og
900 det fjerde. Et tverrsnitt av ett år fanger mange kommuner i en lavperiode,
og medianen undervurderer årsnivået systematisk.

Alle fire sentralmål beregnes og publiseres: median, 10 % trimmet snitt,
aritmetisk snitt og arealvektet snitt. **Standard for årlig normalnivå er
trimmet snitt**, og det står i JSON som
`standard_sentralmaal_vedlikehold`.

## 8. Energibruk

Samme metode som kostnadssiden: kWh delt på eid areal, per funksjon, med
log-Tukey og tre-punktsmodell. Publisert per bygningstype: total kWh/m²,
fordeling på energivare, og andel fornybar.

Feilmodusen er en annen enn på kostnadssiden. Der oppstår nuller fordi
kostnaden er ført et annet sted. Her ber SSB rapportøren anslå tall når
fullstendige opplysninger mangler, så nuller er sjeldnere og estimater
vanligere. Flaggene fanger derfor urimelige nivåer, ikke bare hull:
`kwh_mangler`, `kwh_null`, `kwh_urimelig_lav` (< 50 kWh/m²),
`kwh_urimelig_hoy` (> 500 kWh/m²) og `kwh_uteligger`.

Grove ankerverdier for rimelighetskontroll, fra SSBs undersøkelse av
tjenesteytende næringer: barnehage rundt 177 kWh/m², barne- og videregående
skole rundt 150, ungdomsskole rundt 170, sykehus rundt 375. Tallene er fra
2011 og brukes kun til størrelsesordenskontroll, aldri som fasit.

### Fire forbehold fra rapporteringsinstruksen

Disse følger av SSBs egen veiledning til skjema 35, og de endrer hva tallene
kan brukes til. Alle fire står også på nettsiden.

**Ikke temperaturkorrigert.** SSB publiserer en temperaturkorrigert serie ved
siden av den ukorrigerte i tabell 12150, men modellen bruker den ukorrigerte.
Grunnen er kryssvalideringen: implisitt energipris er kroner delt på
kilowattimer, og energiutgiftene gjelder det faktiske forbruket. Deles de på et
temperaturkorrigert forbruk, måler forholdstallet ikke lenger en pris, men en
pris ganget med årets avvik fra normalen, og den sterkeste automatiske testen i
systemet mister betydning. Forbeholdet under gjelder derfor tallene som
publiseres.

Instruksen sier eksplisitt at forbrukstallene
ikke skal korrigeres for temperaturavvik fra normalen. Et kaldt år løfter alle
kommuner, og nordlige kommuner ligger systematisk høyere enn sørlige. Det er
klima, ikke ineffektiv drift. Hvert års tall er merket med årgang, og
temperaturforbeholdet vises overalt hvor energitall vises, slik at to årganger
ikke kan sammenlignes uten at det er synlig. Grunnlagsstrukturen er forberedt
for graddagskorreksjon som fase 2.

**Gratisvarme rapporteres ikke.** Varme fra varmepumper og solfangere er ikke
med, kun elektrisiteten som driver dem. En kommune med mye varmepumper viser
derfor lavere kWh/m² enn det faktiske varmebehovet. Tallene er tilført energi,
ikke energibehov, og kan ikke sammenlignes direkte med energikrav i TEK.

**Lokale nærvarmeanlegg føres som innsatsenergi.** Har kommunen eget
nærvarmeanlegg, rapporteres energivarene som driver anlegget, ikke den
distribuerte varmen. Konverteringstapet ligger dermed inne i kWh-tallet for
disse kommunene, men ikke for kommuner som kjøper fjernvarme.

**Fordelingen mellom formål kan være skjønnsmessig.** Instruksen ber
rapportøren fordele skjønnsmessig når forbruket ikke lar seg fordele på
funksjon, og å anslå tall der fullstendige opplysninger mangler.
Funksjonssplitt på energi er derfor svakere enn funksjonssplitt på kostnad.

I tillegg: fornybarandelen regnes fra en klassifisering av energivarene i
`config.yaml`. Fjernvarme er klassifisert som fornybar fordi norsk fjernvarme
i hovedsak er avfall og bio, men andelen varierer mellom anlegg. Den som
trenger et presist tall for én kommune må gå til fjernvarmeleverandøren.

### Kryssvalidering mot energiutgifter

```
implisitt energipris = energiutgifter (kr/m²) / energibruk (kWh/m²)
```

Dette er den sterkeste automatiske testen i systemet. Resultatet skal ligge i
et plausibelt intervall for årgangen, konfigurerbart, som utgangspunkt
0,5–3,0 kr/kWh. Faller en kommune utenfor, er enten kWh eller kroner feil — og
de to kommer fra ulike skjema, så feilen kan isoleres til én av sidene.

Avviket flagges per kommune, men blokkerer ikke: det er en kvalitetsindikator,
og landsfordelingen av implisitt pris publiseres som sådan. På landsnivå er
testen derimot blokkerende.

## 9. Historikk

Ingen indeksjustering. Alle tall publiseres i løpende kroner for den årgangen
de gjelder, nøyaktig slik de står i KOSTRA. Et indeksjustert tall finnes ikke i
KOSTRA, og den som skal etterprøve det må først reversere en faktor. En
nominell tidsserie lar leseren se veksten selv og vurdere den mot sin egen
forventning om prisvekst.

### Balansert panel

Kvalitetsflaggene slår ut på ulike kommuner hvert år. Regnes medianen på hele
det rensede utvalget per år, blander tidsserien prisvekst med
sammensetningsendring: en kommune som faller ut i ett år og inn igjen i neste
flytter medianen uten at noen pris har endret seg.

| Serie | Utvalg | Brukes til |
|---|---|---|
| Nivåserie | alle rene kommuner det året | nivåtall per årgang |
| Panelserie | kommuner som er rene i **alle** årene | vekstrater |

Vekstrater regnes utelukkende på panelserien. Funksjonen som beregner dem
kaster hvis den får en nivåserie inn, fordi feilen ellers ikke gir noen synlig
feilmelding — bare et litt galt tall. Antall kommuner i begge utvalg vises ved
siden av tallene, slik at leseren ser hvor mye panelkravet koster.

Per bygningstype og post publiseres: median, P10 og P90 per årgang
(nivåserie), median per årgang (panelserie), nominell endring i prosent fra
første til siste år (panel), og årlig gjennomsnittlig endring (panel).

For vedlikehold publiseres både median og arealvektet snitt i tidsserien, med
merknad om at årlige utslag i medianen kan skyldes syklus framfor prisvekst.

### Brudd i sammenlignbarhet

KOSTRAs kontoplan endres mellom år: funksjoner og arter opprettes, utgår og
skifter navn. Endringene dokumenteres i SSBs årlige KOSTRA-rapporteringsnotat.
`config.yaml` har en liste `brudd` med årstall, berørt funksjon eller art, og
en kort beskrivelse. Berører et brudd en publisert serie, markeres bruddet på
nettsiden og vekstraten over bruddpunktet skjules.

Listen er tom inntil et brudd faktisk er dokumentert. Den skal ikke fylles med
gjetninger. Kommunestrukturen har vært stabil siden 2020, så for fem årganger
bakover er det først og fremst kontoplanendringer som er aktuelle.

### Avrunding

Avrunding skjer kun i presentasjonslaget. All mellomregning går i full
presisjon. Kostnadstall i kr/m² og energibruk i kWh/m² avrundes til nærmeste
5, og JSON inneholder både `verdi` og `verdi_avrundet`. Andeler, vekstrater og
implisitte priser avrundes ikke i JSON; nettsiden formaterer prosent med én
desimal ved visning.

Avrundingen runder halve oppover fra null. Pythons innebygde `round` runder
til nærmeste like tall, som ville gjort 7,5 til 5 ved nærmeste 5.

## 10. Frosset grunnlag

Hvert uttrekk committes under `data/grunnlag/<år>/`. Dette er ikke cache, det
er revisjonsspor og datagrunnlaget for tidsserien. SSB reviderer tabeller også
utenom de faste publiseringsdatoene, så uten frosset grunnlag i git kan ingen
se om en endring skyldtes ny årgang eller en stille revisjon av en gammel.

Ved rehenting av en årgang som allerede er frosset, skrives en diff mot den
frosne versjonen i jobbloggen før overskriving, slik at revisjonens omfang blir
synlig i git-historikken.

## 11. Tester

Blokkerende:

* **Avstemming mot landstall.** `sum(kroner)/sum(areal)` sammenlignes med
  landsaggregatet i de samme tabellene, for hver funksjon og årgang. Avvik over
  1 % rapporteres i loggen; avvik over 5 % stopper jobben.

  De to grensene er forskjellige med hensikt. Testen skal fange regnefeil: feil
  enhetsantakelse gir avvik på omtrent faktor 1000, feil sektorvalg gir titalls
  prosent. Et avvik på noen få prosent er derimot som regel en
  definisjonsforskjell — landsaggregatet er ikke nødvendigvis regnet på samme
  kommuneutvalg som vårt, og det kan bruke samlet areal (eid + leid) som nevner
  der vi bruker eid. Å kreve 1 % ville da stoppet publiseringen på noe som ikke
  er en feil.

  Loggen skriver ut avviket for alle seks funksjonene samlet. Samme fortegn og
  omtrent samme størrelse på alle tyder på ulik nevner, ikke på en regnefeil.
  `test_sammenlign_med_ssbs_egen_kr_per_m2` avgjør spørsmålet: den henter SSBs
  ferdigberegnede kr/m² for landet og viser forholdet mot vårt tall. Er
  forholdet nær 1,00, deler SSB på eid areal som oss.
* **Implisitt energipris på landsnivå.** `sum(energiutgifter)/sum(kWh)` skal
  ligge i konfigurert intervall. Fanger at kostnads- og energiuttrekkene er
  hentet for ulik årgang, ulik sektor eller ulikt arealgrunnlag.
* **Panelkonsistens.** Panelet skal ha like mange kommuner i alle år og være en
  delmengde av hvert års nivåutvalg.

De to første krever nett og kjøres av `grunnlag.yml` ved hver henting, eller
lokalt med `KOSTRA_NETT=1 pytest tests/test_nett.py`.

Uten nett: json-stat2-parsing, kodegjenkjenning, sektorvakt, log-Tukey,
avrunding til nærmeste 5, panelutvelging, vekstrateberegning inkludert
bruddhåndtering, intern konsistens, og hele kjeden fra json-stat2 til
`normtall.json` på et syntetisk grunnlag som inneholder de kjente
feilmodusene med vilje.

Sensitivitet: `kostra-fdv sensitivitet` kjører med terskler ±50 % og skriver
hvordan P10, median og P90 flytter seg til `data/publisert/sensitivitet.json`.

## 12. Uverifiserte antakelser

Disse er ikke bekreftet mot det levende API-et. Koden stoler ikke på dem:
kodegjenkjenningen er bygget på tekstsøk i metadata, og jobben skriver ut hva
den fant.

1. ~~**Kronebeløp i tabell 12905 er i 1000 kr.**~~ **Bekreftet 18.09.2026.**
   Statistikkvariabelen heter «Beløp (1000 kr)». Avstemmingstesten mot
   landstall fanger uansett opp feil enhet: avviket blir omtrent faktor 1000.
2. **Artskodene finnes med de navnene søkemønstrene forutsetter.** Er
   mønsteret for vidt eller for smalt, stopper jobben med en liste over gyldige
   koder, og `overstyring` i `config.yaml` løser det.
3. ~~**Tabell 12367 er riktig kilde for funksjon 121.**~~ **Bekreftet
   18.09.2026, motvillig.** Funksjon 121 står i funksjonsdimensjonen til 12905,
   men er tom der for alle arter. Forvaltningsleddet må derfor hentes fra 12367
   med arten `AGD4`.

   Det er ikke et godt målebegrep. `AGD4` heter «Korrigerte brutto
   driftsutgifter på funksjon/tjenesteområde» og inneholder avskrivninger
   (art 590) og mva-utgift (art 429). Drift og vedlikehold er derimot rene
   aktivitetsarter i artsgruppe 0–2, der ingen av delene kan inngå.

   Konsekvensen er at F-leddet er målt på en annen måte enn D og V, og at
   FDV-summen ikke er et rent FDV-tall. Dette er et forbehold ved KOSTRA, ikke
   ved beregningen, og det står på nettsiden. Publiserer SSB en ren
   forvaltningsart senere, er byttet én linje i `config.yaml`.
4. **Tabell 11906 skiller eid og totalt areal slik metoden forutsetter.**
   Tabelltittelen — *Areal for kommunale formålsbygg, etter eieform og
   funksjon* — tyder på at den gjør det, og kodesøket krever en eieformverdi
   som inneholder «eid» og ikke «leid», «total» eller «samlet».
5. **De fem siste årgangene finnes som reviderte utgaver i alle tre
   tabellene.** Er en årgang kun tilgjengelig som foreløpig, utelates den fra
   tidsserien, ikke blandes inn.
6. ~~**Energibruk er publisert per funksjon.**~~ **Bekreftet 18.09.2026.**
   Tabell 12150 har en funksjonsdimensjon, så energibruk kan splittes per
   bygningstype. Energi får dermed ikke samme begrensning som forvaltning.

### Avklart ved første kjøring

**Tabell 12905 har ingen sektordimensjon.** Sektoren er bakt inn i tabellens
definisjon: den dekker kommunens og de kommunale foretakenes formålsbygg, altså
konserntall. Det er noe annet enn en uavklart dimensjon, og godtas bare fordi
`config.yaml` sier det eksplisitt. Valget logges som `ikke_aktuell` sammen med
de øvrige kodevalgene.

**Dimensjonsnavnene i 12905** er `KOKart0000`, `KOKfunksjon0000` og
`KOKkommuneregion0000`. Ingen av dem lot seg gjette på forhånd, og alle ble
funnet av tekstsøket. Det var poenget med å bygge kodegjenkjenningen slik.

**Energitype-dimensjonen har sju verdier, hvorav to ikke er energivarer.**
«Alle energityper» er totalen, og «Fornybar energi» er en delsum av strøm,
fjernvarme og bioenergi. Begge ligger i samme dimensjon som de fem faktiske
varene. Summeres alt, telles forbruket dobbelt, og implisitt energipris faller
til det halve uten at noe annet ser galt ut. Totalen holdes utenfor summen og
brukes i stedet til å kontrollere at delene stemmer; delsummen holdes helt
utenfor.

**SSB skriver «Strøm», ikke «elektrisitet».** Klassifiseringen av fornybare
energivarer må bruke det ordet, ellers faller den største posten utenfor og
fornybarandelen regnes på resten alene.

**Artsetiketten for renhold** er «Utgifter til renholdsaktiviteter», ikke
«Utgifter til renhold». Energiarten heter `AG1` «Energiutgifter» og følger ikke
AGD-serien som de tre andre. Begge ble funnet av tekstsøket.

**Statistikkvariabelen har to kronevariabler:** «Beløp (1000 kr)» og «Utgifter
per kvadratmeter bygg (kr)». Modellen bruker beløpet og regner kr/m² selv, mot
eid areal. SSBs ferdigberegnede kr/m²-tall har en nevner vi ikke kontrollerer,
og et publisert tall derfra kunne ikke spores tilbake til et areal.

## 13. Fase 2, forberedt men ikke bygget

**Flerårig pooling av vedlikehold.** Regn snitt per kommune over de fem
årgangene i panelet, og beregn fordelingen deretter. Løser vedlikeholdets
periodisitet langt bedre enn trimmet snitt, fordi det fanger syklusen i stedet
for å korrigere for den statistisk. Krever at alle fem årganger er frosset —
derfor mappestrukturen med år. Skal poolede tall publiseres som nivåtall, må
årgangene først gjøres sammenlignbare, og da er indeksjustering uunngåelig.
Merk i så fall tallet tydelig som beregnet, og oppgi indeks og basisår.

**Temperaturkorrigert energi som parallell serie.** Tabell 12150 har allerede
en temperaturkorrigert variant av energibruken. Den bør hentes ved siden av den
ukorrigerte og publiseres som en egen serie, ikke som erstatning: den
ukorrigerte beholdes fordi implisitt pris må regnes på faktisk forbruk.

Med begge seriene kan nettsiden svare på et spørsmål den ikke kan svare på i
dag — om en endring mellom to år skyldes vær eller drift. Differansen mellom
seriene er nettopp værbidraget. Dette er en større forbedring enn å regne
graddagskorreksjonen selv, og den koster ett ekstra uttrekk.

**Andre skjæringer.** Kommunegruppe, fylke, innbyggertall. Store kommuner
rapporterer systematisk høyere vedlikehold og har halvparten så stor spredning
som små, så gruppering på størrelse vil gi bedre normtall enn ett landstall.
