"""
Web3.py integration with the locally deployed RECRegistry smart contract.

Designed to fail soft: if the Hardhat node isn't running (or the contract
hasn't been deployed yet), every call here returns a structured "offline"
result instead of raising, so the rest of the pipeline can keep running and
mark the transaction as pending blockchain synchronization, per the project
requirements.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

from web3 import Web3
from web3.exceptions import Web3Exception

import config

logger = logging.getLogger("blockchain_service")

STATUS_NAMES = ["ACTIVE", "RETIRED", "REVOKED", "FROZEN"]


@dataclass
class TxResult:
    ok: bool
    tx_hash: Optional[str] = None
    error: Optional[str] = None
    pending_sync: bool = False


class BlockchainService:
    def __init__(self):
        self.w3: Optional[Web3] = None
        self.contract = None
        self.wallets: dict[str, dict] = {}   # label -> {address, private_key, role, index}
        self.wallets_by_role: dict[str, list[dict]] = {}
        self._load_wallets()
        self._connect()

    # ---------------- setup ----------------

    def _load_wallets(self) -> None:
        try:
            with open(config.CHAIN_DIR / "wallets.json") as f:
                wallets = json.load(f)
            for w in wallets:
                self.wallets[w["label"]] = w
                self.wallets_by_role.setdefault(w["role"], []).append(w)
        except FileNotFoundError:
            logger.warning("wallets.json not found -- run `npm run deploy && npm run seed-roles` in contracts/")

    def _connect(self) -> None:
        try:
            self.w3 = Web3(Web3.HTTPProvider(config.WEB3_PROVIDER_URI, request_kwargs={"timeout": 3}))
            if not self.w3.is_connected():
                self.w3 = None
                return
            with open(config.CONTRACT_ABI_PATH) as f:
                abi = json.load(f)
            with open(config.CONTRACT_ADDRESS_PATH) as f:
                address = json.load(f)["address"]
            self.contract = self.w3.eth.contract(address=Web3.to_checksum_address(address), abi=abi)
        except (FileNotFoundError, Web3Exception, ConnectionError, Exception) as e:
            logger.warning("Blockchain unavailable, running in offline mode: %s", e)
            self.w3 = None
            self.contract = None

    @property
    def is_online(self) -> bool:
        if self.w3 is None:
            self._connect()  # retry -- the Hardhat node may have started since last check
        return self.w3 is not None and self.contract is not None

    def status(self) -> dict:
        if self.is_online:
            return {
                "status": "ONLINE",
                "provider": config.WEB3_PROVIDER_URI,
                "contract_address": self.contract.address,
                "chain_id": self.w3.eth.chain_id,
                "block_number": self.w3.eth.block_number,
            }
        return {"status": "OFFLINE", "provider": config.WEB3_PROVIDER_URI, "reason": "no connection to Hardhat node"}

    # ---------------- signing helper ----------------

    def _wallet_for_role(self, role: str, prefer_label: Optional[str] = None) -> Optional[dict]:
        if prefer_label and prefer_label in self.wallets:
            return self.wallets[prefer_label]
        candidates = self.wallets_by_role.get(role, [])
        return candidates[0] if candidates else None

    def _send(self, fn, wallet: dict) -> TxResult:
        try:
            account = self.w3.eth.account.from_key(wallet["private_key"])
            tx = fn.build_transaction({
                "from": account.address,
                "nonce": self.w3.eth.get_transaction_count(account.address),
            })
            signed = account.sign_transaction(tx)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=15)
            return TxResult(ok=True, tx_hash=tx_hash.hex())
        except Exception as e:
            logger.error("blockchain tx failed: %s", e)
            return TxResult(ok=False, error=str(e))

    # ---------------- REC lifecycle ----------------

    def issue_rec(self, rec_id: str, generator_id: str, quantity: float, owner_address: str,
                  generation_data_hash: str, issuer_label: str = "Issuer") -> TxResult:
        if not self.is_online:
            return TxResult(ok=False, pending_sync=True, error="blockchain offline")
        wallet = self._wallet_for_role("ISSUER_ROLE", issuer_label)
        if not wallet:
            return TxResult(ok=False, error="no ISSUER_ROLE wallet available")
        fn = self.contract.functions.issueREC(
            rec_id, generator_id, int(quantity * 1000),
            Web3.to_checksum_address(owner_address),
            bytes.fromhex(generation_data_hash.replace("0x", "")),
        )
        return self._send(fn, wallet)

    def transfer_rec(self, rec_id: str, from_label: str, to_address: str) -> TxResult:
        if not self.is_online:
            return TxResult(ok=False, pending_sync=True, error="blockchain offline")
        wallet = self.wallets.get(from_label)
        if not wallet:
            return TxResult(ok=False, error=f"unknown wallet label '{from_label}'")
        fn = self.contract.functions.transferREC(rec_id, Web3.to_checksum_address(to_address))
        return self._send(fn, wallet)

    def retire_rec(self, rec_id: str, owner_label: str) -> TxResult:
        if not self.is_online:
            return TxResult(ok=False, pending_sync=True, error="blockchain offline")
        wallet = self.wallets.get(owner_label)
        if not wallet:
            return TxResult(ok=False, error=f"unknown wallet label '{owner_label}'")
        fn = self.contract.functions.retireREC(rec_id)
        return self._send(fn, wallet)

    def revoke_rec(self, rec_id: str, reason: str = "") -> TxResult:
        if not self.is_online:
            return TxResult(ok=False, pending_sync=True, error="blockchain offline")
        wallet = self._wallet_for_role("REGULATOR_ROLE")
        if not wallet:
            return TxResult(ok=False, error="no REGULATOR_ROLE wallet available")
        fn = self.contract.functions.revokeREC(rec_id, reason)
        return self._send(fn, wallet)

    def freeze_rec(self, rec_id: str) -> TxResult:
        if not self.is_online:
            return TxResult(ok=False, pending_sync=True, error="blockchain offline")
        wallet = self._wallet_for_role("REGULATOR_ROLE")
        fn = self.contract.functions.freezeREC(rec_id)
        return self._send(fn, wallet)

    def verify_rec(self, rec_id: str) -> Optional[dict]:
        if not self.is_online:
            return None
        try:
            result = self.contract.functions.verifyREC(rec_id).call()
            generator_id, quantity, issue_ts, owner, status, data_hash = result
            return {
                "generator_id": generator_id,
                "quantity": quantity / 1000,
                "issue_timestamp": issue_ts,
                "current_owner": owner,
                "status": STATUS_NAMES[status],
                "generation_data_hash": data_hash.hex(),
            }
        except Exception as e:
            logger.info("verify_rec(%s) failed (likely not yet minted): %s", rec_id, e)
            return None

    def get_receipt(self, tx_hash: str) -> Optional[dict]:
        if not self.is_online:
            return None
        try:
            receipt = self.w3.eth.get_transaction_receipt(tx_hash)
            return {
                "block_number": receipt["blockNumber"],
                "gas_used": receipt["gasUsed"],
                "status": receipt["status"],
            }
        except Exception:
            return None


_service: Optional[BlockchainService] = None


def get_service() -> BlockchainService:
    global _service
    if _service is None:
        _service = BlockchainService()
    return _service
