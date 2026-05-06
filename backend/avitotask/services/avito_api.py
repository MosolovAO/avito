from datetime import timedelta

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from urllib.parse import urlencode

from avitotask.models import AvitoAccount, AvitoOAuthToken
from django.core import signing


class AvitoApiError(Exception):
    def __init__(self, message, status_code=None, payload=None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


class AvitoConfigurationError(AvitoApiError):
    pass


DEFAULT_AVITO_OAUTH_SCOPES = (
    "user:read",
    "items:info",
    "stats:read",
    "autoload:reports",
)

AVITO_OAUTH_STATE_SALT = "avitotask.avito.oauth.state"
AVITO_OAUTH_STATE_MAX_AGE_SECONDS = 15 * 60


class AvitoApiClient:
    def __init__(self, session=None, base_url=None, timeout=None):
        self.session = session or requests.Session()
        self.base_url = (base_url or settings.AVITO_API_BASE_URL).rstrip("/")
        self.timeout = timeout

    def get_current_user(self, token):
        return self.request("GET", "/core/v1/accounts/self", token=token)

    def get_items(self, token):
        return self.request("GET", "/core/v1/items", token=token)

    def get_avito_ids_by_ad_ids(self, token, ad_ids):
        return self.request(
            "GET",
            "/autoload/v2/items/avito_ids",
            token=token,
            params={"query": ",".join(ad_ids)},
        )

    def get_item_stats(self, token, item_ids, user_id, date_from, date_to):
        return self.request(
            "POST",
            f"/stats/v1/accounts/{user_id}/items",
            token=token,
            json={
                "itemIds": item_ids,
                "dateFrom": date_from.isoformat(),
                "dateTo": date_to.isoformat(),
            }

        )
    def exchange_authorization_code(self, avito_account, code):
        response = self.request_token(
            {
                "grant_type": "authorization_code",
                "client_id": get_avito_client_id(),
                "client_secret": get_avito_client_secret(),
                "code": code,
            }
        )
        defaults = build_token_defaults(response)
        defaults["auth_type"] = AvitoOAuthToken.AuthType.AUTHORIZATION_CODE

        token, _ = AvitoOAuthToken.objects.update_or_create(
            workspace=avito_account.workspace,
            avito_account=avito_account,
            defaults=defaults
        )

        return token

    def refresh_access_token(self, token):
        if not token.refresh_token:
            raise AvitoApiError("У Avito OAuth-токена нет refresh_token")

        response = self.request_token(
            {
                "grant_type": "refresh_token",
                "client_id": get_avito_client_id(),
                "client_secret": get_avito_client_secret(),
                "refresh_token": token.refresh_token,
            }

        )

        for field, value in build_token_defaults(response).items():
            setattr(token, field, value)

        token.last_refreshed_at = timezone.now()
        token.last_error = None
        token.save(update_fields=[
            "access_token",
            "refresh_token",
            "token_type",
            "scope",
            "expires_at",
            "last_refreshed_at",
            "last_error",
            "updated_at"
        ])

        return token

    def request(self, method, path, token=None, retry_on_unauthorized=True, **kwargs):
        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = kwargs.pop("headers", {})
        headers.setdefault("Accept", "application/json")

        if token:
            headers["Authorization"] = f"Bearer {token.access_token}"

        response = self.session.request(
            method, url, headers=headers, timeout=self.timeout, **kwargs
        )

        if response.status_code == 401 and token and retry_on_unauthorized and token.refresh_token:
            self.refresh_access_token(token)
            return self.request(method, path, token=token, retry_on_unauthorized=False, **kwargs)

        if response.status_code >= 400:
            raise build_api_error(response)

        if not getattr(response, "text", ""):
            return {}

        return response.json()

    def request_token(self, data):
        url = f"{self.base_url}/token"
        response = self.session.request(
            "POST",
            url,
            data=data,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=self.timeout,
        )

        if response.status_code >= 400:
            raise build_api_error(response)

        return response.json()


@transaction.atomic
def connect_avito_account_from_token(avito_account, token, session=None):
    if token.avito_account_id != avito_account.id:
        raise AvitoApiError("OAuth-токен не принадлежит этому AvitoAccount")

    if token.workspace_id != avito_account.workspace_id:
        raise AvitoApiError("OAuth-токен и AvitoAccount находятся в разных workspace")

    client = AvitoApiClient(session=session)
    user_info = client.get_current_user(token)

    avito_user_id = user_info.get("id")
    if not avito_user_id:
        raise AvitoApiError("Avito API не вернул id пользователя", payload=user_info)

    avito_account.external_account_id = str(avito_user_id)
    avito_account.save(update_fields=["external_account_id", "updated_at"])

    token.user_info = user_info
    token.last_verified_at = timezone.now()
    token.last_error = None
    token.save(update_fields=["user_info", "last_verified_at", "last_error", "updated_at"])

    return avito_account


def build_token_defaults(response):
    defaults = {
        "access_token": response.get("access_token"),
        "token_type": response.get("token_type") or "Bearer",
        "scope": response.get("scope") or "",
        "last_error": None
    }

    if response.get("refresh_token"):
        defaults["refresh_token"] = response["refresh_token"]

    expires_in = response.get("expires_in")
    if expires_in:
        defaults["expires_at"] = timezone.now() + timedelta(seconds=int(expires_in))

    return defaults


def build_api_error(response):
    try:
        payload = response.json()
    except ValueError:
        payload = {}

    message = payload.get("error_description") or payload.get("message")

    if not message and isinstance(payload.get("error"), dict):
        message = payload["error"].get("message")
    if not message:
        message = getattr(response, "text", "") or "Ошибка Avito API"

    return AvitoApiError(
        message=message,
        status_code=response.status_code,
        payload=payload
    )


def get_avito_client_id():
    if not settings.AVITO_CLIENT_ID:
        raise AvitoConfigurationError("Не задан AVITO_CLIENT_ID")
    return settings.AVITO_CLIENT_ID


def get_avito_client_secret():
    if not settings.AVITO_CLIENT_SECRET:
        raise AvitoConfigurationError("Не задан AVITO_CLIENT_SECRET")
    return settings.AVITO_CLIENT_SECRET


def build_avito_oauth_state(avito_account):
    return signing.dumps(
        {
            "workspace_id": avito_account.workspace_id,
            "avito_account_id": avito_account.id,
        },
        salt=AVITO_OAUTH_STATE_SALT,
    )


def parse_avito_oauth_state(state):
    try:
        return signing.loads(
            state,
            salt=AVITO_OAUTH_STATE_SALT,
            max_age=AVITO_OAUTH_STATE_MAX_AGE_SECONDS,
        )
    except signing.SignatureExpired as exc:
        raise AvitoApiError("OAuth state устарел. Начните подключение Avito заново.") from exc
    except signing.BadSignature as exc:
        raise AvitoApiError("Некорректный OAuth state.") from exc


def build_avito_authorization_url(avito_account, scopes=None):
    scopes = scopes or DEFAULT_AVITO_OAUTH_SCOPES

    query = urlencode({
        "response_type": "code",
        "pro_users_flow": "true",
        "client_id": get_avito_client_id(),
        "scope": ",".join(scopes),
        "state": build_avito_oauth_state(avito_account),
    })

    return f"{settings.AVITO_OAUTH_AUTHORIZE_URL}?{query}"


@transaction.atomic
def connect_avito_account_from_authorization_code(code, state, session=None):
    state_payload = parse_avito_oauth_state(state)

    try:
        avito_account = AvitoAccount.objects.select_for_update().get(
            id=state_payload["avito_account_id"],
            workspace_id=state_payload["workspace_id"],
        )
    except AvitoAccount.DoesNotExist as exc:
        raise AvitoApiError("AvitoAccount из OAuth state не найден") from exc

    client = AvitoApiClient(session=session)
    token = client.exchange_authorization_code(avito_account, code)

    return connect_avito_account_from_token(
        avito_account=avito_account,
        token=token,
        session=session
    )
