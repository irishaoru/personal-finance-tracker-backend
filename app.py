"""Minimal Flask backend for one Sandbox demo account."""
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import json
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from plaid.exceptions import ApiException
from urllib3.exceptions import HTTPError
from werkzeug.exceptions import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from plaid_service import PlaidService
from database import configured_store

load_dotenv()
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024
CORS(app, resources={r'/api/*': {
    'origins': os.environ.get('FRONTEND_ORIGIN', 'http://localhost:5173')
}})
service = PlaidService()
store = configured_store()


@app.before_request
def require_credentials():
    if request.method == 'OPTIONS':
        return None
    if (request.path.startswith('/api/plaid/') or
            request.path == '/api/transactions/import') and not service.configured:
        return jsonify(error='PLAID_NOT_CONFIGURED', message=
                       'Set PLAID_CLIENT_ID and PLAID_SECRET in .env, then restart.'), 503


@app.get('/api/health')
def health():
    store.check_connection()
    return jsonify(status='ok', environment='sandbox',
                   database='ok',
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
    try:
        start, end = transaction_dates()
    except ValueError:
        return invalid_dates()
    records = store.list_transactions(start, end)
    return jsonify(transactions=records, total_transactions=len(records))


def transaction_dates(importing=False):
    start_text = request.args.get('start_date')
    end_text = request.args.get('end_date')
    if importing:
        start_text = start_text or (date.today() - timedelta(days=90)).isoformat()
        end_text = end_text or date.today().isoformat()
    start = date.fromisoformat(start_text) if start_text is not None else None
    end = date.fromisoformat(end_text) if end_text is not None else None
    if ((start is not None and start.isoformat() != start_text) or
            (end is not None and end.isoformat() != end_text) or
            (start is not None and end is not None and start > end)):
        raise ValueError
    return start, end


def invalid_dates():
    return jsonify(error='INVALID_DATE_RANGE', message=
                   'Use YYYY-MM-DD dates with start_date <= end_date.'), 400


@app.post('/api/transactions/import')
def import_transactions():
    if service.access_token is None:
        return jsonify(error='ACCOUNT_NOT_CONNECTED', message=
                       'Exchange a Sandbox public token first.'), 409
    try:
        start, end = transaction_dates(importing=True)
    except ValueError:
        return invalid_dates()
    result = service.get_transactions(start, end)
    count = store.import_plaid(result['transactions'])
    return jsonify(imported=count, message='Plaid transactions saved.')


@app.post('/api/transactions')
def add_transaction():
    body = request.get_json(silent=True)
    try:
        if not isinstance(body, dict):
            raise ValueError
        name = body.get('name')
        category = body.get('category', 'OTHER')
        currency = body.get('currency', 'USD')
        if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 200 or
                not isinstance(category, str) or not 1 <= len(category.strip()) <= 100 or
                not isinstance(currency, str) or len(currency) != 3 or
                not currency.isascii() or not currency.isalpha()):
            raise ValueError
        date_text = body.get('date')
        if not isinstance(date_text, str):
            raise ValueError
        purchase_date = date.fromisoformat(date_text)
        if purchase_date.isoformat() != date_text:
            raise ValueError
        if isinstance(body.get('amount'), bool):
            raise ValueError
        amount = Decimal(str(body.get('amount')))
        if (not amount.is_finite() or not 0 < amount <= Decimal('999999999999.99') or
                amount != amount.quantize(Decimal('0.01'))):
            raise ValueError
    except (ValueError, InvalidOperation):
        return jsonify(error='INVALID_TRANSACTION', message=
                       'Send name, YYYY-MM-DD date, and a positive amount with at most '
                       'two decimal places. Optional: category and three-letter currency.'), 400
    record = store.add_manual({'name': name.strip(), 'date': purchase_date,
                               'amount': amount, 'category': category.strip(),
                               'currency': currency.upper()})
    return jsonify(record), 201


@app.errorhandler(SQLAlchemyError)
def database_error(error):
    # SQL errors can contain the connection URL or submitted financial data.
    return jsonify(error='DATABASE_UNAVAILABLE', message=
                   'Could not access saved transactions. Try again shortly.'), 503


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
