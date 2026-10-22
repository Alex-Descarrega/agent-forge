# Ejemplo: agente de customer care

Workspace de ejemplo con tres muestras (dos buenas, una mala) listas para el constructor de evals.

```bash
# con API real
export ANTHROPIC_API_KEY=...
forge interview examples/customer-care --describe "Agente de soporte de primer nivel para una tienda online"
forge package     examples/customer-care
forge build-evals examples/customer-care --n 30
forge run         examples/customer-care
forge train       examples/customer-care --runs 3 --holdout-every 2 --ask-every 3
forge export      examples/customer-care

# sin API (tubería completa simulada)
forge demo examples/customer-care-demo

# con Claude Code (sin API key)
forge --backend cli --runner cli train examples/customer-care --runs 3
```
