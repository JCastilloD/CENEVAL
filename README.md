# CENEVAL caso 10360

Simulaciones de Monte Carlo con un lenguaje tipo LaTeX. El modelo se valida con un autómata y un parser, se compila a Python y se simula en paralelo con la gráfica en tiempo real.

* `src` compilador, servicios FastAPI y cliente de escritorio (Tkinter)
* `web` cliente web instalable (PWA)
* `api` publica los dos servicios en un solo contenedor
* `infra` Container App en Azure (Bicep)

## Local

```
pip install -r requirements.txt
python src/servicio_compilacion.py
python src/servicio_simulacion.py
python src/cliente.py
```

Pruebas: `python -m unittest tests.correr_pruebas -v`
