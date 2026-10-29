import re

import pandas as pd

from datastore import apply_order_filters, contains, grouped_aggregate

MAX_ROWS = 200

STORE_PROPERTY = {'type': 'string',
                  'description': 'Store name such as STORE1. Defaults to the active store.'}

ORDER_FILTERS = {
    'type': 'object',
    'description': 'Optional filters applied before aggregating.',
    'properties': {
        'date_from': {'type': 'string', 'description': 'YYYY-MM-DD inclusive'},
        'date_to': {'type': 'string', 'description': 'YYYY-MM-DD inclusive'},
        'genre': {'type': 'string'},
        'publisher': {'type': 'string'},
        'currency': {'type': 'string', 'enum': ['USD', 'EUR']},
        'title_contains': {'type': 'string'},
        'author_contains': {'type': 'string'},
        'year_min': {'type': 'integer', 'description': 'book publication year'},
        'year_max': {'type': 'integer', 'description': 'book publication year'},
        'book_ids': {'type': 'array', 'items': {'type': 'integer'}},
    },
}


def list_stores(data, **_):
    return {'stores': [{'store': name,
                        'orders': data.metrics[name]['rows']['orders'],
                        'revenue_usd': data.metrics[name]['total_revenue']}
                       for name in data.store_names]}


def headline_metrics(data, store=None, **_):
    metrics = data.headline(store)
    return {
        'store': metrics['store'],
        'top_5_days_by_revenue': metrics['top_5_days'],
        'unique_users_after_reconciliation': metrics['unique_users'],
        'raw_user_records': metrics['raw_user_records'],
        'unique_author_sets': metrics['unique_author_sets'],
        'most_popular_author_set': metrics['most_popular_author_set'],
        'most_popular_single_author': metrics['most_popular_single_author'],
        'best_buyer': metrics['best_buyer'],
        'total_revenue_usd': metrics['total_revenue'],
        'days_with_sales': len(metrics['daily_revenue']),
    }


def revenue_summary(data, store=None, filters=None, **_):
    name = data.resolve_store(store)
    orders = apply_order_filters(data.orders(name), filters)
    if orders.empty:
        return {'store': name, 'orders': 0, 'note': 'no orders match these filters'}
    return {
        'store': name,
        'orders': int(len(orders)),
        'units_sold': int(orders['quantity'].sum()),
        'revenue_usd': round(float(orders['paid_price'].sum()), 2),
        'avg_order_value_usd': round(float(orders['paid_price'].mean()), 2),
        'unique_books': int(orders['book_id'].nunique()),
        'unique_customers': int(orders['person_id'].nunique()),
        'first_date': orders['date'].min(),
        'last_date': orders['date'].max(),
    }


def aggregate(data, store=None, group_by='date', metric='revenue',
              order='desc', limit=20, filters=None, **_):
    name = data.resolve_store(store)
    orders = apply_order_filters(data.orders(name), filters)
    return {'store': name, 'group_by': group_by, 'metric': metric,
            'rows': grouped_aggregate(orders, group_by, metric, order,
                                      min(int(limit), MAX_ROWS))}


def search_books(data, store=None, title_contains=None, author_contains=None,
                 genre=None, publisher=None, year_min=None, year_max=None,
                 n_authors=None, order_by='units_sold', limit=25, **_):
    name = data.resolve_store(store)
    books = data.books(name).copy()

    keep = pd.Series(True, index=books.index)
    if title_contains:
        keep &= contains(books['title'], title_contains)
    if author_contains:
        keep &= contains(books['author_label'], author_contains)
    if genre:
        keep &= books['genre'].fillna('').str.lower() == str(genre).lower()
    if publisher:
        keep &= contains(books['publisher'], publisher)
    if year_min is not None:
        keep &= books['year'].fillna(-1) >= int(year_min)
    if year_max is not None:
        keep &= books['year'].fillna(99999) <= int(year_max)
    if n_authors is not None:
        keep &= books['n_authors'] == int(n_authors)
    books = books[keep]

    sold = (data.orders(name).groupby('book_id')
            .agg(units_sold=('quantity', 'sum'), revenue_usd=('paid_price', 'sum')))
    books = books.merge(sold, left_on='id', right_index=True, how='left')
    books['units_sold'] = books['units_sold'].fillna(0).astype(int)
    books['revenue_usd'] = books['revenue_usd'].fillna(0).round(2)

    column = {'units_sold': 'units_sold', 'revenue': 'revenue_usd',
              'title': 'title', 'year': 'year'}.get(order_by, 'units_sold')
    books = books.sort_values(column, ascending=column in ('title', 'year'))

    matched = int(len(books))
    books = books.head(min(int(limit), MAX_ROWS))
    return {
        'store': name, 'matched_books': matched, 'returned': int(len(books)),
        'books': books[['id', 'title', 'author_label', 'n_authors', 'genre',
                        'publisher', 'year', 'units_sold', 'revenue_usd']].to_dict('records'),
    }


