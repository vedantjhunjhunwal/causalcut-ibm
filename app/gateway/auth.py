"""Gateway authentication.

The approval gateway is the one place where a human decision turns a
recommendation into an operational request, so access to it is gated. For the
MVP this is API-key based (design doc 9.2: "Basic API key authentication"),
with each key bound to an operator identity and role. Production would swap
this for real RBAC/SSO behind the same interface.

Roles carry an authority level; an approval is only accepted if the approver's
role meets the recommendation's ``required_approver_role``.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from dataclasses import dataclass

logger = logging.getLogger("causalcut.auth")


# Authority ordering: higher can approve anything a lower role can.
ROLE_AUTHORITY = {
    "viewer": 0,
    "operator": 1,
    "shift_officer": 2,
    "safety_manager": 3,
}


@dataclass(frozen=True)
class Operator:
    operator_id: str
    role: str

    @property
    def authority(self) -> int:
        return ROLE_AUTHORITY.get(self.role, 0)


class AuthError(Exception):
    pass


class AuthService:
    """Maps API keys -> operators and checks role authority.

    Keys are never stored in the clear; only their SHA-256 hash is kept, and
    comparisons use a constant-time compare.
    """

    def __init__(self) -> None:
        self._by_hash: dict[str, Operator] = {}
        self._load_from_env()

    def _load_from_env(self) -> None:
        """Load operator keys from CAUSALCUT_OPERATORS env var.

        Format: "operator_id:role:api_key,operator_id:role:api_key,..."
        Falls back to a deterministic dev set if unset (MVP convenience).
        """
        raw = os.getenv("CAUSALCUT_OPERATORS")
        if raw:
            for entry in raw.split(","):
                parts = entry.strip().split(":")
                if len(parts) == 3:
                    op_id, role, key = parts
                    self.register_key(op_id, role, key)
            logger.info("loaded %d operator key(s) from environment", len(self._by_hash))
            return

        # Dev fallback -- documented in README; DO NOT ship to production.
        self.register_key("SO-A", "shift_officer", "dev-key-so-a")
        self.register_key("SO-B", "shift_officer", "dev-key-so-b")
        self.register_key("SM-01", "safety_manager", "dev-key-sm-01")
        self.register_key("VIEW-01", "viewer", "dev-key-viewer")
        logger.warning("using built-in DEV operator keys -- set CAUSALCUT_OPERATORS in production")

    @staticmethod
    def _hash(api_key: str) -> str:
        return hashlib.sha256(api_key.encode("utf-8")).hexdigest()

    def register_key(self, operator_id: str, role: str, api_key: str) -> None:
        if role not in ROLE_AUTHORITY:
            raise ValueError(f"unknown role: {role}")
        self._by_hash[self._hash(api_key)] = Operator(operator_id, role)

    def authenticate(self, api_key: str | None) -> Operator:
        if not api_key:
            raise AuthError("missing API key")
        digest = self._hash(api_key)
        for known_hash, operator in self._by_hash.items():
            if hmac.compare_digest(known_hash, digest):
                return operator
        raise AuthError("invalid API key")

    def require_authority(self, operator: Operator, required_role: str) -> None:
        need = ROLE_AUTHORITY.get(required_role, 99)
        if operator.authority < need:
            raise AuthError(
                f"operator {operator.operator_id} (role={operator.role}) "
                f"lacks authority for role '{required_role}'"
            )
