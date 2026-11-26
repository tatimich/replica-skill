// Integração no site da marca. Cole no HTML do site, onde a busca deve aparecer:
//
//   <div id="busca-legislacao"></div>
//   <script src="https://SEU-ENDERECO/static/embed.js" data-alvo="busca-legislacao" defer></script>
//
// Opcional: data-categoria="Nome da categoria" abre a busca já filtrada.
(function () {
  var script = document.currentScript;
  if (!script) return;
  var origem = new URL(script.src).href.replace(/\/static\/embed\.js.*$/, "");
  var alvo = document.getElementById(script.dataset.alvo || "busca-legislacao");
  if (!alvo) return;
  var params = new URLSearchParams({ embed: "1" });
  if (script.dataset.categoria) params.set("categoria", script.dataset.categoria);
  var quadro = document.createElement("iframe");
  quadro.src = origem + "/?" + params.toString();
  quadro.title = script.dataset.titulo || "Busca de legislação";
  quadro.loading = "lazy";
  quadro.style.cssText = "width:100%;border:0;min-height:600px;display:block";
  alvo.appendChild(quadro);
  var origemQuadro = new URL(origem).origin;
  window.addEventListener("message", function (ev) {
    if (ev.origin !== origemQuadro || !ev.data || ev.data.tipo !== "legislacao:altura") return;
    quadro.style.height = ev.data.altura + "px";
  });
})();