def top_authors(data, store=None, by='units', basis='author_set', limit=10,
                filters=None, **_):
    name = data.resolve_store(store)
    orders = apply_order_filters(data.orders(name), filters)

    if basis == 'author_set':
        return {'store': name,
                'basis': 'author set (collaboration counts as one)',
                'rows': grouped_aggregate(orders, 'author_label',
                                          'units' if by == 'units' else 'revenue',
                                          'desc', min(int(limit), MAX_ROWS))}

    totals = {}
    for label, quantity, paid in zip(orders['author_label'], orders['quantity'],
                                     orders['paid_price']):
        if not isinstance(label, str):
            continue
        for person in label.split(', '):
            running = totals.setdefault(person, {'units': 0, 'revenue': 0.0})
            running['units'] += int(quantity)
            running['revenue'] += float(paid)

    ranked = sorted(totals.items(), key=lambda item: -item[1][by])
    return {'store': name, 'basis': 'individual author',
            'rows': [{'group': person, by: round(values[by], 2)}
                     for person, values in ranked[:min(int(limit), MAX_ROWS)]]}


def search_customers(data, store=None, name_contains=None, email_contains=None,
                     email_starts_with=None, phone_contains=None,
                     address_contains=None, min_spend=None, limit=25, **_):
    store_name = data.resolve_store(store)
    users = data.users(store_name).copy()

    keep = pd.Series(True, index=users.index)
    if name_contains:
        keep &= contains(users['name'], name_contains)
    if email_contains:
        keep &= contains(users['email'], email_contains)
    if email_starts_with:
        keep &= users['email'].fillna('').str.lower().str.startswith(
            tuple(letter.lower() for letter in str(email_starts_with)))
    if phone_contains:
        digits = re.sub(r'\D', '', str(phone_contains))
        keep &= users['phone'].fillna('').str.replace(r'\D', '', regex=True).str.contains(digits)
    if address_contains:
        keep &= contains(users['address'], address_contains)
    users = users[keep]

    spending = (data.orders(store_name).groupby('person_id')
                .agg(total_spent_usd=('paid_price', 'sum'), orders=('id', 'count')))
    people = (users.groupby('person_id')
              .agg(user_ids=('id', lambda values: sorted(int(v) for v in values)),
                   names=('name', lambda values: sorted({v for v in values if isinstance(v, str)})),
                   emails=('email', lambda values: sorted({v for v in values if isinstance(v, str)})))
              .join(spending, how='left'))
    people['total_spent_usd'] = people['total_spent_usd'].fillna(0).round(2)
    people['orders'] = people['orders'].fillna(0).astype(int)

    if min_spend is not None:
        people = people[people['total_spent_usd'] >= float(min_spend)]
    people = people.sort_values('total_spent_usd', ascending=False)

    matched = int(len(people))
    people = people.head(min(int(limit), MAX_ROWS))
    return {'store': store_name, 'matched_people': matched, 'returned': int(len(people)),
            'note': 'one row is one real person; user_ids lists every alias',
            'people': people.reset_index().to_dict('records')}


def customer_detail(data, store=None, user_id=None, person_id=None, **_):
    store_name = data.resolve_store(store)
    users, orders = data.users(store_name), data.orders(store_name)

    if person_id is None:
        if user_id is None:
            raise ValueError('give user_id or person_id')
        match = users[users['id'] == int(user_id)]
        if match.empty:
            return {'store': store_name, 'found': False, 'user_id': int(user_id)}
        person_id = int(match['person_id'].iloc[0])
    person_id = int(person_id)

    aliases = users[users['person_id'] == person_id]
    own_orders = orders[orders['person_id'] == person_id]
    favourites = grouped_aggregate(own_orders, 'title', 'units', 'desc', 5) \
        if not own_orders.empty else []

    def unique(column):
        return sorted({value for value in aliases[column] if isinstance(value, str)})

    return {
        'store': store_name, 'found': True, 'person_id': person_id,
        'user_ids': sorted(int(value) for value in aliases['id']),
        'names': unique('name'), 'emails': unique('email'),
        'phones': unique('phone'), 'addresses': unique('address'),
        'orders': int(len(own_orders)),
        'units_bought': int(own_orders['quantity'].sum()) if not own_orders.empty else 0,
        'total_spent_usd': round(float(own_orders['paid_price'].sum()), 2)
        if not own_orders.empty else 0.0,
        'favourite_books': favourites,
    }


