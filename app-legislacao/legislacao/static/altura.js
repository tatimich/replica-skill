// Quando a busca está embutida (iframe) no site da marca, informa a altura
// do conteúdo à página que a contém, para o iframe crescer sem barra de rolagem.
(function () {
  if (window.parent === window) return;
  var ultima = 0;
  function enviar() {
    var h = document.documentElement.scrollHeight;
    if (h !== ultima) {
      ultima = h;
      window.parent.postMessage({ tipo: "legislacao:altura", altura: h }, "*");
    }
  }
  window.addEventListener("load", enviar);
  if ("ResizeObserver" in window) new ResizeObserver(enviar).observe(document.body);
  else setInterval(enviar, 500);
})();
