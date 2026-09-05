# contexto_zai/processing/subdivider.py -- Subdivisor de temas grandes: genera subtemas derivados unicos (no parte1/parte2).
"""Subdivisor de temas grandes en subtemas derivados únicos (v3.2).

Cuando un tema individual crece tanto que no cabe en un bloque
(supera MAX_TOKENS_BLOQUE), el Subdivider lo divide en subtemas
derivados que son nuevos temas únicos en el sistema.

Diferencia crítica respecto a v1.0:
- v1.0: subdividía como `tema_parte1`, `tema_parte2` (prohibido por spec v3.2).
- v3.2: subdivide en subtemas con nombres únicos (ej: `validaciones_server`,
  `validaciones_router`, `validaciones_broker`).

Estrategia de subdivisión:
- Si el tema tiene keywords especializables (sub-palabras), se usa esa
  especialización para agrupar intercambios.
- Si no, se subdivide por rango temporal (mitad cronológica).

Atómico standalone: importa config y models, nada más del proyecto.
"""

from __future__ import annotations

# Auto-configuracion de sys.path para ejecucion directa (Windows/Linux)
import os as _os, sys as _sys
_here = _os.path.dirname(_os.path.abspath(__file__))
_candidate = _here
for _ in range(5):
    if _os.path.isdir(_os.path.join(_candidate, 'contexto_zai')):
        if _candidate not in _sys.path:
            _sys.path.insert(0, _candidate)
        break
    _candidate = _os.path.dirname(_candidate)
else:
    _parent = _os.path.dirname(_here)
    if _parent not in _sys.path:
        _sys.path.insert(0, _parent)

import logging
from dataclasses import dataclass
from typing import Optional

from contexto_zai.config import TOKEN_LIMITS
from contexto_zai.models import Exchange

logger = logging.getLogger(__name__)

@dataclass
class SubdivisionResult:
    """Resultado de subdividir un tema grande.

    Attributes:
        tema_padre: Nombre del tema original que se subdividió.
        subtemas: Lista de (subtema_name, intercambios) resultante.
        razon: Por qué se subdividió (qué criterio se aplicó).
    """

    tema_padre: str
    subtemas: list[tuple[str, list[Exchange]]]
    razon: str = ""

