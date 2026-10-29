import json
import os
import sys

from pipeline import all_stores, compute_metrics, load_store

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app', 'data')

ORDER_COLUMNS = [
    'id', 'user_id', 'person_id', 'book_id', 'quantity', 'unit_price_usd',
    'currency', 'paid_price', 'timestamp', 'date', 'has_shipping',
    'title', 'author_label', 'n_authors', 'genre', 'publisher', 'year',
]


def build_store(path):
    store = load_store(path)
    orders, users, books = store['orders'], store['users'], store['books']

    person_of_user = dict(zip(users['id'].astype('int64'), users['person_id']))
    orders = orders.copy()
    orders['person_id'] = orders['user_id'].map(person_of_user).astype('Int64')
    orders['has_shipping'] = orders['shipping'].notna()

    books = books.copy()
    books['n_authors'] = books['author_set'].map(len).astype('Int64')

    orders = orders.merge(
        books[['id', 'title', 'author_label', 'n_authors', 'genre', 'publisher', 'year']],
        left_on='book_id', right_on='id', how='left', suffixes=('', '_book'))
    orders = orders.drop(columns=[c for c in orders.columns if c.endswith('_book')])
    orders['date'] = orders['date'].map(lambda value: value.strftime('%Y-%m-%d'))

    name = store['name']
    orders[ORDER_COLUMNS].to_csv(
        os.path.join(OUTPUT_DIR, f'{name}_orders.csv.gz'), index=False, compression='gzip')
    users[['id', 'person_id', 'name', 'address', 'phone', 'email']].to_csv(
        os.path.join(OUTPUT_DIR, f'{name}_users.csv.gz'), index=False, compression='gzip')
    books[['id', 'title', 'author', 'author_label', 'n_authors',
           'genre', 'publisher', 'year']].to_csv(
        os.path.join(OUTPUT_DIR, f'{name}_books.csv.gz'), index=False, compression='gzip')

    return compute_metrics(store)


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else 'data'
    paths = all_stores(root)
    if not paths:
        print(f'no STORE* folders under {root!r}')
        return 1

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    metrics = {}
    for path in paths:
        result = build_store(path)
        metrics[result['store']] = result
        print(f"{result['store']}: orders={result['rows']['orders']} "
              f"users={result['rows']['users']} books={result['rows']['books']} "
              f"revenue=${result['total_revenue']:,.2f}")

    with open(os.path.join(OUTPUT_DIR, 'metrics.json'), 'w', encoding='utf-8') as handle:
        json.dump(metrics, handle, indent=1)

    written = os.listdir(OUTPUT_DIR)
    size = sum(os.path.getsize(os.path.join(OUTPUT_DIR, name)) for name in written)
    print(f'\n{len(written)} files, {size / 1024:.0f} kB -> {OUTPUT_DIR}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
