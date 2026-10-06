---
description: Revisa el diff, busca secretos, corre la compuerta y hace commits lógicos (Conventional Commits en español, sin trailers). Pregunta antes de cada push.
---

# /commit-seguro

Lee `CLAUDE.md` (reglas duras 4, 6 y 7) antes de empezar.

## 1. Inventario

```bash
git status --porcelain -uall > .gates/status.log 2>&1
echo "EXIT=$?"
```

Revisa **todos** los archivos, incluidos los no seguidos. Lee el diff archivo por archivo (`git diff -- <ruta>`;
para archivos nuevos, `Read`).

## 2. Bloqueos (si alguno aplica, para y avísame)

- `.env` o `.env.*` (salvo `.env.example`), o cualquier ruta bajo `plantilla-agentes/`.
- Secretos: busca en el diff y en los archivos sin seguir patrones como `password`, `secret`, `token`,
  `api_key`, `PRIVATE KEY`, `AKIA`, `sk-`, `ghp_`, cadenas de conexión con credenciales (`://user:pass@`).
  `.env.example` solo puede tener valores de ejemplo vacíos o ficticios.
- Archivos grandes o binarios no esperados.

## 3. Compuerta

Corre la compuerta con el agente `ejecutor-gates` (o con el bloque de `CLAUDE.md`, salida a fichero y
`echo "EXIT=$?"`). Si está **ROJA no hay commit**: infórmame con `archivo:línea`.

Excepción: si el proyecto Python todavía no existe (antes del Paso 1), la compuerta no aplica; dilo en el resumen.

## 4. Commits lógicos

- Agrupa por intención (`feat:`, `fix:`, `chore:`, `docs:`, `test:`, `ci:`, `refactor:`), un commit por grupo.
- **Conventional Commits en español**, en imperativo y en minúscula tras el tipo. Ejemplo:
  `feat: añade MRCDParams con validaciones citadas de rrcov`.
- `git add <rutas explícitas>`. Nunca `git add -A` ni `git add .`.
- **Sin trailers de coautoría** (`Co-Authored-By` ni similares).
- Usa la identidad de git configurada en el repo; no la cambies.

## 5. Push (PARADA)

Muéstrame `git log --oneline origin/main..HEAD` (o el log completo si la rama aún no existe en el remoto) y
**pregúntame antes de cada `git push`**. Solo con mi «sí» explícito: `git push origin main`
(`-u` la primera vez).

## Prohibido

`git push --force` / `--force-with-lease`, `git reset --hard`, `git stash`, `git clean`, `git commit --amend`
sobre commits publicados, `--no-verify`, y cualquier reescritura de historia publicada.
