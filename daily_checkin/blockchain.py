import os
from web3 import Web3
from eth_account import Account


class DailyCheckinBlockchainService:
    def __init__(self):
        self.celo_rpc_url = os.getenv("CELO_RPC_URL", "https://forno.celo.org")
        self.chain_id = int(os.getenv("CHAIN_ID", 42220))
        task_key = os.getenv("TASK_KEY")
        self.w3 = Web3(Web3.HTTPProvider(self.celo_rpc_url))
        self.task_account = None
        if task_key:
            if not task_key.startswith("0x"):
                task_key = "0x" + task_key
            self.task_account = Account.from_key(task_key)

    def send_celo(self, recipient: str, amount_celo: float) -> dict:
        if not self.task_account:
            return {"success": False, "error": "TASK_KEY not configured"}
        if not self.w3.is_connected():
            return {"success": False, "error": "Blockchain connection failed"}

        to_addr = Web3.to_checksum_address(recipient)
        from_addr = self.task_account.address
        value_wei = self.w3.to_wei(amount_celo, "ether")

        gas_price = self.w3.eth.gas_price
        nonce = self.w3.eth.get_transaction_count(from_addr, "pending")
        tx = {
            "chainId": self.chain_id,
            "nonce": nonce,
            "to": to_addr,
            "value": value_wei,
            "gas": 21000,
            "gasPrice": gas_price,
        }

        signed = self.w3.eth.account.sign_transaction(tx, self.task_account.key)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        return {
            "success": receipt.status == 1,
            "tx_hash": tx_hash.hex(),
            "status": receipt.status,
            "amount": amount_celo,
        }


daily_checkin_blockchain = DailyCheckinBlockchainService()
