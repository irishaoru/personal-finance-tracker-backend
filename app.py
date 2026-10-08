"""Minimal Flask backend for one Sandbox demo account."""
from datetime import date, datetime, timedelta
import json
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from plaid.exceptions import ApiException
from urllib3.exceptions import HTTPError
from werkzeug.exceptions import HTTPException

from plaid_service import PlaidService

load_dotenv()
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024
CORS(app, resources={r'/api/*': {
    'origins': os.environ.get('FRONTEND_ORIGIN', 'http://localhost:5173')
}})
service = PlaidService()


@app.before_request
def require_credentials():
    if request.method == 'OPTIONS':
        return None
    if (request.path.startswith('/api/plaid/') or
            request.path == '/api/transactions') and not service.configured:
        return jsonify(error='PLAID_NOT_CONFIGURED', message=
                       'Set PLAID_CLIENT_ID and PLAID_SECRET in .env, then restart.'), 503


@app.get('/api/health')
def health():
    return jsonify(status='ok', environment='sandbox',
                   plaid_configured=service.configured,
                   connected=service.access_token is not None)


@app.post('/api/plaid/link-token')
def link_token():
    return jsonify(service.create_link_token())


@app.post('/api/plaid/sandbox-public-token')
def sandbox_public_token():
    return jsonify(service.create_sandbox_public_token())


@app.post('/api/plaid/exchange-token')
def exchange_token():
    body = request.get_json(silent=True)
    token = body.get('public_token') if isinstance(body, dict) else None
    if not isinstance(token, str) or not token.startswith('public-sandbox-'):
        return jsonify(error='INVALID_PUBLIC_TOKEN', message=
                       'Send JSON with a public_token from Plaid Sandbox.'), 400
    return jsonify(service.exchange_token(token))


@app.get('/api/transactions')
def transactions():
    if service.access_token is None:
        return jsonify(error='ACCOUNT_NOT_CONNECTED', message=
                       'Exchange a Sandbox public token first.'), 409
    try:
        end_text = request.args.get('end_date', date.today().isoformat())
        start_text = request.args.get(
            'start_date', (date.today() - timedelta(days=90)).isoformat())
        start = datetime.strptime(start_text, '%Y-%m-%d').date()
        end = datetime.strptime(end_text, '%Y-%m-%d').date()
        if (start.isoformat() != start_text or end.isoformat() != end_text or
                start > end):
            raise ValueError
    except ValueError:
        return jsonify(error='INVALID_DATE_RANGE', message=
                       'Use YYYY-MM-DD dates with start_date <= end_date.'), 400
    return jsonify(service.get_transactions(start, end))


@app.errorhandler(ApiException)
def plaid_error(error):
    # Do not log the exception: SDK details can contain credentials or tokens.
    try:
        details = json.loads(error.body or '{}')
    except (ValueError, TypeError):
        details = {}
    code = details.get('error_code', 'PLAID_ERROR')
    if code == 'PRODUCT_NOT_READY':
        return jsonify(error=code, message=
                       'Plaid is preparing fake transactions. Try again shortly.'), 503
    return jsonify(error=code, message=
                   'Plaid could not complete the request. Check your Sandbox setup.'), 502


@app.errorhandler(HTTPError)
def network_error(error):
    return jsonify(error='PLAID_UNAVAILABLE', message=
                   'Could not reach Plaid. Try again shortly.'), 502


@app.errorhandler(HTTPException)
def http_error(error):
    return jsonify(error=error.name, message=error.description), error.code


@app.errorhandler(Exception)
def unexpected_error(error):
    return jsonify(error='SERVER_ERROR', message=
                   'The server could not complete the request.'), 500


if __name__ == '__main__':
    # One local process; debug mode and its interactive debugger stay disabled.
    app.run(host='127.0.0.1', port=int(os.environ.get('PORT', '3001')))
