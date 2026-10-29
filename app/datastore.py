import json
import os
import re

import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')

GROUPABLE = {
    'date': 'date',
    'month': None,
    'year_of_sale': None,
    'genre': 'genre',
    'publisher': 'publisher',
    'author_label': 'author_label',
    'title': 'title',
    'book_id': 'book_id',
    'person_id': 'person_id',
    'currency': 'currency',
    'n_authors': 'n_authors',
    'publication_year': 'year',
}

METRICS = ['revenue', 'units', 'orders', 'avg_order_value',
           'unique_books', 'unique_customers']


class DataStore:
    def __init__(self, data_dir=DATA_DIR):
        self.data_dir = data_dir
        with open(os.path.join(data_dir, 'metrics.json'), encoding='utf-8') as handle:
            self.metrics = json.load(handle)
        self.store_names = sorted(self.metrics)
        self.tables = {}

    def table(self, store, name):
        key = (store, name)
        if key not in self.tables:
            path = os.path.join(self.data_dir, f'{store}_{name}.csv.gz')
            frame = pd.read_csv(path, compression='gzip')
            if name == 'orders':
                frame['timestamp'] = pd.to_datetime(frame['timestamp'])
            self.tables[key] = frame
        return self.tables[key]

    def resolve_store(self, store):
        if store is None:
            return self.store_names[0]
        wanted = str(store).strip().upper().replace(' ', '')
        for name in self.store_names:
            if name.upper() == wanted:
                return name
        digits = re.sub(r'\D', '', wanted)
        if digits:
            candidate = f'STORE{int(digits)}'
            if candidate in self.store_names:
                return candidate
        raise ValueError(f'unknown store {store!r}; available: {self.store_names}')

    def orders(self, store):
        return self.table(self.resolve_store(store), 'orders')

    def users(self, store):
        return self.table(self.resolve_store(store), 'users')

    def books(self, store):
        return self.table(self.resolve_store(store), 'books')

    def headline(self, store):
        return self.metrics[self.resolve_store(store)]


def contains(series, needle):
    return series.fillna('').str.contains(re.escape(str(needle)), case=False, regex=True)


def apply_order_filters(orders, filters):
    filters = filters or {}
    keep = pd.Series(True, index=orders.index)

    if filters.get('date_from'):
        keep &= orders['date'] >= str(filters['date_from'])
    if filters.get('date_to'):
        keep &= orders['date'] <= str(filters['date_to'])

    for field in ['genre', 'publisher', 'currency']:
        wanted = filters.get(field)
        if wanted:
            keep &= orders[field].isin(wanted if isinstance(wanted, list) else [wanted])

    if filters.get('title_contains'):
        keep &= contains(orders['title'], filters['title_contains'])
    if filters.get('author_contains'):
        keep &= contains(orders['author_label'], filters['author_contains'])
    if filters.get('min_quantity'):
        keep &= orders['quantity'] >= int(filters['min_quantity'])
    if filters.get('book_ids'):
        keep &= orders['book_id'].isin([int(value) for value in filters['book_ids']])
    if filters.get('person_ids'):
        keep &= orders['person_id'].isin([int(value) for value in filters['person_ids']])
    if filters.get('year_min'):
        keep &= orders['year'].fillna(-1) >= int(filters['year_min'])
    if filters.get('year_max'):
        keep &= orders['year'].fillna(99999) <= int(filters['year_max'])

    return orders[keep]


def measure(grouped, metric):
    if metric == 'revenue':
        return grouped['paid_price'].sum().round(2)
    if metric == 'units':
        return grouped['quantity'].sum()
    if metric == 'orders':
        return grouped.size()
    if metric == 'avg_order_value':
        return grouped['paid_price'].mean().round(2)
    if metric == 'unique_books':
        return grouped['book_id'].nunique()
    return grouped['person_id'].nunique()


def grouped_aggregate(orders, group_by, metric='revenue', order='desc', limit=20,
                      sort='value'):
    if group_by not in GROUPABLE:
        raise ValueError(f'cannot group by {group_by!r}; options: {sorted(GROUPABLE)}')
    if metric not in METRICS:
        raise ValueError(f'unknown metric {metric!r}; options: {METRICS}')

    working = orders.copy()
    if group_by == 'month':
        working['group_key'] = working['timestamp'].dt.strftime('%Y-%m')
    elif group_by == 'year_of_sale':
        working['group_key'] = working['timestamp'].dt.year
    else:
        working['group_key'] = working[GROUPABLE[group_by]]

    series = measure(working.groupby('group_key', dropna=False), metric)
    if sort == 'key':
        series = series.sort_index(ascending=(order != 'desc'))
    else:
        series = series.sort_values(ascending=(order == 'asc'))
    if limit:
        series = series.head(int(limit))

    return [{'group': None if pd.isna(key) else unwrap(key), metric: unwrap(value)}
            for key, value in series.items()]


def unwrap(value):
    return value.item() if hasattr(value, 'item') else value
