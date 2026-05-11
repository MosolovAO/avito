from datetime import timedelta
import time
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


class AvitoApiClient:
    def __init__(self, session=None, base_url=None, timeout=None):
        self.session = session or requests.Session()
        self.base_url = (base_url or settings.AVITO_API_BASE_URL).rstrip("/")
        self.timeout = timeout
        self.min_request_interval = settings.AVITO_API_MIN_REQUEST_INTERVAL_SECONDS
        self.max_retries = settings.AVITO_API_MAX_RETRIEST
        self.default_retry_after = settings.AVITO_API_DEFAULT_RETRY_SECONDS

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

    def refresh_access_token(self, token):
        if not token.refresh_token:
            raise AvitoApiError("У Avito OAuth-токена нет refresh_token")

        avito_account = token.avito_account

        response = self.request_token(
            {
                "grant_type": "refresh_token",
                "client_id": get_avito_account_client_id(avito_account),
                "client_secret": get_avito_account_client_secret(avito_account),
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

        for attempt in range(self.max_retries + 1):
            if self.min_request_interval > 0:
                time.sleep(self.min_request_interval)

            response = self.session.request(
                method,
                url,
                headers=headers,
                timeout=self.timeout,
                **kwargs
            )

            if (
                    response.status_code == 401
                    and token
                    and retry_on_unauthorized
                    and token.refresh_token
            ):
                self.refresh_access_token(token)
                return self.request(
                    method,
                    path,
                    token=token,
                    retry_on_unauthorized=False,
                    **kwargs
                )

            if response.status_code == 429:
                if attempt >= self.max_retries:
                    raise build_api_error(response)

                retry_after = response.headers.get("Retry-After")
                delay = int(retry_after) if retry_after and retry_after.isdigit() else self.default_retry_after
                time.sleep(delay)
                continue

            if response.status_code == 400:
                raise build_api_error(response)

            if not getattr(response, "text", ""):
                return {}

            return response.json()

        raise AvitoApiError("Avito API временно недоступен после повторных попыток")

    def request_token(self, data):
        url = f"{self.base_url}/token"

        for attempt in range(self.max_retries + 1):
            if self.min_request_interval > 0:
                time.sleep(self.min_request_interval)

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

            if response.status_code == 429:
                if attempt >= self.max_retries:
                    raise build_api_error(response)

                retry_after = response.headers.get("Retry-After")
                delay = int(retry_after) if retry_after and retry_after.isdigit() else self.default_retry_after
                time.sleep(delay)
                continue

            elif response.status_code >= 400:
                raise build_api_error(response)

            return response.json()

        raise AvitoApiError("Avito token endpoint временно недоступен после повторных попыток.")


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


def get_avito_account_client_id(avito_account):
    client_id = (avito_account.client_id or "").strip()

    if not client_id:
        raise AvitoConfigurationError(
            "Сначала укажите Client ID для проекта."
        )

    return client_id


def get_avito_account_client_secret(avito_account):
    client_secret = (avito_account.client_secret or "").strip()

    if not client_secret:
        raise AvitoConfigurationError(
            "Сначала укажите Client Secret для проекта."
        )

    return client_secret


def connect_avito_account_with_client_credentials(avito_account, session=None):
    client = AvitoApiClient(session=session)

    response = client.request_token({
        "grant_type": "client_credentials",
        "client_id": get_avito_account_client_id(avito_account),
        "client_secret": get_avito_account_client_secret(avito_account),
    })

    defaults = build_token_defaults(response)
    defaults["auth_type"] = AvitoOAuthToken.AuthType.CLIENT_CREDENTIALS

    token, _ = AvitoOAuthToken.objects.update_or_create(
        workspace=avito_account.workspace,
        avito_account=avito_account,
        defaults=defaults,
    )

    return connect_avito_account_from_token(
        avito_account=avito_account,
        token=token,
        session=session,
    )
