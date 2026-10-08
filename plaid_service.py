"""Sandbox API calls and the single demo account's in-memory token."""
import os

import certifi
import plaid
from plaid.api import plaid_api
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.sandbox_public_token_create_request import SandboxPublicTokenCreateRequest
from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions


class PlaidService:
    def __init__(self):
        if os.environ.get('PLAID_ENV', 'sandbox') != 'sandbox':
            raise ValueError('This project supports PLAID_ENV=sandbox only.')
        self.access_token = None
        self.client = None
        client_id = os.environ.get('PLAID_CLIENT_ID', '').strip()
        secret = os.environ.get('PLAID_SECRET', '').strip()
        if client_id and secret:
            configuration = plaid.Configuration(
                host=plaid.Environment.Sandbox,
                ssl_ca_cert=certifi.where(),
                api_key={'clientId': client_id, 'secret': secret},
            )
            self.client = plaid_api.PlaidApi(plaid.ApiClient(configuration))

    @property
    def configured(self):
        return self.client is not None

    def create_link_token(self):
        response = self.client.link_token_create(LinkTokenCreateRequest(
            user=LinkTokenCreateRequestUser(client_user_id='sandbox-demo'),
            client_name='Personal Finance Behavior Dashboard',
            products=[Products('transactions')],
            country_codes=[CountryCode('US')],
            language='en',
        ), _request_timeout=20)
        return {'link_token': response['link_token'],
                'expiration': response['expiration'].isoformat()}

    def create_sandbox_public_token(self):
        response = self.client.sandbox_public_token_create(
            SandboxPublicTokenCreateRequest(
                institution_id='ins_109508',
                initial_products=[Products('transactions')],
            ), _request_timeout=20)
        return {'public_token': response['public_token']}

    def exchange_token(self, public_token):
        response = self.client.item_public_token_exchange(
            ItemPublicTokenExchangeRequest(public_token=public_token),
            _request_timeout=20,
        )
        # Never return this token to the browser or save it to disk.
        self.access_token = response['access_token']
        return {'connected': True}

    def get_transactions(self, start_date, end_date):
        # Capture the token so every page uses the same account.
        token = self.access_token
        transactions = []
        while True:
            response = self.client.transactions_get(TransactionsGetRequest(
                access_token=token, start_date=start_date, end_date=end_date,
                options=TransactionsGetRequestOptions(
                    count=500, offset=len(transactions)),
            ), _request_timeout=20)
            page = response.to_dict()
            batch = page['transactions']
            transactions.extend(batch)
            if len(transactions) >= page['total_transactions']:
                return {'transactions': transactions,
                        'accounts': page['accounts'],
                        'total_transactions': len(transactions)}
            if not batch:
                raise RuntimeError('Plaid returned an incomplete transaction page.')
