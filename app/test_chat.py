import sys

import app as application

failures = []


def scripted_api(responses):
    steps = iter(responses)

    def call(payload, api_key):
        return next(steps)
    return call


def tool_use(name, arguments, block_id='t1'):
    return {'stop_reason': 'tool_use',
            'content': [{'type': 'tool_use', 'id': block_id,
                         'name': name, 'input': arguments}]}


def final(text):
    return {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': text}]}


def ask(responses, message='question'):
    application.call_anthropic = scripted_api(responses)
    client = application.app.test_client()
    response = client.post('/api/chat', json={
        'store': 'STORE1', 'messages': [{'role': 'user', 'content': message}]})
    return response.status_code, response.get_json()


def check(label, passed, detail=''):
    print(f"  {'pass' if passed else 'FAIL'}  {label}" + ('' if passed else f'  <- {detail}'))
    if not passed:
        failures.append(label)


application.os.environ['ANTHROPIC_API_KEY'] = 'test-key'

print('single data tool')
status, body = ask([tool_use('headline_metrics', {'store': 'STORE1'}),
                    final('STORE1 has 3221 real customers.')])
check('responds 200', status == 200, str(status))
check('calls headline_metrics',
      [call['tool'] for call in body['tool_calls']] == ['headline_metrics'])
check('tool succeeded', body['tool_calls'][0]['ok'])
check('reply passed through', '3221' in body['reply'])
check('no ui actions', body['ui_actions'] == [])

print('\ntool chain producing a ui action')
status, body = ask([
    tool_use('list_book_titles', {'limit': 5}, 'a'),
    tool_use('filter_books', {'book_ids': [23099, 22817], 'mode': 'exclude',
                              'label': 'titles without person names'}, 'b'),
    final('Filtered out two titles.')])
check('both tools in order',
      [call['tool'] for call in body['tool_calls']] == ['list_book_titles', 'filter_books'])
check('one ui action returned', len(body['ui_actions']) == 1)
check('action is filter_books', body['ui_actions'][0]['type'] == 'filter_books')
check('action carries ids', body['ui_actions'][0]['book_ids'] == [23099, 22817])

print('\nswitching store changes the context of later calls')
status, body = ask([tool_use('set_store', {'store': 'STORE3'}, 'a'),
                    tool_use('count_entity', {'entity': 'unique_people'}, 'b'),
                    final('STORE3 has 2955 real customers.')])
check('set_store action', body['ui_actions'][0] == {'type': 'set_store', 'store': 'STORE3'})
check('context switched', body['store'] == 'STORE3', body['store'])

print('\na failing tool goes back to the model instead of crashing')
status, body = ask([tool_use('aggregate', {'group_by': 'nonsense'}, 'a'),
                    final('I cannot group by that field.')])
check('still 200', status == 200, str(status))
check('tool marked as failed', body['tool_calls'][0]['ok'] is False)

print('\nmissing api key')
del application.os.environ['ANTHROPIC_API_KEY']
response = application.app.test_client().post(
    '/api/chat', json={'store': 'STORE1', 'messages': [{'role': 'user', 'content': 'x'}]})
check('503 with a clear message',
      response.status_code == 503 and 'ANTHROPIC_API_KEY' in response.get_json()['error'])
application.os.environ['ANTHROPIC_API_KEY'] = 'test-key'

print('\ntool budget stops the loop')
status, body = ask([tool_use('count_entity', {'entity': 'books'}, f't{index}')
                    for index in range(application.MAX_TOOL_ROUNDS)])
check('loop bounded', len(body['tool_calls']) == application.MAX_TOOL_ROUNDS,
      str(len(body['tool_calls'])))

print('\nlcm endpoint from the previous task still answers')
client = application.app.test_client()
for query, expected in [('x=4&y=6', '12'), ('x=0&y=5', '0'), ('x=-1&y=2', 'NaN'),
                        ('x=abc&y=2', 'NaN'), ('x=1', 'NaN'), ('x=21&y=6', '42')]:
    got = client.get('/cylwikbartosz_gmail_com?' + query).get_data(as_text=True)
    check(f'lcm {query} -> {expected}', got == expected, got)

print()
print('all tests passed' if not failures else f'failed: {failures}')
sys.exit(1 if failures else 0)