def count_entity(data, store=None, entity='orders', filters=None, **_):
    name = data.resolve_store(store)

    if entity in ('orders', 'units', 'revenue'):
        orders = apply_order_filters(data.orders(name), filters)
        if orders.empty:
            value = 0
        elif entity == 'orders':
            value = int(len(orders))
        elif entity == 'units':
            value = int(orders['quantity'].sum())
        else:
            value = round(float(orders['paid_price'].sum()), 2)
    elif entity == 'unique_people':
        value = int(data.users(name)['person_id'].nunique())
    elif entity == 'user_records':
        value = int(len(data.users(name)))
    elif entity == 'books':
        value = int(len(data.books(name)))
    elif entity == 'author_sets':
        value = int(data.books(name)['author_label'].nunique())
    elif entity == 'genres':
        value = int(data.books(name)['genre'].nunique())
    elif entity == 'publishers':
        value = int(data.books(name)['publisher'].nunique())
    else:
        raise ValueError(f'unknown entity {entity!r}')

    return {'store': name, 'entity': entity, 'count': value}


def list_book_titles(data, store=None, offset=0, limit=120, **_):
    name = data.resolve_store(store)
    books = data.books(name)[['id', 'title']]
    window = books.iloc[int(offset):int(offset) + min(int(limit), MAX_ROWS)]
    return {'store': name, 'total_books': int(len(books)), 'offset': int(offset),
            'returned': int(len(window)), 'titles': window.to_dict('records')}


def set_store(data, store=None, **_):
    return {'ui_action': {'type': 'set_store', 'store': data.resolve_store(store)}}


def set_view(data, view='overview', **_):
    if view not in ('overview', 'revenue', 'catalog'):
        raise ValueError("view must be overview, revenue or catalog")
    return {'ui_action': {'type': 'set_view', 'view': view}}


def set_date_range(data, date_from=None, date_to=None, **_):
    return {'ui_action': {'type': 'set_date_range',
                          'date_from': date_from, 'date_to': date_to}}


def filter_books(data, store=None, book_ids=None, title_contains=None,
                 genre=None, label=None, mode='include', **_):
    if mode not in ('include', 'exclude'):
        raise ValueError("mode must be 'include' or 'exclude'")
    return {'ui_action': {'type': 'filter_books', 'mode': mode,
                          'book_ids': [int(value) for value in (book_ids or [])],
                          'title_contains': title_contains, 'genre': genre,
                          'label': label or 'book filter from chat'}}


def filter_customers(data, store=None, person_ids=None, email_starts_with=None,
                     name_contains=None, min_spend=None, label=None, **_):
    return {'ui_action': {'type': 'filter_customers',
                          'person_ids': [int(value) for value in (person_ids or [])],
                          'email_starts_with': email_starts_with,
                          'name_contains': name_contains, 'min_spend': min_spend,
                          'label': label or 'customer filter from chat'}}


def reset_filters(data, **_):
    return {'ui_action': {'type': 'reset_filters'}}


