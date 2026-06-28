"""
Delivery processing — handles both old-format (product dict) and
new-format (catalog_id + type) delivery entries.
"""

from systems.procurement import _deliver_item, _deliver_prop


def update_deliveries(world):
    deliveries = world.get("deliveries", [])
    completed  = []

    for delivery in deliveries:
        if delivery.get("status") != "in_transit":
            continue
        if world["tick"] < delivery.get("arrival_tick", 0):
            continue

        _process_delivery(delivery, world)
        completed.append(delivery)

    for d in completed:
        deliveries.remove(d)


def _process_delivery(delivery, world):
    hid       = delivery.get("household_id")
    household = world.get("households", {}).get(hid)
    if not household:
        return

    dtype      = delivery.get("type")
    catalog_id = delivery.get("catalog_id")

    if catalog_id and dtype == "item":
        _deliver_item(household, catalog_id, world)

    elif catalog_id and dtype == "prop":
        _deliver_prop(household, catalog_id, world)

    else:
        # Legacy format: delivery has a full product dict
        product = delivery.get("product")
        if product:
            _legacy_acquire(household, product, world)

    # Notify household
    household.setdefault("notifications", []).append({
        "type":       "delivery_arrived",
        "catalog_id": catalog_id or delivery.get("product", {}).get("name"),
        "tick":       world["tick"],
    })

    delivery["status"] = "delivered"


def _legacy_acquire(household, product, world):
    """Handle old-style product dict deliveries (owned_objects / resources)."""
    from systems.household_storage import add_household_resource
    from systems.resource_runtime import create_resource

    if "resource_type" in product:
        resource = create_resource(
            product["resource_type"],
            quantity=product.get("quantity", 1),
            quality=product.get("quality", 0.5),
        )
        add_household_resource(household, resource)
    else:
        household.setdefault("owned_objects", []).append({
            "object_type": product.get("object_type"),
            "quality":     product.get("quality", 0.5),
            "product":     product,
        })
