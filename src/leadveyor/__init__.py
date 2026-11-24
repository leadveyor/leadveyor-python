"""Official Python client for the Leadveyor API. Docs: https://leadveyor.com/docs/sdk/python

.. code-block:: python

    from leadveyor import Leadveyor

    lv = Leadveyor()  # reads LEADVEYOR_API_KEY
    inbound = lv.inbounds.create(text="Hi, we need catering for 80 guests on 12 March", wait=True)
    print(inbound.leads[0].evaluation.tier)
"""

from . import models
from ._base_client import DEFAULT_BASE_URL, NOT_GIVEN, NotGiven
from ._client import AsyncLeadveyor, Leadveyor
from ._errors import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    ConflictError,
    InvalidRequestError,
    LeadveyorError,
    NotFoundError,
    PermissionDeniedError,
    QuotaExceededError,
    RateLimitError,
    SignatureVerificationError,
)
from ._object import LeadveyorObject
from ._pagination import AsyncPage, AsyncPageRequest, SyncPage
from ._version import __version__
from .webhooks import Webhook

__all__ = [
    "Leadveyor",
    "AsyncLeadveyor",
    "Webhook",
    "LeadveyorObject",
    "SyncPage",
    "AsyncPage",
    "AsyncPageRequest",
    "NOT_GIVEN",
    "NotGiven",
    "DEFAULT_BASE_URL",
    "models",
    "__version__",
    "LeadveyorError",
    "InvalidRequestError",
    "AuthenticationError",
    "PermissionDeniedError",
    "NotFoundError",
    "ConflictError",
    "QuotaExceededError",
    "RateLimitError",
    "APIError",
    "APIConnectionError",
    "APITimeoutError",
    "SignatureVerificationError",
]
