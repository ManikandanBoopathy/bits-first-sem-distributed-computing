import time
from node import Process
from config import CONFIG


def main():
    p = Process("OrderProcessor", CONFIG)

    def on_message(mtype, sender, payload):
        if mtype == "PickedUp":
            oid = payload["order_id"]
            p.local_state[f"Order#{oid}"] = "OUT_FOR_DELIVERY"

    p.on_message_callback = on_message
    p.start_server()
    time.sleep(3)  # allow all peers to finish start_server()

    # --- Two independent orders placed almost back-to-back ---
    p.internal_event("Customer places Order#101 (Pizza) for Restaurant1")
    p.local_state["Order#101"] = "PLACED"
    p.send("Restaurant1", "NewOrder", {"order_id": 101, "item": "Pizza"})

    p.internal_event("Customer places Order#102 (Burger) for Restaurant2")
    p.local_state["Order#102"] = "PLACED"
    p.send("Restaurant2", "NewOrder", {"order_id": 102, "item": "Burger"})

    # Snapshot timing is deliberately placed AFTER Restaurant1 has sent its
    # OrderReady (fast kitchen) but BEFORE Restaurant2 has sent its (slow
    # kitchen). Combined with DeliveryPartner's simulated message_delay,
    # Restaurant1's OrderReady is still "in transit / unprocessed" at
    # DeliveryPartner when the snapshot markers arrive, so it gets captured
    # in the channel state -- while Restaurant2's channel comes back empty.
    time.sleep(1.3)

    p.internal_event("Initiating global snapshot (Chandy-Lamport)")
    p.initiate_snapshot()

    time.sleep(9)
    p.log("OrderProcessor demo sequence finished.")


if __name__ == "__main__":
    main()
