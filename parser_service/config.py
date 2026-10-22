"""Обязательные ограничения конфигурации API и миграции."""

import os


def positive_setting(name):
    try:
        value = int(os.environ[name])
    except (KeyError, ValueError):
        raise ValueError(f"{name} must be a positive integer") from None
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value
