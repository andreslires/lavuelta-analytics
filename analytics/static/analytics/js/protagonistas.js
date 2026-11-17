/* protagonistas.js - Buscador, ámbito y orden del directorio de ciclistas.
   Funciona también en la web estática: todo se resuelve en el navegador. */
(function () {
  var tbody = document.querySelector('[data-tabla] tbody');
  if (!tbody) return;

  var search = document.querySelector('[data-filtro]');
  var empty = document.querySelector('[data-vacio]');
  var sortSelect = document.querySelector('[data-orden-select]');
  var scopeButtons = Array.prototype.slice.call(document.querySelectorAll('[data-ambito]'));
  var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));
  var ambito = 'etapas';
  var metricaActiva = sortSelect ? sortSelect.value : 'victorias';

  function normalizar(texto) {
    return (texto || '')
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .toLowerCase();
  }

  function claveOrden(metrica) {
    if (
      ambito === 'general' &&
      (metrica === 'victorias' || metrica === 'podios' || metrica === 'top10')
    ) {
      return metrica + '_gc';
    }
    return metrica;
  }

  function renumerar() {
    var visibles = rows.filter(function (fila) { return !fila.hidden; });
    visibles.forEach(function (fila, i) {
      var celda = fila.querySelector('[data-rank]');
      if (celda) celda.textContent = i + 1;
    });
  }

  function filtrar() {
    var q = normalizar(search ? search.value : '').trim();
    rows.forEach(function (fila) {
      fila.hidden = Boolean(q) && normalizar(fila.dataset.nombre).indexOf(q) === -1;
    });
    renumerar();
    if (empty) {
      empty.hidden = rows.some(function (fila) { return !fila.hidden; });
    }
  }

  function actualizarValores() {
    tbody.querySelectorAll('[data-metrica]').forEach(function (celda) {
      var valor = ambito === 'general' ? celda.dataset.general : celda.dataset.etapas;
      celda.textContent = valor;
      celda.classList.toggle('is-positive', Number(valor) > 0);
    });
  }

  function ordenar(metrica) {
    metricaActiva = metrica;
    var clave = claveOrden(metrica);
    rows.sort(function (a, b) {
      if (clave === 'nombre') {
        return a.dataset.nombre.localeCompare(b.dataset.nombre, 'es');
      }
      var diff = Number(b.dataset[clave] || 0) - Number(a.dataset[clave] || 0);
      if (diff) return diff;
      return a.dataset.nombre.localeCompare(b.dataset.nombre, 'es');
    });
    rows.forEach(function (fila) { tbody.appendChild(fila); });
    if (sortSelect && sortSelect.value !== metrica) sortSelect.value = metrica;
    scopeButtons.forEach(function (boton) {
      var activo = boton.dataset.ambito === ambito;
      boton.classList.toggle('is-active', activo);
      boton.setAttribute('aria-pressed', activo ? 'true' : 'false');
    });
    actualizarValores();
    filtrar();
  }

  if (search) search.addEventListener('input', filtrar);
  if (sortSelect) {
    sortSelect.addEventListener('change', function () { ordenar(sortSelect.value); });
  }
  scopeButtons.forEach(function (boton) {
    boton.addEventListener('click', function () {
      ambito = boton.dataset.ambito;
      ordenar(metricaActiva);
    });
  });

  ordenar(metricaActiva);
})();
