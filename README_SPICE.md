# LUNARA — conexión local a NASA/JPL SPICE

Esta carpeta contiene una versión de LUNARA conectada a un pequeño servidor Python local. El navegador no ejecuta SPICE directamente: Python carga los kernels NAIF y calcula los vectores de posición del Sol y la Tierra; después entrega el JSON al HTML usando el mismo formato que ya entiende LUNARA.

## 1. Requisitos

- Windows 10/11.
- Python instalado y disponible mediante el comando `py`.
- Conexión a Internet la primera vez (para instalar SpiceyPy y, si faltan, descargar los kernels).

## 2. Arrancar LUNARA con SPICE

1. Haz una copia de seguridad del `index.html` actual.
2. Extrae el contenido del ZIP directamente en la carpeta del proyecto donde ya está la carpeta `models`. El ZIP incluye un nuevo `index.html` conectado a SPICE.
3. No borres ni sustituyas tu carpeta `models` ni las texturas originales.
4. Haz doble clic en `start_lunara_spice.bat`.
5. El primer arranque instalará SpiceyPy si hace falta y descargará a `kernels/` los tres kernels genéricos si no están ya presentes.
5. Se abrirá el navegador en `http://127.0.0.1:8765/`. Mantén abierta la ventana de terminal mientras uses la web.
7. En LUNARA abre **Data & terrain** y pulsa **Generate real data with SPICE**.

El servidor escucha solo en `127.0.0.1` (tu propio equipo). No cierres la terminal mientras uses la página.

## 3. Kernels utilizados

El servidor busca estos nombres exactos en la carpeta `kernels/`:

- `de442s.bsp` — efemérides planetarias JPL DE442s (preferida si está disponible). También acepta `de440s.bsp` como alternativa compatible, para reutilizar tu kernel anterior.
- `naif0012.tls` — segundos intercalares y conversión UTC ↔ ET/TDB.
- `pck00011.tpc` — constantes físicas y orientación estándar `IAU_MOON`.

Si no están, el BAT usa `--download-missing` para descargarlos desde los directorios genéricos oficiales de NAIF:

- https://naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/planets/de442s.bsp
- https://naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/planets/de440s.bsp (fallback)
- https://naif.jpl.nasa.gov/pub/naif/generic_kernels/lsk/naif0012.tls
- https://naif.jpl.nasa.gov/pub/naif/generic_kernels/pck/pck00011.tpc

Puedes usar los que ya tienes, siempre que se llamen exactamente así y no estén incompletos.

## 4. Qué datos se calculan

Al pulsar el botón, Python lee el inicio UTC, la ventana (24/48/72 h) y el paso (10/15/30/60 min) seleccionados en la interfaz. Para cada instante:

- Convierte la fecha UTC a SPICE ET/TDB con el LSK.
- Calcula la posición geométrica de `SUN` respecto de `MOON`.
- Calcula la posición geométrica de `EARTH` respecto de `MOON`.
- Expresa ambos vectores en kilómetros y en el marco `IAU_MOON`.
- Devuelve los vectores al navegador; la geometría local, elevación, azimut, visibilidad, curvas y métricas siguen calculándose en el JavaScript de LUNARA.

Se usa corrección de aberración `NONE` para que los vectores sean posiciones geométricas coherentes con el modelo geométrico actual de la aplicación. El servidor no extrapola datos fuera de la cobertura del SPK: SPICE devuelve un error en caso de cobertura insuficiente.

## 5. Aviso importante sobre precisión lunar

Esta conexión aporta **efemérides reales de SPICE**, pero la versión HTML actual define coordenadas y cálculos locales en `IAU_MOON`. El kernel de texto `pck00011.tpc` proporciona la orientación lunar estándar de menor precisión. NAIF indica que para orientación lunar de alta precisión deben usarse los kernels lunares binarios y los marcos `MOON_ME` o `MOON_PA`; `IAU_MOON` no proporciona esa orientación de alta precisión.

Por tanto, esta integración es apropiada para desarrollo, visualización y prototipado de análisis geométrico, pero no es una herramienta certificada para seleccionar un lugar de aterrizaje ni para decisiones de misión. No cambia el modelo de terreno: si no cargas un perfil de horizonte derivado de LOLA, LUNARA seguirá usando horizonte geométrico plano. La visibilidad geométrica de la Tierra tampoco equivale a disponibilidad de un enlace RF.

## 6. Solución de problemas

- **“SPICE service not detected”**: abre la web desde la dirección `http://127.0.0.1:8765/`, no haciendo doble clic en el HTML.
- **Faltan kernels**: comprueba que los archivos estén en `kernels/`; vuelve a ejecutar el BAT con conexión a Internet.
- **No se puede instalar SpiceyPy**: ejecuta `py -m pip install -r requirements_spice.txt` en una terminal.
- **Date is outside SPICE file coverage**: escoge una fecha cubierta por DE440s o usa otro SPK con cobertura adecuada.
- **El terminal informa un error de frame**: comprueba que `pck00011.tpc` se ha descargado completo y está en `kernels/`.

## Fuentes oficiales

- NAIF Generic Kernels: https://naif.jpl.nasa.gov/naif/data_generic.html
- NAIF PCK/FK Summary for Moon and Earth (orientation accuracy and frame selection): https://naif.jpl.nasa.gov/pub/naif/toolkit_docs/Tutorials/pdf/individual_docs/23_lunar-earth_pck-fk.pdf
