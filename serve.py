from flask import Flask, jsonify
import os
from main import buttermilk_checker_v2_function

app = Flask(__name__)

@app.get("/health")
def health():
    return jsonify({"ok": True})

@app.get("/check")
def check():
    # Your function ignores the request body, so pass None
    result = buttermilk_checker_v2_function(None)
    return jsonify({"status": result})

@app.get("/")
def root():
    return jsonify({"message": "OK. Use /check to run the stock checker, /health for liveness."})
