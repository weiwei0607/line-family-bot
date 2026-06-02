import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'scripts'))
from webhook import app as _webhook_app

# Quick sanity route to verify Render is serving this file
from flask import jsonify

@_webhook_app.route("/ping")
def _ping():
    return jsonify({"ping": "pong", "commit": "test"})

app = _webhook_app
