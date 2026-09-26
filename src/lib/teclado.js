// Accesibilidad por teclado de los elementos clicables que no son un <button>.
//
// En el dashboard hay spans que hacen de botón (el ✎ de editar un evento, el «+ Evento»,
// los días de una alarma…). Con solo `onClick` no entran en el orden del tabulador, un
// lector de pantalla los lee como texto suelto y no hay forma de pulsarlos sin ratón.
// Cambiarlos por <button> movería su aspecto (los botones traen su propio fondo, borde
// y tipografía), así que se les dan las propiedades que les faltan y se quedan como
// están a la vista.

/** Props para que un elemento cualquiera se comporte como un botón: entra en el orden
 *  del tabulador, se anuncia como botón y responde a Enter y a Espacio igual que al
 *  clic. `etiqueta` es su nombre accesible cuando el texto visible es solo un icono;
 *  `pulsado` (true/false) lo anuncia como interruptor, para los que se marcan y se
 *  desmarcan. Se esparce tal cual: `<span {...comoBoton(abrir, { etiqueta: "Editar" })}>`. */
export function comoBoton(accion, { etiqueta, pulsado } = {}) {
  const props = {
    role: "button",
    tabIndex: 0,
    onClick: accion,
    onKeyDown: e => {
      // Espacio además de Enter porque es lo que hace un <button> de verdad. El
      // preventDefault evita que el Espacio desplace la página además de pulsar.
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        accion(e);
      }
    },
  };
  if (etiqueta) props["aria-label"] = etiqueta;
  if (typeof pulsado === "boolean") props["aria-pressed"] = pulsado;
  return props;
}
