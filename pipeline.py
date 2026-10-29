import collections
import glob
import os

import pandas as pd
import yaml

from parsers import parse_price, parse_timestamp, split_authors

NULLISH = {'', 'null', 'none', 'nan', 'nat', '-', 'n/a', 'na'}
IDENTITY_FIELDS = ['name', 'address', 'phone', 'email']
MISSING = '\x00MISSING'


def blank_to_none(value):
    if value is None:
        return None
    text = str(value).strip()
    return None if text.lower() in NULLISH else text


def load_orders(path):
    orders = pd.read_parquet(os.path.join(path, 'orders.parquet'))
    orders = orders.drop_duplicates(subset=['id'], keep='first').copy()

    parsed = orders['unit_price'].map(parse_price)
    orders['unit_price_usd'] = [float(amount) if amount is not None else None
                                for amount, _ in parsed]
    orders['currency'] = [currency for _, currency in parsed]

    orders['timestamp'] = pd.to_datetime(orders['timestamp'].map(parse_timestamp))
    orders['quantity'] = pd.to_numeric(orders['quantity'], errors='coerce').astype('Int64')
    orders['shipping'] = orders['shipping'].map(blank_to_none)

    orders['paid_price'] = (orders['quantity'].astype('float') *
                            orders['unit_price_usd']).round(2)

    orders['date'] = orders['timestamp'].dt.date
    orders['year'] = orders['timestamp'].dt.year.astype('Int64')
    orders['month'] = orders['timestamp'].dt.month.astype('Int64')
    orders['day'] = orders['timestamp'].dt.day.astype('Int64')

    usable = orders['timestamp'].notna() & orders['paid_price'].notna()
    return orders[usable].reset_index(drop=True), int((~usable).sum())


def reconcile_users(users):
    parent = list(range(len(users)))

    def find(node):
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left, right):
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    records = users[IDENTITY_FIELDS].fillna(MISSING).to_dict('records')
    for omitted in IDENTITY_FIELDS:
        buckets = collections.defaultdict(list)
        for position, record in enumerate(records):
            key = tuple(record[field] for field in IDENTITY_FIELDS if field != omitted)
            buckets[key].append(position)
        for positions in buckets.values():
            for position in positions[1:]:
                union(positions[0], position)

    roots = [find(position) for position in range(len(users))]
    person_numbers = {}
    for root in roots:
        person_numbers.setdefault(root, len(person_numbers))

    users = users.copy()
    users['person_id'] = [person_numbers[root] for root in roots]
    return users


def load_users(path):
    users = pd.read_csv(os.path.join(path, 'users.csv'), dtype=str)
    users = users.drop_duplicates(subset=['id'], keep='first').copy()
    for field in IDENTITY_FIELDS:
        users[field] = users[field].map(blank_to_none)
    users['id'] = pd.to_numeric(users['id'], errors='coerce').astype('Int64')
    return reconcile_users(users).reset_index(drop=True)


def load_books(path):
    with open(os.path.join(path, 'books.yaml'), encoding='utf-8') as handle:
        entries = yaml.safe_load(handle)

    books = pd.DataFrame(entries).rename(columns=lambda name: str(name).lstrip(':'))
    books = books.drop_duplicates(subset=['id'], keep='first').copy()

    books['id'] = pd.to_numeric(books['id'], errors='coerce').astype('Int64')
    books['year'] = pd.to_numeric(books['year'], errors='coerce').astype('Int64')
    for field in ['title', 'author', 'genre', 'publisher']:
        books[field] = books[field].map(blank_to_none)

    books['author_set'] = books['author'].map(split_authors)
    books['author_label'] = books['author_set'].map(
        lambda names: ', '.join(sorted(name.title() for name in names)))
    return books.reset_index(drop=True)


def load_store(path):
    orders, dropped = load_orders(path)
    return {
        'name': os.path.basename(path.rstrip('/')),
        'orders': orders,
        'users': load_users(path),
        'books': load_books(path),
        'dropped_orders': dropped,
    }


def compute_metrics(store):
    orders, users, books = store['orders'], store['users'], store['books']

    daily = (orders.groupby('date', as_index=False)['paid_price']
             .sum().sort_values('date').reset_index(drop=True))
    daily['date'] = daily['date'].map(lambda value: value.strftime('%Y-%m-%d'))
    top_days = daily.sort_values(['paid_price', 'date'], ascending=[False, True]).head(5)

    sold = orders.merge(books[['id', 'author_set', 'author_label']],
                        left_on='book_id', right_on='id', how='left',
                        suffixes=('', '_book'))
    by_author_set = (sold.dropna(subset=['author_label'])
                     .groupby('author_label', as_index=False)['quantity'].sum()
                     .sort_values(['quantity', 'author_label'], ascending=[False, True]))

    by_author = collections.Counter()
    for names, quantity in zip(sold['author_set'], sold['quantity']):
        if isinstance(names, frozenset):
            for name in names:
                by_author[name] += int(quantity)
    best_author = max(by_author.items(), key=lambda item: (item[1], item[0])) if by_author else None

    person_of_user = dict(zip(users['id'].astype('int64'), users['person_id']))
    spending = orders.copy()
    spending['person_id'] = spending['user_id'].map(person_of_user)
    by_person = (spending.dropna(subset=['person_id'])
                 .groupby('person_id', as_index=False)['paid_price'].sum()
                 .sort_values('paid_price', ascending=False))
    best_person = by_person.iloc[0]
    best_person_rows = users[users['person_id'] == best_person['person_id']]

    return {
        'store': store['name'],
        'rows': {'orders': int(len(orders)), 'users': int(len(users)),
                 'books': int(len(books)), 'dropped_orders': store['dropped_orders']},
        'total_revenue': round(float(orders['paid_price'].sum()), 2),
        'top_5_days': [{'date': row['date'], 'revenue': round(float(row['paid_price']), 2)}
                       for _, row in top_days.iterrows()],
        'unique_users': int(users['person_id'].nunique()),
        'raw_user_records': int(len(users)),
        'unique_author_sets': len(set(books['author_set']) - {frozenset()}),
        'most_popular_author_set': {
            'authors': by_author_set.iloc[0]['author_label'],
            'books_sold': int(by_author_set.iloc[0]['quantity']),
        },
        'most_popular_single_author': {
            'author': best_author[0].title(), 'books_sold': int(best_author[1]),
        } if best_author else None,
        'best_buyer': {
            'user_ids': sorted(int(value) for value in best_person_rows['id']),
            'names': sorted({value for value in best_person_rows['name'] if value}),
            'total_spent': round(float(best_person['paid_price']), 2),
        },
        'daily_revenue': [{'date': row['date'], 'revenue': round(float(row['paid_price']), 2)}
                          for _, row in daily.iterrows()],
    }


def all_stores(root='data'):
    return sorted(glob.glob(os.path.join(root, 'STORE*')))
