# app.py
from flask import Flask, request, jsonify, render_template, redirect, url_for, make_response
import os
from typing import List, Any
from pathlib import Path

# Cargar variables desde .env (local). En Render usarás Environment vars.
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).with_name(".env"), override=True)

# CORS opcional (si el front está en otro dominio)
try:
    from flask_cors import CORS  # type: ignore
    _HAS_CORS = True
except Exception:
    _HAS_CORS = False

from supabase import create_client, Client

# -------------------------
# Configuración Flask
# -------------------------
app = Flask(__name__)
if _HAS_CORS:
    CORS(app)

# -------------------------
# Configuración Supabase
# -------------------------
SUPABASE_URL = os.environ.get("SUPABASE_URL")
# Para insertar desde backend, ideal SERVICE_ROLE (seguro, solo en server).
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE") or os.environ.get("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError(
        "Faltan SUPABASE_URL y/o SUPABASE_[SERVICE_ROLE|ANON_KEY]. "
        "Configúralas en .env (local) o en Render → Environment."
    )

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# -------------------------
# Tablas/columnas reales en Supabase
# -------------------------
# Catálogo de autores
TBL_AUTORES = "autores_publicaciones"
COL_AUTOR_ID = "id"
COL_AUTOR_NOMBRE = "nombre_sin_norm"
COL_AUTOR_DOC = "documento"

# Publicaciones/libros
TBL_PUBLICACIONES = "publicaciones"
COL_PUB_ID = "id"
COL_PUB_TITULO = "titulo"

# Matriz intermedia
TBL_MATRIZ = "matriz_intermedia"
COL_MAT_PUB_ID = "publicacion_id"
COL_MAT_AUT_ID = "autor_id"

# -------------------------
# Helpers
# -------------------------
def _json_error(msg: str, code: int = 400):
    return make_response(jsonify({"error": msg}), code)

def _ensure_int_list(values: List[Any]) -> List[int]:
    out: List[int] = []
    for v in values:
        try:
            out.append(int(v))
        except Exception:
            continue
    return out

# -------------------------
# Rutas
# -------------------------
@app.route("/")
def home():
    # Ir directo al formulario
    return redirect(url_for("agregar_publicacion"))

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

@app.route("/formulario", methods=["GET"])
def formulario_publicacion():
    """
    Página de fallback (ya no debería usarse).
    """
    return redirect(url_for("agregar_publicacion"))

@app.route("/agregar_publicacion", methods=["GET", "POST"])
def agregar_publicacion():
    """
    Muestra el formulario y procesa la creación de una publicación.
    """
    if request.method == "POST":
        titulo = (request.form.get("titulo") or "").strip()
        autor_ids = _ensure_int_list(request.form.getlist("autor_ids"))

        if not titulo:
            return _json_error("Falta 'titulo' de la publicación.", 400)

        # 1) Insertar publicación
        pub_insert = {COL_PUB_TITULO: titulo}
        pub_res = supabase.table(TBL_PUBLICACIONES).insert(pub_insert).select(COL_PUB_ID).execute()
        if not pub_res.data:
            return _json_error("No se pudo crear la publicación.", 500)

        publicacion_id = pub_res.data[0][COL_PUB_ID]

        # 2) Insertar relaciones en matriz_intermedia
        if autor_ids:
            relaciones = [{COL_MAT_PUB_ID: publicacion_id, COL_MAT_AUT_ID: aid} for aid in autor_ids]
            supabase.table(TBL_MATRIZ).insert(relaciones).execute()

        return redirect(url_for("agregar_publicacion"))

    # GET → mostrar formulario HTML
    return render_template("agregar_publicacion.html")

@app.route("/api/autores", methods=["GET"])
def api_autores():
    """
    Devuelve autores para el combo: admite 'q' (búsqueda), 'limit' y 'ids' (precarga).
    Salida: [{id, nombre, documento}]
    """
    q = (request.args.get("q") or "").strip()
    limit = int(request.args.get("limit") or 20)
    limit = max(1, min(limit, 100))

    ids_param = (request.args.get("ids") or "").strip()
    ids_list: List[int] = []
    if ids_param:
        ids_list = _ensure_int_list([x for x in ids_param.split(",") if x.strip()])

    query = supabase.table(TBL_AUTORES).select(f"{COL_AUTOR_ID},{COL_AUTOR_DOC},{COL_AUTOR_NOMBRE}")

    if ids_list:
        query = query.in_(COL_AUTOR_ID, ids_list)
    elif q:
        query = query.or_(f"{COL_AUTOR_NOMBRE}.ilike.%{q}%,{COL_AUTOR_DOC}.ilike.%{q}%")

    res = query.limit(limit).execute()
    data = res.data or []

    autores = [
        {
            "id": a.get(COL_AUTOR_ID),
            "documento": a.get(COL_AUTOR_DOC),
            "nombre": a.get(COL_AUTOR_NOMBRE),
        }
        for a in data
        if a.get(COL_AUTOR_ID) is not None
    ]
    return jsonify(autores)

# -------------------------
# Main (local)
# -------------------------
if __name__ == "__main__":
    # En Render usarás: gunicorn app:app
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
