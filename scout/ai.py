"""Optional local commentary. Model output never selects or executes trades."""
import json
import re
from urllib.request import Request, build_opener, HTTPRedirectHandler

SCHEMA = {'type': 'object', 'properties': {
    'summary': {'type': 'string'},
    'risks': {'type': 'array', 'items': {'type': 'string'}},
    'next_checks': {'type': 'array', 'items': {'type': 'string'}}},
    'required': ['summary', 'risks', 'next_checks'], 'additionalProperties': False}

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def validate_notes(value):
    if not isinstance(value, dict) or set(value) != set(SCHEMA['required']):
        raise ValueError('Local model returned an unexpected structure.')
    if not isinstance(value['summary'], str) or len(value['summary']) > 4000:
        raise ValueError('Invalid local model summary.')
    for key in ('risks', 'next_checks'):
        if not isinstance(value[key], list) or len(value[key]) > 12 or not all(isinstance(s, str) and len(s) <= 1000 for s in value[key]):
            raise ValueError('Invalid local model notes.')
    return value


def summarize(report, model, opener=None):
    if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,95}', model):
        raise ValueError('Enter an installed Ollama model name, using letters, numbers, periods, colons, slashes or hyphens.')
    evidence = {k: report[k] for k in ('source', 'settings', 'selection_rule', 'split_at', 'symbols', 'comparison', 'audit', 'limitations')}
    prompt = ('You are a research reviewer, not an execution agent. Explain only the supplied historical simulation. '
              'State when data are synthetic. Do not promise profit, invent live data, recommend transactions, '
              'change allocations, or issue commands. Identify weak evidence, costs and missing tests. '
              'Return only JSON matching this schema: ' + json.dumps(SCHEMA))
    body = {'model': model, 'stream': False, 'format': SCHEMA, 'options': {'temperature': 0},
            'messages': [{'role': 'system', 'content': prompt},
                         {'role': 'user', 'content': json.dumps(evidence, allow_nan=False)}]}
    envelope = local_chat(model, body, opener)
    value = validate_notes(json.loads(envelope['message']['content']))
    return {'model': model, 'unverified': True, **value}


def local_chat(model, body, opener=None):
    """Verify a local model before sending any evidence. No remote or redirect fallback."""
    if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,95}', model) or 'cloud' in model.lower():
        raise ValueError('Use an installed local Ollama model, not a cloud model.')
    opener = opener or build_opener(NoRedirect())
    def post(path, value, limit):
        request = Request('http://127.0.0.1:11434' + path, json.dumps(value, allow_nan=False).encode(),
                          {'Content-Type': 'application/json'}, method='POST')
        with opener.open(request, timeout=60) as response:
            raw = response.read(limit + 1)
        if len(raw) > limit:
            raise ValueError('Ollama response was too large.')
        result = json.loads(raw)
        if not isinstance(result, dict) or result.get('error'):
            raise ValueError('Ollama returned an error or invalid object.')
        return result
    request = Request('http://127.0.0.1:11434/api/tags', method='GET')
    with opener.open(request, timeout=20) as response:
        raw = response.read(2000001)
    if len(raw) > 2000000:
        raise ValueError('Ollama model list was too large.')
    models = json.loads(raw).get('models', [])
    normalized = model if ':' in model.rsplit('/', 1)[-1] else model + ':latest'
    matches = [entry for entry in models if entry.get('name') in (model, normalized) or entry.get('model') in (model, normalized)]
    if len(matches) != 1 or matches[0].get('remote_host') or matches[0].get('remote_model') or not isinstance(matches[0].get('size'), (int, float)) or matches[0]['size'] <= 0:
        raise ValueError('Select a downloaded local model from ollama list. Remote or unknown models are blocked.')
    info = post('/api/show', {'model': model}, 2000000)
    if info.get('remote_host') or info.get('remote_model') or not info.get('model_info'):
        raise ValueError('Could not verify local model weights. Disable Ollama cloud and use a downloaded model.')
    envelope = post('/api/chat', body, 131072)
    if envelope.get('remote_host') or envelope.get('remote_model'):
        raise ValueError('Unexpected remote model response.')
    return envelope


def paper_decision(model, evidence, symbols, opener=None):
    schema = {'type': 'object', 'properties': {
        'actions': {'type': 'object', 'properties': {s: {'type': 'string', 'enum': ['buy', 'sell', 'hold']} for s in symbols},
                    'required': list(symbols), 'additionalProperties': False},
        'reason': {'type': 'string'}}, 'required': ['actions', 'reason'], 'additionalProperties': False}
    body = {'model': model, 'stream': False, 'format': schema, 'options': {'temperature': 0},
            'messages': [{'role': 'system', 'content':
                'Propose paper-only buy, sell or hold actions using only supplied completed bars. '
                'Hold when evidence is weak. Do not invent news or prices. No borrowing, shorting, leverage or real orders. '
                'Risk limits and sizing are controlled by the simulator; you cannot override them. '
                'Historical replay may overlap your training data and is not an untouched predictive test. Return schema JSON.'},
                {'role': 'user', 'content': json.dumps(evidence, allow_nan=False)}]}
    envelope = local_chat(model, body, opener)
    value = json.loads(envelope['message']['content'])
    if not isinstance(value, dict) or set(value) != {'actions', 'reason'} or not isinstance(value['actions'], dict):
        raise ValueError('Invalid paper decision structure.')
    if set(value['actions']) != set(symbols) or any(a not in ('buy', 'sell', 'hold') for a in value['actions'].values()):
        raise ValueError('Invalid paper action or symbol.')
    if not isinstance(value['reason'], str) or len(value['reason']) > 2000:
        raise ValueError('Invalid paper rationale.')
    return value
