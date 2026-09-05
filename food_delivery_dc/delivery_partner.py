import time
from node import Process
from config import CONFIG


def main():
    p = Process("DeliveryPartner", CONFIG)
    # Simulated processing/network latency: makes it likely a message
    # sent just before the snapshot starts is still "in transit" (unprocessed)
    # when this process starts recording, so it shows up in the channel state.
    p.message_delay = 1.5

    def on_message(mtype, sender, payload):
        if mtype == "OrderReady":
            oid = payload["order_id"]
            p.local_state[f"Order#{oid}"] = "PICKING_UP"
            p.internal_event(f"Picking up Order#{oid} from {sender}")
            time.sleep(1.0)
            p.local_state[f"Order#{oid}"] = "OUT_FOR_DELIVERY"
            p.send("OrderProcessor", "PickedUp", {"order_id": oid})

    p.on_message_callback = on_message
    p.start_server()

    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
