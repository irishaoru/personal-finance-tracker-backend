"""Persistence and API behavior against isolated SQLite databases."""
from datetime import date
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from database import TransactionStore, configured_store
import test_backend
import app


class StorageTests(unittest.TestCase):
    def test_persists_after_reopening(self):
        with tempfile.TemporaryDirectory() as folder:
            url = 'sqlite:///' + str(Path(folder) / 'test.db')
            store = TransactionStore(url)
            store.add_manual({'name': 'Cash coffee', 'amount': Decimal('4.25'),
                              'date': date(2026, 10, 7), 'category': 'FOOD',
                              'currency': 'USD'})
            store.engine.dispose()
            reopened = TransactionStore(url)
            try:
                rows = reopened.list_transactions()
                self.assertEqual(rows[0]['amount'], 4.25)
                self.assertEqual(rows[0]['date'], '2026-10-07')
            finally:
                reopened.engine.dispose()

    def test_import_updates_without_duplicates_and_replaces_pending(self):
        store = TransactionStore('sqlite:///:memory:')
        self.addCleanup(store.engine.dispose)
        item = {'transaction_id': 'pending-id', 'date': '2026-10-07',
                'name': 'Lunch', 'amount': 10, 'pending': True}
        store.import_plaid([item])
        item.update(transaction_id='posted-id', pending_transaction_id='pending-id',
                    amount=12.50, pending=False)
        store.import_plaid([item])
        item['amount'] = 13
        store.import_plaid([item])
        rows = store.list_transactions()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['transaction_id'], 'posted-id')
        self.assertEqual(rows[0]['amount'], 13)

    def test_failed_import_rolls_back(self):
        store = TransactionStore('sqlite:///:memory:')
        self.addCleanup(store.engine.dispose)
        item = {'transaction_id': 'a', 'date': '2026-10-07', 'name': 'Lunch', 'amount': 10}
        with self.assertRaises(KeyError):
            store.import_plaid([item, {}])
        self.assertEqual(store.list_transactions(), [])

    def test_render_requires_postgresql(self):
        with patch.dict('os.environ', {'RENDER': 'true', 'DATABASE_URL': ''}):
            with self.assertRaises(ValueError):
                configured_store()


class DatabaseApiTests(unittest.TestCase):
    setUp = test_backend.BackendTests.setUp
    def test_manual_entries_work_without_plaid(self):
        self.service.client = None
        payload = {'name': 'Cash lunch', 'date': '2026-10-07', 'amount': '12.50'}
        response = self.client.post('/api/transactions', json=payload)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()['source'], 'manual')
        rows = self.client.get('/api/transactions').get_json()['transactions']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['amount'], 12.50)
        self.assertEqual(self.client.get(
            '/api/transactions?end_date=2026-10-06').get_json()['transactions'], [])

    def test_invalid_purchases_are_not_saved(self):
        payload = {'name': 'Lunch', 'date': '2026-10-07', 'amount': '12.50'}
        for amount in [True, 0, -1, 'NaN', 'Infinity', '1.001', '1000000000000']:
            self.assertEqual(self.client.post('/api/transactions',
                json=dict(payload, amount=amount)).status_code, 400)
        for fields in [{'date': '2026-02-30'}, {'name': ''}, {'currency': 3}]:
            self.assertEqual(self.client.post('/api/transactions',
                json=dict(payload, **fields)).status_code, 400)
        self.assertEqual(self.store.list_transactions(), [])

    def test_import_endpoint_saves_records(self):
        self.service.access_token = 'fake'
        records = [{'transaction_id': 'bank-1', 'date': date(2026, 10, 7),
                    'name': 'Lunch', 'amount': 10, 'iso_currency_code': 'USD'}]
        with patch.object(self.service, 'get_transactions',
                          return_value={'transactions': records}):
            for _ in range(2):
                self.assertEqual(self.client.post('/api/transactions/import').status_code, 200)
        self.assertEqual(len(self.store.list_transactions()), 1)
        self.service.access_token = None
        self.assertEqual(self.client.get('/api/transactions').status_code, 200)


if __name__ == '__main__':
    unittest.main()
