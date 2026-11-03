"""Money-path checks. Run: python bank_test.py"""

import bank

CHECKING = 428_016
SAVINGS = 1_264_000


def main():
    b = bank.create_bank()
    said = bank.handle(b, "what's my checking balance?")
    assert said["hit"] and "4,280 dollars and 16 cents" in said["speech"]
    assert b["accounts"]["checking"]["cents"] == CHECKING

    said = bank.handle(b, "hello, what's my balance")
    assert "Checking has" in said["speech"] and "Savings has" in said["speech"]

    said = bank.handle(b, "recent charges")
    assert "Netflix" in said["speech"] and "15 dollars and 99 cents" in said["speech"]

    b = bank.create_bank()
    said = bank.handle(b, "move fifty dollars to savings")
    assert "Say confirm." in said["speech"]
    assert b["accounts"]["checking"]["cents"] == CHECKING
    said = bank.handle(b, "what's my balance")
    assert b["pending"] is None
    bank.handle(b, "yes")
    assert b["accounts"]["checking"]["cents"] == CHECKING

    b = bank.create_bank()
    bank.handle(b, "move 50 dollars to savings")
    bank.handle(b, "confirm")
    assert b["accounts"]["checking"]["cents"] == CHECKING - 5_000
    assert b["accounts"]["savings"]["cents"] == SAVINGS + 5_000
    assert sum(a["cents"] for a in b["accounts"].values()) == CHECKING + SAVINGS

    b = bank.create_bank()
    said = bank.handle(b, "move 9000 dollars to savings")
    assert "can't move" in said["speech"]
    assert b["pending"] is None
    assert b["accounts"]["checking"]["cents"] == CHECKING

    b = bank.create_bank()
    bank.handle(b, "transfer 25")
    said = bank.handle(b, "savings")
    assert "Say confirm." in said["speech"]
    bank.handle(b, "cancel")
    assert b["accounts"]["checking"]["cents"] == CHECKING

    b = bank.create_bank()
    said = bank.handle(b, "move 50.25 to savings")
    assert "50 dollars and 25 cents" in said["speech"]
    said = bank.handle(b, "move two hundred fifty dollars to savings")
    assert "250 dollars" in said["speech"]

    b = bank.create_bank()
    bank.handle(b, "freeze my card")
    assert b["card"] == "frozen"
    bank.handle(b, "unlock my card")
    assert b["card"] == "active"

    b = bank.create_bank()
    assert bank.handle(b, "what's the weather in paris")["hit"] is False
    assert b["pending"] is None

    facts = bank.snapshot(bank.create_bank())
    leaked = bank.scrub_amounts("Your balance is $9,999.00 today.", facts)
    assert "$9,999.00" not in leaked
    kept = bank.scrub_amounts("Checking is $4,280.16.", facts)
    assert "$4,280.16" in kept

    print("ok")


if __name__ == "__main__":
    main()
