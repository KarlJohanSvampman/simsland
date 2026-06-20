def build_character_description(
    character,
    definitions
):
    parts = []

    name = character.get(
        "name",
        "Unknown"
    )

    parts.append(
        f"{name}"
    )

    appearance_traits = (
        character
        .get("appearance", {})
        .get("traits", [])
    )

    appearance_descriptions = []

    for trait_id in appearance_traits:

        tpl = (
            definitions
            .get(
                "appearance_trait_templates",
                {}
            )
            .get(trait_id)
        )

        if tpl:

            appearance_descriptions.append(
                tpl.get(
                    "description",
                    trait_id
            )
        )
    
    if appearance_descriptions:

        parts.append(
            "Appearance: "
            + ", ".join(
                appearance_descriptions
            )
        )

    employment = character.get(
        "employment",
        {}
    )

    job_id = employment.get(
        "job"
    )

    company_id = employment.get(
        "company"
    )

    job = (
        definitions
        .get(
            "job_templates",
            {}
        )
        .get(job_id)
    )

    company = (
        definitions
        .get(
            "company_templates",
            {}
        )
        .get(company_id)
    )

    sector = None

    if company:

        sector = (
            definitions
            .get(
                "sector_templates",
                {}
            )
            .get(
                company.get(
                    "sector"
                )
            )
        )

    if job:

        parts.append(

            f"Occupation: "
            f"{job.get('name')}"
        )

        if job.get(
            "job_description"
        ):

            parts.append(

                "Job Duties: "
                + job[
                    "job_description"
                ]
            )

    if company:

        parts.append(

            f"Employer: "
            f"{company.get('name')}"
        )

        if company.get(
            "company_description"
        ):

            parts.append(

                "Company: "
                + company[
                    "company_description"
                ]
            )

    if sector:

        parts.append(

            "Sector: "
            + sector.get(
                "description",
                ""
            )
        )

    personality = character.get(
        "traits",
        []
    )

    if personality:

        parts.append(

            "Personality: "
            + ", ".join(
                personality
            )
        )

    return "\n".join(parts)

def build_visible_person_description(
    observer,
    target,
    definitions
):

    parts = []

    # =========================
    # NAME
    # =========================

    name = target.get(
        "name",
        "Unknown"
    )

    parts.append(name)

    # =========================
    # APPEARANCE
    # =========================

    appearance_parts = []

    appearance_traits = (
        target
        .get("appearance", {})
        .get("traits", [])
    )

    appearance_defs = definitions.get(
        "appearance_trait_templates",
        {}
    )

    for trait_id in appearance_traits:

        trait = appearance_defs.get(
            trait_id
        )

        if trait:

            appearance_parts.append(
                trait.get(
                    "description",
                    trait_id
                )
            )

    if appearance_parts:

        parts.append(

            "Appearance: "
            + ", ".join(
                appearance_parts
            )
        )

    # =========================
    # EMPLOYMENT
    # =========================

    employment = target.get(
        "employment",
        {}
    )

    job_id = employment.get(
        "job"
    )

    company_id = employment.get(
        "company"
    )

    job = (
        definitions
        .get(
            "job_templates",
            {}
        )
        .get(job_id)
    )

    company = (
        definitions
        .get(
            "company_templates",
            {}
        )
        .get(company_id)
    )

    if job:

        parts.append(

            f"Occupation: "
            f"{job.get('name')}"
        )

        if job.get(
            "job_description"
        ):

            parts.append(

                "Duties: "
                + job[
                    "job_description"
                ]
            )

    if company:

        parts.append(

            f"Employer: "
            f"{company.get('name')}"
        )

        if company.get(
            "company_description"
        ):

            parts.append(

                "Company: "
                + company[
                    "company_description"
                ]
            )

    return "\n".join(parts)