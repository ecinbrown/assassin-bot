"""
PRDT Finance Web3 Smart Contract Execution Engine
==================================================
Handles non-custodial automated execution on PRDT Finance decentralized prediction
contracts (BNB Chain, Arbitrum, Polygon, BSC Testnet).

Architecture:
1. Connects directly to blockchain RPC via Web3.py.
2. Queries active round epoch and checks lock-time safety buffers.
3. Prepares, signs, and broadcasts raw EVM transactions (betBull / betBear).
4. Auto-tracks entered rounds and triggers claim() upon settlement.
"""
import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("PRDTContract")

PRDT_PREDICTION_ABI = [
    {
        "inputs": [],
        "name": "currentEpoch",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [{"internalType": "uint256", "name": "epoch", "type": "uint256"}],
        "name": "rounds",
        "outputs": [
            {"internalType": "uint256", "name": "epoch", "type": "uint256"},
            {"internalType": "uint256", "name": "startTimestamp", "type": "uint256"},
            {"internalType": "uint256", "name": "lockTimestamp", "type": "uint256"},
            {"internalType": "uint256", "name": "closeTimestamp", "type": "uint256"},
            {"internalType": "int256", "name": "lockPrice", "type": "int256"},
            {"internalType": "int256", "name": "closePrice", "type": "int256"},
            {"internalType": "uint256", "name": "totalAmount", "type": "uint256"},
            {"internalType": "uint256", "name": "bullAmount", "type": "uint256"},
            {"internalType": "uint256", "name": "bearAmount", "type": "uint256"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "epoch", "type": "uint256"},
            {"internalType": "address", "name": "user", "type": "address"}
        ],
        "name": "ledger",
        "outputs": [
            {"internalType": "uint8", "name": "position", "type": "uint8"},  # 0: Bull, 1: Bear
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
            {"internalType": "bool", "name": "claimed", "type": "bool"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "epoch", "type": "uint256"},
            {"internalType": "address", "name": "user", "type": "address"}
        ],
        "name": "claimable",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [{"internalType": "uint256", "name": "epoch", "type": "uint256"}],
        "name": "betBull",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function"
    },
    {
        "inputs": [{"internalType": "uint256", "name": "epoch", "type": "uint256"}],
        "name": "betBear",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function"
    },
    {
        "inputs": [{"internalType": "uint256[]", "name": "epochs", "type": "uint256[]"}],
        "name": "claim",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]


@dataclass
class EnteredRound:
    epoch: int
    action: str            # 'call' (Bull) or 'put' (Bear)
    amount_native: float
    tx_hash: str
    entry_time: float
    claimed: bool = False


class PRDTAgent:
    """
    Direct Web3 Smart Contract Executor for PRDT Finance.
    """

    def __init__(
        self,
        rpc_url: Optional[str] = None,
        contract_address: Optional[str] = None,
        private_key: Optional[str] = None,
        default_stake_native: float = 0.01,
        min_buffer_seconds: int = 20,
        gas_limit: int = 160000,
        simulation_mode: bool = True
    ):
        self.rpc_url = rpc_url or os.environ.get("PRDT_RPC_URL", "https://bsc-dataseed.binance.org/")
        self.contract_address = contract_address or os.environ.get("PRDT_CONTRACT_ADDRESS", "")
        self.private_key = private_key or os.environ.get("WALLET_PRIVATE_KEY", "")
        self.default_stake = float(os.environ.get("PRDT_STAKE_NATIVE", default_stake_native))
        self.min_buffer_seconds = min_buffer_seconds
        self.gas_limit = gas_limit
        self.simulation_mode = simulation_mode or (not self.private_key or not self.contract_address)

        self.w3 = None
        self.account = None
        self.contract = None
        self.entered_rounds: Dict[int, EnteredRound] = {}
        self._nonce = None

    def initialize(self) -> bool:
        """Initialize Web3 connection, account credentials, and contract instance."""
        try:
            from web3 import Web3
            self.w3 = Web3(Web3.HTTPProvider(self.rpc_url, request_kwargs={'timeout': 10}))
            
            connected = self.w3.is_connected()
            if not connected:
                if self.simulation_mode:
                    logger.warning(f"⚠️ RPC node unreachable at {self.rpc_url}. Running in pure offline SIMULATION mode.")
                    return True
                logger.error(f"❌ Failed to connect to RPC node at {self.rpc_url}")
                return False

            chain_id = self.w3.eth.chain_id
            logger.info(f"🌐 Connected to Web3 RPC (Chain ID: {chain_id})")

            # Load Account
            if self.private_key and not self.private_key.startswith("0x00000"):
                key = self.private_key if self.private_key.startswith("0x") else f"0x{self.private_key}"
                self.account = self.w3.eth.account.from_key(key)
                self._nonce = self.w3.eth.get_transaction_count(self.account.address)
                balance_wei = self.w3.eth.get_balance(self.account.address)
                balance_native = float(self.w3.from_wei(balance_wei, 'ether'))
                logger.info(f"🔑 Wallet Loaded: {self.account.address} | Balance: {balance_native:.4f} Native")
            else:
                logger.info("ℹ️ No private key configured. Running in SIMULATION mode.")
                self.simulation_mode = True

            # Load Contract
            if self.contract_address:
                checksum_addr = self.w3.to_checksum_address(self.contract_address)
                self.contract = self.w3.eth.contract(address=checksum_addr, abi=PRDT_PREDICTION_ABI)
                logger.info(f"📜 PRDT Smart Contract bound: {checksum_addr}")
            else:
                logger.info("ℹ️ No contract address configured. Running in SIMULATION mode.")
                self.simulation_mode = True

            return True
        except Exception as e:
            logger.error(f"Error during PRDTAgent initialization: {e}")
            if self.simulation_mode:
                return True
            return False

    def get_current_epoch(self) -> int:
        """Fetch current active epoch number from the smart contract."""
        if self.contract and self.w3 and self.w3.is_connected():
            try:
                return self.contract.functions.currentEpoch().call()
            except Exception as e:
                logger.warning(f"Failed to fetch currentEpoch: {e}")
        # Fallback simulation epoch based on 5-minute (300s) intervals
        return int(time.time() // 300)

    def get_round_info(self, epoch: Optional[int] = None) -> Dict:
        """Fetch round status, timing, locked price, and remaining betting window."""
        if epoch is None:
            epoch = self.get_current_epoch()

        now = int(time.time())
        if self.contract and self.w3 and self.w3.is_connected():
            try:
                r = self.contract.functions.rounds(epoch).call()
                # round tuple: (epoch, startTimestamp, lockTimestamp, closeTimestamp, lockPrice, closePrice, totalAmount, bullAmount, bearAmount)
                lock_time = r[2]
                time_to_lock = max(0, lock_time - now)
                return {
                    "epoch": r[0],
                    "start_time": r[1],
                    "lock_time": lock_time,
                    "close_time": r[3],
                    "lock_price": r[4] / 1e8 if r[4] > 0 else 0.0,
                    "close_price": r[5] / 1e8 if r[5] > 0 else 0.0,
                    "total_pool_native": float(self.w3.from_wei(r[6], 'ether')),
                    "bull_pool_native": float(self.w3.from_wei(r[7], 'ether')),
                    "bear_pool_native": float(self.w3.from_wei(r[8], 'ether')),
                    "time_to_lock_seconds": time_to_lock,
                    "is_betting_open": time_to_lock > self.min_buffer_seconds
                }
            except Exception as e:
                logger.warning(f"Failed to fetch round data for epoch {epoch}: {e}")

        # Simulated 5-minute round info
        epoch_start = epoch * 300
        lock_time = epoch_start + 300
        time_to_lock = max(0, lock_time - now)
        return {
            "epoch": epoch,
            "start_time": epoch_start,
            "lock_time": lock_time,
            "close_time": lock_time + 300,
            "lock_price": 0.0,
            "close_price": 0.0,
            "total_pool_native": 12.5,
            "bull_pool_native": 6.8,
            "bear_pool_native": 5.7,
            "time_to_lock_seconds": time_to_lock,
            "is_betting_open": time_to_lock > self.min_buffer_seconds
        }

    async def execute_trade(self, signal, stake_native: Optional[float] = None) -> Tuple[bool, str]:
        """
        Execute betBull (CALL) or betBear (PUT) transaction on PRDT Smart Contract.
        
        Args:
            signal: AssassinSignal object.
            stake_native: Optional stake override in native token (BNB/ETH/MATIC).
        
        Returns:
            (success: bool, tx_hash_or_reason: str)
        """
        return await asyncio.to_thread(self._sync_execute_trade, signal, stake_native)

    def _sync_execute_trade(self, signal, stake_native: Optional[float] = None) -> Tuple[bool, str]:
        stake = stake_native if stake_native is not None else self.default_stake
        action = signal.action.lower()  # 'call' or 'put'
        epoch = self.get_current_epoch()
        round_info = self.get_round_info(epoch)

        time_left = round_info.get("time_to_lock_seconds", 0)
        logger.info(
            f"🎯 [PRDT CONTRACT] Target Epoch: #{epoch} | "
            f"Action: {action.upper()} | Time to Lock: {time_left}s | "
            f"Stake: {stake:.4f} Native"
        )

        # Safety buffer check
        if time_left < self.min_buffer_seconds:
            msg = f"Skipped trade: Only {time_left}s left in Epoch #{epoch} (buffer minimum is {self.min_buffer_seconds}s)."
            logger.warning(f"⏳ {msg}")
            return False, msg

        # SIMULATION MODE EXECUTION
        if self.simulation_mode or not self.contract or not self.account:
            sim_tx = f"0xsim_{epoch}_{action}_{int(time.time())}"
            self.entered_rounds[epoch] = EnteredRound(
                epoch=epoch,
                action=action,
                amount_native=stake,
                tx_hash=sim_tx,
                entry_time=time.time(),
                claimed=False
            )
            logger.info(
                f"🧪 [SIMULATION TRADE EXECUTED] Epoch #{epoch} | "
                f"{action.upper()} | Stake: {stake:.4f} Native | "
                f"Simulated TxHash: {sim_tx}"
            )
            return True, sim_tx

        # LIVE ON-CHAIN TRANSACTION EXECUTION
        try:
            stake_wei = self.w3.to_wei(stake, 'ether')
            fn = self.contract.functions.betBull(epoch) if action == 'call' else self.contract.functions.betBear(epoch)

            gas_price = self.w3.eth.gas_price
            nonce = self.w3.eth.get_transaction_count(self.account.address)

            tx_params = {
                'from': self.account.address,
                'value': stake_wei,
                'gas': self.gas_limit,
                'gasPrice': int(gas_price * 1.15),  # 15% priority bump for fast inclusion
                'nonce': nonce,
                'chainId': self.w3.eth.chain_id
            }

            # Build and sign transaction
            tx = fn.build_transaction(tx_params)
            signed_tx = self.w3.eth.account.sign_transaction(tx, private_key=self.account.key)

            # Broadcast transaction
            raw_tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            tx_hash_hex = self.w3.to_hex(raw_tx_hash)

            logger.critical(
                f"🚀 [ON-CHAIN TX BROADCAST] Epoch #{epoch} {action.upper()} | "
                f"Stake: {stake:.4f} Native | TxHash: {tx_hash_hex}"
            )

            # Register entered round for automated settlement claiming
            self.entered_rounds[epoch] = EnteredRound(
                epoch=epoch,
                action=action,
                amount_native=stake,
                tx_hash=tx_hash_hex,
                entry_time=time.time(),
                claimed=False
            )

            return True, tx_hash_hex

        except Exception as e:
            logger.error(f"❌ Smart contract execution failed: {e}")
            return False, str(e)

    async def auto_claim_winnings(self) -> List[str]:
        """Check all past entered epochs and claim winning payouts."""
        return await asyncio.to_thread(self._sync_auto_claim)

    def _sync_auto_claim(self) -> List[str]:
        """Synchronous implementation of auto-claim batching."""
        if not self.entered_rounds or self.simulation_mode or not self.contract or not self.account:
            return []

        current_epoch = self.get_current_epoch()
        claimable_epochs = []

        for epoch, r in self.entered_rounds.items():
            if epoch < current_epoch and not r.claimed:
                try:
                    # Check if claimable on smart contract
                    is_claimable = self.contract.functions.claimable(epoch, self.account.address).call()
                    if is_claimable:
                        claimable_epochs.append(epoch)
                except Exception as e:
                    logger.debug(f"Error checking claimable for epoch #{epoch}: {e}")

        if not claimable_epochs:
            return []

        try:
            logger.info(f"🎁 Claiming winnings for {len(claimable_epochs)} epochs: {claimable_epochs}...")
            nonce = self.w3.eth.get_transaction_count(self.account.address)
            gas_price = self.w3.eth.gas_price

            tx = self.contract.functions.claim(claimable_epochs).build_transaction({
                'from': self.account.address,
                'gas': self.gas_limit * len(claimable_epochs),
                'gasPrice': int(gas_price * 1.1),
                'nonce': nonce,
                'chainId': self.w3.eth.chain_id
            })

            signed_tx = self.w3.eth.account.sign_transaction(tx, private_key=self.account.key)
            raw_tx = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            claim_tx_hash = self.w3.to_hex(raw_tx)

            for ep in claimable_epochs:
                if ep in self.entered_rounds:
                    self.entered_rounds[ep].claimed = True

            logger.critical(f"🎉 [WINNINGS CLAIMED] TxHash: {claim_tx_hash} | Epochs: {claimable_epochs}")
            return [claim_tx_hash]
        except Exception as e:
            logger.error(f"❌ Failed to claim winnings: {e}")
            return []
