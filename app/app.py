import json
import math
import os
import re
import urllib.error
import urllib.request
from math import gcd

from flask import Flask, Response, render_template, request
from flask.json.provider import DefaultJSONProvider

import tools
from datastore import DataStore, apply_order_filters, grouped_aggregate

ANTHROPIC_URL = 'https://api.anthropic.com/v1/messages'
MODEL = os.environ.get('ANTHROPIC_MODEL', 'claude-sonnet-5-5')
MAX_TOOL_ROUNDS = 8

SYSTEM_PROMPT = """You are the analyst built into a bookstore BI dashboard.

Five stores (STORE1..STORE5) each have orders, users and a book catalogue. The
data has already been cleaned: prices are converted to US dollars (EUR x 1.2),
timestamps are parsed, and user records that differ in at most one field are
reconciled into one real person, so one person may own several user_ids.

Rules you must follow:

1. Never state a number you have not obtained from a tool in this conversation.
   You cannot count, sum or rank reliably; the tools do it in pandas. If a tool
   call fails, say so instead of guessing.
2. Prefer one precise tool call over several vague ones. `aggregate` answers most
   "top N by X" and "per month/genre/author" questions.
3. Questions that need you to read text - which titles contain a person's name,
   which titles sound like films - are yours to judge. Fetch the text with
   `list_book_titles` or `search_books`, decide yourself, then pass the chosen ids
   to `filter_books`. Never ask a counting tool to make a semantic judgement, and
   never make a counting judgement yourself.
4. When the user asks to change, filter, sort or navigate the dashboard, call the
   matching dashboard tool so the screen actually changes, then say in one short
   sentence what you changed.
5. Answer in the user's language. Be brief: a sentence or two plus the figures.
   Give money as $1,234.56 and dates as YYYY-MM-DD.
"""

NON_NEGATIVE_INTEGER = re.compile(r'[0-9]+')


def json_safe(value):
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if hasattr(value, 'item') and not isinstance(value, (str, bytes)):
        try:
            value = value.item()
        except (ValueError, AttributeError):
            return value
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


class SafeJSONProvider(DefaultJSONProvider):
    def dumps(self, obj, **kwargs):
        kwargs.setdefault('allow_nan', False)
        return super().dumps(json_safe(obj), **kwargs)


app = Flask(__name__)
app.json = SafeJSONProvider(app)
data = DataStore()


@app.get('/')
def index():
    return render_template('index.html', stores=data.store_names)


@app.get('/api/stores')
def api_stores():
    return tools.list_stores(data)


@app.get('/api/dashboard')
def api_dashboard():
    store = data.resolve_store(request.args.get('store'))
    orders = apply_order_filters(data.orders(store), {
        'date_from': request.args.get('date_from'),
        'date_to': request.args.get('date_to')})
    headline = data.headline(store)

    daily = orders.groupby('date', as_index=False)['paid_price'].sum().sort_values('date')
    top_days = daily.sort_values(['paid_price', 'date'], ascending=[False, True]).head(5)

    def as_rows(frame):
        return [{'date': row['date'], 'revenue': round(float(row['paid_price']), 2)}
                for _, row in frame.iterrows()]

    return {
        'store': store,
        'kpi': {
            'revenue': round(float(orders['paid_price'].sum()), 2) if len(orders) else 0.0,
            'orders': int(len(orders)),
            'units': int(orders['quantity'].sum()) if len(orders) else 0,
            'avg_order_value': round(float(orders['paid_price'].mean()), 2) if len(orders) else 0.0,
            'unique_users': headline['unique_users'],
            'raw_user_records': headline['raw_user_records'],
            'unique_author_sets': headline['unique_author_sets'],
            'books': headline['rows']['books'],
        },
        'top_5_days': as_rows(top_days),
        'most_popular_author_set': headline['most_popular_author_set'],
        'most_popular_single_author': headline['most_popular_single_author'],
        'best_buyer': headline['best_buyer'],
        'daily_revenue': as_rows(daily),
        'by_month': grouped_aggregate(orders, 'month', 'revenue', 'asc', 60, sort='key'),
        'by_genre': grouped_aggregate(orders, 'genre', 'units', 'desc', 10),
        'top_books': grouped_aggregate(orders, 'title', 'units', 'desc', 10),
        'top_author_sets': grouped_aggregate(orders, 'author_label', 'units', 'desc', 10),
    }


