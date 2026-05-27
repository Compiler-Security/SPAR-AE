def parse_packet_babel_packet(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a Babel packet according to RFC 6126 section 4.2.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    # The Babel packet header is 4 bytes: Magic (1), Version (1), Body length (2)
    if len(remaining_input) < 4:
        raise ValueError("Babel packet requires at least 4 bytes for header")

    magic = remaining_input[0]
    version = remaining_input[1]
    body_length = int.from_bytes(remaining_input[2:4], byteorder="big")

    # Validate Magic field
    if magic != 42:
        raise ValueError(f"Expected Magic value 42, got {magic}")

    # Validate Version field
    if version != 2:
        raise ValueError(f"Expected Version value 2, got {version}")

    # Validate Body length
    if len(remaining_input) < 4 + body_length:
        raise ValueError("Not enough bytes for Babel packet body as per Body length field")

    # Extract body and trailer
    body_bytes = remaining_input[4:4 + body_length]
    trailer_bytes = remaining_input[4 + body_length:]

    # Parse packet body as a sequence of TLVs
    body_tlvs = []
    body_remaining = body_bytes
    while len(body_remaining) > 0:
        tlv_result, body_remaining = parse_packet_tlv({}, body_remaining)
        body_tlvs.append(tlv_result)

    # Parse packet trailer as a sequence of TLVs (Pad1 and PadN only, or extensions)
    trailer_tlvs = []
    trailer_remaining = trailer_bytes
    while len(trailer_remaining) > 0:
        tlv_result, trailer_remaining = parse_packet_tlv({}, trailer_remaining)
        trailer_tlvs.append(tlv_result)

    result = {
        "magic": magic,
        "version": version,
        "body_length": body_length,
        "body_tlvs": body_tlvs,
        "trailer_tlvs": trailer_tlvs,
    }
    current_result.update(result)
    return current_result, b""

def parse_packet_tlv(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a generic TLV structure as described in RFC section 4.3.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    # Check for at least one byte for TLV type
    if not remaining_input:
        raise ValueError("No data left for TLV")

    tlv_type = remaining_input[0]

    # Handle Pad1 (single-byte TLV)
    if tlv_type == 0:  # Pad1
        return parse_packet_pad1(current_result, remaining_input)
    # Dispatch to specific TLV parsers for known types
    if tlv_type == 1:
        return parse_packet_padn_tlv(current_result, remaining_input)
    if tlv_type == 2:
        return parse_packet_acknowledgment_request_tlv(current_result, remaining_input)
    if tlv_type == 3:
        return parse_packet_acknowledgment_tlv(current_result, remaining_input)
    if tlv_type == 4:
        return parse_packet_hello_tlv(current_result, remaining_input)
    if tlv_type == 5:
        return parse_packet_ihu_tlv(current_result, remaining_input)
    if tlv_type == 6:
        return parse_packet_router_id_tlv(current_result, remaining_input)
    if tlv_type == 7:
        return parse_packet_next_hop_tlv(current_result, remaining_input)
    if tlv_type == 8:
        return parse_packet_update_tlv(current_result, remaining_input)
    if tlv_type == 9:
        return parse_packet_route_request(current_result, remaining_input)
    if tlv_type == 10:
        return parse_packet_seqno_request_tlv(current_result, remaining_input)
    # All other TLVs need at least Type+Length
    if len(remaining_input) < 2:
        raise ValueError("TLV requires at least 2 bytes for Type and Length fields")

    length = remaining_input[1]
    if len(remaining_input) < 2 + length:
        raise ValueError(f"TLV length field {length} exceeds available bytes")

    payload = remaining_input[2:2 + length]
    remaining_bytes = remaining_input[2 + length:]

    result = {
        "type": tlv_type,
        "length": length,
        "payload": payload,
    }
    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_specific_tlv(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a Specific TLV from RFC specification (Section 4.6).
    """
    if len(remaining_input) < 2:
        raise ValueError("Specific TLV requires at least 2 bytes for Type and Length")
    tlv_type = remaining_input[0]
    length = remaining_input[1]
    if length > len(remaining_input) - 2:
        raise ValueError(f"Length field {length} exceeds available input bytes")
    value = remaining_input[2:2+length]
    remaining_bytes = remaining_input[2+length:]
    result = {
        "type": tlv_type,
        "length": length,
        "value": value,
    }
    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_pad1(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a Pad1 TLV (Type 0) as specified in RFC 6126 Section 4.6.1.
    """
    if len(remaining_input) < 1:
        raise ValueError("Pad1 TLV requires at least 1 byte")
    tlv_type = remaining_input[0]
    if tlv_type != 0:
        raise ValueError(f"Expected Type 0 for Pad1 TLV, got {tlv_type}")
    result = {
        "type": tlv_type
    }
    current_result.update(result)
    return current_result, remaining_input[1:]

def parse_packet_padn_tlv(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a PadN TLV (Type 1) from RFC specification.
    """
    if len(remaining_input) < 2:
        raise ValueError("PadN TLV requires at least 2 bytes for Type and Length")
    tlv_type = remaining_input[0]
    length = remaining_input[1]
    if tlv_type != 1:
        raise ValueError(f"Expected Type 1 for PadN TLV, got {tlv_type}")
    total_tlv_length = 2 + length
    if len(remaining_input) < total_tlv_length:
        raise ValueError(f"PadN TLV claims length {length}, but only {len(remaining_input) - 2} bytes available for MBZ")
    mbz = remaining_input[2:2+length]
    if any(b != 0 for b in mbz):
        raise ValueError("MBZ field in PadN TLV must be all zeros")
    remaining_bytes = remaining_input[total_tlv_length:]
    result = {
        "type": tlv_type,
        "length": length,
        "mbz": mbz,
    }
    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_subtlv(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a Sub-TLV from RFC specification (Section 4.4).

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    # Handle Pad1 (single-byte Sub-TLV) before length check
    if not remaining_input:
        raise ValueError("No data left for Sub-TLV")

    subtlv_type = remaining_input[0]

    if subtlv_type == 0:
        # Pad1 sub-TLV is a single byte
        result = {"type": 0}
        current_result.update(result)
        return current_result, remaining_input[1:]

    # All other sub-TLVs need at least Type+Length
    if len(remaining_input) < 2:
        raise ValueError("Sub-TLV requires at least 2 bytes for Type and Length")

    subtlv_length = remaining_input[1]
    if len(remaining_input) < 2 + subtlv_length:
        raise ValueError(
            f"Sub-TLV body length {subtlv_length} exceeds available bytes"
        )

    body = remaining_input[2 : 2 + subtlv_length]
    remaining_bytes = remaining_input[2 + subtlv_length :]

    # Determine mandatory bit (MSB of type)
    mandatory_bit = bool(subtlv_type & 0x80)

    result = {
        "type": subtlv_type,
        "length": subtlv_length,
        "body": body,
        "mandatory": mandatory_bit,
    }

    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_specific_subtlv(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a Specific Sub-TLV from RFC specification (Section 4.7).

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    # Minimum length check: Type (1) + Length (1) = 2 bytes
    if len(remaining_input) < 2:
        raise ValueError("Specific Sub-TLV requires at least 2 bytes for Type and Length")

    # Parse Type and Length fields
    subtlv_type = remaining_input[0]
    subtlv_length = remaining_input[1]

    # Check if enough bytes for the value
    if len(remaining_input) < 2 + subtlv_length:
        raise ValueError(
            f"Specific Sub-TLV length field {subtlv_length} exceeds available bytes"
        )

    # Extract value
    value = remaining_input[2:2 + subtlv_length]
    remaining_bytes = remaining_input[2 + subtlv_length:]

    # Build result dictionary
    result = {
        "type": subtlv_type,
        "length": subtlv_length,
        "value": value,
    }

    # Update current_result with parsed fields
    current_result.update(result)

    return current_result, remaining_bytes

def parse_packet_padn_subtlv(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a PadN sub-TLV (Type 1) according to RFC specification.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    # Minimum length check: Type (1) + Length (1)
    if len(remaining_input) < 2:
        raise ValueError("PadN sub-TLV requires at least 2 bytes for Type and Length")

    tlv_type = remaining_input[0]
    length = remaining_input[1]

    # Validate Type field
    if tlv_type != 1:
        raise ValueError(f"Expected Type 1 for PadN sub-TLV, got {tlv_type}")

    # Calculate total TLV length
    total_tlv_length = 2 + length  # Type (1) + Length (1) + MBZ (length)
    if len(remaining_input) < total_tlv_length:
        raise ValueError(f"PadN sub-TLV length field {length} exceeds available bytes")

    # MBZ field: Must be zero
    mbz = remaining_input[2:2+length]
    if any(b != 0 for b in mbz):
        raise ValueError("MBZ field in PadN sub-TLV must be all zeros")

    # Remaining bytes after PadN sub-TLV
    remaining_bytes = remaining_input[total_tlv_length:]

    # Build result dictionary
    result = {
        "type": tlv_type,
        "length": length,
        "mbz": mbz,
    }

    # Update current_result with parsed fields
    current_result.update(result)

    return current_result, remaining_bytes

def parse_packet_acknowledgment_request_tlv(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse an Acknowledgment Request TLV (Type 2) from RFC specification.
    """
    if len(remaining_input) < 8:
        raise ValueError("Acknowledgment Request TLV requires at least 8 bytes")
    tlv_type = remaining_input[0]
    length = remaining_input[1]
    reserved = int.from_bytes(remaining_input[2:4], byteorder="big")
    opaque = int.from_bytes(remaining_input[4:6], byteorder="big")
    interval = int.from_bytes(remaining_input[6:8], byteorder="big")
    if tlv_type != 2:
        raise ValueError(f"Expected Type 2 for Acknowledgment Request TLV, got {tlv_type}")
    if length != 6:
        raise ValueError(f"Length field {length} does not match expected body length 6")
    if reserved != 0:
        raise ValueError(f"Reserved field must be 0, got {reserved}")
    if interval == 0:
        raise ValueError("Interval field must not be 0")
    remaining_bytes = remaining_input[8:]
    sub_tlvs = []
    while len(remaining_bytes) > 0:
        try:
            sub_tlv_result, remaining_bytes = parse_packet_subtlv({}, remaining_bytes)
            sub_tlvs.append(sub_tlv_result)
        except Exception:
            break
    result = {
        "type": tlv_type,
        "length": length,
        "reserved": reserved,
        "opaque": opaque,
        "interval": interval,
        "sub_tlvs": sub_tlvs,
    }
    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_acknowledgment_tlv(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse an Acknowledgment TLV (Type 3) from RFC specification.
    """
    if len(remaining_input) < 4:
        raise ValueError("Acknowledgment TLV requires at least 4 bytes")
    tlv_type = remaining_input[0]
    length = remaining_input[1]
    opaque = int.from_bytes(remaining_input[2:4], byteorder="big")
    if tlv_type != 3:
        raise ValueError(f"Expected Type 3 for Acknowledgment TLV, got {tlv_type}")
    if length < 2:
        raise ValueError(f"Length field {length} is less than minimum body length 2")
    if length > len(remaining_input) - 2:
        raise ValueError(f"Length field {length} exceeds available input body length {len(remaining_input) - 2}")
    sub_tlvs = []
    sub_tlv_bytes = remaining_input[4:2+length]
    remaining_bytes = remaining_input[2+length:]
    while len(sub_tlv_bytes) > 0:
        try:
            sub_tlv_result, sub_tlv_bytes = parse_packet_subtlv({}, sub_tlv_bytes)
            sub_tlvs.append(sub_tlv_result)
        except Exception:
            break
    result = {
        "type": tlv_type,
        "length": length,
        "opaque": opaque,
        "sub_tlvs": sub_tlvs,
    }
    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_hello_tlv(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a Hello TLV (Type 4) from RFC specification.
    """
    if len(remaining_input) < 8:
        raise ValueError("Hello TLV requires at least 8 bytes")
    tlv_type = remaining_input[0]
    length = remaining_input[1]
    flags = int.from_bytes(remaining_input[2:4], byteorder="big")
    seqno = int.from_bytes(remaining_input[4:6], byteorder="big")
    interval = int.from_bytes(remaining_input[6:8], byteorder="big")
    if tlv_type != 4:
        raise ValueError(f"Expected Type 4 for Hello TLV, got {tlv_type}")
    expected_body_length = 6
    # Accept any length >= 6
    if length < expected_body_length:
        raise ValueError(f"Length field {length} is less than minimum body length {expected_body_length}")
    if flags & 0x7FFF != 0:
        raise ValueError(f"Flags field has reserved bits set: {flags:#06x}")
    unicast_flag = bool(flags & 0x8000)
    if interval < 0:
        raise ValueError("Interval field must be non-negative")
    # Compute the end of this TLV
    tlv_end = 2 + length
    # The sub-TLV area is the bytes after the fixed header (8 bytes) up to tlv_end
    sub_tlv_bytes = remaining_input[8:tlv_end]
    remaining_bytes = remaining_input[tlv_end:]
    sub_tlvs = []
    while len(sub_tlv_bytes) > 0:
        try:
            sub_tlv_result, sub_tlv_bytes = parse_packet_subtlv({}, sub_tlv_bytes)
            sub_tlvs.append(sub_tlv_result)
        except Exception:
            break
    result = {
        "type": tlv_type,
        "length": length,
        "flags": flags,
        "unicast_flag": unicast_flag,
        "seqno": seqno,
        "interval": interval,
        "sub_tlvs": sub_tlvs,
    }
    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_ihu_tlv(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse an IHU (I Heard You) TLV (Type 5) from RFC specification.
    """
    if len(remaining_input) < 8:
        raise ValueError("IHU TLV requires at least 8 bytes for fixed fields")
    tlv_type = remaining_input[0]
    length = remaining_input[1]
    ae = remaining_input[2]
    reserved = remaining_input[3]
    rxcost = int.from_bytes(remaining_input[4:6], byteorder="big")
    interval = int.from_bytes(remaining_input[6:8], byteorder="big")
    if tlv_type != 5:
        raise ValueError(f"Expected Type 5 for IHU TLV, got {tlv_type}")
    if length < 4:
        raise ValueError(f"IHU TLV Length field {length} is too short (must be at least 4)")
    if ae not in (0, 1, 3):
        raise ValueError(f"Unknown AE value {ae} in IHU TLV; must be 0, 1, or 3")
    if interval == 0:
        raise ValueError("Interval field in IHU TLV must not be 0")
    address_length = {0: 0, 1: 4, 3: 16}[ae]
    if len(remaining_input) < 8 + address_length:
        raise ValueError(f"Insufficient bytes for Address field (AE={ae}) in IHU TLV")
    address = remaining_input[8:8 + address_length]
    remaining_bytes = remaining_input[8 + address_length:]
    sub_tlvs = []
    while len(remaining_bytes) > 0:
        try:
            sub_tlv_result, new_remaining = parse_packet_subtlv({}, remaining_bytes)
            sub_tlvs.append(sub_tlv_result)
            remaining_bytes = new_remaining
        except Exception:
            break
    result = {
        "type": tlv_type,
        "length": length,
        "ae": ae,
        "reserved": reserved,
        "rxcost": rxcost,
        "interval": interval,
        "address": address,
        "sub_tlvs": sub_tlvs,
    }
    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_router_id_tlv(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a Router-Id TLV (Type 6) from RFC specification.
    """
    if len(remaining_input) < 12:
        raise ValueError("Router-Id TLV requires at least 12 bytes")
    tlv_type = remaining_input[0]
    length = remaining_input[1]
    # Accept any length >= 10
    if length < 10:
        raise ValueError(f"Router-Id TLV Length field must be at least 10, got {length}")
    tlv_end = 2 + length  # end offset of this TLV within remaining_input
    reserved = remaining_input[2:4]
    router_id = remaining_input[4:12]
    subtlv_bytes = remaining_input[12:tlv_end]
    remaining_bytes = remaining_input[tlv_end:]
    if tlv_type != 6:
        raise ValueError(f"Expected Type 6 for Router-Id TLV, got {tlv_type}")
    if router_id == b"\x00" * 8:
        raise ValueError("Router-Id must not be all zeroes")
    if router_id == b"\xff" * 8:
        raise ValueError("Router-Id must not be all ones")
    sub_tlvs = []
    while len(subtlv_bytes) > 0:
        subtlv_result, subtlv_bytes = parse_packet_subtlv({}, subtlv_bytes)
        sub_tlvs.append(subtlv_result)
    result = {
        "type": tlv_type,
        "length": length,
        "reserved": reserved,
        "router_id": router_id,
        "sub_tlvs": sub_tlvs,
    }
    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_next_hop_tlv(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a Next Hop TLV (Type 7) from RFC specification.
    """
    if len(remaining_input) < 4:
        raise ValueError("Next Hop TLV requires at least 4 bytes")
    tlv_type = remaining_input[0]
    length = remaining_input[1]
    ae = remaining_input[2]
    reserved = remaining_input[3]
    if tlv_type != 7:
        raise ValueError(f"Expected Type 7 for Next Hop TLV, got {tlv_type}")
    if ae == 0:
        raise ValueError("AE field MUST NOT be 0 in Next Hop TLV")
    if len(remaining_input) < 2 + length:
        raise ValueError(f"Length field {length} exceeds available bytes for Next Hop TLV body")
    next_hop_length = length - 2
    next_hop_start = 4
    next_hop_end = next_hop_start + next_hop_length
    next_hop = remaining_input[next_hop_start:next_hop_end]
    remaining_bytes = remaining_input[next_hop_end:]
    sub_tlvs = []
    while len(remaining_bytes) > 0:
        try:
            sub_tlv_result, remaining_bytes = parse_packet_subtlv({}, remaining_bytes)
            sub_tlvs.append(sub_tlv_result)
        except Exception:
            break
    result = {
        "type": tlv_type,
        "length": length,
        "ae": ae,
        "reserved": reserved,
        "next_hop": next_hop,
        "sub_tlvs": sub_tlvs,
    }
    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_update_tlv(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse an Update TLV (Type 8) from RFC specification.
    """
    if len(remaining_input) < 12:
        raise ValueError("Update TLV requires at least 12 bytes")
    tlv_type = remaining_input[0]
    length = remaining_input[1]
    ae = remaining_input[2]
    # Add explicit AE range check as per RFC 4.6.9
    VALID_AE_VALUES = (0, 1, 2, 3)
    if ae not in VALID_AE_VALUES:
        # Silently ignore the whole TLV as required by RFC 4.6.9
        return {}, remaining_input[2 + length:]
    flags = remaining_input[3]
    plen = remaining_input[4]
    omitted = remaining_input[5]
    interval = int.from_bytes(remaining_input[6:8], byteorder="big")
    seqno = int.from_bytes(remaining_input[8:10], byteorder="big")
    metric = int.from_bytes(remaining_input[10:12], byteorder="big")
    if tlv_type != 8:
        raise ValueError(f"Expected Type 8 for Update TLV, got {tlv_type}")
    if length < 10:
        raise ValueError(f"Length field {length} is less than minimum 10 bytes for Update TLV body")
    if len(remaining_input) < 2 + length:
        raise ValueError(f"Not enough bytes for Update TLV body: need {2 + length}, have {len(remaining_input)}")
    if interval == 0:
        raise ValueError("Interval field must not be 0")
    # RFC 4.6.9: AE=0 is only allowed for infinite metric (retraction). If not, ignore TLV for routing purposes.
    if metric != 0xFFFF and ae == 0:
        # Finite-metric Update with AE=0: per RFC 4.6.9 receiver MUST ignore the TLV.
        # Silently skip this TLV and continue parsing the rest of the packet.
        return {}, remaining_input[2 + length:]
    if metric == 0xFFFF and ae == 0:
        if plen != 0 or omitted != 0:
            raise ValueError("If metric is infinite and AE=0, Plen and Omitted must both be 0")
    if ae == 3 and omitted != 0:
        raise ValueError("If AE=3 (link-local IPv6), Omitted must be 0")
    prefix_length_bits = plen
    prefix_length_bytes = (prefix_length_bits + 7) // 8
    if omitted > prefix_length_bytes:
        raise ValueError("Omitted field cannot be greater than prefix length in bytes")
    prefix_field_length = prefix_length_bytes - omitted if prefix_length_bytes > omitted else 0
    total_header_len = 12
    if length < 10 + prefix_field_length:
        raise ValueError(f"Length field {length} is too small for prefix field of length {prefix_field_length}")
    if len(remaining_input) < 2 + total_header_len + prefix_field_length:
        raise ValueError(f"Not enough bytes for prefix field: need {2 + total_header_len + prefix_field_length}, have {len(remaining_input)}")
    prefix_start = total_header_len
    prefix_end = total_header_len + prefix_field_length
    prefix = remaining_input[prefix_start:prefix_end] if prefix_field_length > 0 else b""
    if prefix and (prefix_length_bits % 8 != 0):
        last_byte_mask = 0xFF & (0xFF << (8 - (prefix_length_bits % 8)))
        prefix = prefix[:-1] + bytes([prefix[-1] & last_byte_mask])
    sub_tlvs = []
    subtlv_offset = prefix_end
    subtlv_end = 2 + length
    while subtlv_offset < subtlv_end:
        subtlv_result, subtlv_remaining = parse_packet_subtlv({}, remaining_input[subtlv_offset:subtlv_end])
        sub_tlvs.append(subtlv_result)
        subtlv_offset = subtlv_end - len(subtlv_remaining)
    result = {
        "type": tlv_type,
        "length": length,
        "ae": ae,
        "flags": flags,
        "plen": plen,
        "omitted": omitted,
        "interval": interval,
        "seqno": seqno,
        "metric": metric,
        "prefix": prefix,
        "sub_tlvs": sub_tlvs,
    }
    current_result.update(result)
    remaining_bytes = remaining_input[2 + length:]
    return current_result, remaining_bytes

def parse_packet_route_request(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a Route Request TLV (Type 9) from RFC specification.
    """
    if len(remaining_input) < 4:
        raise ValueError("Route Request TLV requires at least 4 bytes")
    tlv_type = remaining_input[0]
    length = remaining_input[1]
    ae = remaining_input[2]
    plen = remaining_input[3]
    if tlv_type != 9:
        raise ValueError(f"Expected Type 9 for Route Request TLV, got {tlv_type}")
    if ae == 0:
        if plen != 0:
            raise ValueError("AE=0 (wildcard request) requires Plen=0")
        if length != 2:
            raise ValueError("AE=0 (wildcard request) requires Length=2")
        prefix = b""
        remaining_bytes = remaining_input[4:]
    else:
        prefix_length_bytes = (plen + 7) // 8
        expected_body_length = 2 + prefix_length_bytes
        if length != expected_body_length:
            raise ValueError(f"Length field {length} doesn't match expected body length {expected_body_length}")
        if len(remaining_input) < 4 + prefix_length_bytes:
            raise ValueError(f"Insufficient bytes for prefix: need {prefix_length_bytes} bytes")
        prefix = remaining_input[4 : 4 + prefix_length_bytes]
        remaining_bytes = remaining_input[4 + prefix_length_bytes :]
    result = {
        "type": tlv_type,
        "length": length,
        "ae": ae,
        "plen": plen,
        "prefix": prefix,
    }
    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_seqno_request_tlv(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a Seqno Request TLV (Type 10) from RFC specification.
    """
    if len(remaining_input) < 16:
        raise ValueError("Seqno Request TLV requires at least 16 bytes")
    tlv_type = remaining_input[0]
    length = remaining_input[1]
    ae = remaining_input[2]
    plen = remaining_input[3]
    if tlv_type != 10:
        raise ValueError(f"Expected Type 10 for Seqno Request TLV, got {tlv_type}")
    if ae == 0:
        raise ValueError("AE field MUST NOT be 0 in Seqno Request TLV")
    seqno = int.from_bytes(remaining_input[4:6], byteorder="big")
    hop_count = remaining_input[6]
    reserved = remaining_input[7]
    if hop_count == 0:
        raise ValueError("Hop Count MUST NOT be 0 in Seqno Request TLV")
    router_id = remaining_input[8:16]
    if router_id == b"\x00" * 8:
        raise ValueError("Router-Id MUST NOT be all zeroes")
    if router_id == b"\xff" * 8:
        raise ValueError("Router-Id MUST NOT be all ones")
    prefix_length_bytes = (plen + 7) // 8
    # Accept length >= 14, not 14+8
    if length < 14:
        raise ValueError(f"Length field {length} is less than minimum body length")
    if len(remaining_input) < 16 + prefix_length_bytes:
        raise ValueError(f"Insufficient bytes for prefix: need {prefix_length_bytes} bytes")
    # expected_body_length = 14 + prefix_length_bytes
    expected_body_length = 14 + prefix_length_bytes
    # Accept larger lengths (for sub-TLVs)
    if length < expected_body_length:
        raise ValueError(f"Length field {length} does not match minimum body length {expected_body_length}")
    prefix = remaining_input[16:16 + prefix_length_bytes]
    # Limit sub-TLVs to the declared body
    subtlv_bytes = remaining_input[16 + prefix_length_bytes : 2 + length]
    remaining_bytes = remaining_input[2 + length:]
    sub_tlvs = []
    while len(subtlv_bytes) > 0:
        subtlv_result, subtlv_bytes = parse_packet_subtlv({}, subtlv_bytes)
        sub_tlvs.append(subtlv_result)
    result = {
        "type": tlv_type,
        "length": length,
        "ae": ae,
        "plen": plen,
        "seqno": seqno,
        "hop_count": hop_count,
        "reserved": reserved,
        "router_id": router_id,
        "prefix": prefix,
        "sub_tlvs": sub_tlvs,
    }
    current_result.update(result)
    return current_result, remaining_bytes

def main():
    import sys
    try:
        with open(sys.argv[1], "rb") as f:
            data = f.read()
        result, _ = parse_packet_babel_packet({}, data)
        print(result)
    except Exception as e:
        print(str(e))
        import traceback
        traceback.print_exc()
        print(locals().get('result', {}))
        sys.exit(1)

if __name__ == "__main__":
    main()
