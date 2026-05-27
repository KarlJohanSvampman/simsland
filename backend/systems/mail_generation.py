def generate_bill_document(

    household,

    bill
):

    return {

        "id": f"doc_{uuid.uuid4().hex[:6]}",

        "type": "bill",

        "bill_id": bill["id"],

        "bill_type": bill["type"],

        "amount": bill["remaining"],

        "urgent": False,

        "opened": False
    }