@app.get('/api/books')
def api_books():
    payload = tools.search_books(
        data, store=request.args.get('store'),
        title_contains=request.args.get('title_contains') or None,
        author_contains=request.args.get('author_contains') or None,
        genre=request.args.get('genre') or None,
        order_by=request.args.get('order_by') or 'units_sold',
        limit=int(request.args.get('limit', 200)))

    chosen = request.args.get('book_ids')
    if chosen:
        wanted = {int(value) for value in chosen.split(',') if value.strip()}
        include = request.args.get('mode', 'include') == 'include'
        payload['books'] = [book for book in payload['books']
                            if (book['id'] in wanted) == include]
        payload['returned'] = len(payload['books'])
    return payload


@app.get('/api/customers')
def api_customers():
    return tools.search_customers(
        data, store=request.args.get('store'),
        name_contains=request.args.get('name_contains') or None,
        email_starts_with=request.args.get('email_starts_with') or None,
        min_spend=request.args.get('min_spend') or None,
        limit=int(request.args.get('limit', 200)))


@app.get('/api/health')
def api_health():
    return {'ok': True, 'stores': data.store_names,
            'chat_configured': bool(os.environ.get('ANTHROPIC_API_KEY')),
            'model': MODEL, 'tools': len(tools.schemas())}


@app.get('/cylwikbartosz_gmail_com')
def lowest_common_multiple():
    def parse(raw):
        if raw is None or not NON_NEGATIVE_INTEGER.fullmatch(raw):
            return None
        return int(raw)

    x = parse(request.args.get('x'))
    y = parse(request.args.get('y'))
    if x is None or y is None:
        body = 'NaN'
    elif x == 0 or y == 0:
        body = '0'
    else:
        body = str(x // gcd(x, y) * y)
    return Response(body, status=200, mimetype='text/plain')


def call_anthropic(payload, api_key):
    request_object = urllib.request.Request(
        ANTHROPIC_URL, data=json.dumps(payload).encode('utf-8'), method='POST',
        headers={'content-type': 'application/json', 'x-api-key': api_key,
                 'anthropic-version': '2023-06-01'})
    with urllib.request.urlopen(request_object, timeout=120) as response:
        return json.loads(response.read().decode('utf-8'))


@app.post('/api/chat')
def api_chat():
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        return {'error': 'ANTHROPIC_API_KEY is not set on the server'}, 503

    payload = request.get_json(force=True, silent=True) or {}
    store = data.resolve_store(payload.get('store'))
    history = payload.get('messages') or []
    if not history:
        return {'error': 'no messages'}, 400

    messages = [{'role': message['role'], 'content': message['content']}
                for message in history if message.get('role') in ('user', 'assistant')]
    trace, ui_actions = [], []

    for _ in range(MAX_TOOL_ROUNDS):
        try:
            response = call_anthropic({
                'model': MODEL, 'max_tokens': 1600,
                'system': SYSTEM_PROMPT + f'\nThe dashboard is currently showing {store}.',
                'tools': tools.schemas(), 'messages': messages}, api_key)
        except urllib.error.HTTPError as error:
            detail = error.read().decode('utf-8', 'replace')[:400]
            return {'error': f'Anthropic API {error.code}: {detail}'}, 502
        except Exception as error:
            return {'error': f'{type(error).__name__}: {error}'}, 502

        blocks = response.get('content', [])
        messages.append({'role': 'assistant', 'content': blocks})

        if response.get('stop_reason') != 'tool_use':
            reply = '\n'.join(block.get('text', '') for block in blocks
                              if block.get('type') == 'text')
            return {'reply': reply.strip(), 'tool_calls': trace,
                    'ui_actions': ui_actions, 'store': store}

        results = []
        for block in blocks:
            if block.get('type') != 'tool_use':
                continue
            outcome = tools.call(data, block['name'], block.get('input'), default_store=store)
            trace.append({'tool': block['name'], 'input': block.get('input'),
                          'ok': 'error' not in outcome})
            if isinstance(outcome, dict) and 'ui_action' in outcome:
                ui_actions.append(outcome['ui_action'])
                if outcome['ui_action'].get('type') == 'set_store':
                    store = outcome['ui_action']['store']
            results.append({'type': 'tool_result', 'tool_use_id': block['id'],
                            'content': json.dumps(outcome, default=str)[:20000]})
        messages.append({'role': 'user', 'content': results})

    return {'reply': 'I could not finish within the tool-call budget.',
            'tool_calls': trace, 'ui_actions': ui_actions, 'store': store}


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8000)), debug=True)
