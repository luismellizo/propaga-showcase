"""
Capa de prompts del generador de contenido.

┌──────────────────────────────────────────────────────────────────────────┐
│  ⚠️  PROMPTS DE PRODUCCIÓN OMITIDOS — SECRETO COMERCIAL                   │
│                                                                          │
│  Este archivo es un STUB. Los prompts reales de PROPAGA son el núcleo    │
│  del producto: son el resultado de iterar sobre transcripciones reales   │
│  hasta que el título deja de sonar a robot y empieza a generar clics.    │
│  No se publican.                                                        │
│                                                                          │
│  Lo que SÍ se documenta aquí es la ARQUITECTURA del prompt, que es lo    │
│  que tiene valor de ingeniería: cómo se compone, en qué orden, qué se    │
│  inyecta desde la base de datos y por qué cada capa existe.              │
│                                                                          │
│  Los textos de abajo son ejemplos genéricos e ilustrativos. El sistema   │
│  funciona con ellos, pero NO produce el contenido del producto real.     │
└──────────────────────────────────────────────────────────────────────────┘

ARQUITECTURA DEL PROMPT DE GENERACIÓN
=====================================

Entrada: la transcripción del audio del video (Whisper vía Groq).
Salida: un JSON con `title`, `description` y `hashtags`, listo para persistir.

El prompt se arma por capas, en orden de precedencia creciente — lo que va al
final pesa más en la atención del modelo:

    1. PERSONA            Quién escribe. Sale de `AIConfiguration.personality`
                          (7 personalidades: viral, profesional, casual,
                          humorística, educativa, inspiradora, ventas). Cada
                          persona es un bloque de texto afinado por separado:
                          cambiarla cambia el registro entero de la salida.

    2. REGLAS DE FORMATO  Longitud de título, longitud de descripción, formato
                          de hashtags. Existen porque cada red tiene límites
                          duros distintos y el texto se reutiliza en las cinco:
                          el denominador común se impone en la generación, no
                          en el momento de publicar.

    3. REGLA DE EMOJIS    Derivada de `AIConfiguration.use_emojis`. Binaria a
                          propósito: "usa emojis si encaja" produce resultados
                          inconsistentes, "NO uses emojis" produce cero.

    4. REGLA DE HASHTAGS  Cantidad exacta (`hashtags_count`) más los hashtags
                          fijos de marca (`default_hashtags`), que se anexan
                          siempre. Pedir un número exacto en vez de "algunos"
                          es lo que hace que la salida sea parseable.

    5. INSTRUCCIONES DEL USUARIO   Punto de extensión por cuenta
                          (`custom_instructions`): nicho, palabras prohibidas,
                          tono de marca, CTA. Se inyecta de último y se declara
                          prioritaria sobre las reglas generales — un dueño de
                          canal que prohíbe una palabra tiene que ganarle al
                          prompt base. Se trunca a 2000 caracteres para que no
                          desplace a la transcripción del contexto.

    6. TRANSCRIPCIÓN      El material fuente, truncado. El corte es deliberado:
                          el gancho de un video vive en el primer minuto, y
                          mandar la transcripción completa de un video largo
                          solo sube el costo por token sin mejorar el título.

Decisiones de diseño que sobreviven a la redacción
--------------------------------------------------

* **JSON estructurado en el request, no parseado del texto.** La llamada usa
  `responseMimeType: application/json`, así que el modelo devuelve JSON válido
  por contrato del API y no hay que raspar bloques de markdown de la respuesta.

* **Fallback determinista.** Si el proveedor de IA falla — cuota, timeout, 500
  del lado de Google — `generate_fallback_content()` arma título y descripción
  recortando la propia transcripción. El video llega igual a "Por aprobar" con
  algo editable en pantalla, en vez de morir en FAILED. Degradar es mejor que
  romper: el usuario ya esperó la descarga, la extracción de audio y la
  transcripción.

* **La personalidad vive en la BD, no en el código.** Cambiar el registro de la
  IA no requiere deploy, y cada usuario tiene el suyo.
"""

# ---------------------------------------------------------------------------
# Personas — TEXTOS DE PRODUCCIÓN OMITIDOS.
# Las de abajo son descripciones genéricas de una línea, suficientes para que
# el sistema corra. Las reales son bloques mucho más largos, con ejemplos
# positivos y negativos y reglas de registro por cada personalidad.
# ---------------------------------------------------------------------------
PERSONALITY_PROMPTS = {
    'VIRAL': "Escribes títulos llamativos que generan curiosidad, sin mentir.",
    'PROFESIONAL': "Escribes con tono corporativo, serio y confiable.",
    'CASUAL': "Escribes cercano y natural, como le hablarías a un amigo.",
    'HUMORISTICO': "Escribes con humor ligero, sin ofender.",
    'EDUCATIVO': "Escribes claro y didáctico, prometiendo aprendizaje concreto.",
    'INSPIRADOR': "Escribes motivacional y emotivo.",
    'VENTAS': "Escribes persuasivo, orientado a conversión, con llamado a la acción.",
}

# Tope de caracteres de transcripción que entran al prompt.
TRANSCRIPTION_CHAR_LIMIT = 4000

# Tope de las instrucciones libres del usuario.
CUSTOM_INSTRUCTIONS_CHAR_LIMIT = 2000


def build_content_prompt(transcription, config):
    """
    Compone el prompt final a partir de la transcripción y la configuración de
    IA del usuario (`AIConfiguration` o None).

    ⚠️  VERSIÓN ILUSTRATIVA. El prompt de producción implementa las mismas capas
    documentadas arriba, pero con instrucciones mucho más largas y específicas
    por personalidad. Este stub respeta el contrato — mismas variables de
    entrada, mismo JSON de salida — para que el resto del pipeline sea legible.
    """
    persona = PERSONALITY_PROMPTS.get(
        config.personality if config else 'VIRAL', PERSONALITY_PROMPTS['VIRAL']
    )
    hashtags_count = config.hashtags_count if config else 3

    emoji_rule = (
        "Utiliza un emoji relevante si encaja."
        if (config is None or config.use_emojis)
        else "NO utilices emojis bajo ninguna circunstancia."
    )

    hashtag_rule = (
        f"Genera exactamente {hashtags_count} hashtags de una sola palabra, "
        "relevantes y potentes, separados por espacios."
    )
    if config and config.default_hashtags.strip():
        hashtag_rule += (
            f" Además, incluye SIEMPRE estos hashtags fijos al final: "
            f"{config.default_hashtags.strip()}."
        )

    custom_block = ""
    if config and config.custom_instructions.strip():
        custom_block = (
            "\n    INSTRUCCIONES DEL USUARIO (obligatorias, tienen prioridad "
            "sobre las reglas generales):\n    "
            f"{config.custom_instructions.strip()[:CUSTOM_INSTRUCTIONS_CHAR_LIMIT]}\n"
        )

    return f"""
    {persona} Tu misión es crear contenido para redes sociales a partir de la
    siguiente transcripción.

    REGLAS ESTRICTAS:
    1.  **Título:** Máximo 12 palabras, fiel a la personalidad indicada. {emoji_rule}
    2.  **Descripción:** Corta (2-3 frases, máximo 50 palabras). {emoji_rule}
    3.  **Hashtags:** {hashtag_rule} Ejemplo de formato: #secreto #magia #revelado.
    {custom_block}
    Tu respuesta DEBE ser un objeto JSON válido con tres claves: "title",
    "description" y "hashtags".

    TRANSCRIPCIÓN:
    ---
    {transcription[:TRANSCRIPTION_CHAR_LIMIT]}
    ---
    """
