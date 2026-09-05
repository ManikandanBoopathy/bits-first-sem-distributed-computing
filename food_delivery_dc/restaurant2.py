import time
from node import Process
from config import CONFIG


def main():
    p = Process("Restaurant2", CONFIG)

    def on_message(mtype, sender, payload):
        if mtype == "NewOrder":
            oid = payload["order_id"]
            p.local_state[f"Order#{oid}"] = "RECEIVED"
            p.internal_event(f"Preparing Order#{oid} ({payload['item']}) at Restaurant2")
            time.sleep(1.8)  # slower kitchen: finishes AFTER the snapshot has already started
            p.local_state[f"Order#{oid}"] = "READY"
            p.send("DeliveryPartner", "OrderReady", {"order_id": oid, "restaurant": "Restaurant2"})

    p.on_message_callback = on_message
    p.start_server()

    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