class Subdivider:
    """Subdivide temas grandes en subtemas derivados únicos.

    Args:
        max_tokens_per_block: Límite de tokens por bloque.
            Por defecto usa TOKEN_LIMITS.max_tokens_bloque (70K).

    Usage:
        >>> sub = Subdivider()
        >>> result = sub.subdivide("validaciones", exchanges_grandes)
        >>> for subtema_name, exchanges in result.subtemas:
        ...     print(f"{subtema_name}: {len(exchanges)} intercambios")
    """

    # Prefijos de subtemas conocidos (especialización léxica).
    # Si un tema no tiene sub-palabras conocidas, se subdivide temporalmente.
    SUBTEMAS_LEXICOS: dict[str, list[str]] = {
        "validaciones": [
            "server", "router", "broker", "planner", "client", "model",
            "auth", "config", "ui", "api",
        ],
        "metodologia": [
            "dcpa", "contrato", "identidad", "comunicacion",
            "sesion", "worklog", "handoff",
        ],
        "contexto_compresion": [
            "tokens", "ventana", "compresion", "recuperacion",
        ],
        "almacenamiento": [
            "nas", "backup", "directorio", "storage", "sandbox",
            "ruta", "archivo", "path",
        ],
        "configuracion_proyecto": [
            "worklog", "repositorio", "estrategia", "entorno",
            "proyecto", "clone", "branch",
        ],
        "planificador": [
            "pipeline", "task_queue", "orchestrator", "cola",
            "prioridad", "scheduler",
        ],
        "general": [
            "saludo", "pregunta", "respuesta", "confirmacion",
        ],
    }

    def __init__(
        self,
        max_tokens_per_block: int = TOKEN_LIMITS.max_tokens_bloque,
        safety_margin_tokens: int = 3000,
    ) -> None:
        self._max_tokens = max_tokens_per_block
        # Limite efectivo: igual que BlockPacker (max_tokens - margen)
        # El margen no puede ser mayor que el 10% del limite (para tests con limites bajos)
        effective_margin = min(safety_margin_tokens, int(max_tokens_per_block * 0.1))
        self._effective_max_tokens = max_tokens_per_block - effective_margin
        logger.debug(
            "Subdivider inicializado: max_tokens=%d (efectivo=%d con margen %d)",
            max_tokens_per_block, self._effective_max_tokens, effective_margin,
        )

    # -- API pública ------------------------------------------------

    def needs_subdivision(
        self,
        tema: str,
        exchanges: list[Exchange],
    ) -> bool:
        """Verifica si un tema necesita subdivision.

        Un tema necesita subdivision si la suma de tokens de sus
        intercambios supera el limite efectivo de bloque (90% del max),
        dejando margen para la cabecera del bloque.
        """
        # Usar 90% del max_tokens como limite efectivo (margen para cabecera)
        effective_max = self._effective_max_tokens
        total_tokens = sum(ex.estimated_tokens for ex in exchanges)
        return total_tokens > effective_max

    def subdivide(
        self,
        tema: str,
        exchanges: list[Exchange],
    ) -> SubdivisionResult:
        """Subdivide un tema grande en subtemas derivados únicos.

        Estrategia:
        1. Si el tema tiene SUBTEMAS_LEXICOS, agrupar por sub-palabra
           detectada en el contenido del mensaje del Director.
        2. Si no, subdividir por mitad temporal (cronológica).

        Cada subtema resultante debe caber en un bloque. Si algún
        subtema sigue superando el límite, se subdivide recursivamente.

        Args:
            tema: Nombre del tema a subdividir.
            exchanges: Lista de intercambios del tema.

        Returns:
            SubdivisionResult con los subtemas y sus intercambios.
        """
        if not self.needs_subdivision(tema, exchanges):
            # No necesita subdivisión
            return SubdivisionResult(
                tema_padre=tema,
                subtemas=[(tema, exchanges)],
                razon="no requiere subdivisión",
            )

        # Intentar subdivisión léxica primero
        sub_palabras = self.SUBTEMAS_LEXICOS.get(tema)
        if sub_palabras:
            result = self._subdivide_lexical(tema, exchanges, sub_palabras)
            if result is not None:
                return result

        # Fallback: subdivisión temporal
        return self._subdivide_temporal(tema, exchanges)

    def get_subtema_names(
        self,
        tema_padre: str,
        result: SubdivisionResult,
    ) -> list[str]:
        """Devuelve los nombres de subtemas creados al subdividir."""
        return [name for name, _ in result.subtemas if name != tema_padre]

    # -- Propiedades ------------------------------------------------

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

    def __repr__(self) -> str:
        return f"Subdivider(max_tokens={self._max_tokens})"

    # -- Métodos privados -------------------------------------------

    def _subdivide_lexical(
        self,
        tema: str,
        exchanges: list[Exchange],
        sub_palabras: list[str],
    ) -> Optional[SubdivisionResult]:
        """Subdivide agrupando intercambios por sub-palabra detectada.

        Args:
            tema: Nombre del tema padre.
            exchanges: Intercambios a subdividir.
            sub_palabras: Lista de sub-palabras que definen subtemas.

        Returns:
            SubdivisionResult o None si no se pudo subdividir léxicamente.
        """
        grupos: dict[str, list[Exchange]] = {}
        sobrantes: list[Exchange] = []

        for ex in exchanges:
            text = ex.director_msg.content.lower()
            matched_sub = None
            for sub in sub_palabras:
                if sub.lower() in text:
                    matched_sub = sub
                    break
            if matched_sub:
                subtema_name = f"{tema}_{matched_sub}"
                grupos.setdefault(subtema_name, []).append(ex)
            else:
                sobrantes.append(ex)

        # Si todos los intercambios fueron a "sobrantes", la subdivisión
        # léxica no funcionó
        if not grupos:
            return None

        # Asignar sobrantes al subtema más grande (o crear un subtema "_general")
        if sobrantes:
            subtema_general = f"{tema}_general"
            grupos.setdefault(subtema_general, []).extend(sobrantes)

        # Verificar que cada subtema cabe en un bloque
        # Si alguno sigue superando el limite efectivo, subdividir recursivamente
        effective_max = self._effective_max_tokens
        subtemas_final: list[tuple[str, list[Exchange]]] = []
        for subtema_name, sub_exchanges in grupos.items():
            if sum(ex.estimated_tokens for ex in sub_exchanges) > effective_max:
                # Subdivisión recursiva (con sub_palabras vacías -> temporal)
                recursive_result = self._subdivide_temporal(subtema_name, sub_exchanges)
                subtemas_final.extend(recursive_result.subtemas)
            else:
                subtemas_final.append((subtema_name, sub_exchanges))

        return SubdivisionResult(
            tema_padre=tema,
            subtemas=subtemas_final,
            razon=f"subdivisión léxica por sub-palabras: {sub_palabras}",
        )

    def _subdivide_temporal(
        self,
        tema: str,
        exchanges: list[Exchange],
    ) -> SubdivisionResult:
        """Subdivide por rango temporal (mitad cronologica).

        Crea subtemas derivados con nombres semanticos basados en las
        fechas de los intercambios (ej: tema_2026sep01, tema_2026sep02),
        NO usa parte1/parte2 (prohibido por spec v3.2 seccion 8.3).

        Recursivo: si la mitad sigue superando el limite, se subdivide
        de nuevo. Caso base: si queda 1 solo intercambio y sigue
        superando el limite, se parte el contenido del intercambio
        en fragmentos por bloques de lineas.
        """
        # Caso base: 1 solo intercambio que supera el limite efectivo
        if len(exchanges) == 1:
            tokens = sum(ex.estimated_tokens for ex in exchanges)
            effective_max = self._effective_max_tokens
            if tokens > effective_max:
                logger.warning(
                    "Intercambio individual de tema '%s' supera el limite "
                    "(%d > %d tokens). Partiendo contenido en subtemas.",
                    tema, int(tokens), effective_max,
                )
                return self._split_exchange_content(tema, exchanges[0])

        # Ordenar por timestamp
        sorted_exchanges = sorted(exchanges, key=lambda ex: ex.start_timestamp)
        mid = len(sorted_exchanges) // 2
        if mid == 0:
            return SubdivisionResult(
                tema_padre=tema,
                subtemas=[(tema, exchanges)],
                razon="no se puede partir un unico intercambio",
            )
        parte_a = sorted_exchanges[:mid]
        parte_b = sorted_exchanges[mid:]

        subtemas: list[tuple[str, list[Exchange]]] = []

        for parte in [parte_a, parte_b]:
            if not parte:
                continue
            # Generar nombre semantico basado en la fecha del primer intercambio
            from datetime import datetime
            first_ts = parte[0].start_timestamp
            date_str = datetime.fromtimestamp(first_ts).strftime("%Y%b%d").lower()
            subtema_name = f"{tema}_{date_str}"
            # Si el subtema ya existe (misma fecha), anadir sufijo numerico
            base_name = subtema_name
            counter = 2
            while any(name == subtema_name for name, _ in subtemas):
                subtema_name = f"{base_name}_{counter}"
                counter += 1

            # Si sigue superando el limite efectivo, subdividir recursivamente
            effective_max = self._effective_max_tokens
            if sum(ex.estimated_tokens for ex in parte) > effective_max:
                recursive_result = self._subdivide_temporal(subtema_name, parte)
                subtemas.extend(recursive_result.subtemas)
            else:
                subtemas.append((subtema_name, parte))

        return SubdivisionResult(
            tema_padre=tema,
            subtemas=subtemas,
            razon="subdivision temporal por fechas (cronologica)",
        )

    def _split_exchange_content(
        self,
        tema: str,
        exchange: Exchange,
    ) -> SubdivisionResult:
        """Parte un intercambio individual grande en subtemas derivados unicos.

        Cuando un solo intercambio supera el limite de tokens y no se puede
        subdividir temporalmente (solo hay 1), se divide su contenido en
        secciones basadas en las sub-palabras del tema (SUBTEMAS_LEXICOS).

        Cada seccion del contenido que menciona una sub-palabra se convierte
        en un sub-intercambio con un subtema derivado unico con nombre
        semantico (ej: almacenamiento_nas, almacenamiento_backup).

        Si el contenido no menciona ninguna sub-palabra conocida, se divide
        por bloques de lineas (no por caracteres), creando subtemas con
        nombres basados en el numero de seccion (ej: almacenamiento_seccion1).

        Cada subtema es unico y vive en un solo archivo (spec v3.2 seccion 8.3).
        """
        effective_max_tokens = self._effective_max_tokens
        max_chars = int(effective_max_tokens * 3.5)

        # El contenido del agente es lo que suele ser grande
        agent_content = ""
        if exchange.agent_msgs:
            agent_content = exchange.agent_msgs[0].content

        # Si el contenido del Director solo ya supera el limite, no se puede partir mas
        director_chars = len(exchange.director_msg.content)
        if director_chars > max_chars:
            logger.error(
                "Mensaje del Director de tema '%s' supera el limite por si solo "
                "(%d chars > %d). No se puede subdividir.",
                tema, director_chars, max_chars,
            )
            return SubdivisionResult(
                tema_padre=tema,
                subtemas=[(tema, [exchange])],
                razon="mensaje del Director supera el limite individualmente",
            )

        # Obtener las sub-palabras del tema
        sub_palabras = self.SUBTEMAS_LEXICOS.get(tema, [])

        # Estrategia 0 (v3.3): detectar scripts en el contenido
        # Si hay scripts, subdividir por nombre de script (no por keywords)
        try:
            from contexto_zai.processing.code_detector import CodeDetector
            detector = CodeDetector()
            scripts = detector.detect_scripts(agent_content, exchange_id=exchange.id)
            if scripts:
                subtemas = self._split_by_scripts(tema, exchange, scripts, max_chars, director_chars)
                if subtemas:
                    logger.info(
                        "Intercambio %d de tema '%s' dividido en %d subtemas por scripts.",
                        exchange.id, tema, len(subtemas),
                    )
                    return SubdivisionResult(
                        tema_padre=tema,
                        subtemas=subtemas,
                        razon=f"intercambio dividido en {len(subtemas)} subtemas por scripts detectados",
                    )
        except Exception as e:
            logger.debug("CodeDetector no disponible o sin scripts: %s", e)

        # Estrategia 1: subdividir por sub-palabras (subtemas semanticos)
        if sub_palabras:
            subtemas = self._split_by_keywords(tema, exchange, agent_content, sub_palabras, max_chars, director_chars)
            if subtemas:
                logger.info(
                    "Intercambio %d de tema '%s' dividido en %d subtemas semanticos.",
                    exchange.id, tema, len(subtemas),
                )
                return SubdivisionResult(
                    tema_padre=tema,
                    subtemas=subtemas,
                    razon=f"intercambio dividido en {len(subtemas)} subtemas semanticos",
                )

        # Estrategia 2: subdividir por bloques de lineas (subtemas numerados)
        subtemas = self._split_by_lines(tema, exchange, agent_content, max_chars, director_chars)
        logger.info(
            "Intercambio %d de tema '%s' dividido en %d subtemas por bloques de lineas.",
            exchange.id, tema, len(subtemas),
        )
        return SubdivisionResult(
            tema_padre=tema,
            subtemas=subtemas,
            razon=f"intercambio dividido en {len(subtemas)} subtemas por bloques de lineas",
        )

    def _split_by_scripts(
        self,
        tema: str,
        exchange: Exchange,
        scripts: list,
        max_chars: int,
        director_chars: int,
    ) -> list[tuple[str, list[Exchange]]]:
        """Divide el intercambio por scripts detectados (v3.3).

        Cada script detectado se convierte en un subtema con nombre propio
        (ej: almacenamiento_server, almacenamiento_router). Si dos scripts
        tienen el mismo nombre, se distinguen por apellido/DNI (directorio padre).

        El contenido del sub-intercambio incluye el codigo del script.
        """
        from contexto_zai.models import Message, MessageRole

        subtemas: list[tuple[str, list[Exchange]]] = []
        margin = 5000
        fragment_size = max_chars - director_chars - margin
        if fragment_size <= 0:
            fragment_size = max_chars - margin
        if fragment_size <= 0:
            fragment_size = max(1000, max_chars // 2)

        for script in scripts:
            subtema_name = f"{tema}_{script.name}"

            # Si el contenido del script supera el limite, partirlo por lineas
            if len(script.content) > fragment_size:
                lines = script.content.split("\n")
                sub_fragments = self._split_lines_by_size(lines, fragment_size)
                for i, frag in enumerate(sub_fragments, start=1):
                    sub_name = f"{subtema_name}_bloque{i}" if len(sub_fragments) > 1 else subtema_name
                    virtual_exchange = Exchange(
                        id=exchange.id * 1000 + i,
                        director_msg=exchange.director_msg,
                        agent_msgs=[Message(
                            seq=exchange.agent_msgs[0].seq if exchange.agent_msgs else 1,
                            role=MessageRole.ASSISTANT,
                            timestamp=exchange.end_timestamp,
                            content=frag,
                        )],
                        topic=sub_name,
                        start_timestamp=exchange.start_timestamp,
                        end_timestamp=exchange.end_timestamp,
                    )
                    subtemas.append((sub_name, [virtual_exchange]))
            else:
                virtual_exchange = Exchange(
                    id=exchange.id * 1000 + 1,
                    director_msg=exchange.director_msg,
                    agent_msgs=[Message(
                        seq=exchange.agent_msgs[0].seq if exchange.agent_msgs else 1,
                        role=MessageRole.ASSISTANT,
                        timestamp=exchange.end_timestamp,
                        content=script.content,
                    )],
                    topic=subtema_name,
                    start_timestamp=exchange.start_timestamp,
                    end_timestamp=exchange.end_timestamp,
                )
                subtemas.append((subtema_name, [virtual_exchange]))

        return subtemas

    def _split_by_keywords(
        self,
        tema: str,
        exchange: Exchange,
        agent_content: str,
        sub_palabras: list[str],
        max_chars: int,
        director_chars: int,
    ) -> list[tuple[str, list[Exchange]]]:
        """Divide el contenido por keywords, creando subtemas semanticos.

        Busca lineas que mencionan cada sub-palabra y las agrupa en
        sub-intercambios con nombres semanticos (ej: almacenamiento_nas).
        """
        from contexto_zai.models import Message, MessageRole

        lines = agent_content.split("\n")
        grupos: dict[str, list[str]] = {}
        sobrantes: list[str] = []

        for line in lines:
            line_lower = line.lower()
            matched_sub = None
            for sub in sub_palabras:
                if sub.lower() in line_lower:
                    matched_sub = sub
                    break
            if matched_sub:
                subtema_name = f"{tema}_{matched_sub}"
                grupos.setdefault(subtema_name, []).append(line)
            else:
                sobrantes.append(line)

        if not grupos:
            return []

        # Asignar sobrantes al subtema mas grande
        if sobrantes:
            subtema_general = f"{tema}_general"
            grupos.setdefault(subtema_general, []).extend(sobrantes)

        # Crear sub-intercambios por cada grupo, verificando que no superen el limite
        margin = 5000
        fragment_size = max_chars - director_chars - margin
        if fragment_size <= 0:
            fragment_size = max_chars - margin

        subtemas: list[tuple[str, list[Exchange]]] = []
        for subtema_name, group_lines in grupos.items():
            group_content = "\n".join(group_lines)

            # Si el grupo supera el limite, partirlo en bloques de lineas
            if len(group_content) > fragment_size:
                # Partir por lineas
                sub_fragments = self._split_lines_by_size(group_lines, fragment_size)
                for i, frag in enumerate(sub_fragments, start=1):
                    sub_name = f"{subtema_name}_bloque{i}" if len(sub_fragments) > 1 else subtema_name
                    virtual_exchange = Exchange(
                        id=exchange.id * 1000 + i,
                        director_msg=exchange.director_msg,
                        agent_msgs=[Message(
                            seq=exchange.agent_msgs[0].seq if exchange.agent_msgs else 1,
                            role=MessageRole.ASSISTANT,
                            timestamp=exchange.end_timestamp,
                            content=frag,
                        )],
                        topic=sub_name,
                        start_timestamp=exchange.start_timestamp,
                        end_timestamp=exchange.end_timestamp,
                    )
                    subtemas.append((sub_name, [virtual_exchange]))
            else:
                virtual_exchange = Exchange(
                    id=exchange.id * 1000 + 1,
                    director_msg=exchange.director_msg,
                    agent_msgs=[Message(
                        seq=exchange.agent_msgs[0].seq if exchange.agent_msgs else 1,
                        role=MessageRole.ASSISTANT,
                        timestamp=exchange.end_timestamp,
                        content=group_content,
                    )],
                    topic=subtema_name,
                    start_timestamp=exchange.start_timestamp,
                    end_timestamp=exchange.end_timestamp,
                )
                subtemas.append((subtema_name, [virtual_exchange]))

        return subtemas

    def _split_by_lines(
        self,
        tema: str,
        exchange: Exchange,
        agent_content: str,
        max_chars: int,
        director_chars: int,
    ) -> list[tuple[str, list[Exchange]]]:
        """Divide el contenido por bloques de lineas, creando subtemas con
        nombres semanticos basados en el numero de bloque (ej: tema_bloque1).

        NO usa parte1/parte2 ni frag1/frag2 (prohibido por spec v3.2 seccion 8.3).
        """
        from contexto_zai.models import Message, MessageRole

        lines = agent_content.split("\n")
        margin = 5000
        fragment_size = max_chars - director_chars - margin
        if fragment_size <= 0:
            fragment_size = max_chars - margin
        if fragment_size <= 0:
            fragment_size = max(1000, max_chars // 2)

        sub_fragments = self._split_lines_by_size(lines, fragment_size)

        subtemas: list[tuple[str, list[Exchange]]] = []
        for i, frag in enumerate(sub_fragments, start=1):
            subtema_name = f"{tema}_bloque{i}"
            virtual_exchange = Exchange(
                id=exchange.id * 1000 + i,
                director_msg=exchange.director_msg,
                agent_msgs=[Message(
                    seq=exchange.agent_msgs[0].seq if exchange.agent_msgs else 1,
                    role=MessageRole.ASSISTANT,
                    timestamp=exchange.end_timestamp,
                    content=frag,
                )],
                topic=subtema_name,
                start_timestamp=exchange.start_timestamp,
                end_timestamp=exchange.end_timestamp,
            )
            subtemas.append((subtema_name, [virtual_exchange]))

        return subtemas

    def _split_lines_by_size(
        self,
        lines: list[str],
        max_chars: int,
    ) -> list[str]:
        """Parte una lista de lineas en bloques que no superen max_chars.

        Mantiene las lineas completas (no corta a mitad de linea).
        """
        fragments: list[str] = []
        current: list[str] = []
        current_size = 0

        for line in lines:
            line_size = len(line) + 1  # +1 por el \n
            if current_size + line_size > max_chars and current:
                fragments.append("\n".join(current))
                current = [line]
                current_size = line_size
            else:
                current.append(line)
                current_size += line_size

        if current:
            fragments.append("\n".join(current))

        return fragments

if __name__ == "__main__":
    # Compatibilidad Windows: reconfigurar stdout/stderr a UTF-8
    import io as _io, sys as _sys
    try:
        if hasattr(_sys.stdout, 'buffer') and 'utf' not in (getattr(_sys.stdout, 'encoding', '') or '').lower():
            _sys.stdout = _io.TextIOWrapper(_sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
        if hasattr(_sys.stderr, 'buffer') and 'utf' not in (getattr(_sys.stderr, 'encoding', '') or '').lower():
            _sys.stderr = _io.TextIOWrapper(_sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    except (AttributeError, _io.UnsupportedOperation):
        pass
    # -- Validación interna de subdivider.py (atómico standalone) --
    print("=== Validacion de subdivider.py ===\n")

    from contexto_zai.models import Message, MessageRole

    # Subdivider con límite bajo para forzar subdivisión
    sub = Subdivider(max_tokens_per_block=1000)

    # Test 1: tema que no necesita subdivisión
    exchanges_small = [
        Exchange(id=1, director_msg=Message(seq=1, role=MessageRole.USER, timestamp=1, content="test"), topic="validaciones", start_timestamp=1, end_timestamp=2),
    ]
    result1 = sub.subdivide("validaciones", exchanges_small)
    assert len(result1.subtemas) == 1
    assert result1.subtemas[0][0] == "validaciones"
    print(f"[OK] Tema pequeno: no se subdivide")

    # Test 2: tema que supera el límite -> se subdivide temporalmente
    # Intercambios pequeños (200 chars ~57 tokens cada uno), 30 intercambios = ~1714 tokens
    exchanges_big = [
        Exchange(id=i, director_msg=Message(seq=i, role=MessageRole.USER, timestamp=i, content="x" * 200), topic="general", start_timestamp=i, end_timestamp=i+1)
        for i in range(1, 31)
    ]
    result2 = sub.subdivide("general", exchanges_big)
    assert len(result2.subtemas) > 1, f"Esperaba >1 subtemas, obtuve {len(result2.subtemas)}"
    # Ningún subtema debe superar el límite
    for name, exchanges in result2.subtemas:
        tokens = sum(ex.estimated_tokens for ex in exchanges)
        assert tokens <= sub.max_tokens, f"Subtema '{name}' supera límite: {tokens:.0f}"
    print(f"[OK] Tema grande subdividido temporalmente: {len(result2.subtemas)} subtemas")

    # Test 3: subdivisión léxica para 'validaciones'
    # Intercambios pequeños (200 chars ~57 tokens), 40 intercambios = ~2280 tokens > 1000
    sub_palabras_test = ["server", "router", "broker", "general"]
    big_val = [
        Exchange(
            id=i + 1,
            director_msg=Message(
                seq=i + 1,
                role=MessageRole.USER,
                timestamp=i + 1,
                content=f"test {sub_palabras_test[i % 4]} " + "y" * 180,
            ),
            topic="validaciones",
            start_timestamp=i + 1,
            end_timestamp=i + 2,
        )
        for i in range(40)
    ]
    result3 = sub.subdivide("validaciones", big_val)
    subtema_names = [name for name, _ in result3.subtemas]
    # Debería tener subtemas con sufijos
    assert any(
        "validaciones_" in name for name in subtema_names
    ), f"Esperaba subtemas con prefijo, obtuve {subtema_names}"
    # Ningún subtema debe superar el límite
    for name, exchanges in result3.subtemas:
        tokens = sum(ex.estimated_tokens for ex in exchanges)
        assert tokens <= sub.max_tokens, f"Subtema '{name}' supera límite: {tokens:.0f}"
    print(f"[OK] Subdivision lexica para 'validaciones': {subtema_names}")

    # Test 4: needs_subdivision
    assert not sub.needs_subdivision("general", exchanges_small)
    assert sub.needs_subdivision("general", exchanges_big)
    print(f"[OK] needs_subdivision: detecta correctamente")

    # Test 5: ningún subtema supera el límite tras subdivisión recursiva
    # Intercambios medianos que sí se pueden subdividir
    exchanges_huge = [
        Exchange(id=i, director_msg=Message(seq=i, role=MessageRole.USER, timestamp=i, content="x" * 500), topic="general", start_timestamp=i, end_timestamp=i+1)
        for i in range(1, 21)  # 20 intercambios * ~143 tokens = 2860 tokens
    ]
    result5 = sub.subdivide("general", exchanges_huge)
    for name, exchanges in result5.subtemas:
        tokens = sum(ex.estimated_tokens for ex in exchanges)
        assert tokens <= sub.max_tokens, (
            f"Subtema '{name}' supera límite: {tokens:.0f} > {sub.max_tokens}"
        )
    print(f"[OK] Subdivision recursiva: {len(result5.subtemas)} subtemas, todos < {sub.max_tokens}")

    # Test 6: get_subtema_names
    names = sub.get_subtema_names("validaciones", result3)
    assert all(name.startswith("validaciones_") for name in names)
    print(f"[OK] get_subtema_names: {names}")

    print("\n[PASS] subdivider.py: todos los tests pasaron")
