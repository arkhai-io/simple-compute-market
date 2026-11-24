"""Exact accepted finite once accounting projection; normal verifier precedes use."""
import re
from datetime import datetime
from .mandates import duration_seconds

class Hold(Exception):

    def __init__(self, kind, reason):
        (self.kind, self.reason) = (kind, reason)

def need(ok, reason='MALFORMED_OR_UNBOUND', kind='UNKNOWN'):
    if not ok:
        raise Hold(kind, reason)

def integer(v):
    return type(v) is int and v >= 0

def _money(value):
    need(type(value) is str and re.fullmatch('0|[1-9][0-9]{0,37}', value), 'PAYMENT_AMOUNT_SHAPE')
    return int(value)

def _amounts(snapshot, mandate, now, read_started_at):
    """Conservative finite once-part projection after the normal verifier.
 No alternative event engine: only start/stop/reverse with concrete bounded
 part/time/amounts is understood. Extension/lift/rate shapes remain UNKNOWN.
 """
    need(snapshot.get('livemode') is False, 'PAYMENT_MODE')
    need(integer(snapshot.get('observedAt')) and read_started_at <= snapshot['observedAt'] <= now, 'STALE_PAYMENT_SNAPSHOT')
    expected = mandate['parts']
    parts = snapshot['parts']
    receipt = snapshot['receipt']['receipt']
    need(type(expected) is list and 1 <= len(expected) <= 32 and (len(parts) == len(expected) == len(receipt['parts'])), 'PART_POPULATION')
    need(all((type(p['part']) is int for p in parts)) and sorted((p['part'] for p in parts)) == list(range(len(expected))), 'PART_POPULATION')
    parts = sorted(parts, key=lambda p: p['part'])
    approved = receipt['approvedAt']
    need(integer(approved) and approved <= snapshot['observedAt'], 'PAYMENT_APPROVAL_TIME')
    seq = snapshot['latestEventSequence']
    events = snapshot['events']
    need(integer(seq) and seq <= 128 and (type(events) is list) and (len(events) == seq) and all((type(e.get('sequence')) is int for e in events)) and ([e['sequence'] for e in events] == list(range(1, seq + 1))), 'INCOMPLETE_PAYMENT_EVENTS')
    reversals = [0] * len(parts)
    prior_received = approved
    for stored in events:
        received = stored['receivedAt']
        need(integer(received) and prior_received <= received <= snapshot['observedAt'], 'PAYMENT_EVENT_TIME')
        prior_received = received
        event = stored['event']
        kind = event['kind']
        need(kind in {'start', 'stop', 'reverse'}, 'UNSUPPORTED_PAYMENT_EVENT')
        target = event.get('part')
        need(target is None or (type(target) is int and 0 <= target < len(parts)), 'PAYMENT_EVENT_PART')
        need(all((event.get(k) is None for k in ('until', 'ref'))), 'UNSUPPORTED_PAYMENT_EVENT')
        if event.get('at') is not None:
            need(kind == 'stop' and integer(event['at']) and (event['at'] <= snapshot['observedAt']), 'PAYMENT_EVENT_TIME')
        if kind == 'reverse':
            need(target is not None, 'UNSUPPORTED_TRANSACTION_WIDE_REVERSE')
            amount = _money(event['amount'])
            need(amount > 0, 'PAYMENT_EVENT_AMOUNT')
            reversals[target] += amount
            need(reversals[target] <= _money(expected[target]['amount']), 'PAYMENT_EVENT_AMOUNT')
        else:
            need(event.get('amount') is None, 'PAYMENT_EVENT_AMOUNT')
    projected = []
    for (i, p) in enumerate(parts):
        agreed = expected[i]
        paid = receipt['parts'][i]
        need(agreed['kind'] == 'once', 'UNSUPPORTED_RATE_PAYMENT')
        need(p['asset'] == paid['asset'] == agreed['asset'], 'PAYMENT_PART_ASSET_BINDING')
        need(_money(p['gross']) == _money(paid['gross']) == _money(agreed['amount']), 'PAYMENT_PART_GROSS_BINDING')
        need(p['hold'] == paid['hold'] == agreed['hold'], 'PAYMENT_PART_HOLD_BINDING')
        need(_money(paid['gross']) == _money(paid['fee']) + _money(paid['net']), 'PAYMENT_RECEIPT_CONSERVATION')
        need(paid.get('rate') is None, 'UNSUPPORTED_RATE_PAYMENT')
        amounts = {k: p[k] for k in ('gross', 'held', 'released', 'reversed', 'feePaid')}
        values = {k: _money(v) for (k, v) in amounts.items()}
        need(values['gross'] == values['held'] + values['released'] + values['reversed'], 'PAYMENT_CONSERVATION')
        need(values['reversed'] == reversals[i], 'PAYMENT_REVERSE_EVENT_BINDING')
        need(values['feePaid'] <= _money(paid['fee']) and values['feePaid'] <= values['released'], 'PAYMENT_FEE_BINDING')
        need(values['held'] == 0 and p['status'] in ('released', 'reversed', 'settled') and (not p.get('extensions')), 'HELD_PAYMENT_OR_EXTENSION', 'PENDING')
        need(p.get('rate') is None and p.get('reserved') in (None, '0') and (p.get('pendingStop') is None), 'UNSUPPORTED_PAYMENT_OBLIGATION')
        end = agreed.get('end')
        effective = p.get('end')
        need(effective == ({'at': max(end['at'], approved), 'partialPeriod': end['partialPeriod']} if end is not None else None), 'PAYMENT_END_BINDING')
        if p.get('started') is not None:
            need(integer(p['started']) and approved <= p['started'] <= snapshot['observedAt'], 'PAYMENT_START_TIME')
        stop = p.get('stop')
        if stop is not None:
            need(integer(stop['sequence']) and 1 <= stop['sequence'] <= seq and integer(stop['effectiveAt']) and (approved <= stop['effectiveAt'] <= snapshot['observedAt']), 'PAYMENT_STOP_BINDING')
            recorded = events[stop['sequence'] - 1]
            need(recorded['event']['kind'] == 'stop' and recorded['event'].get('part') in (None, i), 'PAYMENT_STOP_BINDING')
            settled = stop['settled']
            need(settled['part'] == i and settled['asset'] == p['asset'] and (_money(settled['gross']) <= values['gross']) and (_money(settled['gross']) == _money(settled['fee']) + _money(settled['net'])), 'PAYMENT_STOP_BINDING')
        if values['released']:
            maturity = datetime.fromisoformat(p['releaseAt'].replace('Z', '+00:00'))
            need(maturity.tzinfo is not None and maturity.timestamp() <= snapshot['observedAt'], 'PAYMENT_MATURITY')
            hold = agreed['hold']
            need(type(hold) is dict and len(hold) == 1, 'UNSUPPORTED_PAYMENT_HOLD')
            if 'for' in hold:
                duration = duration_seconds(hold['for'])
                need(integer(duration), 'UNSUPPORTED_PAYMENT_HOLD')
                minimum_maturity = approved + duration
            else:
                duration = duration_seconds(hold['afterStop'])
                need(integer(duration) and (stop is not None or effective is not None), 'UNSUPPORTED_PAYMENT_HOLD')
                anchors = ([stop['effectiveAt']] if stop is not None else []) + ([effective['at']] if effective is not None else [])
                minimum_maturity = max(anchors) + duration
            need(maturity.timestamp() >= minimum_maturity, 'PAYMENT_HOLD_MATURITY_BINDING')
        projected.append({'part': p['part'], 'asset': p['asset'], **amounts, 'status': p['status']})
    return projected
