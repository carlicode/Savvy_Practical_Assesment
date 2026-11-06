"""Step 3: detect duplicates by email, phone, or name + location."""

from .data import _clean


def _name_key(row):
    return _clean(row.get("Full_Name")).lower()


def _location_key(row):
    return _clean(row.get("Property_Location")).lower()


def _append_flag(row, flag):
    flags = [item for item in row["Data_Flags"].split(";") if item]
    if flag not in flags:
        flags.append(flag)
    row["Data_Flags"] = ";".join(flags)


def _earliest_id(candidates, leads):
    """Pick the Lead_ID that appears first in the CSV."""
    order = {row["Lead_ID"]: index for index, row in enumerate(leads)}
    return min(candidates, key=lambda lead_id: order[lead_id])


def detect_duplicates(leads):
    """The first lead is the primary. Do not merge or delete records."""
    email_primary = {}
    phone_primary = {}
    name_loc_primary = {}

    for row in leads:
        row["duplicate_of"] = ""
        row["possible_duplicate_of"] = ""

        email = row.get("Email_Normalized") or ""
        phone = row.get("Phone_Normalized") or ""
        name = _name_key(row)
        location = _location_key(row)

        # Confirmed duplicate: same normalized email or phone
        matches = []
        if email and email in email_primary:
            matches.append(email_primary[email])
        if phone and phone in phone_primary:
            matches.append(phone_primary[phone])

        if matches:
            primary_id = _earliest_id(matches, leads)
            row["duplicate_of"] = primary_id
            _append_flag(row, "duplicate")
        else:
            # Same name + location, but contact does not match
            name_loc = (name, location)
            if name and location and name_loc in name_loc_primary:
                row["possible_duplicate_of"] = name_loc_primary[name_loc]
                _append_flag(row, "possible_duplicate")

        # The first lead with that value stays as the primary
        if email and email not in email_primary:
            email_primary[email] = row["Lead_ID"]
        if phone and phone not in phone_primary:
            phone_primary[phone] = row["Lead_ID"]
        if name and location and (name, location) not in name_loc_primary:
            name_loc_primary[(name, location)] = row["Lead_ID"]

    return leads


def print_duplicates(leads):
    confirmed = [row for row in leads if row["duplicate_of"]]
    possible = [row for row in leads if row["possible_duplicate_of"]]

    print(f"\nDuplicates found: {len(confirmed)}")
    if confirmed:
        print(f"{'Lead_ID':<10} {'duplicate_of':<14} Contact")
        print("-" * 70)
        for row in confirmed:
            print(
                f"{row['Lead_ID']:<10} "
                f"{row['duplicate_of']:<14} "
                f"{row['Email_Normalized']} / {row['Phone_Normalized']}"
            )
    else:
        print("None")

    print(f"\nPossible duplicates (same name + location, different contact): {len(possible)}")
    if possible:
        print(f"{'Lead_ID':<10} {'possible_duplicate_of':<22} Name / Location")
        print("-" * 70)
        for row in possible:
            print(
                f"{row['Lead_ID']:<10} "
                f"{row['possible_duplicate_of']:<22} "
                f"{row['Full_Name']} / {row['Property_Location']}"
            )
    else:
        print("None")
