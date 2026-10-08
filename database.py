"""One transaction table, using SQLite locally or PostgreSQL on Render."""
from datetime import date
from decimal import Decimal
import os
from pathlib import Path
from uuid import uuid4

from sqlalchemy import (Boolean, Column, Date, MetaData, Numeric, String, Table,
                        create_engine, delete, select, text)
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

metadata = MetaData()
transactions = Table(
    'transactions', metadata,
    Column('transaction_id', String(200), primary_key=True),
    Column('date', Date, nullable=False),
    Column('name', String(200), nullable=False),
    Column('amount', Numeric(14, 2), nullable=False),
    Column('category', String(100), nullable=False),
    Column('source', String(10), nullable=False),
    Column('currency', String(10), nullable=False),
    Column('pending', Boolean, nullable=False, default=False),
    Column('account_id', String(200)),
)


class TransactionStore:
    def __init__(self, url):
        if url.startswith(('postgres://', 'postgresql://')):
            url = 'postgresql+psycopg://' + url.split('://', 1)[1]
        self.engine = create_engine(url, pool_pre_ping=True)
        if self.engine.dialect.name not in ('sqlite', 'postgresql'):
            raise ValueError('Use SQLite or PostgreSQL for this project.')
        metadata.create_all(self.engine)

    def check_connection(self):
        with self.engine.connect() as connection:
            connection.execute(text('SELECT 1'))

    def list_transactions(self, start=None, end=None):
        query = select(transactions)
        if start:
            query = query.where(transactions.c.date >= start)
        if end:
            query = query.where(transactions.c.date <= end)
        query = query.order_by(transactions.c.date.desc(), transactions.c.transaction_id)
        with self.engine.connect() as connection:
            rows = connection.execute(query).mappings().all()
        return [self.serialize(row) for row in rows]

    @staticmethod
    def serialize(row):
        result = dict(row)
        result['date'] = result['date'].isoformat()
        result['amount'] = float(result['amount'])
        return result

    def add_manual(self, fields):
        record = dict(fields, transaction_id='manual-' + str(uuid4()),
                      source='manual', pending=False, account_id=None)
        with self.engine.begin() as connection:
            connection.execute(transactions.insert().values(**record))
        return self.serialize(record)

    def import_plaid(self, records):
        # One database transaction makes the whole import succeed or roll back.
        insert = (sqlite_insert if self.engine.dialect.name == 'sqlite'
                  else postgres_insert)
        with self.engine.begin() as connection:
            for item in records:
                category = item.get('personal_finance_category') or {}
                record = {
                    'transaction_id': item['transaction_id'],
                    'date': (item['date'] if isinstance(item['date'], date)
                             else date.fromisoformat(item['date'])),
                    'name': item['name'],
                    'amount': Decimal(str(item['amount'])),
                    'category': category.get('primary') or 'OTHER',
                    'source': 'plaid',
                    'currency': (item.get('iso_currency_code') or
                                 item.get('unofficial_currency_code') or 'UNKNOWN'),
                    'pending': item.get('pending', False),
                    'account_id': item.get('account_id'),
                }
                # Posted transactions can replace a previous pending ID.
                pending_id = item.get('pending_transaction_id')
                if pending_id:
                    connection.execute(delete(transactions).where(
                        transactions.c.transaction_id == pending_id,
                        transactions.c.source == 'plaid'))
                statement = insert(transactions).values(**record)
                statement = statement.on_conflict_do_update(
                    index_elements=['transaction_id'],
                    set_={key: statement.excluded[key] for key in record
                          if key != 'transaction_id'},
                )
                connection.execute(statement)
        return len(records)


def configured_store():
    url = os.environ.get('DATABASE_URL', '').strip()
    if os.environ.get('RENDER') and not url.startswith(
            ('postgres://', 'postgresql://', 'postgresql+psycopg://')):
        raise ValueError('Set a PostgreSQL DATABASE_URL on Render.')
    if not url:
        url = 'sqlite:///' + str(Path(__file__).with_name('finance.db'))
    return TransactionStore(url)
