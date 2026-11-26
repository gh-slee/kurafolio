"""Closed SQL-to-wire conversions for the two ingestion read pages."""
from kurafolio.ingestion import codec, cursors
from .auth import RequestError


def preview_page(value, cursor_key):
    try:
        if type(value) is not dict or set(value) != {'page', 'next'}:
            raise ValueError()
        page, nxt = value['page'], value['next']
        if type(page) is not dict or 'next_cursor' in page:
            raise ValueError()
        if nxt is not None:
            if type(nxt) is not dict or any(nxt.get(a) != page.get(b) for a, b in (
                    ('resource_id', 'id'), ('resource_revision', 'set_revision'),
                    ('review_digest', 'review_digest'))) or nxt.get('filter') is not None:
                raise ValueError()
            token = cursors.sign(cursor_key, nxt)
        else:
            token = None
        return codec.validate(dict(page, next_cursor=token), 'PreviewPage')
    except Exception:
        raise RequestError('internal_error', 500) from None


def set_list(value, cursor_key):
    try:
        if type(value) is not dict or set(value) != {'items', 'next'}:
            raise ValueError()
        nxt = value['next']
        if nxt is not None and type(nxt) is not dict:
            raise ValueError()
        token = cursors.sign(cursor_key, nxt) if nxt is not None else None
        return codec.validate({'items': value['items'], 'next_cursor': token}, 'SetList')
    except Exception:
        raise RequestError('internal_error', 500) from None
