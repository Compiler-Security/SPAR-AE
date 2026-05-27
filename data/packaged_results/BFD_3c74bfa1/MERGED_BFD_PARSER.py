def parse_packet_bfd_control_packet(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a BFD Control Packet from RFC specification.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    # Minimum length check for mandatory section: 24 bytes
    if len(remaining_input) < 24:
        raise ValueError(
            "BFD Control Packet requires at least 24 bytes for mandatory section"
        )

    # Parse the first byte (Vers and Diag)
    first_byte = remaining_input[0]
    vers = (first_byte & 0xE0) >> 5  # Bits 7-5 (3 bits)
    diag = first_byte & 0x1F  # Bits 4-0 (5 bits)

    # Parse the second byte (flags and Detect Mult)
    second_byte = remaining_input[1]
    sta = (second_byte & 0xC0) >> 6  # Bits 7-6 (2 bits)
    p_flag = (second_byte & 0x20) >> 5  # Bit 5 (1 bit)
    f_flag = (second_byte & 0x10) >> 4  # Bit 4 (1 bit)
    c_flag = (second_byte & 0x08) >> 3  # Bit 3 (1 bit)
    a_flag = (second_byte & 0x04) >> 2  # Bit 2 (1 bit)
    d_flag = (second_byte & 0x02) >> 1  # Bit 1 (1 bit)
    m_flag = second_byte & 0x01  # Bit 0 (1 bit)
    detect_mult = remaining_input[2]
    length = remaining_input[3]

    # Validate Version field
    if vers != 1:
        raise ValueError(f"Expected Version 1 for BFD Control Packet, got {vers}")

    # Validate Diagnostic field
    if diag > 8 and diag < 32:
        raise ValueError(f"Diagnostic value {diag} is reserved for future use")

    # Validate State field
    if sta > 3:
        raise ValueError(f"Invalid State value {sta}, must be 0-3")

    # Validate Multipoint bit
    if m_flag != 0:
        raise ValueError("Multipoint bit (M) must be zero")

    # Validate Length field
    if length < 24:
        raise ValueError(f"Length field {length} is less than minimum 24 bytes")
    if length > len(remaining_input):
        raise ValueError(
            f"Length field {length} does not match available input length {len(remaining_input)}"
        )

    # Parse discriminator fields (4 bytes each)
    my_discriminator = int.from_bytes(remaining_input[4:8], byteorder="big")
    your_discriminator = int.from_bytes(remaining_input[8:12], byteorder="big")

    # Validate My Discriminator
    if my_discriminator == 0:
        raise ValueError("My Discriminator must be nonzero")

    # Validate Your Discriminator and Packet State
    if sta in (2, 3) and your_discriminator == 0:
        raise ValueError(
            "Your Discriminator must be nonzero when State is Init or Up"
        )

    # Parse interval fields (4 bytes each)
    desired_min_tx_interval = int.from_bytes(remaining_input[12:16], byteorder="big")
    required_min_rx_interval = int.from_bytes(remaining_input[16:20], byteorder="big")
    required_min_echo_rx_interval = int.from_bytes(
        remaining_input[20:24], byteorder="big"
    )

    # Validate Desired Min TX Interval
    if desired_min_tx_interval == 0:
        raise ValueError("Desired Min TX Interval must not be zero")

    # Calculate remaining bytes after mandatory section
    remaining_bytes = remaining_input[24:length]

    # Handle authentication section if present
    auth_section = None
    auth_type = None
    auth_len = None

    if a_flag:
        # Check if we have enough bytes for authentication header
        if len(remaining_bytes) < 2:
            raise ValueError(
                "Authentication Present bit set but insufficient bytes for auth header"
            )

        auth_type = remaining_bytes[0]
        auth_len = remaining_bytes[1]

        # Validate Auth Type
        if auth_type == 0 or (auth_type > 5 and auth_type < 256):
            raise ValueError(f"Auth Type {auth_type} is reserved")

        # Validate Auth Len
        if auth_type == 1:
            # Simple Password: auth_len = password length + 3, password 1-16 bytes
            if auth_len < 4 or auth_len > 19:
                raise ValueError("Auth Len for Simple Password must be 4-19 bytes")
            auth_section, _ = parse_packet_simple_password_auth_section(
                {}, remaining_bytes[:auth_len]
            )
            remaining_bytes = remaining_bytes[auth_len:]
        elif auth_type in (2, 3):
            # Keyed MD5: auth_len = 24
            if auth_len != 24:
                raise ValueError("Auth Len for Keyed MD5 must be 24 bytes")
            auth_section, _ = parse_packet_keyed_md5_auth_section(
                {}, remaining_bytes[:auth_len]
            )
            remaining_bytes = remaining_bytes[auth_len:]
        elif auth_type == 4:
            # Keyed SHA1: auth_len = 28
            if auth_len != 28:
                raise ValueError("Auth Len for Keyed SHA1 must be 28 bytes")
            auth_section, _ = parse_packet_keyed_sha1_auth_section(
                {}, remaining_bytes[:auth_len]
            )
            remaining_bytes = remaining_bytes[auth_len:]
        elif auth_type == 5:
            # Meticulous Keyed SHA1: auth_len = 28
            if auth_len != 28:
                raise ValueError("Auth Len for Meticulous Keyed SHA1 must be 28 bytes")
            auth_section, _ = parse_packet_meticulous_keyed_sha1_auth_section(
                {}, remaining_bytes[:auth_len]
            )
            remaining_bytes = remaining_bytes[auth_len:]
        else:
            raise ValueError(f"Unsupported Auth Type {auth_type}")

    # Build result dictionary
    result = {
        "version": vers,
        "diagnostic": diag,
        "state": sta,
        "poll": bool(p_flag),
        "final": bool(f_flag),
        "control_plane_independent": bool(c_flag),
        "authentication_present": bool(a_flag),
        "demand": bool(d_flag),
        "multipoint": bool(m_flag),
        "detect_mult": detect_mult,
        "length": length,
        "my_discriminator": my_discriminator,
        "your_discriminator": your_discriminator,
        "desired_min_tx_interval": desired_min_tx_interval,
        "required_min_rx_interval": required_min_rx_interval,
        "required_min_echo_rx_interval": required_min_echo_rx_interval,
    }

    # Add authentication fields if present
    if a_flag:
        result.update(
            {"auth_type": auth_type, "auth_len": auth_len, "auth_section": auth_section}
        )

    # Update current_result with parsed fields
    current_result.update(result)

    return current_result, remaining_bytes

def parse_packet_simple_password_auth_section(
    current_result: dict, remaining_input: bytes
) -> tuple[dict, bytes]:
    """
    Parse Simple Password Authentication Section from RFC specification.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    # Minimum length for Simple Password Authentication Section is 4 bytes:
    # Auth Type (1) + Auth Len (1) + Auth Key ID (1) + Password (at least 1)
    if len(remaining_input) < 4:
        raise ValueError("Simple Password Authentication Section requires at least 4 bytes")

    auth_type = remaining_input[0]
    auth_len = remaining_input[1]
    auth_key_id = remaining_input[2]

    # Validate Auth Type
    if auth_type != 1:
        raise ValueError(f"Expected Auth Type 1 for Simple Password, got {auth_type}")

    # Validate Auth Len
    if auth_len < 4:
        raise ValueError(f"Auth Len {auth_len} is less than minimum 4 bytes")
    if auth_len > 19:
        raise ValueError(f"Auth Len {auth_len} exceeds maximum allowed for Simple Password (19 bytes)")
    if auth_len > len(remaining_input):
        raise ValueError(f"Auth Len {auth_len} exceeds available input bytes {len(remaining_input)}")

    # Password length is auth_len - 3
    password_length = auth_len - 3
    if password_length < 1 or password_length > 16:
        raise ValueError(f"Password length {password_length} must be between 1 and 16 bytes")

    password = remaining_input[3:3 + password_length]
    remaining_bytes = remaining_input[auth_len:]

    result = {
        "auth_type": auth_type,
        "auth_len": auth_len,
        "auth_key_id": auth_key_id,
        "password": password,
    }

    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_keyed_md5_auth_section(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a Keyed MD5 or Meticulous Keyed MD5 Authentication Section from RFC 5880 section 4.3.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    # The authentication section must be exactly 24 bytes for Keyed MD5/Meticulous Keyed MD5
    if len(remaining_input) < 24:
        raise ValueError("Keyed MD5 Authentication Section requires at least 24 bytes")

    auth_type = remaining_input[0]
    auth_len = remaining_input[1]
    auth_key_id = remaining_input[2]
    reserved = remaining_input[3]
    sequence_number = int.from_bytes(remaining_input[4:8], byteorder="big")
    auth_digest = remaining_input[8:24]

    # Validate Auth Type
    if auth_type not in (2, 3):
        raise ValueError(f"Auth Type must be 2 (Keyed MD5) or 3 (Meticulous Keyed MD5), got {auth_type}")

    # Validate Auth Len
    if auth_len != 24:
        raise ValueError(f"Auth Len must be 24 for Keyed MD5/Meticulous Keyed MD5, got {auth_len}")

    # Reserved byte must be zero (on transmit, but ignore on receipt)
    # No exception raised for reserved field

    result = {
        "auth_type": auth_type,
        "auth_len": auth_len,
        "auth_key_id": auth_key_id,
        "reserved": reserved,
        "sequence_number": sequence_number,
        "auth_digest": auth_digest,
    }
    current_result.update(result)
    remaining_bytes = remaining_input[24:]
    return current_result, remaining_bytes

def parse_packet_meticulous_keyed_md5_auth_section(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse Meticulous Keyed MD5 Authentication Section from RFC specification.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    # This function is kept for compatibility, but parse_packet_keyed_md5_auth_section handles both types.
    return parse_packet_keyed_md5_auth_section(current_result, remaining_input)

def parse_packet_keyed_sha1_auth_section(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a Keyed SHA1 Authentication Section from RFC specification.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    # The Keyed SHA1 Authentication Section must be exactly 28 bytes
    if len(remaining_input) < 28:
        raise ValueError("Keyed SHA1 Authentication Section requires 28 bytes")

    auth_type = remaining_input[0]
    auth_len = remaining_input[1]
    auth_key_id = remaining_input[2]
    reserved = remaining_input[3]
    sequence_number = int.from_bytes(remaining_input[4:8], byteorder="big")
    auth_key_hash = remaining_input[8:28]

    # Validate Auth Type
    if auth_type != 4:
        raise ValueError(f"Auth Type must be 4 for Keyed SHA1, got {auth_type}")

    # Validate Auth Len
    if auth_len != 28:
        raise ValueError(f"Auth Len must be 28 for Keyed SHA1, got {auth_len}")

    # Reserved byte must be zero
    if reserved != 0:
        raise ValueError("Reserved byte must be zero")

    result = {
        "auth_type": auth_type,
        "auth_len": auth_len,
        "auth_key_id": auth_key_id,
        "reserved": reserved,
        "sequence_number": sequence_number,
        "auth_key_hash": auth_key_hash,
    }
    current_result.update(result)
    remaining_bytes = remaining_input[28:]
    return current_result, remaining_bytes

def parse_packet_meticulous_keyed_sha1_auth_section(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a Meticulous Keyed SHA1 Authentication Section from RFC specification.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    # The Meticulous Keyed SHA1 Authentication Section must be exactly 28 bytes
    if len(remaining_input) < 28:
        raise ValueError("Meticulous Keyed SHA1 Authentication Section requires 28 bytes")

    auth_type = remaining_input[0]
    auth_len = remaining_input[1]
    auth_key_id = remaining_input[2]
    reserved = remaining_input[3]
    sequence_number = int.from_bytes(remaining_input[4:8], byteorder="big")
    auth_key_hash = remaining_input[8:28]

    # Validate Auth Type
    if auth_type != 5:
        raise ValueError(f"Auth Type must be 5 for Meticulous Keyed SHA1, got {auth_type}")

    # Validate Auth Len
    if auth_len != 28:
        raise ValueError(f"Auth Len must be 28 for Meticulous Keyed SHA1, got {auth_len}")

    # Reserved byte must be zero
    if reserved != 0:
        raise ValueError("Reserved byte must be zero")

    result = {
        "auth_type": auth_type,
        "auth_len": auth_len,
        "auth_key_id": auth_key_id,
        "reserved": reserved,
        "sequence_number": sequence_number,
        "auth_key_hash": auth_key_hash,
    }
    current_result.update(result)
    remaining_bytes = remaining_input[28:]
    return current_result, remaining_bytes

def main():
    import sys
    try:
        with open(sys.argv[1], "rb") as f:
            data = f.read()
        result, remaining = parse_packet_bfd_control_packet({}, data)
        print(result)
    except Exception as e:
        print(str(e))
        import traceback
        traceback.print_exc()
        print(locals().get('result', {}))
        sys.exit(1)

if __name__ == "__main__":
    main()
