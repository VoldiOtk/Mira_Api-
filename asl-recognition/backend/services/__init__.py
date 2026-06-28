from __future__ import annotations
from typing import Any, Optional


class ApiAccessStore:
    def log_request(self, **kwargs: Any) -> None:
        pass

    def find_by_api_key(self, api_key: str) -> Optional[Any]:
        return None


api_access_store = ApiAccessStore()
