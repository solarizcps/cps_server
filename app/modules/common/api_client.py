# -*- coding: utf-8 -*-
"""CPS - MES v2 API Client (Faz 4.3 Remote)"""
import requests
from config import Config

DEFAULT_TIMEOUT = 10


def get(path, headers=None, params=None):
    url = Config.MES_API_URL.rstrip('/') + ('/' + path.lstrip('/'))
    return requests.get(url, headers=headers, params=params, timeout=DEFAULT_TIMEOUT)


def post(path, data=None, headers=None):
    url = Config.MES_API_URL.rstrip('/') + ('/' + path.lstrip('/'))
    h = dict(headers or {})
    h.setdefault('Content-Type', 'application/json')
    return requests.post(url, json=data, headers=h, timeout=DEFAULT_TIMEOUT)
