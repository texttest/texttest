"""
Minimal client for the HashiCorp Nomad HTTP API, used by the nomad queue system module.

Requests and responses are plain Python data. This is kept in its own module so that
all traffic with Nomad can be intercepted as a whole, e.g. by CaptureMock in the self-tests.
Import it as "import texttestlib.queuesystem.nomadapi": "from ... import" forms bypass the
import hooks CaptureMock relies on, so the self-tests would contact Nomad for real.
The standard Nomad environment variables NOMAD_ADDR and NOMAD_TOKEN are respected, as are
NOMAD_CACERT or NOMAD_CAPATH (to trust a private certificate authority) and NOMAD_CLIENT_CERT
with NOMAD_CLIENT_KEY (for servers that require client certificates) when using https.
TLS 1.2 is the minimum version accepted.
"""

import functools
import http.client
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_ADDRESS = "http://127.0.0.1:4646"
REQUEST_TIMEOUT = 30


class NomadError(Exception):
    pass


def getAddress():
    return os.getenv("NOMAD_ADDR", DEFAULT_ADDRESS).rstrip("/")


def get(path, **params):
    return request("GET", path, params=params)


def request(method, path, body=None, params=None, parseJson=True):
    address = getAddress()
    url = address + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    token = os.getenv("NOMAD_TOKEN")
    if token:
        headers["X-Nomad-Token"] = token
    httpRequest = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        context = getSslContext(*getTlsSettings()) if url.startswith("https:") else None
    except (OSError, ValueError) as e:  # e.g. a missing certificate file, or a client key without a certificate
        raise NomadError("could not set up TLS for Nomad at " + address + ": " + str(e))
    try:
        with urllib.request.urlopen(httpRequest, timeout=REQUEST_TIMEOUT, context=context) as response:
            # Log output may be cut in the middle of a character
            text = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise NomadError(method + " " + url + " failed with HTTP status " + str(e.code) + ": " + readErrorBody(e))
    except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
        raise NomadError("could not contact Nomad at " + address + ": " + str(getattr(e, "reason", e)))
    if not parseJson:
        return text
    try:
        return json.loads(text) if text else None
    except ValueError:
        raise NomadError("unexpected response from " + method + " " + url + ": " + text[:200])


def readErrorBody(error):
    try:
        return error.read().decode("utf-8", "replace").strip()
    except OSError:
        return ""


def getTlsSettings():
    return tuple(os.getenv(var) or None for var in ["NOMAD_CACERT", "NOMAD_CAPATH", "NOMAD_CLIENT_CERT", "NOMAD_CLIENT_KEY"])


@functools.lru_cache(maxsize=None)
def getSslContext(caFile, caPath, clientCert, clientKey):
    context = ssl.create_default_context(cafile=caFile, capath=caPath)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    if clientCert:
        context.load_cert_chain(clientCert, clientKey)
    elif clientKey:
        raise ValueError("NOMAD_CLIENT_KEY is set but NOMAD_CLIENT_CERT is not")
    return context
