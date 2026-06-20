import time
from brain.memory import store_memory
from systems.sms_emotion import apply_sms_emotion

def queue_message(world, sender_id, receiver_id, text, delay=5):

    world.setdefault("message_queue", []).append({
        "id": f"msg_{time.time()}",
        "from": sender_id,
        "to": receiver_id,
        "text": text,
        "send_time": time.time(),
        "deliver_at": time.time() + delay
    })


def deliver_messages(world):

    now = time.time()
    remaining = []

    for msg in world.get("message_queue", []):


        if msg["deliver_at"] > now:
            store_memory(
                receiver,
                f"Received SMS from {msg['from']}: {msg['text']}",
                tags=["phone","sms"]
            )
            remaining.append(msg)
            continue

        receiver = world["characters"].get(msg["to"])
        if not receiver:
            continue

        receiver.setdefault("phone", {}).setdefault("inbox", []).append(msg)

        sender = world["characters"].get(msg["from"])
        if sender:
            apply_sms_emotion(receiver, sender, msg["text"])
        
        contact = receiver.get("contacts", {}).get(sender["id"], {})
        count = contact.get("interaction_count", 0)

        if count > 10:
            # amplify reaction
            apply_emotion_inertia(receiver, emotion)

        # 🔔 notification
        receiver["phone"].setdefault("notifications", []).append({
            "type": "sms",
            "from": msg["from"],
            "text": msg["text"],
            "time": now
        })

    world["message_queue"] = remaining