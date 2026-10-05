"""Pure outcome for a purchase that cannot be fulfilled. No I/O or payment clients."""

from enum import Enum


class Action(Enum):
    REFUND = "refund"
    HOLD = "hold"
    HOLD_AND_DISABLE = "hold_and_disable"


def settlement_outcome(payment_status, reverted):
    """Choose one action from the payment state and whether the transfer reverted.

    Refund only when no payment was sent or signed, or the signed transfer
    reverted. A confirmed payment stays reserved and disables the service.
    A sent API-key request holds the reservation and leaves the provider enabled.
    Any other status holds the reservation and leaves the provider enabled.
    """
    if payment_status == "sent":
        return Action.HOLD
    if reverted or payment_status == "unsigned":
        return Action.REFUND
    if payment_status == "signed":
        return Action.HOLD
    if payment_status == "confirmed":
        return Action.HOLD_AND_DISABLE
    return Action.HOLD
