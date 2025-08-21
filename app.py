from flask import Flask, request, jsonify, render_template, redirect, url_for, make_response
import os
from typing import List, Any
from pathlib import Path
from datetime import datetime

# Cargar variables desde .env
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).with_name(".env"), override=True)

# CORS opcional
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
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE") or os.environ.get("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError(
        "Faltan SUPABASE_URL y/o SUPABASE_[SERVICE_ROLE|ANON_KEY]. "
        "Configúralas en .env (local) o en Render → Environment."
    )

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# -------------------------
# Tablas/columnas en Supabase
# -------------------------
TBL_AUTORES = "autores_publicaciones"
COL_AUTOR_ID = "id"
COL_AUTOR_NOMBRE = "nombre"
COL_AUTOR_DOC = "documento"

TBL_PUBLICACIONES = "publicaciones"
COL_PUB_ID = "id"
COL_PUB_TITULO = "titulo"

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
    return redirect(url_for("formulario_publicacion"))

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

@app.route("/formulario", methods=["GET"])
def formulario_publicacion():
    try:
        return render_template("agregar_publicacion.html")
    except Exception:
        return """
        <!doctype html>
        <html lang="es">
        <head><meta charset="utf-8"><title>Formulario Publicación</title></head>
        <body><h2>Nueva publicación (fallback)</h2></body>
        </html>
        """

@app.route("/api/autores", methods=["GET"])
def api_autores():
    """
    Devuelve autores para el combo: admite 'q', 'limit' y 'ids'.
    """
    q = (request.args.get("q") or "").strip()
    limit = int(request.args.get("limit") or 20)
    limit = max(1, min(limit, 100))

    ids_param = (request.args.get("ids") or "").strip()
    ids_list: List[int] = []
    if ids_param:
        ids_list = _ensure_int_list([x for x in ids_param.split(",") if x.strip()])

    query = supabase.table(TBL_AUTORES).select(
        f"{COL_AUTOR_ID},{COL_AUTOR_DOC},{COL_AUTOR_NOMBRE}"
    )

    if ids_list:
        query = query.in_(COL_AUTOR_ID, ids_list)
    elif q:
        # Búsqueda por nombre o documento con patrón %...%
        query = query.or_(
            f"{COL_AUTOR_NOMBRE}.ilike.%{q}%,{COL_AUTOR_DOC}.ilike.%{q}%"
        )
        print(f"[DEBUG] Buscando autores con patrón: %{q}%")

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

# =======================
# Nuevo endpoint: check autor
# =======================
@app.route("/check_autor/<documento>", methods=["GET"])
def check_autor(documento):
    res = supabase.table(TBL_AUTORES).select("id").eq("documento", documento).execute()
    exists = bool(res.data)
    return jsonify({"exists": exists})

# =======================
# Guardar publicación (publicación + autores)
# =======================
@app.route("/guardar-publicacion", methods=["POST"])
def guardar_publicacion():
    body = request.get_json(silent=True) or {}
    titulo = (body.get("titulo_libro") or "").strip()
    autores = body.get("autores") or []

    if not titulo:
        return jsonify({"status": "error", "mensaje": "Falta título"}), 400

    # 1. Insertar publicación
    pub_insert = {"titulo": titulo}
    pub_res = supabase.table(TBL_PUBLICACIONES).insert(pub_insert).select("id").execute()
    if not pub_res.data:
        return jsonify({"status": "error", "mensaje": "No se pudo guardar la publicación"}), 500

    publicacion_id = pub_res.data[0]["id"]

    # 2. Insertar autores si no existen
    autor_ids = []
    for autor in autores:
        doc = autor.get("documento")
        nombre = autor.get("nombre")
        if not doc or not nombre:
            continue

        # buscar si existe
        existe = supabase.table(TBL_AUTORES).select("id").eq("documento", doc).execute()
        if existe.data:
            autor_id = existe.data[0]["id"]
        else:
            ahora = datetime.now()
            fecha = ahora.date().isoformat()
            hora = ahora.time().strftime("%H:%M:%S")
            autor_insert = {
                "documento": doc,
                "nombre": nombre,
                "fecha_ultimo_diligenciamiento": fecha,
                "hora_ultimo_diligenciamiento": hora,
            }
            nuevo = supabase.table(TBL_AUTORES).insert(autor_insert).select("id").execute()
            autor_id = nuevo.data[0]["id"] if nuevo.data else None

        if autor_id:
            autor_ids.append(autor_id)

    # 3. Insertar relaciones en matriz_intermedia
    if autor_ids:
        relaciones = [{COL_MAT_PUB_ID: publicacion_id, COL_MAT_AUT_ID: aid} for aid in autor_ids]
        supabase.table(TBL_MATRIZ).insert(relaciones).execute()

    return jsonify({"status": "ok", "publicacion_id": publicacion_id, "autor_ids": autor_ids})

# -------------------------
# Main
# -------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
