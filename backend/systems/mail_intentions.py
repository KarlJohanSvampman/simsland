# =========================================================
# MAILBOX INTENTIONS
# =========================================================

def update_mail_intentions(

    c,

    world
):

    household = world[
        "households"
    ].get(
        c.get("household_id")
    )

    if not household:
        return

    mailbox = household.get(
        "mailbox",
        {}
    )

    # =====================================================
    # MAIL
    # =====================================================

    if mailbox.get(
        "has_mail"
    ):

        push_intention(

            c,

            {

                "type":
                    "check_mail",

                "category":
                    "errand",

                "priority":
                    0.45,

                "source":
                    "mail"
            }
        )

    # =====================================================
    # PACKAGES
    # =====================================================

    if household.get(
        "pending_packages"
    ):

        push_intention(

            c,

            {

                "type":
                    "retrieve_package",

                "category":
                    "errand",

                "priority":
                    0.65,

                "source":
                    "delivery"
            }
        )