import sys
import struct

def parse_packet_membership_query_message(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse an IGMPv3 Membership Query Message according to RFC 3376 section 4.1.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    # Minimum length for IGMPv3 Membership Query Message is 12 bytes (no sources)
    if len(remaining_input) < 12:
        raise ValueError("Membership Query Message requires at least 12 bytes")

    # Parse fixed header fields
    type_field = remaining_input[0]
    max_resp_code = remaining_input[1]
    checksum = int.from_bytes(remaining_input[2:4], byteorder="big")
    group_address = remaining_input[4:8]
    resv_s_qrv = remaining_input[8]
    qqic = remaining_input[9]
    number_of_sources = int.from_bytes(remaining_input[10:12], byteorder="big")

    # Validate Type field
    if type_field != 0x11:
        raise ValueError(f"Expected Type 0x11 for Membership Query Message, got {type_field:#x}")

    # Extract Resv, S, QRV fields
    resv = (resv_s_qrv & 0b11111000) >> 3  # upper 5 bits
    s_flag = (resv_s_qrv & 0b00000100) >> 2  # bit 2
    qrv = resv_s_qrv & 0b00000011  # lower 2 bits

    # Parse source addresses
    expected_length = 12 + number_of_sources * 4
    if len(remaining_input) < expected_length:
        raise ValueError(f"Insufficient bytes for {number_of_sources} source addresses")
    source_addresses = []
    for i in range(number_of_sources):
        offset = 12 + i * 4
        source_addr = remaining_input[offset:offset+4]
        if len(source_addr) != 4:
            raise ValueError(f"Source address {i+1} is not 4 bytes")
        source_addresses.append(source_addr)

    # Remaining bytes after the IGMP message
    remaining_bytes = remaining_input[expected_length:]

    # Build result dictionary
    result = {
        "type": type_field,
        "max_resp_code": max_resp_code,
        "checksum": checksum,
        "group_address": group_address,
        "resv": resv,
        "s_flag": bool(s_flag),
        "qrv": qrv,
        "qqic": qqic,
        "number_of_sources": number_of_sources,
        "source_addresses": source_addresses,
    }
    current_result.update(result)
    return current_result, remaining_bytes


def parse_packet_igmpv3_group_record(current_result: dict, remaining_input: bytes, offset: int) -> tuple[dict, int]:
    """
    Parse IGMPv3 Group Record from RFC specification.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse
        offset: Current offset in bytes

    Returns:
        Tuple of (parsed_fields_dict, new_offset)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    # Minimum length for group record header: 8 bytes
    if len(remaining_input) < offset + 8:
        raise ValueError("Group Record requires at least 8 bytes")

    record_type = remaining_input[offset]
    aux_data_len = remaining_input[offset + 1]
    num_sources = int.from_bytes(remaining_input[offset + 2:offset + 4], byteorder="big")
    multicast_address = remaining_input[offset + 4:offset + 8]

    # Validate Record Type (1-6 are valid, others ignored)
    if record_type < 1 or record_type > 6:
        # Unrecognized record type, silently ignore
        return {}, offset + 8

    # Parse source addresses
    sources = []
    source_offset = offset + 8
    for i in range(num_sources):
        if len(remaining_input) < source_offset + 4:
            raise ValueError(f"Insufficient bytes for Source Address {i+1} in Group Record")
        source_addr = remaining_input[source_offset:source_offset + 4]
        sources.append(source_addr)
        source_offset += 4

    # Parse auxiliary data (aux_data_len is in 32-bit words)
    aux_data_bytes = aux_data_len * 4
    if len(remaining_input) < source_offset + aux_data_bytes:
        raise ValueError("Insufficient bytes for Auxiliary Data in Group Record")
    auxiliary_data = remaining_input[source_offset:source_offset + aux_data_bytes]
    new_offset = source_offset + aux_data_bytes

    result = {
        "record_type": record_type,
        "aux_data_len": aux_data_len,
        "num_sources": num_sources,
        "multicast_address": multicast_address,
        "sources": sources,
        "auxiliary_data": auxiliary_data,
    }
    current_result.update(result)
    return current_result, new_offset


def parse_packet_igmpv3_membership_report(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse IGMPv3 Membership Report Message from RFC specification.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    # Minimum length check: 8 bytes for header
    if len(remaining_input) < 8:
        raise ValueError("IGMPv3 Membership Report requires at least 8 bytes for header")

    # Parse header fields
    type_field = remaining_input[0]
    reserved1 = remaining_input[1]
    checksum = int.from_bytes(remaining_input[2:4], byteorder="big")
    reserved2 = int.from_bytes(remaining_input[4:6], byteorder="big")
    num_group_records = int.from_bytes(remaining_input[6:8], byteorder="big")

    # Validate Type field
    if type_field != 0x22:
        raise ValueError(f"Expected Type 0x22 for IGMPv3 Membership Report, got {type_field}")

    # Reserved fields must be zero on transmission, but ignored on reception
    # No strict validation for reserved fields

    # Check if enough bytes for all group records
    offset = 8
    group_records = []
    for i in range(num_group_records):
        if len(remaining_input) < offset + 8:
            raise ValueError(f"Insufficient bytes for Group Record {i+1}")
        group_record_result, offset = parse_packet_igmpv3_group_record({}, remaining_input, offset)
        group_records.append(group_record_result)

    # Any additional data beyond last group record is ignored except for checksum computation
    remaining_bytes = remaining_input[offset:]

    result = {
        "type": type_field,
        "reserved1": reserved1,
        "checksum": checksum,
        "reserved2": reserved2,
        "num_group_records": num_group_records,
        "group_records": group_records,
    }
    current_result.update(result)
    return current_result, remaining_bytes


def main():
    import sys
    try:
        if len(sys.argv) < 2:
            print("Usage: python script.py <input_file>")
            sys.exit(1)
        with open(sys.argv[1], "rb") as f:
            data = f.read()
        # Try both parsers: Membership Query first, then Membership Report
        try:
            result, remaining = parse_packet_membership_query_message({}, data)
            print("Membership Query Message Parsed:")
            print(result)
        except Exception as e1:
            try:
                result, remaining = parse_packet_igmpv3_membership_report({}, data)
                print("IGMPv3 Membership Report Parsed:")
                print(result)
            except Exception as e2:
                print("Failed to parse as Membership Query or Membership Report.")
                print(str(e1))
                print(str(e2))
                sys.exit(1)
    except Exception as e:
        print(str(e))
        if 'result' in locals():
            print(result)
        sys.exit(1)

if __name__ == "__main__":
    main()
