"""
systems/banking.py

Real deposit-account ledger for the 5 starter banks (personal_items.py's
STARTER_BANKS). Mirrors investments.py's per-character-dict pattern, but
the ledger here lives on world["banks"] since an account balance belongs
to the bank's own records, not the character (a bank_card item only ever
references {bank, account_number} — see personal_items.py::make_bank_card).

world["banks"] = {
    "bank_jpmc": {
        "accounts": {
            "1234567890": {"owner_id": "char_...", "balance": 100.0, "opened_tick": 42},
        }
    },
    ...
}
"""

import random

# personal_items.STARTER_BANKS display names -> company_templates keys
# (see definitions.json's bank_jpmc/bank_morgan_stanley/bank_barclays/
# bank_td_bank/bank_of_america entries).
BANK_NAME_TO_KEY = {
    "JPMC": "bank_jpmc",
    "Morgan Stanley": "bank_morgan_stanley",
    "Barclays": "bank_barclays",
    "TD Bank": "bank_td_bank",
    "Bank of America": "bank_of_america",
}


def bank_key_for_name(name):
    return BANK_NAME_TO_KEY.get(name)


def _bank_ledger(world, bank_key):
    return world.setdefault("banks", {}).setdefault(bank_key, {}).setdefault("accounts", {})


def open_account(world, bank_key, owner_id, initial_balance=0.0):
    """Creates a new account at bank_key, returns its account_number."""
    ledger = _bank_ledger(world, bank_key)
    account_number = str(random.randint(10**9, 10**10 - 1))
    while account_number in ledger:
        account_number = str(random.randint(10**9, 10**10 - 1))
    ledger[account_number] = {
        "owner_id": owner_id,
        "balance": round(float(initial_balance), 2),
        "opened_tick": world.get("tick", 0),
    }
    return account_number


def get_account(world, bank_key, account_number):
    return world.get("banks", {}).get(bank_key, {}).get("accounts", {}).get(account_number)


def get_balance(world, bank_key, account_number):
    account = get_account(world, bank_key, account_number)
    return account["balance"] if account else None


def deposit(world, bank_key, account_number, amount):
    account = get_account(world, bank_key, account_number)
    if not account or amount <= 0:
        return False
    account["balance"] = round(account["balance"] + amount, 2)
    return True


def withdraw(world, bank_key, account_number, amount):
    account = get_account(world, bank_key, account_number)
    if not account or amount <= 0 or account["balance"] < amount:
        return False
    account["balance"] = round(account["balance"] - amount, 2)
    return True
