from http import HTTPStatus
from unittest import mock
from urllib.parse import quote

from authlib.jose import jwt
from pytest import fixture

from .utils import headers


def routes():
    yield '/health'


@fixture(scope='module', params=routes(), ids=lambda route: f'POST {route}')
def route(request):
    return request.param


def test_health_call_with_invalid_jwt_failure(route, client, invalid_jwt):
    response = client.post(route, headers=headers(invalid_jwt))

    expected_payload = {
        'errors': [
            {
                'code': 'authorization failed',
                'message': 'Authorization failed: Failed to decode JWT with '
                           'provided key',
                'type': 'fatal',
            }
        ]
    }

    assert response.status_code == HTTPStatus.OK
    assert response.get_json() == expected_payload


@fixture(scope='function')
def hibp_api_request():
    with mock.patch('requests.get') as mock_request:
        yield mock_request


def hibp_api_response(status_code):
    mock_response = mock.MagicMock()

    mock_response.status_code = status_code
    if status_code == HTTPStatus.UNAUTHORIZED:
        mock_response.json = lambda: {
            "message": "Unauthorized error from 3rd party"
        }

    return mock_response


def test_health_call_success(route, client, hibp_api_request, valid_jwt):
    app = client.application

    hibp_api_request.return_value = hibp_api_response(HTTPStatus.OK)

    response = client.post(route, headers=headers(valid_jwt))

    email = app.config['HIBP_TEST_EMAIL']

    expected_url = app.config['HIBP_API_URL'].format(
        email=quote(email, safe=''),
        truncate='true',
    )

    expected_headers = {
        'user-agent': app.config['CTR_USER_AGENT'],
        'hibp-api-key': (
            jwt.decode(valid_jwt, app.config['SECRET_KEY'])['key']
        ),
    }

    hibp_api_request.assert_called_once_with(expected_url,
                                             headers=expected_headers)

    expected_payload = {'data': {'status': 'ok'}}

    assert response.status_code == HTTPStatus.OK
    assert response.get_json() == expected_payload


def test_health_call_with_external_error_from_hibp_failure(route,
                                                           client,
                                                           hibp_api_request,
                                                           valid_jwt):
    for status_code, error_code, error_message, is_authentic in [
        (
            HTTPStatus.UNAUTHORIZED,
            'access denied',
            'Authorization failed: Unauthorized error from 3rd party',
            False,
        ),
        (
            HTTPStatus.TOO_MANY_REQUESTS,
            'too many requests',
            'Rate limit is exceeded. Try again in 3 seconds.',
            True,
        ),
        (
            HTTPStatus.SERVICE_UNAVAILABLE,
            'service unavailable',
            'Service temporarily unavailable. Please try again later.',
            False,
        ),
        (
            HTTPStatus.INTERNAL_SERVER_ERROR,
            'oops',
            'Something went wrong.',
            False,
        ),
    ]:
        app = client.application

        hibp_api_request.return_value = hibp_api_response(status_code)

        if is_authentic:
            hibp_api_request.return_value.json = (
                lambda: {'message': error_message}
            )

        response = client.post(route, headers=headers(valid_jwt))

        email = app.config['HIBP_TEST_EMAIL']

        expected_url = app.config['HIBP_API_URL'].format(
            email=quote(email, safe=''),
            truncate='true',
        )

        expected_headers = {
            'user-agent': app.config['CTR_USER_AGENT'],
            'hibp-api-key': (
                jwt.decode(valid_jwt, app.config['SECRET_KEY'])['key']
            ),
        }

        hibp_api_request.assert_called_once_with(expected_url,
                                                 headers=expected_headers)

        hibp_api_request.reset_mock()

        expected_payload = {
            'errors': [
                {
                    'code': error_code,
                    'message': error_message,
                    'type': 'fatal',
                }
            ]
        }

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == expected_payload
