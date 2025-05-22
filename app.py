from flask import Flask, request, jsonify
from pymongo import MongoClient
from dotenv import load_dotenv
import os
import datetime
import requests

# Cargar variables de entorno
load_dotenv()

# MongoDB
client_mongo = MongoClient(os.getenv("MONGO_URI"))
db = client_mongo["mcp_db"]
conversations = db["conversations"]

# Flask app
app = Flask(__name__)

# Construir contexto desde historial en MongoDB
def build_context(user_id):
    history = conversations.find({"user_id": user_id}).sort("timestamp", -1).limit(10)
    return [
        {"role": msg["role"], "content": msg["content"]}
        for msg in reversed(list(history))
    ]

# Llamar al LLM 
def ask_openrouter(context, user_input, model="openai/gpt-3.5-turbo"):
    headers = {
        "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
        "Content-Type": "application/json",
        "X-Title": "mcp-server"
    }

    messages = (
        [{"role": "system", "content": "Eres un asistente de IA que responde siempre en español de forma clara y profesional."}]
        + context
        + [{"role": "user", "content": user_input}]
    )

    data = {"model": model, "messages": messages}

    response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=data)
    return response.json()["choices"][0]["message"]["content"]

# Traducir lenguaje natural a comando MongoDB
def translate_to_mongo(user_input):
    headers = {
        "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
        "Content-Type": "application/json",
        "X-Title": "mcp-server"
    }

    prompt = f"""
Eres un asistente que traduce instrucciones en lenguaje natural a comandos de Python usando PyMongo.

Solo responde con el código MongoDB sin explicaciones, por ejemplo:
db.usuarios.insert_one({{"nombre": "Juan", "edad": 30}})
db.usuarios.find({{}})
db.usuarios.drop()

El usuario dijo: {user_input}
"""

    data = {
        "model": "openai/gpt-3.5-turbo",
        "messages": [
            {"role": "system", "content": "Responde con código válido de PyMongo solamente."},
            {"role": "user", "content": prompt}
        ]
    }

    response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=data)
    return response.json()["choices"][0]["message"]["content"] # type: ignore

# Endpoint principal
@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    user_id = data["user_id"]
    user_input = data["message"]

    # Detectar si es una orden MongoDB
    if any(p in user_input.lower() for p in ["inserta", "muestra", "cuántos", "elimina", "borra", "crear base de datos", "colección"]):
        mongo_code = translate_to_mongo(user_input)
        print("Comando MongoDB generado:", mongo_code)

        try:
            # Ejecutar en entorno seguro
            result = eval(mongo_code, {"__builtins__": {}}, {"db": db})

            # Interpretar el resultado
            if hasattr(result, "inserted_id"):
                reply = f" Documento insertado con ID: {result.inserted_id}"
            elif hasattr(result, "deleted_count"):
                reply = f" Se eliminaron {result.deleted_count} documentos."
            elif hasattr(result, "next"):  # es un cursor de find()
                reply = " Documentos encontrados:\n" + "\n".join([str(doc) for doc in result])
            else:
                reply = " Comando ejecutado correctamente."

        except Exception as e:
            reply = f" Error al ejecutar el comando: {str(e)}"

    else:
        # Flujo normal de conversación
        context = build_context(user_id)
        reply = ask_openrouter(context, user_input)

    # Guardar conversación
    conversations.insert_many([
        {"user_id": user_id, "role": "user", "content": user_input, "timestamp": datetime.datetime.utcnow()},
        {"user_id": user_id, "role": "assistant", "content": reply, "timestamp": datetime.datetime.utcnow()}
    ])

    return jsonify({"response": reply})

# Ejecutar server
if __name__ == "__main__":
    print("MCP Server conectado a OpenRouter y MongoDB corriendo en http://localhost:5000")
    app.run(debug=True, port=5000)
