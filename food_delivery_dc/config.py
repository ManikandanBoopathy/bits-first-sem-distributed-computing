"""
Static process registry for the distributed food delivery system.

In a real cloud-lab deployment, replace "127.0.0.1" with the actual
node IP addresses of each VM/container, one process per node.
"""

CONFIG = {
    "OrderProcessor":  ("127.0.0.1", 6000),
    "Restaurant1":     ("127.0.0.1", 6001),
    "Restaurant2":     ("127.0.0.1", 6002),
    "DeliveryPartner": ("127.0.0.1", 6003),
}