TOOLS = [
    (list_stores, 'List every store with its order count and total revenue.', {}),
    (headline_metrics,
     'The six headline dashboard numbers for one store: top 5 revenue days, '
     'unique users after reconciliation, unique author sets, most popular author '
     'set, best buyer with all alias ids, total revenue.',
     {'store': STORE_PROPERTY}),
    (revenue_summary,
     'Totals (orders, units, revenue, average order value, unique books and '
     'customers, date span) for a store, optionally filtered.',
     {'store': STORE_PROPERTY, 'filters': ORDER_FILTERS}),
    (aggregate,
     'Group orders and compute a metric per group. Use this for any "per", '
     '"top", "by month", "best selling" or ranking question.',
     {'store': STORE_PROPERTY,
      'group_by': {'type': 'string',
                   'enum': ['date', 'month', 'year_of_sale', 'genre', 'publisher',
                            'author_label', 'title', 'book_id', 'person_id',
                            'currency', 'n_authors', 'publication_year']},
      'metric': {'type': 'string',
                 'enum': ['revenue', 'units', 'orders', 'avg_order_value',
                          'unique_books', 'unique_customers']},
      'order': {'type': 'string', 'enum': ['desc', 'asc']},
      'limit': {'type': 'integer'},
      'filters': ORDER_FILTERS}),
    (search_books,
     'Find books in the catalogue by title, author, genre, publisher, year or '
     'number of authors, with units sold and revenue for each.',
     {'store': STORE_PROPERTY,
      'title_contains': {'type': 'string'}, 'author_contains': {'type': 'string'},
      'genre': {'type': 'string'}, 'publisher': {'type': 'string'},
      'year_min': {'type': 'integer'}, 'year_max': {'type': 'integer'},
      'n_authors': {'type': 'integer'},
      'order_by': {'type': 'string', 'enum': ['units_sold', 'revenue', 'title', 'year']},
      'limit': {'type': 'integer'}}),
    (top_authors,
     'Rank authors by units sold or revenue. basis="author_set" treats a '
     'collaboration as one entity; basis="individual" credits each co-author.',
     {'store': STORE_PROPERTY,
      'by': {'type': 'string', 'enum': ['units', 'revenue']},
      'basis': {'type': 'string', 'enum': ['author_set', 'individual']},
      'limit': {'type': 'integer'}, 'filters': ORDER_FILTERS}),
    (search_customers,
     'Find real customers (after reconciliation) by name, e-mail, phone, '
     'address or minimum spend. Each row lists every alias id for that person.',
     {'store': STORE_PROPERTY,
      'name_contains': {'type': 'string'}, 'email_contains': {'type': 'string'},
      'email_starts_with': {'type': 'string',
                            'description': 'One or more leading letters, e.g. "sp" matches s* and p*'},
      'phone_contains': {'type': 'string'}, 'address_contains': {'type': 'string'},
      'min_spend': {'type': 'number'}, 'limit': {'type': 'integer'}}),
    (customer_detail,
     'Everything about one customer: all alias ids, names, e-mails, phones, '
     'addresses, order count, total spend and favourite books.',
     {'store': STORE_PROPERTY, 'user_id': {'type': 'integer'},
      'person_id': {'type': 'integer'}}),
    (count_entity,
     'An exact count. Use this instead of counting rows yourself.',
     {'store': STORE_PROPERTY,
      'entity': {'type': 'string',
                 'enum': ['orders', 'units', 'revenue', 'unique_people',
                          'user_records', 'books', 'author_sets', 'genres',
                          'publishers']},
      'filters': ORDER_FILTERS}),
    (list_book_titles,
     'Plain list of book ids and titles, paginated. Use it when the question '
     'needs your own reading of the titles, for example deciding which titles '
     'contain a person name, then pass the ids you chose to filter_books.',
     {'store': STORE_PROPERTY, 'offset': {'type': 'integer'},
      'limit': {'type': 'integer'}}),
    (set_store, 'Switch the dashboard to another store.', {'store': STORE_PROPERTY}),
    (set_view, 'Switch the dashboard tab.',
     {'view': {'type': 'string', 'enum': ['overview', 'revenue', 'catalog']}}),
    (set_date_range, 'Restrict every dashboard figure to a date range.',
     {'date_from': {'type': 'string'}, 'date_to': {'type': 'string'}}),
    (filter_books,
     'Filter the catalogue table on the dashboard. Pass explicit book_ids after '
     'you have read the titles, or a title substring or genre.',
     {'store': STORE_PROPERTY,
      'book_ids': {'type': 'array', 'items': {'type': 'integer'}},
      'title_contains': {'type': 'string'}, 'genre': {'type': 'string'},
      'mode': {'type': 'string', 'enum': ['include', 'exclude']},
      'label': {'type': 'string', 'description': 'Short label shown as a chip'}}),
    (filter_customers, 'Filter the customers table on the dashboard.',
     {'store': STORE_PROPERTY,
      'person_ids': {'type': 'array', 'items': {'type': 'integer'}},
      'email_starts_with': {'type': 'string'}, 'name_contains': {'type': 'string'},
      'min_spend': {'type': 'number'}, 'label': {'type': 'string'}}),
    (reset_filters, 'Clear every dashboard filter.', {}),
]

REGISTRY = {function.__name__: function for function, _, _ in TOOLS}


def schemas():
    return [{'name': function.__name__, 'description': description,
             'input_schema': {'type': 'object', 'properties': properties}}
            for function, description, properties in TOOLS]


def call(data, name, arguments, default_store=None):
    if name not in REGISTRY:
        return {'error': f'unknown tool {name}'}

    arguments = dict(arguments or {})
    if default_store and not arguments.get('store'):
        arguments['store'] = default_store

    try:
        return REGISTRY[name](data, **arguments)
    except Exception as error:
        return {'error': f'{type(error).__name__}: {error}'}
