from cardly_cli.models.contact import Contact, build_contact


def test_build_contact_uses_locality_not_city():
    # THE test. Orders serialize `city`; contacts serialize `locality`.
    # Sharing one address model 422s every contact write.
    out = build_contact(
        {"firstName": "Ada", "address": "x", "locality": "Melbourne", "country": "AU"}, {}
    )
    assert out["locality"] == "Melbourne"
    assert "city" not in out


def test_build_contact_compacts_empties():
    out = build_contact({"firstName": "Ada", "lastName": "", "email": None}, {})
    assert out == {"firstName": "Ada"}


def test_build_contact_includes_fields_map():
    out = build_contact({"firstName": "Ada"}, {"birthday": "1815-12-10"})
    assert out["fields"] == {"birthday": "1815-12-10"}


def test_build_contact_omits_empty_fields_map():
    assert "fields" not in build_contact({"firstName": "Ada"}, {})


def test_contact_model_reads_admin_area_level_1():
    # Reads come back with adminAreaLevel1, not `region`.
    c = Contact.model_validate({"id": "1", "firstName": "Ada", "adminAreaLevel1": "VIC"})
    assert c.adminAreaLevel1 == "VIC"
