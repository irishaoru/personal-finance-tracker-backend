"""Offline checks; these do not prove live Plaid connectivity."""
from datetime import date
import unittest
from unittest.mock import Mock, patch

import app
from plaid_service import PlaidService


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.service = PlaidService()
        self.service.client = Mock()
        self.patcher = patch.object(app, 'service', self.service)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.client = app.app.test_client()

    def test_missing_credentials(self):
        self.service.client = None
        self.assertEqual(self.client.get('/api/health').status_code, 200)
        for path in ['link-token', 'sandbox-public-token', 'exchange-token']:
            self.assertEqual(self.client.post('/api/plaid/' + path).status_code, 503)

    def test_exchange_validation_and_token_privacy(self):
        for body in [[], {}, {'public_token': 4}, {'public_token': 'public-production-x'}]:
            self.assertEqual(self.client.post(
                '/api/plaid/exchange-token', json=body).status_code, 400)
        self.service.client.item_public_token_exchange.return_value = {
            'access_token': 'test-token-never-returned'}
        response = self.client.post('/api/plaid/exchange-token',
                                    json={'public_token': 'public-sandbox-test'})
        self.assertEqual(response.get_json(), {'connected': True})
        self.assertEqual(self.service.access_token, 'test-token-never-returned')

    def test_connection_and_date_validation(self):
        self.assertEqual(self.client.get('/api/transactions').status_code, 409)
        self.service.access_token = 'test-token'
        for query in ['start_date=bad', 'start_date=2026-02-30',
                      'start_date=2026-03-02&end_date=2026-03-01']:
            self.assertEqual(self.client.get('/api/transactions?' + query).status_code, 400)
        self.service.client.transactions_get.assert_not_called()

    def test_all_pages_are_fetched(self):
        self.service.access_token = 'test-token'
        pages = [Mock(), Mock()]
        pages[0].to_dict.return_value = {
            'transactions': [{'transaction_id': 'a'}], 'total_transactions': 2,
            'accounts': []}
        pages[1].to_dict.return_value = {
            'transactions': [{'transaction_id': 'b'}], 'total_transactions': 2,
            'accounts': []}
        self.service.client.transactions_get.side_effect = pages
        result = self.service.get_transactions(date(2026, 1, 1), date(2026, 2, 1))
        self.assertEqual(len(result['transactions']), 2)
        second_request = self.service.client.transactions_get.call_args_list[1].args[0]
        self.assertEqual(second_request.options.offset, 1)

    def test_only_sandbox_is_allowed(self):
        with patch.dict('os.environ', {'PLAID_ENV': 'production'}):
            with self.assertRaises(ValueError):
                PlaidService()


if __name__ == '__main__':
    unittest.main()
