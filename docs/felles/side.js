/* Felles oppførsel for formålsbygg-sidene: bygger «På denne siden» fra
   overskriftene og markerer seksjonen leseren er i. Ingen avhengigheter.
   En h2 kommer med i listen hvis den har id. data-kort gir en kortere etikett. */
(function () {
  "use strict";

  function bygg() {
    var toc = document.querySelector("[data-toc]");
    if (!toc) return;
    var liste = toc.querySelector("ol");
    var overskrifter = [].slice.call(document.querySelectorAll("main h2[id]")).filter(function (h) {
      return !h.closest("[hidden]");
    });
    if (!overskrifter.length) return;
    toc.hidden = false;
    liste.textContent = "";
    var lenker = overskrifter.map(function (h) {
      var li = document.createElement("li");
      var a = document.createElement("a");
      a.href = "#" + h.id;
      a.textContent = h.dataset.kort || h.textContent;
      li.appendChild(a);
      liste.appendChild(li);
      return a;
    });

    function marker(i) {
      lenker.forEach(function (a, j) {
        if (j === i) a.setAttribute("aria-current", "true");
        else a.removeAttribute("aria-current");
      });
      var aktiv = lenker[i];
      // Hold aktiv lenke synlig i den liggende listen på smale skjermer.
      if (aktiv && liste.scrollWidth > liste.clientWidth) {
        var venstre = aktiv.offsetLeft - liste.clientWidth / 2 + aktiv.clientWidth / 2;
        liste.scrollTo({ left: venstre, behavior: "smooth" });
      }
    }

    var aktivIndeks = -1;
    function oppdater() {
      var grense = window.innerHeight * 0.3;
      var i = 0;
      overskrifter.forEach(function (h, j) {
        if (h.getBoundingClientRect().top <= grense) i = j;
      });
      // Helt nederst: marker siste seksjon selv om overskriften ikke har nådd grensen.
      if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4) {
        i = overskrifter.length - 1;
      }
      if (i !== aktivIndeks) { aktivIndeks = i; marker(i); }
    }

    var venter = false;
    window.addEventListener("scroll", function () {
      if (venter) return;
      venter = true;
      requestAnimationFrame(function () { venter = false; oppdater(); });
    }, { passive: true });
    window.addEventListener("resize", oppdater);
    oppdater();
  }

  window.vvByggToc = bygg;
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bygg, { once: true });
  } else {
    bygg();
  }
})();
