from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from profits_check_backend.models import AppSetting, Channel
from profits_check_backend.security import SecretCipher, mask_secret


def list_channels(session: Session) -> list[Channel]:
    return list(session.scalars(select(Channel).order_by(Channel.id)))


def create_channel(
    session: Session,
    *,
    cipher: SecretCipher,
    name: str,
    provider: str,
    kind: str,
    enabled: bool,
    public_config: dict[str, object],
    secret_config: dict[str, object],
) -> Channel:
    encrypted = {key: cipher.encrypt(str(value)) for key, value in secret_config.items()}
    channel = Channel(
        name=name,
        provider=provider,
        kind=kind,
        enabled=enabled,
        public_config_json=json.dumps(public_config),
        secret_config_encrypted=json.dumps(encrypted),
    )
    session.add(channel)
    session.commit()
    session.refresh(channel)
    return channel


def decode_public_config(channel: Channel) -> dict[str, object]:
    return json.loads(channel.public_config_json)


def decode_secret_config(channel: Channel, cipher: SecretCipher) -> dict[str, str]:
    payload = json.loads(channel.secret_config_encrypted or "{}")
    return {key: cipher.decrypt(value) for key, value in payload.items()}


def channel_payload(channel: Channel, cipher: SecretCipher) -> dict[str, object]:
    secrets = decode_secret_config(channel, cipher)
    public_config = decode_public_config(channel)
    return {
        "id": channel.id,
        "name": channel.name,
        "provider": channel.provider,
        "providerType": channel.provider,
        "provider_type": channel.provider,
        "kind": channel.kind,
        "enabled": channel.enabled,
        "publicConfig": public_config,
        "config": public_config,
        "secretConfigured": bool(secrets),
        "secretConfigMask": {key: mask_secret(value) for key, value in secrets.items()},
        "lastTestStatus": channel.last_test_status,
        "last_test_status": channel.last_test_status,
    }


def get_or_create_setting(session: Session, key: str, default: str) -> AppSetting:
    setting = session.get(AppSetting, key)
    if setting is None:
        setting = AppSetting(key=key, value_json=default)
        session.add(setting)
        session.commit()
        session.refresh(setting)
    return setting
