import collections
import re
import sys
from decimal import Decimal

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from parsers import parse_timestamp
from pipeline import all_stores, compute_metrics, load_store


def price_in_cents(raw):
    text = str(raw)
    is_euro = 'EUR' in text.upper() or '€' in text
    cleaned = re.sub(r'(?<=\d)[$€¢](?=\d)', '.', text)
    cleaned = re.sub(r'[^\d.]', '', cleaned).rstrip('.')
    amount = Decimal(cleaned) * (Decimal('1.2') if is_euro else 1)
    return int((amount * 100).quantize(Decimal('1'), rounding='ROUND_HALF_UP'))


def revenue_in_cents(rows):
    return sum(price_in_cents(row['unit_price']) * int(row['quantity']) for row in rows)


def top_days(rows):
    daily = collections.Counter()
    for row in rows:
        day = parse_timestamp(row['timestamp']).date()
        daily[day] += price_in_cents(row['unit_price']) * int(row['quantity'])
    ranked = sorted(daily.items(), key=lambda item: (-item[1], item[0]))[:5]
    return [(day.strftime('%Y-%m-%d'), cents / 100) for day, cents in ranked]


def people_by_brute_force(users):
    values = users[['name', 'address', 'phone', 'email']].fillna('\x00M').to_numpy()
    parent = list(range(len(values)))

    def find(node):
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for left in range(len(values)):
        differences = (values[left + 1:] != values[left]).sum(axis=1)
        for offset in np.nonzero(differences <= 1)[0]:
            left_root, right_root = find(left), find(left + 1 + int(offset))
            if left_root != right_root:
                parent[right_root] = left_root

    return len({find(position) for position in range(len(values))})


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else 'data'
    mismatches = []

    for path in all_stores(root):
        expected = compute_metrics(load_store(path))
        rows = pq.read_table(path + '/orders.parquet').to_pylist()
        users = pd.read_csv(path + '/users.csv', dtype=str)

        revenue = revenue_in_cents(rows) / 100
        days = top_days(rows)
        people = people_by_brute_force(users)

        checks = {
            'revenue': abs(revenue - expected['total_revenue']) <= 0.02,
            'top_5_days': days == [(d['date'], d['revenue']) for d in expected['top_5_days']],
            'unique_users': people == expected['unique_users'],
        }
        failed = [name for name, passed in checks.items() if not passed]
        mismatches.extend((expected['store'], name) for name in failed)

        print(f"{expected['store']}: revenue ${revenue:,.2f}, people {people}, "
              f"{'all checks agree' if not failed else 'MISMATCH ' + str(failed)}")

    print('\nindependent recomputation agrees with the pipeline' if not mismatches
          else f'\nMISMATCHES: {mismatches}')
    return 1 if mismatches else 0


if __name__ == '__main__':
    sys.exit(main())
