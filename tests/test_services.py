import asyncio
import httpx
import pytest
from app.services import group_messages, scan_promotions, demo_scan


def message(sender='News <news@example.com>', list_id='', timestamp='1', subject='Hello'):
    return {'internalDate': timestamp, 'payload': {'headers': [
        {'name': 'From', 'value': sender}, {'name': 'List-Id', 'value': list_id},
        {'name': 'Subject', 'value': subject}]}}


def test_lists_from_same_sender_remain_separate():
    groups = group_messages([message(list_id='<a.example>'), message(list_id='<b.example>')])
    assert len(groups) == 2


def test_list_grouping_and_latest_subject():
    groups = group_messages([message(list_id='List <a.example>', timestamp='1'),
                             message(sender='Other <other@example.com>', list_id='<a.example>', timestamp='2', subject='Latest')])
    assert len(groups) == 1
    assert groups[0].count == 2
    assert groups[0].latest_subject == 'Latest'


def test_sender_fallback_and_encoded_subject():
    groups = group_messages([message(subject='=?utf-8?q?Hello_=E2=9C=93?='), message()])
    assert len(groups) == 1
    assert groups[0].latest_subject == 'Hello ✓'
    assert groups[0].unsubscribe_method == 'No unsubscribe header'


def test_demo_is_explicit():
    data = demo_scan()
    assert data['demo'] is True
    assert data['scanned'] == 53
    assert len(data['subscriptions']) == 4


def test_scan_paginates_and_fetches_only_metadata():
    requests = []
    def handler(request):
        requests.append(request)
        assert request.headers['authorization'] == 'Bearer test-token'
        if request.url.path.endswith('/messages'):
            assert request.url.params['q'] == 'category:promotions newer_than:90d'
            if 'pageToken' in request.url.params:
                return httpx.Response(200, json={'messages': [{'id': 'two'}]})
            return httpx.Response(200, json={'messages': [{'id': 'one'}], 'nextPageToken': 'next'})
        assert request.url.params['format'] == 'metadata'
        assert 'List-Unsubscribe' in request.url.params.get_list('metadataHeaders')
        return httpx.Response(200, json=message())
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await scan_promotions(client, 'test-token')
    result = asyncio.run(run())
    assert result['scanned'] == 2
    assert result['subscriptions'][0]['count'] == 2
    assert result['limited'] is False
    assert len(requests) == 4


def test_scan_limit_and_deleted_message():
    def handler(request):
        if request.url.path.endswith('/messages'):
            return httpx.Response(200, json={'messages': [{'id': 'one'}], 'nextPageToken': 'next'})
        return httpx.Response(404)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await scan_promotions(client, 'token', limit=1)
    result = asyncio.run(run())
    assert result['scanned'] == 0
    assert result['limited'] is True


def test_gmail_error_is_not_silently_empty():
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(403))) as client:
            return await scan_promotions(client, 'token')
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(run())
