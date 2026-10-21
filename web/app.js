(() => {
  const API = "api/";            // relativo: /tareas/api/ (nginx -> servicio en 8771)
  const CADA_CUANTO_MS = 5000;   // revisión de cambios hechos en otros dispositivos
  const CLAVE_FILTRO = "tareas.filtro"; // a quién se está viendo en este dispositivo
  const REPETICION = { una: "Solo una vez", diaria: "Todos los días", semanal: "Esta semana" };

  const $ = (id) => document.getElementById(id);
  const estado = $("estado");
  const cajaError = $("error");
  const plantilla = $("plantilla");
  const dialogoTarea = $("dialogo-tarea");
  const dialogoPersonas = $("dialogo-personas");

  let tablero = { personas: [], tareas: [] };
  let version = -1;
  let hoy = "";
  let ocupado = 0;
  let filtro = leerFiltro(); // "todos" | id de persona (texto)
  let editando = null;       // id de la tarea abierta en el diálogo

  function leerFiltro() {
    try {
      return localStorage.getItem(CLAVE_FILTRO) || "todos";
    } catch {
      return "todos";
    }
  }

  function guardarFiltro() {
    try {
      localStorage.setItem(CLAVE_FILTRO, filtro);
    } catch {
      /* sin almacenamiento: el filtro solo dura mientras la página esté abierta */
    }
  }

  // ---------- API ----------

  async function pedir(ruta, opciones = {}) {
    const respuesta = await fetch(API + ruta, {
      ...opciones,
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
    });
    const datos = await respuesta.json().catch(() => ({}));
    if (!respuesta.ok) throw new Error(datos.error || `Error ${respuesta.status}`);
    return datos;
  }

  function marcarEstado(tipo, texto) {
    estado.dataset.estado = tipo;
    estado.textContent = texto;
  }

  function mostrarError(texto) {
    cajaError.textContent = texto;
    cajaError.hidden = !texto;
  }

  function aplicar(datos) {
    // Al cambiar el día también hay que redibujar (las diarias vuelven a quedar pendientes)
    if (datos.version === version && datos.hoy === hoy) return;
    version = datos.version;
    hoy = datos.hoy;
    tablero = datos;
    dibujar();
  }

  async function revisar() {
    if (ocupado) return;
    try {
      const datos = await pedir("tablero");
      if (!ocupado) aplicar(datos);
      marcarEstado("ok", "Al día");
    } catch {
      marcarEstado("error", "Sin conexión");
    }
  }

  // Cambio: se refleja de una vez en pantalla (si se puede) y luego se confirma con el servidor
  async function cambiar(ruta, metodo, cuerpo, cambioLocal) {
    ocupado++;
    if (cambioLocal) {
      cambioLocal();
      dibujar();
    }
    try {
      const datos = await pedir(ruta, { method: metodo, body: cuerpo ? JSON.stringify(cuerpo) : undefined });
      mostrarError("");
      marcarEstado("ok", "Al día");
      version = -1;
      aplicar(datos);
      return true;
    } catch (e) {
      mostrarError(`No se pudo guardar: ${e.message}`);
      marcarEstado("error", "Sin conexión");
      version = -1;
      return false;
    } finally {
      ocupado--;
      if (version === -1) revisar();
    }
  }

  // ---------- Dibujo ----------

  const personaDe = (id) => tablero.personas.find((p) => p.id === id);

  function dibujarFiltro() {
    const nav = $("filtro");
    if (filtro !== "todos" && !personaDe(Number(filtro))) filtro = "todos";
    const opciones = [{ id: "todos", nombre: "Todos" }, ...tablero.personas];
    nav.replaceChildren(
      ...opciones.map((p) => {
        const b = document.createElement("button");
        b.type = "button";
        b.dataset.filtro = String(p.id);
        b.setAttribute("aria-pressed", String(String(p.id) === filtro));
        if (p.color) {
          const punto = document.createElement("span");
          punto.className = "punto";
          punto.style.background = p.color;
          b.append(punto);
        }
        b.append(p.nombre);
        return b;
      })
    );
    nav.hidden = tablero.personas.length === 0;
  }

  function crearFila(t) {
    const li = plantilla.content.firstElementChild.cloneNode(true);
    const persona = personaDe(t.persona_id);
    li.dataset.id = t.id;
    li.classList.toggle("hecha", t.hecha);
    if (persona) li.style.setProperty("--color", persona.color);
    li.querySelector(".tarea-titulo").textContent = t.titulo;
    li.querySelector(".tarea-persona").textContent = persona ? persona.nombre : "Cualquiera";
    li.querySelector(".tarea-repeticion").textContent = REPETICION[t.repeticion];
    li.querySelector(".tarea-marcar").setAttribute(
      "aria-label",
      `${t.titulo}, ${persona ? persona.nombre : "cualquiera"}: ${t.hecha ? "marcar como pendiente" : "marcar como hecha"}`
    );
    li.querySelector(".tarea-editar").setAttribute("aria-label", `Editar ${t.titulo}`);
    return li;
  }

  function dibujarBloque(nombre, tareas) {
    // Pendientes primero; dentro de cada grupo, en el orden en que se crearon
    const orden = [...tareas].sort((a, b) => a.hecha - b.hecha || a.id - b.id);
    $(`lista-${nombre}`).replaceChildren(...orden.map(crearFila));
    $(`vacio-${nombre}`).hidden = tareas.length > 0;
    const hechas = tareas.filter((t) => t.hecha).length;
    $(`avance-${nombre}`).textContent = tareas.length ? `${hechas} de ${tareas.length}` : "";
  }

  function dibujar() {
    dibujarFiltro();
    const visibles = tablero.tareas.filter(
      (t) => filtro === "todos" || t.persona_id === Number(filtro) || t.persona_id === null
    );
    dibujarBloque("hoy", visibles.filter((t) => t.repeticion !== "semanal"));
    dibujarBloque("semana", visibles.filter((t) => t.repeticion === "semanal"));
    $("sin-personas").hidden = tablero.personas.length > 0 || version === -1;
    if (dialogoPersonas.open) dibujarPersonas();
  }

  // ---------- Tareas ----------

  function abrirTarea(tarea) {
    editando = tarea ? tarea.id : null;
    $("titulo-dialogo-tarea").textContent = tarea ? "Editar tarea" : "Nueva tarea";
    $("tarea-titulo").value = tarea ? tarea.titulo : "";

    const selector = $("tarea-persona");
    selector.replaceChildren(
      new Option("Cualquiera", ""),
      ...tablero.personas.map((p) => new Option(p.nombre, String(p.id)))
    );
    const porDefecto = tarea ? tarea.persona_id : filtro !== "todos" ? Number(filtro) : null;
    selector.value = porDefecto ? String(porDefecto) : "";

    const repeticion = tarea ? tarea.repeticion : "una";
    dialogoTarea.querySelectorAll('input[name="repeticion"]').forEach((r) => {
      r.checked = r.value === repeticion;
    });
    $("borrar-tarea").hidden = !tarea;
    dialogoTarea.showModal();
    if (!tarea) $("tarea-titulo").focus();
  }

  $("form-tarea").addEventListener("submit", async (e) => {
    e.preventDefault();
    const titulo = $("tarea-titulo").value.trim();
    if (!titulo) return;
    const personaId = $("tarea-persona").value;
    const cuerpo = {
      titulo,
      persona_id: personaId ? Number(personaId) : null,
      repeticion: dialogoTarea.querySelector('input[name="repeticion"]:checked').value,
    };
    dialogoTarea.close();
    if (editando) await cambiar(`tareas/${editando}`, "PATCH", cuerpo);
    else await cambiar("tareas", "POST", cuerpo);
  });

  $("borrar-tarea").addEventListener("click", () => {
    const t = tablero.tareas.find((x) => x.id === editando);
    if (!t || !confirm(`¿Borrar la tarea "${t.titulo}"?`)) return;
    dialogoTarea.close();
    cambiar(`tareas/${t.id}`, "DELETE", null, () => {
      tablero.tareas = tablero.tareas.filter((x) => x.id !== t.id);
    });
  });

  $("nueva-tarea").addEventListener("click", () => abrirTarea(null));

  function alTocar(e) {
    const boton = e.target.closest("button[data-accion]");
    if (!boton) return;
    const t = tablero.tareas.find((x) => x.id === Number(boton.closest(".tarea").dataset.id));
    if (!t) return;
    if (boton.dataset.accion === "editar") {
      abrirTarea(t);
    } else {
      const hecha = !t.hecha;
      cambiar(`tareas/${t.id}/hecha`, "POST", { hecha }, () => {
        t.hecha = hecha;
      });
    }
  }
  $("lista-hoy").addEventListener("click", alTocar);
  $("lista-semana").addEventListener("click", alTocar);

  $("filtro").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-filtro]");
    if (!b) return;
    filtro = b.dataset.filtro;
    guardarFiltro();
    dibujar();
  });

  // ---------- Personas ----------

  function dibujarPersonas() {
    const lista = $("lista-personas");
    // No se redibuja una fila mientras alguien la está editando
    if (lista.contains(document.activeElement) && document.activeElement.tagName === "INPUT") return;
    lista.replaceChildren(
      ...tablero.personas.map((p) => {
        const li = document.createElement("li");
        li.className = "persona";

        const punto = document.createElement("span");
        punto.className = "punto";
        punto.style.background = p.color;

        const campo = document.createElement("input");
        campo.type = "text";
        campo.maxLength = 30;
        campo.value = p.nombre;
        campo.setAttribute("aria-label", `Nombre de ${p.nombre}`);
        campo.addEventListener("change", () => {
          const nombre = campo.value.trim();
          if (!nombre) {
            campo.value = p.nombre;
            return;
          }
          if (nombre !== p.nombre) cambiar(`personas/${p.id}`, "PATCH", { nombre });
        });

        const quitar = document.createElement("button");
        quitar.type = "button";
        quitar.textContent = "✕";
        quitar.setAttribute("aria-label", `Quitar a ${p.nombre}`);
        quitar.addEventListener("click", () => {
          if (!confirm(`¿Quitar a ${p.nombre}? Sus tareas quedan para "Cualquiera".`)) return;
          cambiar(`personas/${p.id}`, "DELETE");
        });

        li.append(punto, campo, quitar);
        return li;
      })
    );
  }

  $("form-persona").addEventListener("submit", async (e) => {
    e.preventDefault();
    const campo = $("persona-nombre");
    const nombre = campo.value.trim();
    if (!nombre) return;
    campo.value = "";
    await cambiar("personas", "POST", { nombre });
    campo.focus();
  });

  document.querySelectorAll('[data-abrir="personas"]').forEach((b) =>
    b.addEventListener("click", () => {
      dibujarPersonas();
      dialogoPersonas.showModal();
      if (!tablero.personas.length) $("persona-nombre").focus();
    })
  );

  document.querySelectorAll("[data-cerrar]").forEach((b) =>
    b.addEventListener("click", () => b.closest("dialog").close())
  );

  // ---------- Revisión periódica ----------

  let temporizador = null;
  function arrancar() {
    clearInterval(temporizador);
    revisar();
    temporizador = setInterval(revisar, CADA_CUANTO_MS);
  }
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) clearInterval(temporizador);
    else arrancar();
  });
  window.addEventListener("online", revisar);

  arrancar();
})();
